"""DXF importer.

Reads recognised layers from a DXF file (see core.layers.ALL_LAYERS).
Flattens arcs, splines, and polylines to point lists at chord_tol precision.
GuildDraw exports with Y negated (DXF Y-up convention); ezdxf reads this correctly.

GuildDraw draws the ANTERIOR view of the frame front; all GuildModel modeling and
machining happens on the POSTERIOR. import_dxf() therefore mirrors x -> -x by
default (posterior=True) so every downstream consumer works in posterior
coordinates. This is the single flip point in the pipeline (BUILDPLAN M1.2).

**Splines are also kept as splines.** Flattening still happens and still drives
everything that wants points — the CAM, the raster, Shapely — but a `SPLINE`
entity's actual definition is now preserved alongside it in `import_curves()`,
so the B-Rep path can build the exact curve instead of a 342-segment
approximation of it. See `core.geometry.curves` for why re-fitting the flattened
points is not the same thing and does not work.
"""
from __future__ import annotations
from pathlib import Path
import math
import ezdxf

from guildmodel.core.geometry.curves import NurbsCurve, mirror_x
from guildmodel.core.layers import ALL_LAYERS

SUPPORTED_LAYERS = ALL_LAYERS   # public alias kept for callers that import this name
CHORD_TOL_MM = 0.01


def _arc_to_points(entity, tol: float) -> list[tuple[float, float]]:
    cx, cy = entity.dxf.center.x, entity.dxf.center.y
    r = entity.dxf.radius
    a0 = math.radians(entity.dxf.start_angle)
    a1 = math.radians(entity.dxf.end_angle)
    if a1 <= a0:
        a1 += 2 * math.pi
    half_angle = math.acos(max(-1.0, 1.0 - tol / r)) if r > 0 else math.pi
    n = max(2, math.ceil((a1 - a0) / (2 * half_angle)))
    angles = [a0 + (a1 - a0) * i / n for i in range(n + 1)]
    return [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]


def _lwpolyline_to_points(entity) -> list[tuple[float, float]]:
    return [(v[0], v[1]) for v in entity.get_points("xy")]


def _spline_curve(entity, layer: str) -> NurbsCurve | None:
    """The entity's own B-spline definition, or None if it is unusable.

    Never raises: an odd spline is a reason to fall back to the flattened
    points, which are always produced anyway, not a reason to fail the import.
    """
    try:
        # ezdxf hands control points back as bare sequences (numpy rows), not
        # as Vec3 — indexing works for both, attribute access only for one.
        cps = [(float(p[0]), float(p[1])) for p in entity.control_points]
        if not cps:
            return None
        weights = [float(w) for w in entity.weights]
        curve = NurbsCurve(
            control_points=cps,
            knots=[float(k) for k in entity.knots],
            degree=int(entity.dxf.degree),
            closed=bool(entity.closed),
            weights=weights if weights else None,
            layer=layer,
        )
    except Exception:
        return None
    return curve if curve.is_consistent() else None


def import_curves(
    path: Path,
    chord_tol: float = CHORD_TOL_MM,
    posterior: bool = True,
) -> tuple[dict[str, list[list[tuple[float, float]]]],
           dict[str, list[NurbsCurve | None]]]:
    """`(points, curves)` — the flattened geometry, and what it was flattened from.

    The two dicts are **index-aligned**: `curves[layer][i]` is the exact curve
    that produced `points[layer][i]`, or None where the source was genuinely a
    polyline (or a spline we could not read). Parallel lists rather than a
    richer point type on purpose — every consumer downstream does list
    comprehensions over these points, and any attribute hung on the list would
    be silently dropped by the first one.
    """
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()

    result: dict[str, list[list[tuple[float, float]]]] = {k: [] for k in ALL_LAYERS}
    curves: dict[str, list[NurbsCurve | None]] = {k: [] for k in ALL_LAYERS}

    def add(layer: str, pts, curve: NurbsCurve | None = None) -> None:
        result[layer].append(pts)
        curves[layer].append(curve)

    for entity in msp:
        layer = entity.dxf.layer.upper()
        if layer not in ALL_LAYERS:
            continue
        dxf_type = entity.dxftype()

        if dxf_type == "LWPOLYLINE":
            pts = _lwpolyline_to_points(entity)
            if pts:
                add(layer, pts)
        elif dxf_type == "POLYLINE":
            pts = [(v.x, v.y) for v in entity.points()]
            if pts:
                add(layer, pts)
        elif dxf_type == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            add(layer, [(s.x, s.y), (e.x, e.y)])
        elif dxf_type == "ARC":
            add(layer, _arc_to_points(entity, chord_tol))
        elif dxf_type == "CIRCLE":
            cx, cy, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
            n = max(16, int(2 * math.pi * r / chord_tol))
            pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
            add(layer, pts)
        elif dxf_type == "SPLINE":
            approx = list(entity.flattening(chord_tol))
            add(layer, [(v.x, v.y) for v in approx], _spline_curve(entity, layer))

    if posterior:
        # The single flip point in the pipeline — and it has to move BOTH
        # representations, or the curve and the points describe different frames.
        result = {
            layer: [[(-x, y) for x, y in pts] for pts in layer_pts]
            for layer, layer_pts in result.items()
        }
        curves = {
            layer: [mirror_x(c) if c is not None else None for c in layer_curves]
            for layer, layer_curves in curves.items()
        }

    return result, curves


def import_dxf(
    path: Path,
    chord_tol: float = CHORD_TOL_MM,
    posterior: bool = True,
) -> dict[str, list[list[tuple[float, float]]]]:
    """Return layer-keyed lists of point-list curves from a DXF file.

    posterior=True (default) mirrors x -> -x: GuildDraw DXF is the anterior
    view, GuildModel coordinates are posterior. Pass False only for tooling that
    must see the raw drawing (e.g. side-by-side debug against GuildDraw).

    Points only. Callers that can use the exact source curves — the B-Rep path —
    want `import_curves`, which returns these same points plus what they were
    flattened from.
    """
    return import_curves(path, chord_tol, posterior)[0]
