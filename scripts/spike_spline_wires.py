#!/usr/bin/env python3
"""Spike: B-spline ring wires instead of polygons (BUILDPLAN Stage 2).

**The problem.** `occ.ring_wire` builds each contour straight from the Shapely
coordinate list, so the demo outline's 342 vertices become 342 one-segment
`TopoDS_Edge`s. Those are real boundaries but they are not curves. Stage 4's
curve-driven CAM wants an exact curve to drive a tool along; a 342-segment
polyline is closer to today's raster situation than to the goal.

**The thing that makes it non-trivial.** A zone polygon's boundary is a mixture
of outline arc and SCULPT cut line, meeting at genuine corners. Fitting one
spline around the whole ring would smooth across those corners and destroy the
terrace steps. So the ring has to be split at corners first, and only the smooth
runs between them fitted.

**What this measures**, against the Demo Project frame:
  * edge count before/after
  * geometric deviation of the fitted curve from the source polyline
  * whether terraces still fuse, footings still sweep, booleans still hold
  * timing

Two fitting strategies are compared, because they trade differently:
  interpolate — passes exactly through every source point (C2, zero error at
                the samples, but inherits the discretisation's own wobble)
  approximate — fits within a tolerance (smoother, fewer poles, recovers
                something closer to the DXF's original spline)

Usage:
    DISPLAY= .venv/bin/python scripts/spike_spline_wires.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEMO = ROOT / "tests" / "fixtures" / "demo"

from OCP.BRepBuilderAPI import (                                     # noqa: E402
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSpline  # noqa: E402
from OCP.GeomAbs import GeomAbs_Shape                                # noqa: E402
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_HArray1OfPnt       # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum                              # noqa: E402
from OCP.gp import gp_Pnt                                            # noqa: E402

CORNER_DEG = 25.0      # turn angle above which a vertex is a real corner
APPROX_TOL_MM = 0.005  # chordal tolerance for the approximating fit


# ------------------------------------------------------------ ring splitting

def ring_coords(ring) -> np.ndarray:
    pts = np.asarray(ring.coords, dtype=float)
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts


def corner_mask(pts: np.ndarray, corner_deg: float) -> np.ndarray:
    """True where the contour turns by more than `corner_deg` — a real corner.

    Wraps, because the coordinate list's start is arbitrary and a corner can sit
    on it.
    """
    prev = pts - np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0) - pts
    pn = np.linalg.norm(prev, axis=1)
    nn = np.linalg.norm(nxt, axis=1)
    ok = (pn > 1e-12) & (nn > 1e-12)
    cosang = np.ones(len(pts))
    cosang[ok] = np.clip(
        (prev[ok] * nxt[ok]).sum(axis=1) / (pn[ok] * nn[ok]), -1.0, 1.0)
    return np.degrees(np.arccos(cosang)) > corner_deg


def smooth_runs(pts: np.ndarray, corners: np.ndarray) -> list[np.ndarray]:
    """Split the closed ring into runs between corners (inclusive endpoints)."""
    idx = np.where(corners)[0]
    if len(idx) == 0:
        return [np.vstack([pts, pts[:1]])]          # no corners: one closed run
    runs = []
    for a, b in zip(idx, np.roll(idx, -1)):
        if b > a:
            seg = pts[a:b + 1]
        else:
            seg = np.vstack([pts[a:], pts[:b + 1]])
        if len(seg) >= 2:
            runs.append(seg)
    return runs


# -------------------------------------------------------------- curve fitting

def _interp_curve(seg: np.ndarray, z: float):
    arr = TColgp_HArray1OfPnt(1, len(seg))
    for i, (x, y) in enumerate(seg, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), z))
    it = GeomAPI_Interpolate(arr, False, 1e-7)
    it.Perform()
    if not it.IsDone():
        raise RuntimeError("interpolation failed")
    return it.Curve()


def _approx_curve(seg: np.ndarray, z: float, tol: float):
    arr = TColgp_Array1OfPnt(1, len(seg))
    for i, (x, y) in enumerate(seg, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), z))
    return GeomAPI_PointsToBSpline(arr, 3, 8, GeomAbs_Shape.GeomAbs_C2,
                                   float(tol)).Curve()


def spline_ring_wire(ring, z: float, mode: str, corner_deg: float = CORNER_DEG,
                     tol: float = APPROX_TOL_MM):
    pts = ring_coords(ring)
    runs = smooth_runs(pts, corner_mask(pts, corner_deg))
    mw = BRepBuilderAPI_MakeWire()
    curves = []
    for seg in runs:
        if len(seg) < 4:
            # Too short to fit: keep the polyline segments verbatim.
            for a, b in zip(seg[:-1], seg[1:]):
                mw.Add(BRepBuilderAPI_MakeEdge(
                    gp_Pnt(float(a[0]), float(a[1]), z),
                    gp_Pnt(float(b[0]), float(b[1]), z)).Edge())
            continue
        curve = (_interp_curve(seg, z) if mode == "interpolate"
                 else _approx_curve(seg, z, tol))
        curves.append((curve, seg))
        mw.Add(BRepBuilderAPI_MakeEdge(curve).Edge())
    if not mw.IsDone():
        raise RuntimeError("wire did not close")
    return mw.Wire(), runs, curves


def deviation(curves) -> tuple[float, float]:
    """Max and RMS distance from each source point to its fitted curve."""
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve

    errs = []
    for curve, seg in curves:
        for x, y in seg:
            p = gp_Pnt(float(x), float(y), 0.0)
            proj = GeomAPI_ProjectPointOnCurve(p, curve)
            if proj.NbPoints() > 0:
                errs.append(proj.LowerDistance())
    if not errs:
        return 0.0, 0.0
    e = np.array(errs)
    return float(e.max()), float(np.sqrt((e ** 2).mean()))


# ------------------------------------------------------------------- harness

def load_demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams()


def n_edges(shape) -> int:
    from guildmodel.core.solid.occ import explore

    return sum(1 for _ in explore(shape, TopAbs_ShapeEnum.TopAbs_EDGE))


def main() -> None:
    from guildmodel.core.solid import build as B
    from guildmodel.core.solid.occ import (
        extrude, fuse_all, is_valid, polygon_to_face, volume)
    from guildmodel.core.solid.tessellate import tessellate

    part, castle = load_demo()
    print("=" * 74)
    print("Spike: B-spline ring wires vs polygonal ring wires — Demo Project")
    print("=" * 74)

    body = part.body
    pts = ring_coords(body.exterior)
    corners = corner_mask(pts, CORNER_DEG)
    print(f"\noutline: {len(pts)} vertices, {int(corners.sum())} corners "
          f"above {CORNER_DEG}deg -> {len(smooth_runs(pts, corners))} smooth runs")
    for lr in body.interiors:
        lp = ring_coords(lr)
        lc = corner_mask(lp, CORNER_DEG)
        print(f"lens ring: {len(lp)} vertices, {int(lc.sum())} corners "
              f"-> {len(smooth_runs(lp, lc))} runs")

    print("\n--- fit quality on the outline " + "-" * 42)
    for mode in ("interpolate", "approximate"):
        t0 = time.perf_counter()
        wire, runs, curves = spline_ring_wire(body.exterior, 0.0, mode)
        dt = time.perf_counter() - t0
        mx, rms = deviation(curves)
        ne = sum(1 for _ in __import__("itertools").count(0)) if False else None
        print(f"  {mode:12s} {len(curves):3d} spline edges  "
              f"max dev {mx * 1000:7.3f} um   rms {rms * 1000:7.3f} um   "
              f"[{dt * 1000:.0f} ms]")

    print("\n--- does the solid still build? " + "-" * 41)
    heights = B.zone_heights(part, castle)

    # Baseline: today's polygonal path.
    t0 = time.perf_counter()
    base = B.build_castle_solid(part, castle)
    tb = time.perf_counter() - t0
    tess_b = tessellate(base)
    print(f"  polygonal (today)   valid={is_valid(base)}  "
          f"vol={volume(base):8.2f}  edges={n_edges(base):5d}  "
          f"build {tb:5.2f}s  tris={len(tess_b.faces):6d}  "
          f"tess-edges={len(tess_b.edges):5d}")

    # Spline zone faces -> terraces only (the footing sweep machinery is
    # unchanged, so terrace validity is what this spike is really asking).
    for mode in ("interpolate", "approximate"):
        try:
            t0 = time.perf_counter()
            solids = []
            for zone in part.zones:
                poly = zone.polygon
                if poly.is_empty or poly.area <= 0:
                    continue
                outer, _, _ = spline_ring_wire(poly.exterior, 0.0, mode)
                mf = BRepBuilderAPI_MakeFace(outer)
                for interior in poly.interiors:
                    hole, _, _ = spline_ring_wire(interior, 0.0, mode)
                    mf.Add(hole)
                solids.append(extrude(mf.Face(), heights[zone.name]))
            terr = fuse_all(solids)
            dt = time.perf_counter() - t0
            tess = tessellate(terr)
            print(f"  spline/{mode:11s} valid={is_valid(terr)}  "
                  f"vol={volume(terr):8.2f}  edges={n_edges(terr):5d}  "
                  f"build {dt:5.2f}s  tris={len(tess.faces):6d}  "
                  f"tess-edges={len(tess.edges):5d}")
        except Exception as exc:                             # noqa: BLE001
            print(f"  spline/{mode:11s} FAILED — {type(exc).__name__}: {exc}")

    poly_terr = B.build_terraces(part, heights)
    print(f"  polygonal terraces  valid={is_valid(poly_terr)}  "
          f"vol={volume(poly_terr):8.2f}  edges={n_edges(poly_terr):5d}")


if __name__ == "__main__":
    main()
