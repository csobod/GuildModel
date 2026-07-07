"""Per-component workspace state for the component notebook (BUILDPLAN M7.3).

A :class:`ComponentWorkspace` is one component's working set — its layer geometry,
the derived polygons (outline / lenses / SCULPT partition / hinges / engraving), the
per-component mesh stage cache, generated artifacts, and readiness — over the
MainWindow's *single shared* set of heavy views (2D canvas, 3D preview, cut-sim).
On a component-tab switch the window swaps its active ``self._*`` working set to the
selected workspace, so the existing build / generate / simulate code operates on
the active component transparently (one live set of VTK views, not five).

`derive_workspace` and `build_workspaces_from_gdraw` are pure (shapely + core, no
Qt), so the multi-component intake is unit-tested without a Qt platform.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guildmodel.core.project.schema import ComponentKind, component_label


@dataclass
class ComponentWorkspace:
    """One component's working set (see module docstring)."""
    kind: ComponentKind
    label: str
    layers: dict
    enabled: bool = True
    source_workspace: str = ""
    forming: object = None
    # Raw GuildDraw text objects (engraving) for this workspace; the GUI outlines them
    # to ENGRAVING polylines on open (fonts need Qt, so not done in this pure module).
    texts: list = field(default_factory=list)
    # Set once derive_workspace has applied the temple Y-axis re-orientation, so a
    # re-derive never double-flips the layers.
    layers_oriented: bool = False

    # per-component editable params (pushed into / pulled from the kind-aware
    # param dock on a tab switch, M7.3). Exactly one is populated, per kind;
    # None means "leave the dock as-is" (a plain DXF frame uses the panel state).
    castle_params: object = None
    temple_params: object = None
    block_params: object = None
    program_zero: object = None     # per-component G54 datum (M11); None = panel default

    # derived geometry (filled by derive_workspace)
    outline_poly: object = None
    lens_od: object = None
    lens_os: object = None
    partition: object = None
    hinge_polys: list = field(default_factory=list)
    engraving_curves: list = field(default_factory=list)
    is_temple: bool = False
    matched: bool = False
    boxing: object = None

    # per-component mesh + generated artifacts + readiness (swapped on tab switch)
    stage: str = "pockets"
    stage_cache: dict = field(default_factory=dict)
    mesh_built: bool = False
    core_guide: object = None        # temple injected-core bar bounds (3D marker)
    last_programs: dict = field(default_factory=dict)
    last_setup: object = None
    last_machine: object = None
    last_report: object = None
    program_stored: bool = False
    diag: dict = field(default_factory=dict)   # M7.14 inspector inputs (reach/clearance/lint)


def derive_workspace(ws: ComponentWorkspace, boxing=None) -> ComponentWorkspace:
    """Fill ``ws``'s derived geometry from ``ws.layers`` — the same extraction the
    DXF import does (outline / lenses / OD-OS / SCULPT partition / hinges /
    engraving / is_temple / matched / boxing). Pure shapely; no Qt.

    A frame front has an OUTLINE + two LENS curves (+ SCULPT for the castle); a
    temple has an OUTLINE and no lenses; a base-curve template carries its single
    LENS (placed in ``lens_od`` so the block generator can build from it).
    """
    from guildmodel.core.geometry.boxing import measure_from_polygon
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.normalize import points_to_polygon

    layers = ws.layers

    # Temples are drawn in the POSTERIOR view in GuildDraw, but the reader applies the
    # frame-front's anterior->posterior x-mirror to every workspace — over-mirroring a
    # temple so its geometry (and engraving) reads backwards. Reflect a temple back
    # across the Y axis (negate X) once, up front, so the whole part builds correctly.
    # A temple is an OUTLINE with no lens openings; temple-ness is invariant under the
    # flip, so the pre-flip check is valid. Idempotent via `layers_oriented`.
    if not ws.layers_oriented:
        _outline = layers.get("OUTLINE", [])
        _lenses = [points_to_polygon(c) for c in layers.get("LENS", []) if len(c) >= 3]
        if _outline and not any(p.is_valid and p.area > 1.0 for p in _lenses):
            layers = ws.layers = {lyr: [[(-x, y) for x, y in c] for c in curves]
                                  for lyr, curves in layers.items()}
        ws.layers_oriented = True

    ws.engraving_curves = list(layers.get("ENGRAVING", []))

    outline_curves = layers.get("OUTLINE", [])
    ws.outline_poly = points_to_polygon(outline_curves[0]) if outline_curves else None

    lens_polys = [points_to_polygon(c) for c in layers.get("LENS", []) if len(c) >= 3]
    valid_lens = [p for p in lens_polys if p.is_valid and p.area > 1.0]

    # A temple is an outline with no lenses (no castle relief).
    ws.is_temple = ws.outline_poly is not None and len(valid_lens) == 0
    if len(valid_lens) >= 2:
        ordered = sorted(valid_lens, key=lambda p: p.centroid.x)
        ws.lens_os, ws.lens_od = ordered[0], ordered[-1]      # OD on +x (posterior)
    elif len(valid_lens) == 1:
        ws.lens_od = valid_lens[0]                            # base-curve template's lens

    ws.hinge_polys = [
        p for p in (points_to_polygon(c) for c in layers.get("HINGE", []) if len(c) >= 3)
        if p.is_valid and p.area > 0.5
    ]

    sculpt = layers.get("SCULPT", [])
    if ws.outline_poly is not None and len(valid_lens) >= 2 and sculpt:
        ws.partition = partition_zones(ws.outline_poly, valid_lens[:2], sculpt)
        ws.matched = bool(ws.partition.matched)

    if boxing is not None:
        ws.boxing = boxing
    elif len(valid_lens) >= 2:
        try:
            ws.boxing = measure_from_polygon(valid_lens[0], valid_lens[1])
        except Exception:
            ws.boxing = None
    return ws


def build_workspaces_from_gdraw(path) -> tuple[list[ComponentWorkspace], str]:
    """Read a ``.gdraw`` and build a derived :class:`ComponentWorkspace` per
    component (frame front + both temples + a base-curve template per lens). Pure;
    no Qt. Returns ``(workspaces, active_tab)`` — the front is always index 0.
    """
    from guildmodel.core.io_import.gdraw import build_project_from_gdraw

    gp = build_project_from_gdraw(path)
    out: list[ComponentWorkspace] = []
    for gc in gp.components:
        c = gc.component
        ws = ComponentWorkspace(
            kind=c.kind, label=component_label(c.kind), layers=gc.layers,
            enabled=c.enabled, source_workspace=c.source_workspace, forming=c.forming,
            texts=list(gc.texts),
            castle_params=c.castle, temple_params=c.temple,
            block_params=c.base_curve_block)
        derive_workspace(ws)
        out.append(ws)
    return out, gp.active_tab
