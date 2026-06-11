"""DXF importer.

Reads recognised layers from a DXF file (see core.layers.ALL_LAYERS).
Flattens arcs, splines, and polylines to point lists at chord_tol precision.
GuildDraw exports with Y negated (DXF Y-up convention); ezdxf reads this correctly.

GuildDraw draws the ANTERIOR view of the frame front; all GuildCAM modeling and
machining happens on the POSTERIOR. import_dxf() therefore mirrors x -> -x by
default (posterior=True) so every downstream consumer works in posterior
coordinates. This is the single flip point in the pipeline (BUILDPLAN M1.2).
"""
from __future__ import annotations
from pathlib import Path
import math
import ezdxf
from ezdxf.math import Vec3

from guildcam.core.layers import ALL_LAYERS

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


def import_dxf(
    path: Path,
    chord_tol: float = CHORD_TOL_MM,
    posterior: bool = True,
) -> dict[str, list[list[tuple[float, float]]]]:
    """Return layer-keyed lists of point-list curves from a DXF file.

    posterior=True (default) mirrors x -> -x: GuildDraw DXF is the anterior
    view, GuildCAM coordinates are posterior. Pass False only for tooling that
    must see the raw drawing (e.g. side-by-side debug against GuildDraw).
    """
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()

    result: dict[str, list[list[tuple[float, float]]]] = {k: [] for k in ALL_LAYERS}

    for entity in msp:
        layer = entity.dxf.layer.upper()
        if layer not in ALL_LAYERS:
            continue
        dxf_type = entity.dxftype()

        if dxf_type == "LWPOLYLINE":
            pts = _lwpolyline_to_points(entity)
            if pts:
                result[layer].append(pts)
        elif dxf_type == "POLYLINE":
            pts = [(v.x, v.y) for v in entity.points()]
            if pts:
                result[layer].append(pts)
        elif dxf_type == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            result[layer].append([(s.x, s.y), (e.x, e.y)])
        elif dxf_type == "ARC":
            result[layer].append(_arc_to_points(entity, chord_tol))
        elif dxf_type == "CIRCLE":
            cx, cy, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
            n = max(16, int(2 * math.pi * r / chord_tol))
            pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
            result[layer].append(pts)
        elif dxf_type == "SPLINE":
            approx = list(entity.flattening(chord_tol))
            result[layer].append([(v.x, v.y) for v in approx])

    if posterior:
        result = {
            layer: [[(-x, y) for x, y in curve] for curve in curves]
            for layer, curves in result.items()
        }

    return result
