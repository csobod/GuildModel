"""Interactive worktable: a user-defined cutting bed from DXF (BUILDPLAN M7.4).

Reads a bed drawn in CAD, `polygonize`s its closed loops into candidate regions
the maker tags by role (frame-front / temple R-L / base-curve R-L / keep-out), and
loads the built-in Guild fixture (`config/fixtures/guild_cnc.yaml`) as the default
bed. The `Worktable` model itself lives in `project/schema.py`; this module is the
DXF intake + the config/`.bed` I/O around it.

Bed DXFs are in **machine coordinates** (origin lower-left, Y up) — unlike the
frame-front DXF there is no anterior→posterior flip; the linework is read as drawn.
"""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import yaml
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from ..project.schema import BedRole, Worktable, WorktableZone, bed_role_label

CHORD_TOL_MM = 0.05
_MIN_REGION_AREA_MM2 = 1.0   # drop polygonize slivers
_CIRCLE_SEGMENTS = 48


class WorktableError(Exception):
    """Raised on an unreadable or empty bed DXF."""


# ------------------------------------------------------------------ DXF intake

def _arc_pts(entity, tol: float) -> list[tuple[float, float]]:
    cx, cy = entity.dxf.center.x, entity.dxf.center.y
    r = entity.dxf.radius
    a0 = math.radians(entity.dxf.start_angle)
    a1 = math.radians(entity.dxf.end_angle)
    if a1 <= a0:
        a1 += 2 * math.pi
    half = math.acos(max(-1.0, 1.0 - tol / r)) if r > 0 else math.pi
    n = max(2, math.ceil((a1 - a0) / (2 * half)))
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _circle_ring(cx: float, cy: float, r: float,
                 segments: int = _CIRCLE_SEGMENTS) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * k / segments),
             cy + r * math.sin(2 * math.pi * k / segments)) for k in range(segments)]


def read_bed_linework(
    path, chord_tol: float = CHORD_TOL_MM,
) -> tuple[list[list[tuple[float, float]]], list[tuple[float, float, float]]]:
    """Read every drawable entity from a bed DXF (all layers) into open/closed
    polylines plus a list of true circles (cx, cy, r). Machine coordinates as
    drawn — no posterior flip."""
    try:
        doc = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as exc:
        raise WorktableError(f"Cannot read {Path(path).name}: {exc}") from exc
    msp = doc.modelspace()

    segments: list[list[tuple[float, float]]] = []
    circles: list[tuple[float, float, float]] = []
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = [(v[0], v[1]) for v in e.get_points("xy")]
            if e.closed and len(pts) >= 3:
                pts = pts + [pts[0]]
            if len(pts) >= 2:
                segments.append(pts)
        elif t == "POLYLINE":
            pts = [(v.x, v.y) for v in e.points()]
            if getattr(e, "is_closed", False) and len(pts) >= 3:
                pts = pts + [pts[0]]
            if len(pts) >= 2:
                segments.append(pts)
        elif t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            segments.append([(s.x, s.y), (en.x, en.y)])
        elif t == "ARC":
            segments.append(_arc_pts(e, chord_tol))
        elif t == "CIRCLE":
            circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
        elif t == "SPLINE":
            segments.append([(v.x, v.y) for v in e.flattening(chord_tol)])
    return segments, circles


def polygonize_bed(
    segments: list[list[tuple[float, float]]],
    circles: list[tuple[float, float, float]],
    *, min_area: float = _MIN_REGION_AREA_MM2,
) -> list[tuple[list[tuple[float, float]], float | None]]:
    """Turn bed linework into candidate regions: every CIRCLE is its own region
    (radius known — a likely keep-out screw); the remaining linework is unioned
    and `polygonize`d into faces (radius None). Returns (ring, radius_or_None)."""
    faces: list[tuple[list[tuple[float, float]], float | None]] = []
    for cx, cy, r in circles:
        faces.append((_circle_ring(cx, cy, r), r))

    lines = [LineString(s) for s in segments if len(s) >= 2]
    if lines:
        merged = unary_union(lines)
        for poly in polygonize(merged):
            if poly.area >= min_area:
                ring = [(float(x), float(y)) for x, y in poly.exterior.coords[:-1]]
                faces.append((ring, None))
    return faces


def build_worktable_from_dxf(
    path, *, name: str | None = None, chord_tol: float = CHORD_TOL_MM,
    work_area: tuple[float, float] | None = None,
) -> Worktable:
    """Import a bed DXF into a `Worktable` of untagged regions (BUILDPLAN M7.4).

    Each polygonized region is an `UNASSIGNED` zone; the maker tags roles in the
    Worktable tab (or a caller via `Worktable.set_role`). The work area defaults to
    the geometry's positive-quadrant extent (a lower-left-origin bed)."""
    path = Path(path)
    segments, circles = read_bed_linework(path, chord_tol)
    faces = polygonize_bed(segments, circles)
    if not faces:
        raise WorktableError(
            f"No closed regions found in {path.name} — is it a bed outline DXF?")

    zones = [
        WorktableZone(
            id=f"region_{i + 1}", role=BedRole.UNASSIGNED,
            label=bed_role_label(BedRole.UNASSIGNED),
            polygon=ring, radius_mm=radius, source=f"dxf:{path.name}")
        for i, (ring, radius) in enumerate(faces)
    ]

    if work_area is None:
        xs = [p[0] for z in zones for p in z.polygon]
        ys = [p[1] for z in zones for p in z.polygon]
        w = max(xs) if xs else 300.0
        h = max(ys) if ys else 200.0
    else:
        w, h = work_area

    return Worktable(
        name=name or path.stem, display_name=name or path.stem,
        work_area_width_mm=w, work_area_height_mm=h,
        zones=zones, source_dxf=path.name)


# ------------------------------------------------------------------ default bed

def _config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def load_fixture_dict(name: str = "guild_cnc", config_dir=None) -> dict:
    """Read a built-in fixture YAML (config/fixtures/<name>.yaml) as a dict."""
    base = Path(config_dir) if config_dir is not None else _config_dir()
    return yaml.safe_load((base / "fixtures" / f"{name}.yaml").read_text(encoding="utf-8"))


def default_worktable(name: str = "guild_cnc", config_dir=None) -> Worktable:
    """The built-in Guild fixture as a `Worktable` (the default bed, M7.4)."""
    return Worktable.from_fixture_dict(load_fixture_dict(name, config_dir), name=name)


# ------------------------------------------------------------------ .bed I/O

def save_bed(worktable: Worktable, path) -> None:
    """Persist a worktable as a reusable `.bed` (YAML) for a shop's fixtures."""
    data = worktable.model_dump(mode="json")     # JSON-native: tuples → lists, enums → values
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def load_bed(path) -> Worktable:
    """Load a `.bed` (YAML) worktable written by `save_bed`."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Worktable.model_validate(data)
