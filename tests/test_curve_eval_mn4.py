"""Evaluating the drawing's own curves, without the kernel (BUILDPLAN-NEW M-N4).

`geometry.rings.offset_aperture` was the last thing pulling OpenCASCADE into a
mesh-kernel G-code build — 349 OCP modules for the lens groove against zero for
every other feature — and only because sampling an exact offset needed OCCT's
`GCPnts_QuasiUniformDeflection`. `curves.sample_curve` replaces that sampler.

**Everything here is measured against OCCT, not against closed forms.** A
circle's offset is a circle, so a self-consistent evaluator with the sign
backwards still passes every analytic check; the demo frame's two lens rings
wind opposite ways and one would grow while the other shrank. The same curves
still reach the kernel through `occ.nurbs_edge`, so the two representations have
to be the same curve, and that is what these assert.
"""
import numpy as np
import pytest

TOL_MM = 1e-9


def _occ_geom(curve):
    """The same curve as OCCT builds it, for comparison."""
    from OCP.BRep import BRep_Tool
    from guildmodel.core.solid.occ import nurbs_edge

    return BRep_Tool.Curve_s(nurbs_edge(curve, 0.0), 0.0, 1.0)


def _occ_point(geom, u):
    from OCP.gp import gp_Pnt

    p = gp_Pnt()
    geom.D0(float(u), p)
    return np.array([p.X(), p.Y()])


def _occ_tangent(geom, u):
    from OCP.gp import gp_Pnt, gp_Vec

    p, v = gp_Pnt(), gp_Vec()
    geom.D1(float(u), p, v)
    t = np.array([v.X(), v.Y()])
    return t / np.linalg.norm(t)


def _curves():
    """A rational curve, a non-rational one, and a real drawing's rings."""
    from pathlib import Path

    from guildmodel.core.geometry.curves import circle_curve, cubic_bezier_chain
    from guildmodel.core.io_import.dxf import import_curves

    out = [("circle (rational, degree 2)", circle_curve((2.0, -1.0), 12.0)),
           ("bezier chain (cubic)",
            cubic_bezier_chain([((0.0, 0.0), (4.0, 6.0), (10.0, -6.0), (14.0, 0.0)),
                                ((14.0, 0.0), (18.0, 6.0), (24.0, -6.0), (28.0, 0.0))]))]
    fixture = (Path(__file__).parent / "fixtures" / "demo"
               / "GuildDraw DXF Export.dxf")
    _layers, curves = import_curves(fixture)
    for layer in ("OUTLINE", "LENS"):
        for i, c in enumerate(curves.get(layer, [])[:2]):
            out.append((f"demo {layer} {i}", c))
    return out


@pytest.mark.parametrize("label,curve", _curves(), ids=lambda v: v if isinstance(v, str) else "")
def test_the_evaluator_is_on_the_same_curve_as_the_kernel(label, curve):
    """Point and tangent, at 97 parameters across the domain.

    97 rather than a round number so the samples do not land on the knots, which
    are where a de Boor span index is easiest to get wrong and where a bug would
    hide behind exact agreement at the multiple-knot ends.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")

    geom = _occ_geom(curve)
    lo, hi = curve.domain
    worst_p = worst_t = 0.0
    for u in np.linspace(lo, hi, 97):
        worst_p = max(worst_p, np.linalg.norm(curve.point(u) - _occ_point(geom, u)))
        worst_t = max(worst_t, np.linalg.norm(curve.tangent(u) - _occ_tangent(geom, u)))
    assert worst_p < TOL_MM, f"{label}: point differs by {worst_p:.3e} mm"
    assert worst_t < 1e-7, f"{label}: tangent differs by {worst_t:.3e}"


@pytest.mark.parametrize("distance", [-0.75, 0.75, -0.2])
def test_the_offset_sign_matches_occt(distance):
    """The one that a circle alone cannot catch.

    `OffsetCurve.point` places the offset at `C(u) + d * (Z x T)`. Get the sign
    backwards and every analytic check on a circle still passes — it is a
    circle either way — while the demo frame's two lens rings, which wind
    opposite ways, would have one grow and the other shrink. So this compares
    against `Geom_OffsetCurve` itself, on a curve with no symmetry to hide in.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.geometry.curves import OffsetCurve, cubic_bezier_chain

    basis = cubic_bezier_chain(
        [((0.0, 0.0), (4.0, 6.0), (10.0, -6.0), (14.0, 0.0)),
         ((14.0, 0.0), (18.0, 6.0), (24.0, -6.0), (28.0, 0.0))])
    offset = OffsetCurve(basis=basis, distance=distance)
    geom = _occ_geom(offset)

    lo, hi = offset.domain
    worst = max(np.linalg.norm(offset.point(u) - _occ_point(geom, u))
                for u in np.linspace(lo, hi, 97))
    assert worst < TOL_MM, (
        f"offset {distance} differs from Geom_OffsetCurve by {worst:.3e} mm — "
        "a sign flip here puts the rim lip on the wrong side of the contour")


@pytest.mark.parametrize("tol", [0.01, 0.001, 0.0001])
def test_the_sampler_honors_its_chord_tolerance(tol):
    """Every chord must sit within `tol` of the curve, and the point count must
    fall as the tolerance loosens — an adaptive sampler that quietly always
    subdivides to `max_depth` would pass the first half alone."""
    from guildmodel.core.geometry.curves import circle_curve, sample_curve

    center, radius = np.array([2.0, -1.0]), 12.0
    pts = sample_curve(circle_curve(tuple(center), radius), tol)
    assert len(pts) > 8

    mids = 0.5 * (pts[:-1] + pts[1:])
    sagitta = radius - np.linalg.norm(mids - center, axis=1)
    assert sagitta.max() <= tol * 1.001, (
        f"worst sagitta {sagitta.max() * 1000:.4f} um against a {tol * 1000:.1f} um "
        "tolerance")
    assert len(sample_curve(circle_curve(tuple(center), radius), tol * 10)) < len(pts)


def test_a_closed_ring_is_not_collapsed_by_its_own_symmetry():
    """A closed curve returns to its start with the same tangent, so bisection
    that only asks "is the midpoint far from the chord?" can stop at one
    segment. `_MAX_SAMPLE_STEP` forces the first few splits regardless; without
    it a whole aperture comes back as a couple of points."""
    from guildmodel.core.geometry.curves import circle_curve, sample_curve

    pts = sample_curve(circle_curve((0.0, 0.0), 10.0), 0.01)
    assert len(pts) > 50, f"a closed ring sampled to {len(pts)} points"
    r = np.linalg.norm(pts, axis=1)
    assert r.min() > 9.9, "sampling wandered off the circle"


def test_the_sampler_agrees_with_the_one_it_replaces():
    """Against `GCPnts_QuasiUniformDeflection` at the same tolerance, on the
    real aperture curve `offset_aperture` uses it for. The two need not place
    points identically — one is quasi-uniform, this one is adaptive — so the
    measure is Hausdorff distance between the polylines they produce.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from pathlib import Path

    from shapely.geometry import LineString
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection

    from guildmodel.core.geometry.curves import OffsetCurve, sample_curve
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.solid.occ import nurbs_edge

    fixture = (Path(__file__).parent / "fixtures" / "demo"
               / "GuildDraw DXF Export.dxf")
    _layers, curves = import_curves(fixture)
    lens = curves["LENS"][0]
    offset = OffsetCurve(basis=lens, distance=-0.6)

    mine = sample_curve(offset, 0.01)
    sampler = GCPnts_QuasiUniformDeflection(
        BRepAdaptor_Curve(nurbs_edge(offset, 0.0)), 0.01)
    theirs = [(sampler.Value(i).X(), sampler.Value(i).Y())
              for i in range(1, sampler.NbPoints() + 1)]

    gap = LineString(mine).hausdorff_distance(LineString(theirs))
    assert gap < 0.01, f"the two samplings are {gap * 1000:.2f} um apart"
