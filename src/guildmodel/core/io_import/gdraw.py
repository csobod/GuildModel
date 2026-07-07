"""GuildDraw ``.gdraw`` / ``.svg`` intake (BUILDPLAN M7.2).

A ``.gdraw`` is a ZIP of ``manifest.json`` + ``front.svg`` + ``temple_r.svg`` +
``temple_l.svg`` + ``hinge.svg``. Each SVG carries the authoritative geometry in a
``<metadata>`` child of the root ``<svg>`` — a JSON blob with the curves (line /
spline / circle / arc, each with cubic spline nodes), the ``forming`` metadata
(``apical_radius_mm`` = base curve, ``bridge_angle_deg``), the bridge ``mirror``
axis, and per-layer visibility (see GuildDraw ``framedraft/export/svg.py`` +
``export/gdraw.py``). This reader parses that JSON **directly** — not the rendered
``<path>`` ``d`` strings — and flattens every curve to the **same layer-keyed point
lists** that :func:`io_import.dxf.import_dxf` yields, so a ``.gdraw`` and a
per-workspace DXF import identically (the §3 contract holds across both paths).

Coordinate frame: GuildDraw scene units are mm in screen space (Y down). A DXF
export negates Y (DXF Y-up) and GuildModel flips X for the posterior, so the **net
scene → posterior transform is (x, y) → (-x, -y)** — applied here once, exactly as
``import_dxf(posterior=True)`` does its single flip.

``read_gdraw`` is the low-level intake (geometry per workspace, like ``import_dxf``).
``build_project_from_gdraw`` assembles a multi-component :class:`ProjectSchema` —
the frame front, both temples, and a base-curve template per lens (BUILDPLAN M7.1
kinds) — each paired with its layer geometry for the GUI / CAM dispatcher.
"""
from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely.geometry import Polygon

from guildmodel.core.layers import ALL_LAYERS
from guildmodel.core.project.schema import (
    Component,
    ComponentKind,
    FormingMetadata,
    ProjectSchema,
)

CHORD_TOL_MM = 0.01
_SVG_NS = "http://www.w3.org/2000/svg"

#: GuildDraw workspace tabs, in document order (export/gdraw.py).
TABS = ("front", "temple_r", "temple_l", "hinge")
_TAB_KIND = {
    "temple_r": ComponentKind.TEMPLE_RIGHT,
    "temple_l": ComponentKind.TEMPLE_LEFT,
}

# No legitimate GuildDraw SVG comes near this; the cap + DTD scan close the
# entity-expansion ("billion laughs") hole without a third-party parser, exactly
# as GuildDraw's own loader does (these files are shared between makers).
_MAX_SVG_BYTES = 64 * 1024 * 1024


class GdrawError(Exception):
    """Raised on a malformed or non-GuildDraw ``.gdraw`` / ``.svg``."""


# ------------------------------------------------------------------ flattening

Point = tuple[float, float]


def _mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _flatten_cubic(p0: Point, p1: Point, p2: Point, p3: Point,
                   tol: float, out: list[Point], depth: int = 0) -> None:
    """Adaptive de Casteljau flattening of one cubic Bézier; appends the segment
    *end* points (not p0) to ``out``. AGG flatness test against the chord."""
    if depth >= 20:
        out.append(p3)
        return
    ux = 3.0 * p1[0] - 2.0 * p0[0] - p3[0]
    uy = 3.0 * p1[1] - 2.0 * p0[1] - p3[1]
    vx = 3.0 * p2[0] - p0[0] - 2.0 * p3[0]
    vy = 3.0 * p2[1] - p0[1] - 2.0 * p3[1]
    if max(ux * ux, vx * vx) + max(uy * uy, vy * vy) <= 16.0 * tol * tol:
        out.append(p3)
        return
    p01, p12, p23 = _mid(p0, p1), _mid(p1, p2), _mid(p2, p3)
    p012, p123 = _mid(p01, p12), _mid(p12, p23)
    p0123 = _mid(p012, p123)
    _flatten_cubic(p0, p01, p012, p0123, tol, out, depth + 1)
    _flatten_cubic(p0123, p123, p23, p3, tol, out, depth + 1)


def _node_xy(n: dict) -> Point:
    return (float(n["x"]), float(n["y"]))


def _flatten_spline(curve: dict, tol: float) -> list[Point]:
    nodes = curve.get("nodes", [])
    if not nodes:
        return []
    pts: list[Point] = [_node_xy(nodes[0])]
    segs = list(zip(nodes, nodes[1:]))
    if curve.get("closed") and len(nodes) > 2:
        segs.append((nodes[-1], nodes[0]))
    for a, b in segs:
        p0, p3 = _node_xy(a), _node_xy(b)
        c_out = a.get("cp_out")
        c_in = b.get("cp_in")
        p1 = (float(c_out["x"]), float(c_out["y"])) if c_out else p0
        p2 = (float(c_in["x"]), float(c_in["y"])) if c_in else p3
        _flatten_cubic(p0, p1, p2, p3, tol, pts)
    return pts


def _flatten_line(curve: dict) -> list[Point]:
    return [_node_xy(n) for n in curve.get("nodes", [])]


def _flatten_circle(curve: dict, tol: float) -> list[Point]:
    nodes = curve.get("nodes", [])
    r = curve.get("radius")
    if not nodes or not r:
        return []
    cx, cy = _node_xy(nodes[0])
    n = max(16, int(2.0 * math.pi * r / max(tol, 1e-6)))
    return [(cx + r * math.cos(2.0 * math.pi * i / n),
             cy + r * math.sin(2.0 * math.pi * i / n)) for i in range(n)]


def _flatten_arc(curve: dict, tol: float) -> list[Point]:
    nodes = curve.get("nodes", [])
    r = curve.get("radius")
    a0d, a1d = curve.get("start_angle"), curve.get("end_angle")
    if not nodes or not r or a0d is None or a1d is None:
        return _flatten_line(curve)
    cx, cy = _node_xy(nodes[0])
    a0, a1 = math.radians(a0d), math.radians(a1d)
    if a1 <= a0:
        a1 += 2.0 * math.pi
    half = math.acos(max(-1.0, 1.0 - tol / r)) if r > 0 else math.pi
    n = max(2, math.ceil((a1 - a0) / (2.0 * half)))
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _flatten_curve(curve: dict, tol: float) -> list[Point]:
    kind = curve.get("kind", "line")
    if kind == "spline":
        return _flatten_spline(curve, tol)
    if kind == "circle":
        return _flatten_circle(curve, tol)
    if kind == "arc":
        return _flatten_arc(curve, tol)
    return _flatten_line(curve)


# ------------------------------------------------------------------ workspace read

@dataclass
class GdrawWorkspace:
    """One parsed workspace: layer-keyed geometry (``import_dxf``-shaped) + forming.

    ``texts`` are the raw GuildDraw text objects (``state["texts"]``, filtered to
    recognised layers) — engraving is stored as a text object (string + font +
    cap-height ``size_mm`` + anchor + rotation), NOT as curves, so this reader can't
    outline it without a font engine. They are carried raw (scene coords) with the
    ``posterior`` flag; the GUI renders them to ENGRAVING polylines (``gui.text_outline``)
    applying the same scene→posterior flip the layer curves already got."""
    name: str
    layers: dict[str, list[list[Point]]]
    apical_radius_mm: float = 0.0
    bridge_angle_deg: float = 0.0
    mirror_enabled: bool = True
    mirror_x: float = 0.0
    texts: list[dict] = field(default_factory=list)
    posterior: bool = True

    def is_empty(self) -> bool:
        return not any(self.layers.values())


@dataclass
class GdrawDocument:
    """Every workspace in a ``.gdraw`` (or a single ``front`` for a plain ``.svg``)."""
    workspaces: dict[str, GdrawWorkspace]
    active_tab: str = "front"


def read_workspace_geometry(
    state: dict, chord_tol: float = CHORD_TOL_MM, posterior: bool = True,
) -> dict[str, list[list[Point]]]:
    """Flatten a workspace's ``state["curves"]`` to layer-keyed point lists.

    Mirrors :func:`io_import.dxf.import_dxf`: only recognised layers are kept, and
    ``posterior=True`` applies the single (x, y) → (-x, -y) flip.
    """
    result: dict[str, list[list[Point]]] = {k: [] for k in ALL_LAYERS}
    for curve in state.get("curves", []):
        layer = curve.get("layer")
        if layer not in ALL_LAYERS:
            continue
        pts = _flatten_curve(curve, chord_tol)
        if len(pts) < 2:
            continue
        if posterior:
            pts = [(-x, -y) for x, y in pts]
        result[layer].append(pts)
    return result


def _check_svg_bytes(data: bytes) -> None:
    if len(data) > _MAX_SVG_BYTES:
        raise GdrawError(
            f"refusing to open: SVG is {len(data) // 1_048_576} MB, over the "
            f"{_MAX_SVG_BYTES // 1_048_576} MB limit for a GuildDraw file")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise GdrawError(
            "refusing to open: the SVG declares an XML DTD or entities, which "
            "GuildDraw never writes and which can be abused for a denial-of-"
            "service (entity-expansion) attack")


def _parse_svg_state(data: bytes) -> dict:
    """Extract the GuildDraw JSON state from an SVG's ``<metadata>`` block."""
    _check_svg_bytes(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GdrawError(f"not valid XML: {exc}") from exc
    meta = root.find(f"{{{_SVG_NS}}}metadata")
    if meta is None or not (meta.text and meta.text.strip()):
        raise GdrawError("SVG has no GuildDraw metadata block")
    try:
        return json.loads(meta.text)
    except json.JSONDecodeError as exc:
        raise GdrawError(f"invalid GuildDraw metadata JSON: {exc}") from exc


def _workspace_from_state(name: str, state: dict, chord_tol: float,
                          posterior: bool) -> GdrawWorkspace:
    frm = state.get("forming", {}) or {}
    mir = state.get("mirror", {}) or {}
    texts = [dict(t) for t in (state.get("texts") or [])
             if isinstance(t, dict) and t.get("layer") in ALL_LAYERS]
    return GdrawWorkspace(
        name=name,
        layers=read_workspace_geometry(state, chord_tol, posterior),
        apical_radius_mm=float(frm.get("apical_radius_mm", 0.0) or 0.0),
        bridge_angle_deg=float(frm.get("bridge_angle_deg", 0.0) or 0.0),
        mirror_enabled=bool(mir.get("enabled", True)),
        mirror_x=float(mir.get("x", 0.0) or 0.0),
        texts=texts,
        posterior=posterior,
    )


def _empty_workspace(name: str) -> GdrawWorkspace:
    return GdrawWorkspace(name=name, layers={k: [] for k in ALL_LAYERS})


def read_gdraw(path, chord_tol: float = CHORD_TOL_MM,
               posterior: bool = True) -> GdrawDocument:
    """Read a ``.gdraw`` ZIP (or a plain ``.svg``) into a :class:`GdrawDocument`.

    Per-tab parse failures raise :class:`GdrawError` (a corrupt workspace must not
    be silently treated as empty — that lets the next save destroy it).
    """
    path = Path(path)
    if not zipfile.is_zipfile(path):
        # A plain GuildDraw .svg = a single front workspace.
        data = path.read_bytes()
        ws = _workspace_from_state("front", _parse_svg_state(data), chord_tol, posterior)
        return GdrawDocument({"front": ws}, active_tab="front")

    workspaces: dict[str, GdrawWorkspace] = {}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        active = "front"
        if "manifest.json" in names:
            try:
                manifest = json.loads(zf.read("manifest.json"))
            except json.JSONDecodeError as exc:
                raise GdrawError(f"invalid manifest.json: {exc}") from exc
            active = manifest.get("active_tab", "front")
            if active == "temple":          # legacy single-temple tab name
                active = "temple_r"

        # backward compat: old files store a single temple.svg
        compat: dict[str, str] = {}
        if "temple.svg" in names and "temple_r.svg" not in names:
            compat["temple_r"] = "temple.svg"

        for tab in TABS:
            svg_name = compat.get(tab, f"{tab}.svg")
            if svg_name not in names:
                workspaces[tab] = _empty_workspace(tab)
                continue
            try:
                state = _parse_svg_state(zf.read(svg_name))
            except GdrawError as exc:
                raise GdrawError(f"{svg_name}: {exc}") from exc
            workspaces[tab] = _workspace_from_state(tab, state, chord_tol, posterior)

    return GdrawDocument(workspaces, active_tab=active)


# ------------------------------------------------------------------ project assembly

@dataclass
class GdrawComponent:
    """A built :class:`Component` paired with its layer geometry (``import_dxf``-
    shaped) — the GUI / worker build the relief / outline / lens from ``layers``.

    ``texts`` carries the workspace's raw GuildDraw text objects (engraving); the GUI
    outlines them to ENGRAVING polylines on open (see ``GdrawWorkspace.texts``)."""
    component: Component
    layers: dict[str, list[list[Point]]]
    texts: list[dict] = field(default_factory=list)


@dataclass
class GdrawProject:
    """The multi-component project assembled from a ``.gdraw`` (BUILDPLAN M7.2)."""
    project: ProjectSchema
    components: list[GdrawComponent] = field(default_factory=list)
    active_tab: str = "front"


def _lens_centroid_x(pts: list[Point]) -> float:
    """Centroid x of a lens ring (posterior frame). OD (right) lands on +x."""
    if len(pts) >= 3:
        try:
            return float(Polygon(pts).centroid.x)
        except Exception:
            pass
    return sum(x for x, _ in pts) / len(pts) if pts else 0.0


def _forming_of(ws: GdrawWorkspace) -> FormingMetadata:
    return FormingMetadata(apical_radius_mm=ws.apical_radius_mm,
                           bridge_angle_deg=ws.bridge_angle_deg)


def build_project_from_gdraw(path) -> GdrawProject:
    """Assemble a multi-component :class:`ProjectSchema` from a ``.gdraw``.

    Produces the frame front (front workspace), both temples (temple_r / temple_l —
    ``enabled=False`` when a workspace has no OUTLINE), and one base-curve template
    per LENS in the front (split right/left by centroid x, OD on +x). Each component
    is paired with its layer geometry for downstream relief / outline / lens builds.
    """
    path = Path(path)
    doc = read_gdraw(path)
    front = doc.workspaces.get("front") or _empty_workspace("front")

    project = ProjectSchema(job_name=path.stem, source_file=str(path))
    project.forming = _forming_of(front)
    comps: list[GdrawComponent] = []

    # frame front
    ff = Component.for_kind(
        ComponentKind.FRAME_FRONT, forming=_forming_of(front),
        source_file=str(path), source_workspace="front")
    project.add_component(ff)
    comps.append(GdrawComponent(ff, front.layers, texts=list(front.texts)))

    # temples (disabled when the workspace is empty / has no outline)
    for tab, kind in _TAB_KIND.items():
        ws = doc.workspaces.get(tab) or _empty_workspace(tab)
        has_outline = bool(ws.layers.get("OUTLINE"))
        comp = Component.for_kind(
            kind, enabled=has_outline, forming=_forming_of(ws),
            source_file=str(path), source_workspace=tab)
        project.add_component(comp)
        comps.append(GdrawComponent(comp, ws.layers, texts=list(ws.texts)))

    # base-curve templates, one per front LENS (OD/+x → right, OS/-x → left)
    for lens_pts in front.layers.get("LENS", []):
        kind = (ComponentKind.BASE_CURVE_RIGHT if _lens_centroid_x(lens_pts) >= 0
                else ComponentKind.BASE_CURVE_LEFT)
        comp = Component.for_kind(
            kind, forming=_forming_of(front),
            source_file=str(path), source_workspace="front")
        project.add_component(comp)
        empty = {k: [] for k in ALL_LAYERS}
        empty["LENS"] = [lens_pts]
        comps.append(GdrawComponent(comp, empty))

    return GdrawProject(project=project, components=comps, active_tab=doc.active_tab)
