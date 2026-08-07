"""The drawing's own curves, carried through instead of thrown away.

GuildDraw exports NURBS; the DXF holds `SPLINE` entities (the demo outline is 64
control points of a closed cubic). The importer used to flatten them on sight,
so every stage downstream — regions, relief, the B-Rep solid, the CAM — only
ever saw polygons, and the solid's "3,850 real edges" were 3,850 straight lines.

These pin the alternative: capture the authored definition alongside the
flattened points, and hand it to OCCT as-is. The claim that matters is
**exactness** — this is a transcription, not a fit, which is what separates it
from the rejected re-fitting spike (BUILDPLAN "Spline ring wires", 5.2 um).
"""
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf"


@pytest.fixture(scope="module")
def imported():
    from guildmodel.core.io_import.dxf import import_curves
    return import_curves(DEMO)


def test_the_demo_frame_is_made_of_splines(imported):
    """If this ever fails the drawing changed, and the rest is moot."""
    points, curves = imported
    assert curves["OUTLINE"][0] is not None, "the outline is a SPLINE in the DXF"
    outline = curves["OUTLINE"][0]
    assert outline.degree == 3
    assert outline.closed
    # 64 control points describe what flattens to 342 points.
    assert len(outline.control_points) == 64
    assert len(points["OUTLINE"][0]) > 300
    assert [len(c.control_points) for c in curves["LENS"]] == [13, 7]


def test_points_and_curves_stay_index_aligned(imported):
    """`curves[layer][i]` must describe `points[layer][i]` — the whole contract."""
    points, curves = imported
    for layer in points:
        assert len(points[layer]) == len(curves[layer]), layer


def test_polylines_report_no_curve(imported):
    """SCULPT cuts are drawn as polylines and must not acquire a curve."""
    _, curves = imported
    assert curves["SCULPT"], "the demo has SCULPT cuts"
    assert all(c is None for c in curves["SCULPT"])


def test_the_posterior_flip_moves_both_representations():
    """M1.2's single flip point has to mirror the curve too, or the curve and
    the points end up describing different frames."""
    from guildmodel.core.io_import.dxf import import_curves

    (ant_pts, ant_curves) = import_curves(DEMO, posterior=False)
    (post_pts, post_curves) = import_curves(DEMO, posterior=True)

    a, p = ant_curves["OUTLINE"][0], post_curves["OUTLINE"][0]
    assert np.allclose(a.control_points[:, 0], -p.control_points[:, 0])
    assert np.allclose(a.control_points[:, 1], p.control_points[:, 1])
    # knots and degree describe the basis, which mirroring does not touch
    assert np.allclose(a.knots, p.knots)
    # and the flattened points agree with the flipped curve's hull
    assert post_pts["OUTLINE"][0][0][0] == pytest.approx(-ant_pts["OUTLINE"][0][0][0])


def test_the_rebuilt_curve_is_exact_not_a_fit(imported):
    """**The claim.** Every point of the DXF's own flattening must lie ON the
    curve rebuilt from the DXF's control points — to numerical zero.

    The re-fitting spike managed 5.2 um worst case and was rejected for the
    faces it produced. That 5.2 um is a fit error against the curve's own
    approximation and should not exist; here there is no fitting step, so it
    does not.
    """
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    from guildmodel.core.solid.occ import nurbs_edge

    points, curves = imported
    worst = 0.0
    for layer in ("OUTLINE", "LENS"):
        for pts, curve in zip(points[layer], curves[layer]):
            edge = TopoDS.Edge_s(nurbs_edge(curve, 0.0))
            geom = BRep_Tool.Curve_s(edge, 0.0, 1.0)
            for x, y in pts:
                proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(x, y, 0.0), geom)
                if proj.NbPoints():
                    worst = max(worst, proj.LowerDistance())
    assert worst < 1e-6, f"worst deviation {worst * 1e6:.4f} um — that is a fit"


def test_a_ring_becomes_one_edge_not_three_hundred(imported):
    """The payoff: the outline is a single exact edge instead of 342 chords."""
    from OCP.TopAbs import TopAbs_EDGE
    from guildmodel.core.solid.occ import curve_ring_wire, explore, polygon_ring_wire

    points, curves = imported
    coords = points["OUTLINE"][0]

    poly_edges = sum(1 for _ in explore(polygon_ring_wire(coords, 0.0), TopAbs_EDGE))
    curve_edges = sum(1 for _ in explore(curve_ring_wire(curves["OUTLINE"][0], 0.0),
                                         TopAbs_EDGE))
    assert poly_edges > 300
    assert curve_edges == 1


# ------------------------------------------------------- carrying it downstream

@pytest.fixture(scope="module")
def partition_with_curves(imported):
    from guildmodel.core.geometry.regions import curves_by_ring, partition_zones
    from guildmodel.core.io_import.normalize import points_to_polygon

    points, curves = imported
    outline = points_to_polygon(points["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in points["LENS"]]
    src = {}
    for layer in ("OUTLINE", "LENS"):
        src.update(curves_by_ring(points[layer], curves[layer]))
    return partition_zones(outline, lenses, points["SCULPT"], source_curves=src)


def test_every_uncut_ring_still_knows_its_curve(partition_with_curves):
    """The body exterior and both apertures survive Shapely's booleans
    unmodified, so all three must still resolve to their authored curve.

    This is what `_ring_key` has to be invariant to: `outline.difference(lenses)`
    hands back the same coordinates rotated to a different start vertex, and
    sometimes reversed. Keying on the start point matched only one ring of three.
    """
    part = partition_with_curves
    outer = part.ring_curve(part.body.exterior)
    assert outer is not None and outer.layer == "OUTLINE"
    assert len(outer.control_points) == 64

    holes = [part.ring_curve(r) for r in part.body.interiors]
    assert all(h is not None for h in holes), "both apertures must match"
    assert sorted(len(h.control_points) for h in holes) == [7, 13]


def test_a_modified_ring_correctly_matches_nothing(partition_with_curves):
    """Fragility in the right direction: a ring Shapely genuinely reshaped is no
    longer the authored curve, and must not claim to be."""
    part = partition_with_curves
    shrunk = part.body.buffer(-0.5)
    assert part.ring_curve(shrunk.exterior) is None


def test_face_from_curves_matches_the_polygon_area(partition_with_curves):
    """Using the exact curve must not move the part. The curve bulges very
    slightly outside the polygon inscribed in it — that is the point — but by
    the flattening tolerance, not by anything a maker would see."""
    from guildmodel.core.solid.occ import area, is_valid, polygon_to_face

    part = partition_with_curves
    plain = polygon_to_face(part.body, 0.0)
    curved = polygon_to_face(part.body, 0.0, curves=part)
    assert is_valid(plain) and is_valid(curved)
    # Sub-mm2 on a ~1484 mm2 body: the outline curve adds 0.649 mm2 over the
    # polygon inscribed in it and the (larger) true apertures take 0.889 back.
    assert area(curved) == pytest.approx(area(plain), abs=1.0)


def test_mass_properties_need_adaptive_integration(partition_with_curves):
    """`BRepGProp` without an `Eps` integrates spline-bounded faces on a fixed
    grid and gets them badly wrong — 1546.690 mm2 against a true 1483.750, a 4%
    error that reads as "the curve added material". It did not. This is the same
    hazard as the invalid-face-with-a-plausible-bounding-box already documented
    on `ring_wire`, and it is why `occ.volume` passes `GPROP_EPS`."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from guildmodel.core.solid.occ import area, polygon_to_face

    curved = polygon_to_face(partition_with_curves.body, 0.0,
                             curves=partition_with_curves)
    naive = GProp_GProps()
    BRepGProp.SurfaceProperties_s(curved, naive)      # no Eps — the trap
    assert naive.Mass() - area(curved) > 10.0, (
        "if these now agree, OCCT changed and the GPROP_EPS note can be revisited")


def test_no_curves_available_changes_nothing(partition_with_curves):
    """A drawing made of polylines must behave exactly as it did before."""
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.solid.occ import polygon_to_face

    part = partition_with_curves
    bare = partition_zones(part.body, [], [])
    assert bare.source_curves == {}
    assert bare.ring_curve(bare.body.exterior) is None
    assert polygon_to_face(bare.body, 0.0, curves=bare) is not None
