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


# ------------------------------------------- zone boundaries as trimmed arcs

def test_zone_faces_can_be_rebuilt_from_authored_curves(partition_with_curves):
    """A zone boundary is arcs of the outline and lens curves joined by the
    straight SCULPT cuts that severed them — so a whole-ring lookup finds
    nothing and `curved_ring_wire` has to reconstruct it run by run.

    All nine zones must come out valid, with areas matching the polygons: using
    the true curve may move a zone by the chord deficit, never by more.
    """
    from guildmodel.core.solid.occ import (SourceCurves, area, is_valid,
                                           polygon_to_face)

    part = partition_with_curves
    source = SourceCurves(part)
    assert source, "the demo frame has authored curves to match against"

    total_poly = total_curved = 0.0
    for zone in part.zones:
        plain = polygon_to_face(zone.polygon, 0.0)
        curved = polygon_to_face(zone.polygon, 0.0, curves=source)
        assert is_valid(curved), f"{zone.name} built an invalid face"
        a_plain, a_curved = area(plain), area(curved)
        assert a_curved == pytest.approx(a_plain, abs=1.0), zone.name
        total_poly += a_plain
        total_curved += a_curved

    assert total_poly == pytest.approx(part.body.area, abs=0.01)
    assert total_curved == pytest.approx(total_poly, abs=0.5)


def test_curved_terraces_collapse_edges(partition_with_curves):
    """Arcs must collapse edges, not add them — that is the whole point."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import zone_heights
    from guildmodel.core.solid.build import build_terraces
    from guildmodel.core.solid.occ import explore
    from OCP.TopAbs import TopAbs_EDGE

    part = partition_with_curves
    heights = zone_heights(part, CastleParams())
    n_plain = sum(1 for _ in explore(build_terraces(part, heights, curved=False),
                                     TopAbs_EDGE))
    n_curved = sum(1 for _ in explore(build_terraces(part, heights, curved=True),
                                      TopAbs_EDGE))
    assert n_curved < n_plain


def test_the_curved_castle_meshes_watertight(partition_with_curves, imported):
    """**The gate that kept `CURVED_TERRACES` off, and the fix for it.**

    A leaking mesh fails the M2 STL gate and the CAM, so this is the property
    that decides whether the curved path can be the default at all.

    It looked like a tessellation bug and was not. The terraces mesh closed on
    their own; the crack arrived with the footing fills, because
    `footing_bodies` clipped each fill to a zone prism built from the *flattened
    polygon* while the terraces followed the *curve*. The clip sat a chord-width
    inside the real boundary, the fill stopped short of the terrace it blends
    into, and that near-coincident pair of faces tessellated with a gap — a
    valid solid with a leaking mesh, this kernel's signature failure.

    So the invariant worth pinning is not "the mesher works" but **"one curve
    set, used by everything that touches the same boundary"**.
    """
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache, is_valid
    from guildmodel.core.solid.tessellate import tessellate

    points, _ = imported
    hinges = [points_to_polygon(c) for c in points["HINGE"]]

    clear_base_cache()
    solid = build_castle_solid(partition_with_curves, CastleParams(), hinges)
    assert is_valid(solid)

    mesh = tessellate(solid).to_trimesh()
    assert mesh.is_watertight, "the curved castle must mesh closed"
    assert mesh.volume == pytest.approx(7825.0, abs=5.0)


def test_curves_only_engage_when_the_caller_supplies_them():
    """`CURVED_TERRACES` is opt-in by *data*, not by flag.

    A partition built without authored curves yields an empty `SourceCurves` and
    the historical polygonal path, which is why turning the flag on left the
    whole suite unmoved.
    """
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.solid.occ import SourceCurves

    raw = import_dxf(DEMO)
    part = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                           [points_to_polygon(c) for c in raw["LENS"]],
                           raw["SCULPT"])
    assert part.source_curves == {}
    assert not SourceCurves(part)


# ------------------------------------------------------- Bezier chains (.gdraw)

def test_a_bezier_chain_is_a_b_spline_not_an_approximation_of_one():
    """`.gdraw` stores Bezier nodes; a chain of cubic Beziers *is* a cubic
    B-spline. Sampling each segment's Bernstein form and projecting onto the
    converted curve is the whole claim."""
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.gp import gp_Pnt
    from guildmodel.core.geometry.curves import cubic_bezier_chain
    from guildmodel.core.solid.occ import nurbs_edge

    segments = [
        ((0.0, 0.0), (5.0, 12.0), (15.0, 12.0), (20.0, 0.0)),
        ((20.0, 0.0), (25.0, -12.0), (35.0, -12.0), (40.0, 0.0)),
        ((40.0, 0.0), (45.0, 12.0), (55.0, 8.0), (60.0, 4.0)),
    ]
    curve = cubic_bezier_chain(segments)
    assert curve.degree == 3
    assert len(curve.control_points) == 3 * len(segments) + 1
    assert curve.is_consistent()

    geom = BRep_Tool.Curve_s(nurbs_edge(curve, 0.0), 0.0, 1.0)
    worst = 0.0
    for p0, p1, p2, p3 in segments:
        for i in range(51):
            t = i / 50.0
            b = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3)
            x = sum(w * p[0] for w, p in zip(b, (p0, p1, p2, p3)))
            y = sum(w * p[1] for w, p in zip(b, (p0, p1, p2, p3)))
            worst = max(worst,
                        GeomAPI_ProjectPointOnCurve(gp_Pnt(x, y, 0.0), geom).LowerDistance())
    assert worst < 1e-9, f"{worst} mm — the conversion has no tolerance to spend"


def test_a_degenerate_bezier_segment_is_dropped_not_built():
    """Four coincident poles would give the kernel a stationary point for no
    geometry in return."""
    from guildmodel.core.geometry.curves import cubic_bezier_chain

    p = (3.0, 4.0)
    assert cubic_bezier_chain([(p, p, p, p)]) is None
    curve = cubic_bezier_chain([(p, p, p, p),
                                ((3.0, 4.0), (5.0, 6.0), (7.0, 6.0), (9.0, 4.0))])
    assert len(curve.control_points) == 4


def test_mirroring_a_curve_leaves_its_basis_alone():
    """Mirroring moves the hull; knots, degree and weights do not move with it."""
    from guildmodel.core.geometry.curves import circle_curve, mirror_x, mirror_y

    c = circle_curve((4.0, -3.0), 2.0)
    for flip, axis in ((mirror_x, 0), (mirror_y, 1)):
        m = flip(c)
        assert np.allclose(m.knots, c.knots)
        assert np.allclose(m.weights, c.weights)
        assert m.degree == c.degree
        expected = c.control_points.copy()
        expected[:, axis] = -expected[:, axis]
        assert np.allclose(m.control_points, expected)


# ------------------------------------------------------- kernel-side economies

def test_an_arc_carries_only_its_own_span(imported):
    """A trimmed edge still references all 64 poles of the outline; a segmented
    one carries just the arc. Extruding the trimmed form makes every boolean and
    every meshing pass work on the whole surface — 19.96 s vs 16.67 s on the
    demo frame's cold build."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeVertex
    from guildmodel.core.solid.occ import _arc_edge, nurbs_edge

    _, curves = imported
    full = BRep_Tool.Curve_s(nurbs_edge(curves["OUTLINE"][0], 0.0), 0.0, 1.0)
    u0, u1 = full.FirstParameter(), full.LastParameter()
    ua, ub = u0 + 0.20 * (u1 - u0), u0 + 0.45 * (u1 - u0)
    v0 = BRepBuilderAPI_MakeVertex(full.Value(ua)).Vertex()
    v1 = BRepBuilderAPI_MakeVertex(full.Value(ub)).Vertex()

    trimmed = BRep_Tool.Curve_s(
        BRepBuilderAPI_MakeEdge(full, v0, v1, ua, ub).Edge(), 0.0, 1.0)
    segmented = BRep_Tool.Curve_s(_arc_edge(full, v0, v1, ua, ub), 0.0, 1.0)
    assert trimmed.NbPoles() == full.NbPoles() == 64
    assert segmented.NbPoles() < 30

    # ...and it is the same arc: knot insertion is exact.
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        want = full.Value(ua + (ub - ua) * t)
        got = segmented.Value(segmented.FirstParameter()
                              + (segmented.LastParameter() - segmented.FirstParameter()) * t)
        assert want.Distance(got) < 1e-9


def test_a_span_running_against_the_curve_spans_the_same_arc():
    """A ring winding opposite the curve arrives with `ua > ub`.

    `MakeEdge` matches the parameter pair against the vertex pair positionally,
    so the descending order has to be passed through: normalise it and the edge
    is refused, silently, because the caller falls back on any exception. What
    comes back is a FORWARD edge over the ascending range, which is correct —
    ring direction is settled on the finished wire by `polygon_to_face`.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from guildmodel.core.geometry.curves import cubic_bezier_chain
    from guildmodel.core.solid.occ import _arc_edge, nurbs_edge

    curve = cubic_bezier_chain([
        ((0.0, 0.0), (5.0, 10.0), (15.0, 10.0), (20.0, 0.0)),
        ((20.0, 0.0), (25.0, -10.0), (35.0, -10.0), (40.0, 0.0)),
    ])
    geom = BRep_Tool.Curve_s(nurbs_edge(curve, 0.0), 0.0, 1.0)
    ua, ub = 1.6, 0.4                                    # descending
    v0 = BRepBuilderAPI_MakeVertex(geom.Value(ua)).Vertex()
    v1 = BRepBuilderAPI_MakeVertex(geom.Value(ub)).Vertex()
    edge = _arc_edge(geom, v0, v1, ua, ub)
    lo, hi = BRep_Tool.Range_s(edge)
    assert (lo, hi) == pytest.approx((ub, ua))
    arc = BRep_Tool.Curve_s(edge, 0.0, 1.0)
    for t in (0.0, 0.5, 1.0):
        assert arc.Value(lo + (hi - lo) * t).Distance(geom.Value(ub + (ua - ub) * t)) < 1e-9


def test_fuse_all_is_one_pass_and_says_the_same_thing():
    """A union is associative, so the pairwise fold and the multi-tool pass must
    agree exactly — the only difference is that the fold re-intersects the
    growing result on every step (3.2 s vs 0.35 s on the demo footings)."""
    from guildmodel.core.solid.occ import fuse, fuse_all, mesh_volume
    from guildmodel.core.solid.occ import extrude, polygon_to_face
    from shapely.geometry import box

    boxes = [extrude(polygon_to_face(box(i * 8.0, 0.0, i * 8.0 + 10.0, 10.0)), 5.0)
             for i in range(4)]
    folded = boxes[0]
    for b in boxes[1:]:
        folded = fuse(folded, b)
    assert mesh_volume(fuse_all(boxes)) == pytest.approx(mesh_volume(folded), abs=1e-6)


# ------------------------------------------------------- the rim lip (groove on)

def test_the_offset_curve_is_exactly_parallel_to_its_basis():
    """`OffsetCurve` says "that curve, d away" and means it. Sampled all round,
    every point is exactly `d` from the basis — which no offset of a *flattened*
    ring can claim, and no B-spline fit of the offset can either (the exact
    offset of a B-spline is not a B-spline)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from guildmodel.core.geometry.curves import OffsetCurve, circle_curve
    from guildmodel.core.solid.occ import nurbs_edge

    basis = circle_curve((2.0, -1.0), 12.0)
    offset = OffsetCurve(basis=basis, distance=-0.75)
    base_geom = BRep_Tool.Curve_s(nurbs_edge(basis, 0.0), 0.0, 1.0)

    sampler = GCPnts_QuasiUniformDeflection(
        BRepAdaptor_Curve(nurbs_edge(offset, 0.0)), 0.001)
    worst = 0.0
    for i in range(1, sampler.NbPoints() + 1):
        d = GeomAPI_ProjectPointOnCurve(sampler.Value(i), base_geom).LowerDistance()
        worst = max(worst, abs(d - 0.75))
    assert worst < 1e-9, f"{worst} mm from parallel"


def test_the_rim_lip_keeps_every_ring_curved(partition_with_curves):
    """With the groove on, the terraces are built against the *shrunk* apertures.
    Re-partitioning used to drop every curve on the floor, so a grooved build was
    polygonal however carefully the frame was drawn — the single biggest hole
    left after the intakes were wired.
    """
    from guildmodel.core.geometry.curves import NurbsCurve, OffsetCurve
    from guildmodel.core.solid.features import lip_partition

    lip = lip_partition(partition_with_curves, 0.6)
    assert isinstance(lip.ring_curve(lip.body.exterior), NurbsCurve)   # untouched
    apertures = [lip.ring_curve(r) for r in lip.body.interiors]
    assert apertures and all(isinstance(c, OffsetCurve) for c in apertures)


def test_the_lip_zones_are_as_curved_as_the_ungrooved_ones(partition_with_curves):
    """The measure that matters: what fraction of the zone boundaries the solid
    is actually built from can be rebuilt as arcs. Grooved must match ungrooved
    — 94% on the demo frame — or the groove is still costing curvature."""
    from guildmodel.core.solid.features import lip_partition
    from guildmodel.core.solid.occ import SourceCurves

    def curved_fraction(part):
        src = SourceCurves(part)
        pts = [p for z in part.zones for p in list(z.polygon.exterior.coords)[:-1]]
        return sum(src.classify(x, y)[0] is not None for x, y in pts) / len(pts)

    plain = curved_fraction(partition_with_curves)
    lip = curved_fraction(lip_partition(partition_with_curves, 0.6))
    assert plain > 0.9
    assert lip >= plain - 0.01, f"grooved {lip:.2f} against ungrooved {plain:.2f}"


def test_the_offset_direction_is_measured_not_assumed(partition_with_curves):
    """OCCT offsets along `Z x tangent`, so which sign shrinks depends on how the
    curve winds — and the demo frame's two lens rings wind opposite ways. Assume
    a sign and one eye grows while the other shrinks."""
    from guildmodel.core.solid.features import lip_partition
    from shapely.geometry import Polygon

    before = sorted(Polygon(r).area for r in partition_with_curves.body.interiors)
    after = sorted(Polygon(r).area
                   for r in lip_partition(partition_with_curves, 0.6).body.interiors)
    assert len(before) == len(after) == 2
    for a, b in zip(before, after):
        assert b < a, "every aperture must shrink"


def test_the_exact_offset_is_only_taken_when_it_agrees_with_the_buffer():
    """The guard, and why it is comparative rather than local.

    `Geom_OffsetCurve` does not trim. Offset a 5 mm aperture inward by 9 mm and
    it sails through the centre and returns a 4 mm ring wound the other way —
    valid, simple, closed, *smaller* than the original. Every cheap local test
    passes it. Only "does this agree with the shrink Shapely computed?" does not.
    """
    from guildmodel.core.solid.features import _offset_aperture
    from guildmodel.core.geometry.curves import circle_curve
    from shapely.geometry import Point

    circle = circle_curve((0.0, 0.0), 5.0)
    lens = Point(0.0, 0.0).buffer(5.0, quad_segs=64)

    from shapely.geometry import Polygon
    from guildmodel.core.solid.features import _LIP_AREA_TOL

    pts, offset = _offset_aperture(circle, lens.buffer(-1.0), 1.0)
    assert Polygon(pts).area == pytest.approx(lens.buffer(-1.0).area,
                                              rel=_LIP_AREA_TOL)
    assert abs(offset.distance) == pytest.approx(1.0)

    # the through-the-middle ring, offered against the shrink it should match
    assert _offset_aperture(circle, lens.buffer(-4.5), 9.0) is None
    assert _offset_aperture(circle, None, 1.0) is None        # buffer came back empty
    assert _offset_aperture(None, lens.buffer(-1.0), 1.0) is None   # no authored curve


def test_a_vanishing_aperture_is_left_alone(partition_with_curves):
    """A groove deeper than the aperture must not punch the lens out. Shapely's
    buffer empties, the exact offset is refused with it, and the lip keeps the
    rings it had — no zone changes, so `lip_partition` does not raise."""
    from shapely.geometry import Polygon
    from guildmodel.core.solid.features import lip_partition

    before = sorted(Polygon(r).area for r in partition_with_curves.body.interiors)
    lip = lip_partition(partition_with_curves, 40.0)
    after = sorted(Polygon(r).area for r in lip.body.interiors)
    assert after == pytest.approx(before, rel=1e-9)


def test_the_grooved_curved_castle_is_still_watertight(partition_with_curves, imported):
    """The whole chain, with the feature that used to switch the curves off."""
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.occ import is_valid
    from guildmodel.core.solid.tessellate import tessellate

    points, _ = imported
    hinges = [points_to_polygon(c) for c in points["HINGE"]]
    castle = CastleParams()
    castle.lens_groove.enabled = True

    clear_base_cache()
    solid = build_castle_solid(partition_with_curves, castle, hinges)
    assert is_valid(solid)
    assert tessellate(solid).to_trimesh().is_watertight


# ------------------------------------------------------- swept, not lofted

def _ray_crossings(solid, x, y):
    """Z values where a vertical ray enters or leaves the solid."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

    it = BRepIntCurveSurface_Inter()
    it.Init(solid, gp_Lin(gp_Pnt(float(x), float(y), -1e4),
                          gp_Dir(0.0, 0.0, 1.0)), 1e-7)
    zs = []
    while it.More():
        zs.append(it.Pnt().Z())
        it.Next()
    return sorted(zs)


@pytest.fixture(scope="module")
def grooved(partition_with_curves):
    """The lip partition and its two groove cutters, built both ways."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.features import groove_cutter, lip_partition

    castle = CastleParams()
    castle.lens_groove.enabled = True
    g = castle.lens_groove
    lip = lip_partition(partition_with_curves, g.depth_mm)
    rings = [r for r in lip.body.interiors if not lip.is_hole(r)]
    lofted = [groove_cutter(lip.body, r, g) for r in rings]
    swept = [groove_cutter(lip.body, r, g, curve=lip.ring_curve(r)) for r in rings]
    return lip, g, lofted, swept


def test_the_swept_groove_is_three_faces_not_five_hundred(grooved):
    """A loft over 180 stations spends 540 faces describing one V running round
    one ring. Riding the curve, it is three."""
    from OCP.TopAbs import TopAbs_ShapeEnum
    from guildmodel.core.solid.occ import explore

    _lip, _g, lofted, swept = grooved
    faces = lambda s: sum(1 for _ in explore(s, TopAbs_ShapeEnum.TopAbs_FACE))
    assert all(faces(c) == 540 for c in lofted)
    assert all(faces(c) == 3 for c in swept)


def test_the_swept_groove_is_the_same_v_as_the_lofted_one(grooved):
    """Equivalence, and in the right direction: the sweep must be a whisker
    *larger*, because the loft is a polygon inscribed in the ring.

    This is the assertion that would have caught the first attempt, which put the
    profile on the wrong side and was 7% out — the placement is read off the lip
    ring rather than derived from OCCT's offset-sign convention precisely
    because that convention turned out to be the opposite of the documented one.
    """
    from guildmodel.core.solid.occ import mesh_volume

    _lip, _g, lofted, swept = grooved
    for a, b in zip(lofted, swept):
        va, vb = mesh_volume(a), mesh_volume(b)
        assert vb > va, "the exact sweep cannot be smaller than the inscribed loft"
        assert vb == pytest.approx(va, rel=0.005)


def test_the_swept_groove_still_matches_the_cutter_spec(partition_with_curves):
    """The same 5 um gate `test_lens_groove_v_matches_the_cutter_spec` holds the
    lofted V to, applied to the swept one on a curved frame — half-width falling
    linearly from `width_mm / 2` at the lip to zero at `depth_mm`, centred on the
    apex height. That fixture builds from `import_dxf` and so exercises the
    fallback; nothing pinned the sweep until this.
    """
    from shapely.geometry import LineString

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid import features as FT

    castle = CastleParams()
    castle.lens_groove.enabled = True
    g = castle.lens_groove
    clear_base_cache()
    solid = build_castle_solid(partition_with_curves, castle, [])

    lip = FT.lip_partition(partition_with_curves, g.depth_mm)
    ring = next(r for r in lip.body.interiors if not lip.is_hole(r))
    pts, tans = FT._ring_stations(LineString(ring), 8)
    inward = FT._inward(lip.body, pts, tans)

    for u in (0.02, 0.25, 0.55):
        z = _ray_crossings(solid, *(pts[0] + inward[0] * u))
        assert len(z) >= 4, f"no undercut at u={u}"
        half_w = (z[2] - z[1]) / 2.0
        assert half_w == pytest.approx((g.width_mm / 2.0) * (1.0 - u / g.depth_mm),
                                       abs=0.005)
        assert (z[1] + z[2]) / 2.0 == pytest.approx(g.anterior_offset_mm, abs=0.01)


def test_the_swept_groove_undercuts_all_the_way_round(partition_with_curves):
    """Ray crossings at 40 stations: four surfaces inside the V, two past the
    apex. A sweep that drifts off the ring would lose the undercut somewhere."""
    from shapely.geometry import LineString

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid import features as FT

    castle = CastleParams()
    castle.lens_groove.enabled = True
    g = castle.lens_groove
    clear_base_cache()
    solid = build_castle_solid(partition_with_curves, castle, [])

    lip = FT.lip_partition(partition_with_curves, g.depth_mm)
    ring = next(r for r in lip.body.interiors if not lip.is_hole(r))
    pts, tans = FT._ring_stations(LineString(ring), 40)
    inward = FT._inward(lip.body, pts, tans)

    deep = sum(1 for k in range(len(pts))
               if len(_ray_crossings(solid, *(pts[k] + inward[k] * 0.35))) >= 4)
    assert deep == len(pts), f"undercut missing at {len(pts) - deep} stations"
    assert len(_ray_crossings(solid, *(pts[0] + inward[0] * (g.depth_mm + 0.15)))) == 2


def test_a_curveless_aperture_still_gets_its_groove(partition_with_curves):
    """Opt-in by data, here as everywhere: with no authored curve the loft is
    still what runs, and it still produces a V."""
    from OCP.TopAbs import TopAbs_ShapeEnum
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.features import groove_cutter, lip_partition
    from guildmodel.core.solid.occ import explore

    g = CastleParams().lens_groove
    lip = lip_partition(partition_with_curves, g.depth_mm)
    ring = next(r for r in lip.body.interiors if not lip.is_hole(r))
    cutter = groove_cutter(lip.body, ring, g, curve=None)
    assert sum(1 for _ in explore(cutter, TopAbs_ShapeEnum.TopAbs_FACE)) == 540


# ------------------------------------------------------- every verified arc lands

def test_a_junction_vertex_admits_how_well_it_is_located():
    """A vertex where an arc meets a straight run sits at a flattened point but
    is claimed to be at a parameter on the curve. `MakeEdge` rejects the pair
    outright when they disagree by more than the vertex's tolerance, and the
    default is 1e-7 mm — tighter than Shapely's own noding noise."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    from guildmodel.core.geometry.curves import cubic_bezier_chain
    from guildmodel.core.solid.occ import (JUNCTION_TOL_MM, _arc_edge, _junction_vertex,
                                           nurbs_edge)

    curve = cubic_bezier_chain([((0.0, 0.0), (5.0, 10.0), (15.0, 10.0), (20.0, 0.0))])
    geom = BRep_Tool.Curve_s(nurbs_edge(curve, 0.0), 0.0, 1.0)
    ua, ub = 0.2, 0.8
    exact = geom.Value(ub)
    # nudge the far vertex by half the tolerance, as Shapely's noding would
    off = gp_Pnt(exact.X() + JUNCTION_TOL_MM / 2.0, exact.Y(), exact.Z())

    v0 = _junction_vertex(geom.Value(ua))
    assert BRep_Tool.Tolerance_s(v0) == pytest.approx(JUNCTION_TOL_MM)
    _arc_edge(geom, v0, _junction_vertex(off), ua, ub)          # must not raise

    with pytest.raises(Exception):
        _arc_edge(geom, BRepBuilderAPI_MakeVertex(geom.Value(ua)).Vertex(),
                  BRepBuilderAPI_MakeVertex(off).Vertex(), ua, ub)


def test_every_verified_arc_becomes_an_arc(partition_with_curves):
    """No silent fallbacks.

    `_arc_spans` verifies a span and then `curved_ring_wire` tries to build it;
    on any exception it re-emits the span's vertices as line edges instead. That
    fallback fired on the demo frame's two largest zones and nothing noticed:
    `eyewire_superior_od` came out a 48-edge face carrying one arc, where its
    neighbours were 8-edge faces carrying two. The zone vertices still
    *classified* at 94%, so every measure short of counting the edges said the
    model was curved.
    """
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    from guildmodel.core.solid.occ import (SourceCurves, _arc_spans, explore,
                                           polygon_to_face)

    part = partition_with_curves
    src = SourceCurves(part)
    for zone in part.zones:
        coords = list(zone.polygon.exterior.coords)[:-1]
        tagged = [(float(x), float(y)) + src.classify(x, y) for x, y in coords]
        want = len(_arc_spans(tagged, src))
        face = polygon_to_face(zone.polygon, 0.0, curves=src)
        got = sum(1 for e in explore(face, TopAbs_ShapeEnum.TopAbs_EDGE)
                  if "BSpline" in str(BRepAdaptor_Curve(TopoDS.Edge_s(e)).GetType()))
        assert got == want, f"{zone.name}: {want} verified spans, {got} arcs built"


def test_a_zone_face_is_a_handful_of_edges_not_a_polygon(partition_with_curves):
    """The consequence, stated as the number a reader can check by eye. Nine
    zones built from 645 ring vertices come to well under a hundred edges."""
    from OCP.TopAbs import TopAbs_ShapeEnum
    from guildmodel.core.solid.occ import SourceCurves, explore, polygon_to_face

    part = partition_with_curves
    src = SourceCurves(part)
    verts = sum(len(z.polygon.exterior.coords) - 1 for z in part.zones)
    edges = sum(sum(1 for _ in explore(polygon_to_face(z.polygon, 0.0, curves=src),
                                       TopAbs_ShapeEnum.TopAbs_EDGE))
                for z in part.zones)
    assert verts > 600
    assert edges < 100, f"{verts} vertices became {edges} edges"
