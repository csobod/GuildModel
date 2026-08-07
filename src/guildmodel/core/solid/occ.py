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
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.GProp import GProp_GProps
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Pnt, gp_Vec

__all__ = [
    "BooleanError",
    "common",
    "cut",
    "edge_points",
    "explore",
    "extrude",
    "fuse",
    "fuse_all",
    "is_valid",
    "polygon_to_face",
    "polyline_wire",
    "ring_wire",
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

def ring_wire(coords, z: float):
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


def polygon_to_face(poly: Polygon, z: float = 0.0):
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
    mf = BRepBuilderAPI_MakeFace(ring_wire(poly.exterior.coords, z))
    for interior in poly.interiors:
        mf.Add(ring_wire(interior.coords, z))
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
