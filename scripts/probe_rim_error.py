#!/usr/bin/env python3
"""Measure the rim-vertex Z error that makes the cutting features look pitted.

Evidence for `BREP-REWRITE-REPORT.md` §1.2. Run it to re-derive the numbers in
that report, or to check whether a fix actually moved them.

The defect: `castle._conform_rim` projects each silhouette vertex onto the true
outline / lens ring **in XY only**, keeping the Z it was carved with at the cell
centre. A chamfer anchored to that ring has not reached full depth at the cell
centre, so every rim vertex is left proud by `d * tan(angle)`, where `d` is the
cell's true distance to the ring — which varies quasi-periodically as the ring's
curvature beats against the grid. The result is a moiré ripple on the one line
that should be the crispest on the part.

Two independent measurements:

  A. PREDICTED, on a synthetic aperture — the error the bezel's own arithmetic
     implies, across grid resolutions. No fixtures, fully deterministic.
  B. OBSERVED, on the Demo Project frame — the Z jitter of the actual conformed
     rim vertices walking around a real lens aperture. This is the pitting
     itself, measured on the shipping code path.

Usage:
    DISPLAY= .venv/bin/python scripts/probe_rim_error.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEMO = ROOT / "tests" / "fixtures" / "demo"

BEZEL_WIDTH_MM = 1.2
BEZEL_ANGLE_DEG = 45.0


# --------------------------------------------------------- A. predicted error

def predicted_error() -> None:
    """The error implied by `features._carve_eyewire_bezel` on a clean ellipse.

    Isolates the sampling term: no footing swells, no clamping, no zone
    boundaries — just the distance from each rim cell centre to the true ring.
    """
    from scipy.ndimage import binary_dilation
    from shapely import contains_xy, distance, points
    from shapely.geometry import Polygon

    tan_a = float(np.tan(np.radians(BEZEL_ANGLE_DEG)))

    outer = Polygon([(-20, -15), (20, -15), (20, 15), (-20, 15)])
    t = np.linspace(0, 2 * np.pi, 721)[:-1]
    hole = Polygon(np.column_stack([12.0 * np.cos(t), 8.5 * np.sin(t)]))
    body = outer.difference(hole)
    ring = hole.exterior

    print("A. PREDICTED — synthetic 24 x 17 mm aperture")
    print(f"   bezel width {BEZEL_WIDTH_MM} mm, angle {BEZEL_ANGLE_DEG}deg")
    print()
    print(f"   {'res (mm)':>9}  {'cells':>6}  {'mean':>7}  {'max':>7}  {'p-p':>7}")

    for res in (0.30, 0.15, 0.05):
        ox, oy = -22.0, -17.0
        cols, rows = int(44 / res), int(34 / res)
        X, Y = np.meshgrid(ox + np.arange(cols) * res, oy + np.arange(rows) * res)
        inside = contains_xy(body, X.ravel(), Y.ravel()).reshape(rows, cols)

        # The innermost ring of body cells — the ones `_conform_rim` snaps.
        adj = inside & binary_dilation(~inside) & (np.abs(X) < 14) & (np.abs(Y) < 10.5)
        d = distance(points(X[adj], Y[adj]), ring)
        err = d * tan_a          # z_cell - z_at_ring, always >= 0 (material left)

        print(f"   {res:>9.2f}  {len(d):>6d}  {err.mean():>7.3f}  {err.max():>7.3f}"
              f"  {err.max() - err.min():>7.3f}")
    print()
    print("   Error scales linearly with resolution: raising the grid always")
    print("   helps and never fixes it.")
    print()


# ---------------------------------------------------------- B. observed error

def observed_jitter() -> None:
    """Z jitter of the real conformed rim vertices on the Demo Project frame.

    Walks the mesh's rim vertices around one lens aperture in arc-length order
    and reports the step-to-step Z change. A chamfer rim that followed the true
    curve would vary smoothly with the footing swells underneath it; the ripple
    reported here is the sampling artifact riding on top of that.
    """
    from shapely import line_locate_point, points
    from shapely.geometry import LineString

    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_relief

    dxf = DEMO / "GuildDraw DXF Export.dxf"
    if not dxf.exists():
        print(f"B. OBSERVED — skipped, fixture missing: {dxf}")
        return

    raw = import_dxf(dxf)
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    castle.eyewire_bezel.width_mm = BEZEL_WIDTH_MM
    castle.eyewire_bezel.angle_deg = BEZEL_ANGLE_DEG

    print("B. OBSERVED — Demo Project frame, eyewire bezel on")
    print(f"   {'res (mm)':>9}  {'rim pts':>7}  {'|dz| mean':>10}  {'|dz| max':>9}")

    for res in (0.30, 0.15):
        relief = build_castle_relief(part, castle, hinges, resolution=res)
        mesh = build_castle_mesh(relief, conform=True)

        # The largest lens aperture, and the mesh vertices sitting on it.
        ring = max((LineString(r) for r in relief.mask_body.interiors),
                   key=lambda r: r.length)
        v = np.asarray(mesh.vertices)
        near = np.abs(v[:, 2]) > 1e-9        # drop the flat anterior twins
        cand = v[near]
        d = np.asarray([ring.distance(p) for p in points(cand[:, 0], cand[:, 1])])
        on_ring = cand[d < 1e-6]
        if len(on_ring) < 16:
            print(f"   {res:>9.2f}  {len(on_ring):>7d}   (too few rim vertices)")
            continue

        s = line_locate_point(ring, points(on_ring[:, 0], on_ring[:, 1]))
        order = np.argsort(s)
        dz = np.abs(np.diff(on_ring[order, 2]))
        print(f"   {res:>9.2f}  {len(on_ring):>7d}  {dz.mean():>10.4f}  {dz.max():>9.4f}")
    print()
    print("   Step-to-step Z change along a rim that should be a smooth curve.")
    print()


if __name__ == "__main__":
    predicted_error()
    observed_jitter()
