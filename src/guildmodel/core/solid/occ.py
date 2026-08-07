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

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GeomAbs import GeomAbs_Shape
from OCP.Geom import Geom_BSplineCurve
from OCP.GeomConvert import GeomConvert
from OCP.GeomAPI import (GeomAPI_Interpolate, GeomAPI_PointsToBSpline,
                         GeomAPI_ProjectPointOnCurve)
from OCP.GProp import GProp_GProps
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_HArray1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.TopAbs import TopAbs_EDGE, TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import TopTools_ListOfShape
from OCP.gp import gp_Pnt, gp_Vec

__all__ = [
    "CORNER_DEG",
    "FIT_TOL_MM",
    "BooleanError",
    "area",
    "common",
    "SourceCurves",
    "curve_ring_wire",
    "curved_ring_wire",
    "cut",
    "cut_many",
    "edge_points",
    "explore",
    "extrude",
    "fuse",
    "fuse_all",
    "is_valid",
    "mesh_volume",
    "nurbs_edge",
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


def surface_z_at(shape: TopoDS_Shape, pts_xy, missing: float = 0.0,
                 tol: float = 1e-7, face: str = "top") -> np.ndarray:
    """Exact surface height above each (x, y), by vertical ray.

    `face="bottom"` takes the lowest hit instead of the highest — the anterior
    face. In a solid the front of the frame is simply the underside; it needs no
    second heightfield and no `thickness()` invariant to keep the two from
    eating each other, which is the 2.5D scaffolding M17 had to build and the
    rewrite deletes.

    Used to anchor features that must ride the surface they are cut into — the
    eyewire bezel keeps a constant width and rim depth all the way round, which
    means following the footing swells rather than sitting at a fixed Z.

    Exact against the B-Rep rather than sampled off a mesh: there are only a few
    hundred of these per ring, and the anchor is the one thing in the feature
    that must not carry a sampling error.

    The shape is `Load`ed once and each ray fired with the curve-only `Init`.
    The three-argument `Init(shape, line, tol)` re-loads the shape *per ray*,
    which is O(faces) every time — on a 6,000-face castle that made the anchor
    rays cost more than some of the booleans they were feeding.
    """
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.GeomAdaptor import GeomAdaptor_Curve
    from OCP.Geom import Geom_Line
    from OCP.gp import gp_Ax1, gp_Dir

    inter = BRepIntCurveSurface_Inter()
    inter.Load(shape, float(tol))
    up = gp_Dir(0.0, 0.0, 1.0)
    want_top = face != "bottom"
    out = np.full(len(pts_xy), float(missing), dtype=float)
    for i, (x, y) in enumerate(pts_xy):
        line = Geom_Line(gp_Ax1(gp_Pnt(float(x), float(y), -1e4), up))
        inter.Init(GeomAdaptor_Curve(line))
        best = None
        while inter.More():
            z = inter.Pnt().Z()
            if best is None or (z > best if want_top else z < best):
                best = z
            inter.Next()
        if best is not None:
            out[i] = best
    return out


#: Relative precision for **surface** mass properties. On a planar face bounded
#: by splines the default (no `Eps`) integrates on a fixed grid and gets it
#: wrong by 4%: the demo body face reads 1546.690 mm2 by default against
#: 1483.750 adaptively, in the direction that looks like the curve added
#: material. It did not — the true outline adds 0.649 mm2 over the polygon
#: inscribed in it (exactly the chord deficit) and the true apertures take 0.889
#: back, which is what the adaptive figure shows and the theory predicts.
GPROP_EPS = 1e-6


def volume(shape: TopoDS_Shape) -> float:
    """Enclosed volume — **trustworthy only while every face is planar.**

    No `Eps`, and that is deliberate. Passing one is the obvious move after the
    surface-area finding above and it is wrong here: on a solid carrying spline
    faces `VolumeProperties_s` disagrees with itself at every setting. Two
    *disjoint* zone prisms from the demo frame, whose fused volume must be
    exactly their sum:

        setting        od          os          fused       sum
        default      985.435   1011.400     2006.927    1996.835
        Eps 1e-6     919.773   1038.664     1550.374    1958.437
        Eps 1e-9    1045.464   1051.349     2413.023    2096.813
        mesh         994.498   1013.568     2008.066    2008.066

    Only the tessellation is self-consistent, and it is exact — the fused mesh
    equals the sum of the parts to the last digit, watertight. An `Eps` of 1e-6
    was briefly shipped here and made the answer *worse*; it survives above for
    `area`, where it was verified against theory on a planar face.

    So: this stays on the default, which is exact for the polygonal solids the
    whole test suite and `bench_solid.py` are pinned to, and callers measuring
    anything that may carry a real curve use `mesh_volume`. The empty-but-valid
    guards in `build_castle_solid` only ask whether this is greater than zero,
    which no setting gets wrong.
    """
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def mesh_volume(shape: TopoDS_Shape, deflection: float = 0.005) -> float:
    """Volume via tessellation — the referee when a shape carries curves.

    Slower than `volume` and the only measurement that stays consistent once
    spline faces are involved. See `volume` for the numbers that establish that.
    """
    from .tessellate import tessellate
    return float(tessellate(shape, deflection=deflection).to_trimesh().volume)


def area(shape: TopoDS_Shape) -> float:
    """Surface area, adaptively integrated — see `GPROP_EPS`.

    Verified on a planar spline-bounded face, where adaptive integration agrees
    with theory to 0.001 mm2. Unlike `volume`, the `Eps` earns its place here.
    """
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props, GPROP_EPS)
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
        # Always down-cast: `explore` yields TopoDS_Shape, and BRepAdaptor_Curve
        # given a Shape raises "No geometry" rather than accepting it. The
        # earlier `hasattr(edge, "Orientation")` guard was inverted nonsense —
        # every TopoDS_Shape has Orientation — so this returned None for
        # literally every edge.
        ad = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
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


def _wire_signed_area(wire) -> float:
    """Sign of a wire's enclosed area, from a coarse sample of its edges.

    A wire built from trimmed arcs has no coordinate list to shoelace, and its
    direction still has to match the ring it replaces or the face comes out
    invalid. Five points per edge is far more than the sign needs.
    """
    pts = []
    for edge in explore(wire, TopAbs_EDGE):
        sampled = edge_points(edge, 5)
        if sampled:
            pts.extend((p.X(), p.Y()) for p in sampled)
    return _signed_area(pts) if len(pts) >= 3 else 0.0


def _signed_area(points) -> float:
    """Shoelace area — positive counter-clockwise. Used only for its sign.

    A closed B-spline's control polygon winds the same way the curve does, so
    this answers "which way round does this go?" for a ring of coordinates and
    for a curve's poles alike.
    """
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        return 0.0
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return 0.5 * sum(x0 * y1 - x1 * y0
                     for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


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


def nurbs_edge(curve, z: float = 0.0):
    """One `TopoDS_Edge` carrying the drawing's exact B-spline.

    Not a fit. `curve` is a `core.geometry.curves.NurbsCurve` holding the poles,
    knots, multiplicities and degree the DXF `SPLINE` was authored with, so this
    is a transcription: the resulting edge *is* the curve GuildDraw drew.

    Verified on the demo frame by projecting every point of the DXF's own
    `flattening(0.01)` onto the rebuilt curve — **worst deviation 0.0000 nm**,
    for the outline and both lens rings. Compare the re-fitting spike's 5.2 um
    (BUILDPLAN "Spline ring wires"), which is the error you get for
    reconstructing a curve from its own approximation.

    Closed DXF splines arrive *clamped* with coincident first and last poles,
    not periodic — measured, and OCCT rejects them outright as periodic
    ("# Poles and degree mismatch"). So `Periodic=False` here is not a
    simplification; it is what the data is.
    """
    vals, mults = curve.knots_and_multiplicities()

    poles = TColgp_Array1OfPnt(1, len(curve.control_points))
    for i, (x, y) in enumerate(curve.control_points, start=1):
        poles.SetValue(i, gp_Pnt(float(x), float(y), float(z)))

    knots = TColStd_Array1OfReal(1, len(vals))
    multiplicities = TColStd_Array1OfInteger(1, len(vals))
    for i, (v, m) in enumerate(zip(vals, mults), start=1):
        knots.SetValue(i, float(v))
        multiplicities.SetValue(i, int(m))

    try:
        if curve.rational:
            weights = TColStd_Array1OfReal(1, len(curve.weights))
            for i, w in enumerate(curve.weights, start=1):
                weights.SetValue(i, float(w))
            geom = Geom_BSplineCurve(poles, weights, knots, multiplicities,
                                     int(curve.degree), False)
        else:
            geom = Geom_BSplineCurve(poles, knots, multiplicities,
                                     int(curve.degree), False)
    except Exception as exc:                       # OCCT raises its own types
        raise BooleanError(f"B-spline construction failed: {exc}") from exc

    return BRepBuilderAPI_MakeEdge(geom).Edge()


def curve_ring_wire(curve, z: float = 0.0):
    """A closed wire that is ONE edge — the drawing's curve, whole.

    This is the payoff. The demo outline is 64 control points; flattened it is
    342 points and therefore 342 `TopoDS_Edge`s, and the solid carries ~3,850
    edges of which not one is a boundary of the frame in any meaningful sense.
    Here it is a single edge, exact at any zoom, and a real curve for
    curve-driven CAM to follow.
    """
    edge = nurbs_edge(curve, z)
    mw = BRepBuilderAPI_MakeWire(edge)
    if not mw.IsDone():
        raise BooleanError("curve wire did not close")
    return mw.Wire()


def ring_wire(coords, z: float = 0.0, spline: bool = False, curve=None):
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

    **`curve` is the third option, and the right one.** Where the caller can
    hand over the drawing's own `NurbsCurve` — not a fit to these coords, the
    authored definition — this returns a single exact edge. That is a different
    proposition from `spline=True` above: there is no fitting step, so none of
    the tolerance behaviour in that table applies. The polyline stays the
    fallback for geometry that genuinely has no source curve (SCULPT cuts,
    derived zone boundaries) and for any curve the kernel refuses.
    """
    if curve is not None:
        try:
            wire = curve_ring_wire(curve, z)
            # A B-spline carries its own direction, and it has nothing to do
            # with how the caller wound the Shapely ring. `polygon_to_face`
            # relies on `orient(poly, 1.0)` to get exterior-CCW / holes-CW, so a
            # curve running the other way silently produces a face OCCT calls
            # invalid — the failure this kernel likes to hand back with a
            # plausible bounding box attached. Match the ring the wire replaces.
            if _signed_area(coords) * _signed_area(curve.control_points) < 0:
                wire.Reverse()
            return wire
        except BooleanError:
            pass                      # fall through to the polyline
    if not spline:
        return polygon_ring_wire(coords, z)
    try:
        return spline_ring_wire(coords, z)
    except BooleanError:
        return polygon_ring_wire(coords, z)


#: A trimmed arc is trusted only if it stays this close to the ring polyline it
#: was derived from, in mm. A correct arc rides within the chord sagitta (<= the
#: importer's 0.01 mm flattening tolerance); a wrong-branch arc — the trim
#: sweeping the long way round a closed curve — misses by millimetres. There is
#: no middle ground, so the threshold is not delicate.
ARC_VERIFY_TOL_MM = 0.05

#: Fewest ring vertices a run must have before it is worth trying as an arc.
#: Two vertices are a chord and carry no curvature information.
MIN_ARC_VERTS = 3


class SourceCurves:
    """The authored curves behind a partition, ready to rebuild wires from.

    Holds the OCCT handles so they are built once for a whole terrace pass
    rather than once per zone, and answers the two different questions the two
    kinds of ring ask:

    * **Whole ring** — the body exterior, the lens apertures. One authored
      curve, one exact edge. `ring()`.
    * **Partial ring** — a zone boundary, which is arcs of those curves joined
      by the straight SCULPT cuts that made it. Needs each vertex tested
      against every candidate. `classify()`.
    """

    def __init__(self, partition):
        self._partition = partition
        self._curves = list(partition.curve_list()) if partition is not None else []
        self._geoms = []
        for curve in self._curves:
            try:
                edge = TopoDS.Edge_s(nurbs_edge(curve, 0.0))
                adaptor = BRepAdaptor_Curve(edge)
                self._geoms.append((BRep_Tool.Curve_s(edge, 0.0, 1.0),
                                    adaptor.FirstParameter(),
                                    adaptor.LastParameter()))
            except Exception:                                # noqa: BLE001
                self._geoms.append(None)

    def __bool__(self) -> bool:
        return any(g is not None for g in self._geoms)

    def ring(self, ring):
        return self._partition.ring_curve(ring) if self._partition else None

    def geom(self, index):
        return self._geoms[index]

    def classify(self, x: float, y: float, tol: float = 1e-3):
        """`(curve_index, parameter)` for the curve this point lies on, else
        `(None, None)`. The point must be *on* the curve, not merely near it."""
        point = gp_Pnt(float(x), float(y), 0.0)
        best = (None, None, tol)
        for i, entry in enumerate(self._geoms):
            if entry is None:
                continue
            proj = GeomAPI_ProjectPointOnCurve(point, entry[0])
            if proj.NbPoints() and proj.LowerDistance() < best[2]:
                best = (i, proj.LowerDistanceParameter(), proj.LowerDistance())
        return best[0], best[1]


def _arc_spans(tagged, source: "SourceCurves"):
    """Maximal runs of ring vertices lying on one authored curve, split where
    the run crosses that curve's start/end and verified against the ring."""
    from shapely.geometry import LineString, Point

    n = len(tagged)
    runs, i = [], 0
    while i < n:
        ci = tagged[i][2]
        if ci is None:
            i += 1
            continue
        j = i
        while j + 1 < n and tagged[j + 1][2] == ci:
            j += 1
        runs.append((i, j, ci))
        i = j + 1

    spans = []
    for (a, b, ci) in runs:
        _, u0, u1 = source.geom(ci)
        period = u1 - u0
        us = [tagged[k][3] for k in range(a, b + 1)]
        # A run passing the curve's start/end point shows up as a parameter
        # jump. Trimming straight across it sweeps the complement arc — the
        # whole rest of the outline — which is how this first presented:
        # negative areas, and one zone seven times too large.
        start = 0
        for k in range(1, len(us)):
            if abs(us[k] - us[k - 1]) > period / 2:
                if k - start >= MIN_ARC_VERTS:
                    spans.append((a + start, a + k - 1, ci, us[start], us[k - 1]))
                start = k
        if len(us) - start >= MIN_ARC_VERTS:
            spans.append((a + start, a + len(us) - 1, ci, us[start], us[-1]))

    verified = []
    for (ia, ib, ci, ua, ub) in sorted(spans):
        geom = source.geom(ci)[0]
        polyline = LineString([(tagged[k % n][0], tagged[k % n][1])
                               for k in range(ia, ib + 1)])
        ok = True
        for t in (0.15, 0.35, 0.5, 0.65, 0.85):
            q = geom.Value(float(ua) + (float(ub) - float(ua)) * t)
            if Point(q.X(), q.Y()).distance(polyline) > ARC_VERIFY_TOL_MM:
                ok = False
                break
        if ok:
            verified.append((ia, ib, ci, ua, ub))
    return verified


def _arc_edge(geom, v0, v1, ua: float, ub: float):
    """One edge carrying **only** the arc `[ua, ub]`, not the whole curve.

    `BRepBuilderAPI_MakeEdge(curve, v0, v1, ua, ub)` builds a perfectly correct
    edge, but it still references the entire curve and is merely *trimmed* in
    parameter. Extruding a zone boundary made of those gives faces whose surface
    is a 64-pole extrusion with a small window cut out of it, and the boolean
    engine and the mesher then both work on the whole surface. Cutting the arc
    out first leaves a 22-pole curve for a third of the outline. On the demo
    frame's curved build:

        whole curve, trimmed   terraces 0.95 s   full cold build 19.96 s
        segmented arc          terraces 0.40 s   full cold build 16.67 s

    Same solid: watertight either way, mesh volumes 8,004.80 vs 8,004.90 mm3.

    It does **not** repair `volume()` — `BRepGProp` still reads ~17 mm3 light on
    the curved terraces (7,987.6 against a true 8,004.9), so `mesh_volume` is
    still the one to measure these with.

    Knot insertion is exact, so this is a re-spelling and not an approximation.

    A run winding against the curve arrives with `ua > ub`, and the two
    parameters must still be handed over **in the run's order**: they are
    matched against `v0` and `v1` positionally, so passing the ascending pair
    with descending vertices makes `MakeEdge` refuse the edge outright. OCCT
    then normalises internally and returns a FORWARD edge over the ascending
    range, which is fine — ring direction is settled once, on the finished wire,
    by `polygon_to_face`.
    """
    lo, hi = (ua, ub) if ua <= ub else (ub, ua)
    # `GeomConvert.SplitBSplineCurve_s`, not `Segment` on a downcast copy:
    # `Geom_Geometry.Copy()` hands back the base type and this OCP build exposes
    # no `DownCast_s`, so that route raises AttributeError — and the caller falls
    # back on *any* exception, so it fails silently. It cost an afternoon of
    # believing a speedup that was really the polyline fallback being fast.
    seg = GeomConvert.SplitBSplineCurve_s(geom, float(lo), float(hi), 1e-9)
    first, last = seg.FirstParameter(), seg.LastParameter()
    pa, pb = (first, last) if ua <= ub else (last, first)
    return BRepBuilderAPI_MakeEdge(seg, v0, v1, pa, pb).Edge()


def curved_ring_wire(coords, z: float, source: "SourceCurves"):
    """A wire that uses the authored curves wherever the ring follows them.

    This is what makes the *model* curved rather than just its outer silhouette.
    `build_terraces` extrudes **zone** polygons, and a zone boundary is arcs of
    the outline and lens rings joined by the straight SCULPT cuts that severed
    them — so a whole-ring lookup finds nothing and the polygon survives. On the
    demo frame ~94% of every zone's vertices lie on an authored curve, in two to
    five clean runs, and rebuilding those as trimmed arcs takes the nine zones
    from 649 ring vertices to 170 edges with every area inside 0.5 mm2.

    Raises `BooleanError` if no arc survives verification, so the caller can
    fall back to the plain polygon rather than pay for this twice.

    **Vertices are shared explicitly.** Arc endpoints are exact points on the
    curve; straight endpoints are flattened ring vertices; the two differ by up
    to the flattening tolerance. Left to match them by proximity,
    `BRepBuilderAPI_MakeWire` stitched the gap where it could and produced a
    disordered wire where it could not — while still reporting `IsDone()`.
    Building each `TopoDS_Vertex` once and handing it to both neighbours took
    this from five of nine zones to seven.
    """
    pts = list(coords)
    if len(pts) > 1 and tuple(pts[0][:2]) == tuple(pts[-1][:2]):
        pts = pts[:-1]
    if len(pts) < 3:
        raise BooleanError(f"ring has only {len(pts)} distinct points")

    tagged = [(float(x), float(y)) + source.classify(x, y) for x, y in
              ((p[0], p[1]) for p in pts)]
    n = len(tagged)
    spans = _arc_spans(tagged, source)
    if not spans:
        raise BooleanError("no verified arc on this ring")

    def ring_pnt(k):
        return gp_Pnt(tagged[k % n][0], tagged[k % n][1], float(z))

    # Describe the ring as an ordered segment list, then realise it.
    segs, cursor = [], 0
    for (ia, ib, ci, ua, ub) in spans:
        if ia < cursor:
            continue                       # overlaps a span already taken
        for k in range(cursor, ia):
            segs.append(("line", k, 0, 0))
        segs.append(("arc", ci, ua, ub, ia, ib))
        cursor = ib
    for k in range(cursor, n):
        segs.append(("line", k, 0, 0))

    starts = [source.geom(s[1])[0].Value(float(s[2])) if s[0] == "arc"
              else ring_pnt(s[1]) for s in segs]
    verts = [BRepBuilderAPI_MakeVertex(p).Vertex() for p in starts]

    edges = []
    for idx, seg in enumerate(segs):
        v0, v1 = verts[idx], verts[(idx + 1) % len(segs)]
        if seg[0] == "arc":
            _, ci, ua, ub, ia, ib = seg
            try:
                edges.append(_arc_edge(source.geom(ci)[0], v0, v1, ua, ub))
                continue
            except Exception:                                # noqa: BLE001
                pass
            # A rejected arc falls back to the vertices it was derived from —
            # NOT to one chord across the whole span. Cutting that corner left
            # two zones wrong by +180 and +225 mm2, which is how we learned
            # those failures were never about the curves at all.
            prev = v0
            for k in range(ia + 1, ib):
                nxt = BRepBuilderAPI_MakeVertex(ring_pnt(k)).Vertex()
                try:
                    edges.append(BRepBuilderAPI_MakeEdge(prev, nxt).Edge())
                    prev = nxt
                except Exception:                            # noqa: BLE001
                    continue
            try:
                edges.append(BRepBuilderAPI_MakeEdge(prev, v1).Edge())
            except Exception:                                # noqa: BLE001
                pass
            continue
        try:
            edges.append(BRepBuilderAPI_MakeEdge(v0, v1).Edge())
        except Exception:                                    # noqa: BLE001
            pass                            # coincident junction: no edge needed

    mw = BRepBuilderAPI_MakeWire()
    for edge in edges:
        mw.Add(edge)
    if not mw.IsDone():
        raise BooleanError("curved ring wire did not close")
    return mw.Wire()


def polygon_to_face(poly: Polygon, z: float = 0.0, spline: bool = False,
                    curves=None):
    """Planar face at height `z`, holes included.

    The hole wires must wind **opposite** to the outer wire, and must be added
    as they are — reversing them on top of that produces a face OCCT reports as
    invalid while still handing back a shape with a plausible-looking bounding
    box, so the mistake surfaces later as an empty boolean rather than as an
    error. `orient(poly, 1.0)` normalises to exterior-CCW / holes-CW regardless
    of how the caller's polygon was wound, so this does not depend on Shapely's
    incoming convention.

    `curves` is anything with a `ring_curve(ring)` method — in practice a
    `CastlePartition` — used to look up the authored `NurbsCurve` behind each
    ring. Where one is found the wire is a single exact edge instead of one
    edge per flattened vertex; where it is not, nothing changes.
    """
    poly = orient(poly, 1.0)

    # Accept a bare CastlePartition as well as a prepared SourceCurves. Callers
    # building many faces (build_terraces) should pass the latter so the OCCT
    # handles are made once; a one-off caller should not have to know that.
    source = curves
    if source is not None and not hasattr(source, "ring"):
        source = SourceCurves(source)

    def wire_for(ring):
        if source is None:
            return ring_wire(ring.coords, z, spline)
        # Fast path: the whole ring is one authored curve (the body exterior,
        # the apertures) — one exact edge, no per-vertex work.
        curve = source.ring(ring)
        if curve is not None:
            return ring_wire(ring.coords, z, spline, curve=curve)
        # Otherwise the ring may still *follow* authored curves in runs, which
        # is what every zone boundary does.
        if source:
            try:
                wire = curved_ring_wire(ring.coords, z, source)
                if _signed_area(ring.coords) * _wire_signed_area(wire) < 0:
                    wire.Reverse()
                return wire
            except BooleanError:
                pass
        return ring_wire(ring.coords, z, spline)

    mf = BRepBuilderAPI_MakeFace(wire_for(poly.exterior))
    for interior in poly.interiors:
        mf.Add(wire_for(interior))
    return mf.Face()


def extrude(face, height: float) -> TopoDS_Shape:
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, float(height))).Shape()


def polyline_wire(pts_xy: np.ndarray, z: float):
    mp = BRepBuilderAPI_MakePolygon()
    for x, y in pts_xy:
        mp.Add(gp_Pnt(float(x), float(y), float(z)))
    return mp.Wire()


def closed_spline_wire(pts_xy: np.ndarray, z: float):
    """A closed periodic B-spline through the points, as a one-edge wire.

    For sweeping around an aperture ring. An *open* fit through the same points
    fails here: the first and last stations are neighbours on the ring, so the
    approximating fit has no room to resolve them and `MakePipeShell` comes back
    with `BRepAdaptor_Curve::No geometry`. Periodic interpolation closes the
    spine properly and leaves no seam for the sweep to trip on.
    """
    arr = TColgp_HArray1OfPnt(1, len(pts_xy))
    for i, (x, y) in enumerate(pts_xy, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), float(z)))
    it = GeomAPI_Interpolate(arr, True, 1e-7)
    it.Perform()
    if not it.IsDone():
        raise BooleanError("closed spine interpolation failed")
    return BRepBuilderAPI_MakeWire(
        BRepBuilderAPI_MakeEdge(it.Curve()).Edge()).Wire()


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
    # OCCT's boolean core is thread-parallel and it is simply off by default.
    # Measured on the demo frame's all-features build: 82.0 s -> 62.2 s, with a
    # bit-identical result (same volume, same face count). There is no accuracy
    # trade here — it is the same algorithm on more cores.
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise BooleanError(f"{label}: operation did not complete")
    return op.Shape()


def cut(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Cut(a, b), "cut")


def cut_many(target: TopoDS_Shape, tools: list[TopoDS_Shape]) -> TopoDS_Shape:
    """Subtract every tool in ONE boolean pass.

    Not the same thing as `cut(target, fuse_all(tools))`, and not the same thing
    as cutting them one at a time — both of those were measured and both are
    worse:

    * **Fuse first, then cut.** Fusing the demo frame's eight feature cutters
      into a single tool costs 23.6 s on its own and the cut that follows costs
      31.8 s. OCCT's boolean cost is superlinear in the complexity of *both*
      operands, so building one enormous tool is the wrong direction.
    * **One cut per tool.** Each result carries the previous tool's faces, so
      the target inflates as you go — 1,244 -> 6,471 faces across the demo
      build, and the last cuts pay for all the earlier ones. Cutting the groove
      out of the inflated 5,349-face solid cost 9.6 s; the same groove against
      the un-inflated target is part of a 7.5 s pass that does two other
      features as well.

    One pass with N tools keeps the target at its original complexity and lets
    the kernel intersect everything once: 32.9 s -> 7.5 s for the demo frame's
    bezel + edge features + groove, with a volume delta of 0.00 mm3.

    **The caller owns the ordering question.** This is only equivalent to
    sequential cutting when the tools do not depend on one another — see
    `build_castle_solid`, where the features that read the surface beneath them
    stay sequential and only the independent ones come here.
    """
    if not tools:
        return target
    if len(tools) == 1:
        return cut(target, tools[0])
    op = BRepAlgoAPI_Cut()
    args, tool_list = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(target)
    for t in tools:
        tool_list.Append(t)
    op.SetArguments(args)
    op.SetTools(tool_list)
    return _run(op, "cut_many")


def fuse(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Fuse(a, b), "fuse")


def common(a: TopoDS_Shape, b: TopoDS_Shape) -> TopoDS_Shape:
    return _run(BRepAlgoAPI_Common(a, b), "common")


def fuse_all(shapes: list[TopoDS_Shape]) -> TopoDS_Shape:
    """Union every shape in ONE boolean pass.

    Same reasoning as `cut_many`, and the same measurement. Folding them
    pairwise re-does the accumulated result's intersections on every step, so
    the cost climbs as the union grows. Uniting the demo frame's terrace solid
    with its ten footing fills:

        pairwise fold      3.2 s polygonal   3.3 s curved
        one multi-tool     0.35 s            0.54 s

    identical mesh volume in every case.

    Unlike `cut_many` this needs no ordering caveat: a union is commutative and
    associative, so one pass is always the same answer as any fold.
    """
    if not shapes:
        raise BooleanError("nothing to fuse")
    if len(shapes) == 1:
        return shapes[0]
    op = BRepAlgoAPI_Fuse()
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(shapes[0])
    for s in shapes[1:]:
        tools.Append(s)
    op.SetArguments(args)
    op.SetTools(tools)
    return _run(op, "fuse_all")
