"""Thin bridge between Shapely/NumPy and OpenCASCADE (BUILDPLAN Stage 2).

Everything in `core/solid` speaks OCCT through this module, so the kernel's API
quirks live in one place. Two of them cost time during the Stage 1 spike and are
worth stating up front:

* `BRep_Tool.Curve_s` does **not** return the parameter range through the OCP
  binding the way the C++ signature suggests. Use `BRepAdaptor_Curve`, which is
  what `edge_points` does.
* `SetTransitionMode` takes a `BRepBuilderAPI_TransitionMode` enum member, not
  the plain int the OCCT docs imply.

Importing this module pulls in OCP (~70 MB of shared libraries), so nothing on
the application's startup path may import `core.solid` eagerly — the splash in
`gui/boot.py` exists to get ahead of exactly this kind of cost for VTK.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GeomAbs import GeomAbs_Shape
from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSpline
from OCP.GProp import GProp_GProps
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_HArray1OfPnt
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Pnt, gp_Vec

__all__ = [
    "CORNER_DEG",
    "FIT_TOL_MM",
    "BooleanError",
    "common",
    "cut",
    "edge_points",
    "explore",
    "extrude",
    "fuse",
    "fuse_all",
    "is_valid",
    "polygon_ring_wire",
    "polygon_to_face",
    "polyline_wire",
    "ring_wire",
    "spline_ring_wire",
    "spline_wire",
    "volume",
]


class BooleanError(RuntimeError):
    """A kernel operation did not complete, or completed into an invalid shape.

    Raised rather than returned because every caller in `core/solid` treats a
    failed boolean as fatal to the build: a silently-dropped feature would post
    G-code for geometry the maker never asked for.
    """


# ----------------------------------------------------------------- inspection

def is_valid(shape: TopoDS_Shape) -> bool:
    """`BRepCheck_Analyzer` — the check a mesh cannot offer.

    A valid solid tessellates to a closed mesh by construction, which is the
    whole reason the readiness dot can trust it before export.
    """
    return BRepCheck_Analyzer(shape).IsValid()


def volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def explore(shape: TopoDS_Shape, kind: TopAbs_ShapeEnum) -> Iterator[TopoDS_Shape]:
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        yield exp.Current()
        exp.Next()


def edge_points(edge, n: int = 5) -> list[gp_Pnt] | None:
    """`n` points along an edge, or None if it carries no curve.

    Via `BRepAdaptor_Curve`: the OCP binding of `BRep_Tool.Curve_s` returns only
    the curve, not the parameter range, so the range has to come from an adaptor
    regardless.
    """
    try:
        ad = BRepAdaptor_Curve(TopoDS.Edge_s(edge) if not hasattr(edge, "Orientation")
                               else edge)
        u0, u1 = ad.FirstParameter(), ad.LastParameter()
        if not (np.isfinite(u0) and np.isfinite(u1)):
            return None
        return [ad.Value(u0 + (u1 - u0) * i / (n - 1)) for i in range(n)]
    except Exception:                                        # noqa: BLE001
        return None


# -------------------------------------------------------------- construction

#: Turn angle above which a contour vertex is a genuine corner rather than
#: discretisation. A zone boundary is a mixture of outline arc and SCULPT cut
#: meeting at real corners; fitting one curve straight around the ring would
#: smooth those away and destroy the terrace steps.
CORNER_DEG = 25.0

#: Chordal tolerance for the approximating fit, mm. Measured on the demo
#: outline: 4.7 um worst case, 1.4 um rms — 30x tighter than the 0.15 mm raster
#: this replaces, and invisible against any acetate machining tolerance.
FIT_TOL_MM = 0.005


def polygon_ring_wire(coords, z: float):
    """Closed polygonal wire at height `z` from a Shapely coordinate sequence."""
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise BooleanError(f"ring has only {len(pts)} distinct points")
    mp = BRepBuilderAPI_MakePolygon()
    for x, y in pts:
        mp.Add(gp_Pnt(float(x), float(y), float(z)))
    mp.Close()
    return mp.Wire()


def _ring_points(coords) -> np.ndarray:
    pts = np.asarray(list(coords), dtype=float)[:, :2]
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts


def _corner_mask(pts: np.ndarray, corner_deg: float) -> np.ndarray:
    """True where the contour turns by more than `corner_deg`. Wraps, because
    the coordinate list's start is arbitrary and a corner can land on it."""
    prev = pts - np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0) - pts
    pn, nn = np.linalg.norm(prev, axis=1), np.linalg.norm(nxt, axis=1)
    ok = (pn > 1e-12) & (nn > 1e-12)
    cosang = np.ones(len(pts))
    cosang[ok] = np.clip(
        (prev[ok] * nxt[ok]).sum(axis=1) / (pn[ok] * nn[ok]), -1.0, 1.0)
    return np.degrees(np.arccos(cosang)) > corner_deg


def _runs_between_corners(pts: np.ndarray, corners: np.ndarray):
    """(runs, closed). A ring with no corners is one closed run."""
    idx = np.where(corners)[0]
    if len(idx) == 0:
        return [pts], True
    runs = []
    for a, b in zip(idx, np.roll(idx, -1)):
        seg = pts[a:b + 1] if b > a else np.vstack([pts[a:], pts[:b + 1]])
        if len(seg) >= 2:
            runs.append(seg)
    return runs, False


def _periodic_curve(seg: np.ndarray, z: float):
    """Closed C2 curve through every point — no seam.

    Periodic *interpolation* rather than approximation: a closed run has no
    corner to hide a tangent break at, and the lens apertures are the most
    visible edges on the part. `GeomAPI_PointsToBSpline` has no periodic mode,
    so an approximating fit here would join end-to-start with a crease.
    """
    arr = TColgp_HArray1OfPnt(1, len(seg))
    for i, (x, y) in enumerate(seg, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), float(z)))
    it = GeomAPI_Interpolate(arr, True, 1e-7)
    it.Perform()
    if not it.IsDone():
        raise BooleanError("periodic interpolation failed")
    return it.Curve()


def _approx_curve(seg: np.ndarray, z: float, tol: float):
    arr = TColgp_Array1OfPnt(1, len(seg))
    for i, (x, y) in enumerate(seg, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), float(z)))
    return GeomAPI_PointsToBSpline(arr, 3, 8, GeomAbs_Shape.GeomAbs_C2,
                                   float(tol)).Curve()


def spline_ring_wire(coords, z: float, corner_deg: float = CORNER_DEG,
                     tol: float = FIT_TOL_MM):
    """Closed wire of B-spline edges, split at genuine corners.

    Replaces one `TopoDS_Edge` per source vertex with one per smooth run: the
    demo outline goes from 342 straight edges to 4 curves plus its 4 corners,
    and each lens ring to a single closed curve. That is what Stage 4's
    curve-driven CAM needs to drive a tool along, and what lets the viewer draw
    122 meaningful edges instead of 3,549 segments.

    Falls back to polyline segments for any run too short to fit or that the
    fitter rejects — a contour that will not fit is not a reason to fail the
    build, it is a reason for that stretch to stay faceted.
    """
    pts = _ring_points(coords)
    if len(pts) < 3:
        raise BooleanError(f"ring has only {len(pts)} distinct points")
    runs, closed = _runs_between_corners(pts, _corner_mask(pts, corner_deg))

    mw = BRepBuilderAPI_MakeWire()
    for seg in runs:
        curve = None
        if len(seg) >= 4:
            try:
                curve = (_periodic_curve(seg, z) if closed
                         else _approx_curve(seg, z, tol))
            except Exception:                                # noqa: BLE001
                curve = None
        if curve is not None:
            mw.Add(BRepBuilderAPI_MakeEdge(curve).Edge())
            continue
        pl = np.vstack([seg, seg[:1]]) if closed else seg
        for a, b in zip(pl[:-1], pl[1:]):
            mw.Add(BRepBuilderAPI_MakeEdge(
                gp_Pnt(float(a[0]), float(a[1]), float(z)),
                gp_Pnt(float(b[0]), float(b[1]), float(z))).Edge())
    if not mw.IsDone():
        raise BooleanError("ring wire did not close")
    return mw.Wire()


def ring_wire(coords, z: float, spline: bool = False):
    """Closed wire at height `z`.

    **Polygonal by default, deliberately.** `spline_ring_wire` produces a far
    better wire — 5.2 um worst-case deviation on the demo outline, and 244 edges
    where the polygon needs 3,850 — but a *planar face* built on spline
    boundaries misbehaves in OCCT 7.9 on this geometry, and no fit tolerance
    fixes it:

        fit tol   face tris   prism tris   watertight   GProp volume err
        5e-3 mm           0      119,229        False       -105.06 mm^3
        1e-3 mm         991       23,184         True        -55.59
        1e-4 mm       1,077      103,028         True        -79.03
        1e-5 mm       1,453      126,430         True        +22.35

    The polygonal prism does the same shape in 1,360 triangles with an exact
    volume. Note the failure signature is the house style for this kernel: the
    face reports `BRepCheck_Analyzer.IsValid()` throughout, and returns three
    different areas depending on how you ask. See BUILDPLAN "Stage 2 progress"
    for the route that gets the benefit without this risk — refit smooth edge
    chains at *extraction* time, for CAM and display, rather than changing the
    faces the booleans run on.
    """
    if not spline:
        return polygon_ring_wire(coords, z)
    try:
        return spline_ring_wire(coords, z)
    except BooleanError:
        return polygon_ring_wire(coords, z)


def polygon_to_face(poly: Polygon, z: float = 0.0, spline: bool = False):
    """Planar face at height `z`, holes included.

    The hole wires must wind **opposite** to the outer wire, and must be added
    as they are — reversing them on top of that produces a face OCCT reports as
    invalid while still handing back a shape with a plausible-looking bounding
    box, so the mistake surfaces later as an empty boolean rather than as an
    error. `orient(poly, 1.0)` normalises to exterior-CCW / holes-CW regardless
    of how the caller's polygon was wound, so this does not depend on Shapely's
    incoming convention.
    """
    poly = orient(poly, 1.0)
    mf = BRepBuilderAPI_MakeFace(ring_wire(poly.exterior.coords, z, spline))
    for interior in poly.interiors:
        mf.Add(ring_wire(interior.coords, z, spline))
    return mf.Face()


def extrude(face, height: float) -> TopoDS_Shape:
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, float(height))).Shape()


def polyline_wire(pts_xy: np.ndarray, z: float):
    mp = BRepBuilderAPI_MakePolygon()
    for x, y in pts_xy:
        mp.Add(gp_Pnt(float(x), float(y), float(z)))
    return mp.Wire()


def spline_wire(pts_xy: np.ndarray, z: float):
    """A B-spline fitted through the points, as a one-edge wire.

    Stage 1 finding, and it is the opposite of the obvious guess: for
    `MakePipeShell` the fitted spline is the *easy* spine and the raw polyline is
    the hard one. Sweeping the demo brow along the ring's own vertices failed
    `MakeSolid()` after 5 s; the spline through the same stations built in 0.14 s.
    """
    arr = TColgp_Array1OfPnt(1, len(pts_xy))
    for i, (x, y) in enumerate(pts_xy, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), float(z)))
    curve = GeomAPI_PointsToBSpline(arr).Curve()
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve).Edge()).Wire()


# ------------------------------------------------------------------ booleans

def _run(op, label: str) -> TopoDS_Shape:
    op.Build()
    if not op.IsDone():
        raise BooleanError(f"{label}: operation did not complete")
    return op.Shape()


def cut(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Cut(a, b), "cut")


def fuse(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Fuse(a, b), "fuse")


def common(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Common(a, b), "common")


def fuse_all(shapes: list[TopoDS_Shape]) -> TopoDS_Shape:
    if not shapes:
        raise BooleanError("nothing to fuse")
    out = shapes[0]
    for s in shapes[1:]:
        out = fuse(out, s)
    return out
