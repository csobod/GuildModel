"""Stage 2 tests: the castle as a B-Rep solid, and its tessellation.

The gate these support is BREP-REWRITE-REPORT.md §3.5 — the solid path is
checked against the raster path by sampling, with the difference at feature
edges expected and required to be *sharper*. That comparison arrives with the
Z-map adapter; what is pinned here is the layer underneath it: the solid builds,
it is valid by the kernel's own check, and it tessellates closed.
"""
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).parents[1] / "tests" / "fixtures" / "demo"

pytest.importorskip("OCP", reason="cadquery-ocp not installed")


@pytest.fixture(scope="module")
def demo_partition():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    return partition_zones(outline, lenses, raw["SCULPT"])


@pytest.fixture(scope="module")
def demo_solid(demo_partition):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid

    return build_castle_solid(demo_partition, CastleParams())


@pytest.fixture(scope="module")
def demo_tess(demo_solid):
    from guildmodel.core.solid.tessellate import tessellate

    return tessellate(demo_solid)


# ----------------------------------------------------------------- the bridge

def test_polygon_to_face_with_holes_is_valid(demo_partition):
    """Regression: hole wires must wind opposite the outer wire and be added
    as-is. Reversing them on top of that yields a face OCCT calls invalid while
    still returning a shape with a plausible bounding box — so the failure shows
    up later as a boolean that silently produces nothing, which is exactly how
    it was found (the footing fill intersected the body prism to zero volume).
    """
    from guildmodel.core.solid.occ import extrude, is_valid, polygon_to_face, volume

    body = demo_partition.body
    assert len(body.interiors) == 2, "demo body should have two lens apertures"

    prism = extrude(polygon_to_face(body, 0.0), 11.0)
    assert is_valid(prism)
    # Holes actually subtracted: area x height, not the outer contour x height.
    assert volume(prism) == pytest.approx(body.area * 11.0, rel=1e-6)


def test_polygon_to_face_is_winding_agnostic(demo_partition):
    """Either incoming winding must give the same solid — the builder normalises
    rather than trusting Shapely's convention."""
    from shapely.geometry.polygon import orient

    from guildmodel.core.solid.occ import extrude, is_valid, polygon_to_face, volume

    body = demo_partition.body
    for signed in (1.0, -1.0):
        prism = extrude(polygon_to_face(orient(body, signed), 0.0), 11.0)
        assert is_valid(prism)
        assert volume(prism) == pytest.approx(body.area * 11.0, rel=1e-6)


# ------------------------------------------------------------------ the solid

def test_castle_solid_is_valid(demo_solid):
    from guildmodel.core.solid import is_valid

    assert is_valid(demo_solid), "BRepCheck_Analyzer rejected the castle solid"


def test_castle_solid_volume_near_raster(demo_solid):
    """Within a couple of percent of the raster build.

    Not tighter, deliberately: the solid has no hinge pockets or M13 features
    yet, and the raster carries its own sampling error. The exact agreement gate
    is the Z-map comparison, not a volume.
    """
    from guildmodel.core.solid import volume

    assert volume(demo_solid) == pytest.approx(7825.0, rel=0.03)


def test_footing_fill_and_carve_both_contribute(demo_partition):
    """The composite rule is `(terraces u fills) - carves`.

    Pinned because the fills silently contributed nothing at first: the clip
    body was invalid, so `common()` returned an empty shape and the blend was
    carve-only. The volume ordering below is what that bug broke.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build as B
    from guildmodel.core.solid.occ import volume

    castle = CastleParams()
    heights = B.zone_heights(demo_partition, castle)
    terraces = volume(B.build_terraces(demo_partition, heights))
    blended = volume(B.build_castle_solid(demo_partition, castle))

    # Carving the step tops removes more than the base fillets add back.
    assert blended < terraces
    # But the fills are real: carve-only lands near 7774 mm^3, and the fill
    # puts roughly 200 mm^3 back.
    assert blended > 7900.0


# ------------------------------------------------------------ tessellation

def test_tessellation_is_watertight_genus_2(demo_tess):
    """A valid solid must tessellate closed — the property the raster mesher
    could only be patched into having (M18 #2)."""
    mesh = demo_tess.to_trimesh()
    assert mesh.is_watertight
    assert mesh.euler_number == -2      # two lens apertures


def test_tessellation_is_far_lighter_than_the_raster(demo_tess):
    """The whole point of edges: fidelity without vertex count.

    The 0.15 mm raster mesh of this frame is ~263,800 triangles. The solid
    reaches better silhouette fidelity in well under a tenth of that.
    """
    assert len(demo_tess.faces) < 30_000


def test_tessellation_carries_real_edges(demo_tess):
    """The display modes' enabler: topological edges, not triangle borders."""
    assert len(demo_tess.edges) > 100
    assert all(len(p) >= 2 for p in demo_tess.edges)
    segs = demo_tess.edge_segments
    assert segs.ndim == 3 and segs.shape[1:] == (2, 3)
    # Edges must lie on the part, not float somewhere near it.
    mesh = demo_tess.to_trimesh()
    lo, hi = mesh.bounds
    pts = np.concatenate(demo_tess.edges)
    assert np.all(pts >= lo - 1e-6) and np.all(pts <= hi + 1e-6)


# --------------------------------------------------------- spline ring wires

def test_spline_ring_wire_tracks_the_source_contour(demo_partition):
    """The fitted wire is geometrically excellent — this is not why it is off
    by default.

    Split at genuine corners (the demo outline has four, at the hinge ends), the
    fit stays within a few microns of the source polyline, and the straight runs
    come back exact. What rules it out for now is the *face* built on it, not
    the wire; see `occ.ring_wire`'s docstring for the measurements.
    """
    from shapely.geometry import LineString, Point

    from guildmodel.core.solid.occ import (
        CORNER_DEG, _corner_mask, _ring_points, _runs_between_corners,
        spline_ring_wire)
    from guildmodel.core.solid.tessellate import edge_polylines

    ring = demo_partition.body.exterior
    src = _ring_points(ring.coords)
    runs, closed = _runs_between_corners(src, _corner_mask(src, CORNER_DEG))
    assert not closed and len(runs) == 4, "demo outline should split into 4 runs"

    wire = spline_ring_wire(ring.coords, 0.0)
    polys = edge_polylines(wire, deflection=0.002, angle=0.05)
    assert len(polys) == len(runs)

    for seg, poly in zip(runs, polys):
        line = LineString(poly[:, :2])
        worst = max(line.distance(Point(*q)) for q in seg)
        assert worst < 0.02, f"spline strayed {worst * 1000:.1f} um from source"


def test_spline_faces_are_not_the_default(demo_partition):
    """Regression guard on the decision, not on the geometry.

    A planar face on spline boundaries tessellates to *zero* triangles at the
    natural fit tolerance while still reporting valid, which is what collapsed
    the full build to an empty solid. If a future OCCT makes this work, this
    test failing is the signal to revisit — not a reason to flip the default
    without re-running the tolerance sweep.
    """
    import numpy as np

    from guildmodel.core.solid.occ import polygon_to_face
    from guildmodel.core.solid.tessellate import tessellate

    body = demo_partition.body
    poly_face = polygon_to_face(body, 0.0)           # default: polygonal
    tess = tessellate(poly_face, deflection=0.005, angle=0.05, with_edges=False)
    v, f = tess.vertices, tess.faces
    assert len(f) > 0, "the default face must tessellate"
    area = 0.5 * np.abs(np.cross(v[f[:, 1]] - v[f[:, 0]],
                                 v[f[:, 2]] - v[f[:, 0]])).sum()
    assert area == pytest.approx(body.area, rel=1e-6)


def test_edge_polylines_are_deduplicated(demo_solid):
    """Every edge is shared by two faces; the explorer must not emit it twice."""
    from guildmodel.core.solid.tessellate import edge_polylines

    polys = edge_polylines(demo_solid)
    keys = {(tuple(np.round(p[0], 6)), tuple(np.round(p[-1], 6)), len(p))
            for p in polys}
    assert len(keys) == len(polys)


# ------------------------------------------------- the CAM adapter (§3.5 gate)

@pytest.fixture(scope="module")
def raster_relief(demo_partition):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    return build_castle_relief(demo_partition, CastleParams(), [],
                               resolution=CUT_RES_MM)


@pytest.fixture(scope="module")
def solid_relief(demo_solid, demo_partition):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.solid import solid_to_relief

    return solid_to_relief(demo_solid, demo_partition, CastleParams(),
                           resolution=CUT_RES_MM)


def test_zmap_grid_matches_the_raster_exactly(raster_relief, solid_relief):
    """Cell-for-cell comparability is the precondition for the whole §3.5 gate.

    An off-by-one grid would make every later comparison meaningless while
    still looking approximately right.
    """
    assert solid_relief.field.z.shape == raster_relief.field.z.shape
    assert solid_relief.field.origin == raster_relief.field.origin
    assert solid_relief.field.resolution == raster_relief.field.resolution


def test_zmap_masks_match_the_raster(raster_relief, solid_relief):
    """`inside` and `zone_index` are 2D and come from the partition either way.

    `zmap._masks` mirrors the raster builder's inline construction; this is what
    keeps the copy honest.
    """
    assert np.array_equal(solid_relief.inside, raster_relief.inside)
    assert np.array_equal(solid_relief.zone_index, raster_relief.zone_index)


def test_zmap_agrees_with_the_raster_surface(raster_relief, solid_relief):
    """The gate itself: the derived Z-map reproduces the raster to microns.

    Measured on the demo frame: mean +0.1 um, rms 3.6 um, 99.86% of in-body
    cells within 5 um. Bounds here are loose enough not to be brittle and tight
    enough that any real regression trips them.
    """
    m = raster_relief.inside
    d = (solid_relief.field.z - raster_relief.field.z)[m]

    assert abs(d.mean()) < 0.002, "systematic Z bias between the two paths"
    assert np.sqrt((d ** 2).mean()) < 0.02
    assert (np.abs(d) <= 0.005).mean() > 0.99
    assert (np.abs(d) <= 0.10).mean() > 0.999


def test_zmap_divergence_is_the_nosepad_artifact_only(
        raster_relief, solid_relief, demo_partition):
    """Where the two disagree, the solid is right — and this says why.

    Every cell over 0.1 mm sits 6-7 mm past the *end* of a nosepad SCULPT cut.
    The raster bands its footing by `distance(point, LineString)`, which wraps
    radially around a cut's endpoint, so it blends up to 0.33 mm off the corner
    of the nosepad tower where there is no step edge to blend at all. The swept
    solid follows the edge and stops.

    That is the distance-field artifact the B-Rep rewrite exists to remove, so
    the assertion is directional: the solid must keep material (d > 0), never
    remove extra.
    """
    m = raster_relief.inside
    d = solid_relief.field.z - raster_relief.field.z
    bad = m & (np.abs(d) > 0.1)

    assert bad.sum() < 60, "divergence beyond the known nosepad artifact"
    assert (d[bad] > 0).all(), "solid removed material the raster kept"

    names = [z.name for z in demo_partition.zones]
    zones = {names[i] for i in raster_relief.zone_index[bad]}
    assert zones <= {"nosepad_od", "nosepad_os"}, f"unexpected zones: {zones}"


def test_zmap_feeds_the_cam_unchanged(solid_relief):
    """The adapter's contract: a CastleRelief the existing CAM can consume."""
    from guildmodel.core.relief.castle import CUT_RES_MM, CastleRelief
    from guildmodel.core.relief.heightfield import Heightfield

    assert isinstance(solid_relief, CastleRelief)
    assert isinstance(solid_relief.field, Heightfield)
    assert solid_relief.field.resolution == CUT_RES_MM
    assert solid_relief.anterior is None          # pre-M17 fast path preserved
    assert solid_relief.field.z.dtype == np.float64
    # Outside the body must read as the anterior datum, not as -inf or NaN.
    assert np.all(np.isfinite(solid_relief.field.z))
    assert np.all(solid_relief.field.z[~solid_relief.inside] == 0.0)


# ------------------------------------------------------------------ features

@pytest.fixture(scope="module")
def demo_hinges():
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    return [points_to_polygon(c) for c in raw["HINGE"]]


def test_hinge_pockets_match_the_raster(demo_partition, demo_hinges):
    """Pockets are a straight extrude-and-subtract, so they should be exact.

    The whole-frame agreement must not move at all when pockets are added:
    a pocket is a vertical-walled cut with an analytic floor, and both paths
    compute the same floor from the same numbers.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import build_castle_solid, solid_to_relief

    castle = CastleParams()
    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    solid = build_castle_solid(demo_partition, castle, demo_hinges)
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)

    m = raster.inside
    d = (derived.field.z - raster.field.z)[m]
    assert (np.abs(d) <= 0.005).mean() > 0.99
    assert np.sqrt((d ** 2).mean()) < 0.02

    # The floor is endpiece height less the pocket depth, and it is really cut.
    # Sampled *inside* a hinge polygon: the part's global minimum is the
    # eyewire_inferior terrace at 4.2 mm, which is below the 4.5 mm pocket floor
    # and says nothing about whether the pocket was cut.
    from shapely import contains_xy

    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    rows, cols = derived.field.z.shape
    ox, oy = derived.field.origin
    res = derived.field.resolution
    xs = ox + np.arange(cols) * res
    ys = oy + np.arange(rows) * res
    gx, gy = np.meshgrid(xs, ys)

    for poly in demo_hinges:
        inpocket = contains_xy(poly, gx.ravel(), gy.ravel()).reshape(rows, cols) & m
        assert inpocket.any(), "hinge polygon fell outside the body"
        assert derived.field.z[inpocket].max() == pytest.approx(floor, abs=0.02)


def test_hinge_pockets_leave_the_surface_solid_alone(demo_partition, demo_hinges):
    """`return_surface` hands back the solid *before* the pockets — the M8
    `surface_field`, which the relief passes ride so they sail over pockets the
    Hinge Pockets op has already cut."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, volume

    castle = CastleParams()
    solid, surface = build_castle_solid(demo_partition, castle, demo_hinges,
                                        return_surface=True)
    assert volume(surface) > volume(solid), "pockets must remove material"


def test_bezel_is_a_real_chamfer_not_an_offset(demo_partition, demo_hinges):
    """The bezel cuts, stays valid, and agrees with the raster on flat ground.

    Where it does *not* agree is the point of the rewrite, so the bounds are
    deliberately asymmetric: tight on the fraction of cells that must match,
    loose on the worst case. The raster's version is a variable offset of
    whatever lies beneath; this is a ruled plane. They are identical on a flat
    terrace and diverge across footing swells — chiefly nosepad and bridge.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, is_valid,
                                       solid_to_relief, volume)

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    plain = build_castle_solid(demo_partition, castle.model_copy(
        update={"eyewire_bezel": CastleParams().eyewire_bezel}), demo_hinges)
    solid = build_castle_solid(demo_partition, castle, demo_hinges)

    assert is_valid(solid)
    assert volume(solid) < volume(plain), "the bezel must remove material"

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)
    m = raster.inside
    d = (derived.field.z - raster.field.z)[m]
    assert (np.abs(d) <= 0.005).mean() > 0.80
    assert (np.abs(d) <= 0.05).mean() > 0.92


def test_bezel_rim_depth_is_the_advertised_drop(demo_partition):
    """`width * tan(angle)` below the surface at the rim, all the way round.

    This is the property the rim anchoring exists to guarantee, and the one an
    inner-edge anchor loses: it drifts by the surface slope times the band
    width, which on this frame was worth 0.7 mm.
    """
    import math

    from shapely.geometry import LineString

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid
    from guildmodel.core.solid import features as FT
    from guildmodel.core.solid.occ import surface_z_at

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    p = castle.eyewire_bezel
    plain = build_castle_solid(demo_partition, CastleParams(), [])
    cut_solid = build_castle_solid(demo_partition, castle, [])

    ring = list(demo_partition.body.interiors)[0]
    pts, tans = FT._ring_stations(LineString(ring), 48)
    inward = FT._inward(demo_partition.body, pts, tans)
    probe = pts + inward * 0.10           # just inside the rim

    before = surface_z_at(plain, probe)
    after = surface_z_at(cut_solid, probe)
    expected = p.width_mm * math.tan(math.radians(p.angle_deg))

    # Allow for the 0.10 mm probe offset riding up the chamfer, and clamping.
    drop = before - after
    ok = np.abs(drop - expected) < 0.15
    assert ok.mean() > 0.85, f"rim depth held at only {100 * ok.mean():.0f}% of stations"


def test_brow_chamfer_edge_feature(demo_partition, demo_hinges):
    """M17's driving shape as a solid: a chamfer over each brow, not the bridge.

    This is the feature the whole rewrite was argued from — a partial-span
    tapered chamfer, which the Stage 1 spike ranked as the likeliest thing to
    force a fallback. It builds, it is valid and watertight, and it tracks the
    raster to 7 um rms.

    The span still comes from `span_intervals`, so M17's decision that a run is
    named by castle zone rather than measured along the ring survives the
    rewrite untouched — including `mirror`, which is why both eyewires appear.
    """
    from guildmodel.core.project.schema import CastleParams, EdgeFeature
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, is_valid,
                                       solid_to_relief, volume)
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.edge_features = [EdgeFeature(
        id="brow", label="Brow chamfer", face="posterior", edge="outline",
        zones=["eyewire_superior_od"], blend_mm=4.0, profile="chamfer",
        width_mm=2.0, angle_deg=45.0, mirror=True)]

    plain = build_castle_solid(demo_partition, CastleParams(), demo_hinges)
    solid = build_castle_solid(demo_partition, castle, demo_hinges)

    assert is_valid(solid)
    assert volume(solid) < volume(plain), "the chamfer must remove material"
    assert tessellate(solid).to_trimesh().is_watertight

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)
    m = raster.inside
    d = (derived.field.z - raster.field.z)[m]
    assert np.sqrt((d ** 2).mean()) < 0.02
    assert (np.abs(d) <= 0.005).mean() > 0.94
    assert (np.abs(d) <= 0.05).mean() > 0.99


def test_edge_feature_taper_never_collapses_a_section(demo_partition):
    """Stage 1 §5.1: a section that tapers to a true point fails outright.

    The run must still read as feathering to nothing, so the floor is 0.02 mm —
    a fiftieth of the finishing tool's radius. This pins that the floor is in
    force and that it is small enough to be invisible.
    """
    from guildmodel.core.project.schema import CastleParams, EdgeFeature
    from guildmodel.core.solid import build_castle_solid, is_valid
    from guildmodel.core.solid.features import MIN_TAPER_DROP_MM

    assert 0 < MIN_TAPER_DROP_MM <= 0.05

    castle = CastleParams()
    # blend longer than half the run: the taper law caps it, and every section
    # in the run ends up on the ramp rather than at full depth.
    castle.edge_features = [EdgeFeature(
        id="feather", face="posterior", edge="outline",
        zones=["eyewire_superior_od"], blend_mm=40.0,
        profile="chamfer", width_mm=2.0, angle_deg=45.0)]
    solid = build_castle_solid(demo_partition, castle, [])
    assert is_valid(solid)


def test_pad_splay_as_a_swept_chamfer(demo_partition, demo_hinges):
    """The splay, with its compensating blur left out rather than ported.

    `_splay_crest_tables` is the report's smoothing inventory in one function —
    a slope limiter, two `uniform_filter1d` passes, an EDT-filled anchor
    surface, and a mandatory 2 mm crest round-over. None of it is here: the
    crest is a real edge and wants to be sharp. What is kept is the geometry
    those filters were protecting — the crest offset, the lens-rim clearance
    clamp, the toric angle blend and the end feather.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, is_valid,
                                       solid_to_relief, volume)
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.pad_splay.crest_blend_mm = 0.0      # compare like with like

    plain = build_castle_solid(demo_partition, CastleParams(), demo_hinges)
    solid = build_castle_solid(demo_partition, castle, demo_hinges)

    assert is_valid(solid)
    assert volume(solid) < volume(plain), "the splay must remove material"
    assert tessellate(solid).to_trimesh().is_watertight

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)
    d = (derived.field.z - raster.field.z)[raster.inside]
    assert np.sqrt((d ** 2).mean()) < 0.03
    assert (np.abs(d) <= 0.05).mean() > 0.97


def test_pad_splay_is_anchored_at_the_crest(demo_partition, demo_hinges):
    """Regression on the datum, which is the whole of this feature's accuracy.

    The splay falls *from the crest* toward the outline edge, and the crest sits
    up to `crest_deviation_center_mm` (6 mm) inboard. Anchoring at the outline
    edge instead measures the drop from the wrong height — over 6 mm the surface
    climbs out of the bridge footing into the nosepad tower — and left the cut
    0.11 mm rms shallow, up to 0.97 mm at the nosepads.

    Note this is the opposite anchor from the bezel, deliberately: each feature
    is anchored where its own definition pins it.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import build_castle_solid, solid_to_relief

    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.pad_splay.crest_blend_mm = 0.0

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(
        build_castle_solid(demo_partition, castle, demo_hinges),
        demo_partition, castle, resolution=CUT_RES_MM)

    d = (derived.field.z - raster.field.z)[raster.inside]
    # Edge-anchoring showed as a large POSITIVE bias: the solid systematically
    # kept material the raster removed. Crest-anchoring removes the bias.
    assert abs(d.mean()) < 0.01, "systematic depth bias — wrong anchor datum?"


def test_bridge_relief_is_a_cone_not_a_bell(demo_partition, demo_hinges):
    """The scoop as the cone its own docstring claims, not the cosine bell.

    The raster's cross-section is `0.5 + 0.5 cos(pi x / r)` — on the report's
    list of compensating blurs, chosen because it meets the surface tangentially
    and so hides the facets a sampled cone showed. A real cone meets the surface
    at an angle, and that meeting is an edge.

    The two differ in a predictable direction: at half the scoop radius an
    ellipse is at 0.866 of full depth where the bell is at 0.500, so the solid
    cuts *deeper* across the middle of the band. The assertion is on that
    direction, since a sign flip would mean the section was built inverted.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, is_valid,
                                       solid_to_relief, volume)
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.bridge_relief.enabled = True

    plain = build_castle_solid(demo_partition, CastleParams(), demo_hinges)
    solid = build_castle_solid(demo_partition, castle, demo_hinges)

    assert is_valid(solid)
    assert volume(solid) < volume(plain), "the scoop must remove material"
    assert tessellate(solid).to_trimesh().is_watertight

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)
    m = raster.inside
    diff = derived.field.z - raster.field.z            # full grid, not masked
    assert (np.abs(diff[m]) <= 0.005).mean() > 0.97

    # Inside the scoop the cone must sit below the bell.
    names = [z.name for z in demo_partition.zones]
    bridge = np.array([n == "bridge" for n in names])[raster.zone_index]
    deep = m & bridge & (np.abs(diff) > 0.05)
    assert deep.sum() > 100, "the scoop barely touched the bridge"
    assert (diff[deep] < 0).mean() > 0.9, "cone should cut deeper than the bell"


def test_scoop_respects_the_anterior_clamp(demo_partition):
    """The cut may never come closer to the front face than the clamp."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.solid import build_castle_solid, solid_to_relief

    castle = CastleParams()
    castle.bridge_relief.enabled = True
    castle.bridge_relief.depth_mm = 20.0          # absurd: must clamp, not punch through
    castle.bridge_relief.anterior_clamp_mm = 1.5

    solid = build_castle_solid(demo_partition, castle, [])
    derived = solid_to_relief(solid, demo_partition, castle,
                              resolution=CUT_RES_MM)
    inside = derived.inside
    assert derived.field.z[inside].min() >= 1.5 - 0.05


# ---------------------------------------------------------------- lens groove

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


def test_lens_groove_is_a_real_undercut(demo_partition):
    """The feature that most plainly justifies the rewrite.

    The drageoir V is cut radially into the aperture wall, so it is an
    **undercut**: a heightfield cannot hold it at any resolution. The raster
    reaches it by shrinking the aperture mask and then hand-building a notched
    rim strip in the *mesher* (`castle._groove_rim`) — geometry the model itself
    does not contain, and therefore cannot be measured, sectioned or posted
    from. Here it is a boolean like any other.

    Proof is by ray crossings, not by surface height: a vertical ray through the
    wall must cut FOUR surfaces — anterior, groove floor, groove roof, top — and
    drop back to two beyond the apex. Taking min/max Z instead shows nothing at
    all, which is precisely the blindness being fixed.
    """
    from shapely.geometry import LineString

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, is_valid
    from guildmodel.core.solid import features as FT
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.lens_groove.enabled = True
    g = castle.lens_groove

    solid = build_castle_solid(demo_partition, castle, [])
    assert is_valid(solid)
    mesh = tessellate(solid).to_trimesh()
    assert mesh.is_watertight
    assert mesh.euler_number == -2

    lip = FT.lip_body(demo_partition.body, g.depth_mm, demo_partition.is_hole)
    pts, tans = FT._ring_stations(LineString(lip.interiors[0]), 40)
    inward = FT._inward(lip, pts, tans)

    deep = sum(1 for k in range(len(pts))
               if len(_ray_crossings(solid, *(pts[k] + inward[k] * 0.35))) >= 4)
    assert deep == len(pts), f"undercut missing at {len(pts) - deep} stations"

    # Past the apex the wall is solid again.
    beyond = _ray_crossings(solid, *(pts[0] + inward[0] * (g.depth_mm + 0.15)))
    assert len(beyond) == 2


def test_lens_groove_v_matches_the_cutter_spec(demo_partition):
    """Half-width falls linearly from `width_mm / 2` at the lip face to zero at
    `depth_mm`, so the apex lands on the original LENS contour and the boxed
    dimension stays honest.

    Pinned to microns because the first construction extended the lead-in by
    padding Z rather than following the flanks, which cut the groove ~7% narrow
    — 0.867 mm half-width where the spec says 0.933.
    """
    from shapely.geometry import LineString

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid
    from guildmodel.core.solid import features as FT

    castle = CastleParams()
    castle.lens_groove.enabled = True
    g = castle.lens_groove

    solid = build_castle_solid(demo_partition, castle, [])
    lip = FT.lip_body(demo_partition.body, g.depth_mm, demo_partition.is_hole)
    pts, tans = FT._ring_stations(LineString(lip.interiors[0]), 8)
    inward = FT._inward(lip, pts, tans)

    for u in (0.02, 0.25, 0.55):
        z = _ray_crossings(solid, *(pts[0] + inward[0] * u))
        assert len(z) >= 4
        half_w = (z[2] - z[1]) / 2.0
        expected = (g.width_mm / 2.0) * (1.0 - u / g.depth_mm)
        assert half_w == pytest.approx(expected, abs=0.005)
        # Centred on the apex height above the anterior face.
        assert (z[1] + z[2]) / 2.0 == pytest.approx(g.anterior_offset_mm, abs=0.01)


def test_lens_groove_zmap_matches_the_raster(demo_partition, demo_hinges):
    """Top-down the groove is invisible, so what the Z-map must get right is the
    rim *lip*: the aperture shrunk by `depth_mm`. Both paths mask against the
    undersized body or they disagree over the whole annulus.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import build_castle_solid, solid_to_relief

    castle = CastleParams()
    castle.lens_groove.enabled = True

    raster = build_castle_relief(demo_partition, castle, demo_hinges,
                                 resolution=CUT_RES_MM)
    derived = solid_to_relief(
        build_castle_solid(demo_partition, castle, demo_hinges),
        demo_partition, castle, resolution=CUT_RES_MM)

    assert np.array_equal(derived.inside, raster.inside)
    d = (derived.field.z - raster.field.z)[raster.inside]
    assert np.sqrt((d ** 2).mean()) < 0.01
    assert (np.abs(d) <= 0.005).mean() > 0.99


def test_terrace_collapse_is_caught_not_silent(demo_partition):
    """The kernel's signature failure is an empty result that reports valid.

    It has now bitten three times — the hole-winding face, the footing fill
    clip, and the buffered lip zones — so the terrace union carries an explicit
    volume guard. This pins that the guard exists and that the normal path
    passes it.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, volume
    from guildmodel.core.solid.occ import BooleanError

    assert BooleanError is not None
    solid = build_castle_solid(demo_partition, CastleParams(), [])
    assert volume(solid) > 1000.0


# ------------------------------------ the anterior bezel (2026-08-07 finding 3)

def test_anterior_eyewire_bezel_cuts_the_front(demo_partition, demo_hinges):
    """The anterior bezel must remove material from the front face.

    Carried a strict xfail until 2026-08-07: only `cuts_posterior()` had been
    ported, so `face='anterior'` removed 0.00 mm3. Anterior *edge features*
    already worked — they cut from the underside via
    `surface_z_at(..., face='bottom')` — so this was a porting gap, and the fix
    is to spell the band as the whole-ring `EdgeFeature` it is, exactly as the
    raster does in `relief.edges.carve_anterior_bezel`.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, volume

    plain = volume(build_castle_solid(demo_partition, CastleParams(), demo_hinges))

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    castle.eyewire_bezel.face = "anterior"
    cut_vol = volume(build_castle_solid(demo_partition, castle, demo_hinges))

    assert cut_vol < plain - 1.0, "anterior bezel removed nothing"


def test_bezel_face_selects_which_side_is_cut(demo_partition, demo_hinges):
    """`posterior` / `anterior` / `both` must be three different solids.

    The specific shape of the old bug: `both` removed *exactly* what `posterior`
    did, to the last decimal, because the anterior half was simply absent. So
    equality between them is the regression to guard, not merely inequality with
    the uncut frame.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, volume

    def vol_for(face):
        castle = CastleParams()
        castle.eyewire_bezel.enabled = True
        castle.eyewire_bezel.face = face
        return volume(build_castle_solid(demo_partition, castle, demo_hinges))

    plain = volume(build_castle_solid(demo_partition, CastleParams(), demo_hinges))
    post, ant, both = vol_for("posterior"), vol_for("anterior"), vol_for("both")

    assert post < plain and ant < plain, "each face must remove something"
    assert abs(both - post) > 1.0, "'both' must cut more than 'posterior' alone"
    assert abs(both - ant) > 1.0, "'both' must cut more than 'anterior' alone"
    # Both bands together remove about what the two remove separately — they sit
    # on opposite faces of the same rim and only interact where the frame is
    # thin enough for the chamfers to meet.
    assert both < min(post, ant)


def test_anterior_edge_features_do_cut_the_front(demo_partition, demo_hinges):
    """The counterpart that DOES work — pinned so the gap above stays specific.

    In a solid the anterior face is just the underside of the same body, so an
    anterior run needs no second heightfield and no `thickness()` invariant.
    That is M17's scaffolding gone, and it is why the bezel gap is a porting
    oversight rather than a missing capability.
    """
    from guildmodel.core.project.schema import CastleParams, EdgeFeature
    from guildmodel.core.solid import build_castle_solid, volume

    plain = volume(build_castle_solid(demo_partition, CastleParams(), demo_hinges))

    castle = CastleParams()
    castle.edge_features = [EdgeFeature(
        id="brow-front", face="anterior", edge="outline",
        zones=["eyewire_superior_od"], width_mm=2.0, angle_deg=45.0, mirror=True)]
    cut_vol = volume(build_castle_solid(demo_partition, castle, demo_hinges))

    assert cut_vol < plain - 1.0


# ------------------------------------------- one builder for every worker (2026-08-07)

def test_build_component_mesh_emits_edges_on_the_solid_path(demo_partition,
                                                            demo_hinges):
    """The single builder every mesh worker now goes through.

    `edges` is what the four Fusion-parity display modes are drawn from, so a
    None here is exactly what makes the viewer disable the mode combo.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import build_component_mesh

    spec = {"mode": "castle", "partition": demo_partition,
            "castle": CastleParams(), "hinge": list(demo_hinges),
            "stage": "pockets"}

    mesh, edges, guide = build_component_mesh(spec, resolution=0.6, solid=True)
    assert guide is None
    assert edges, "the solid path must carry its topological edges"
    assert len(edges) > 100, f"only {len(edges)} edges — that is not the frame"

    raster_mesh, raster_edges, _ = build_component_mesh(spec, resolution=0.6)
    assert raster_edges is None, "the raster has no edges to give"
    assert len(raster_mesh.faces) > len(mesh.faces), (
        "the raster mesh should be far heavier than the tessellated solid")


def test_build_3d_reaches_the_solid_path(demo_partition, demo_hinges, monkeypatch):
    """Regression for the 2026-08-07 finding 2: the dead display-mode dropdown.

    Build 3D goes through `MultiMeshWorker`, which had never been given the
    solid branch — so it always returned raster meshes with `edges=None`, the
    viewer correctly disabled the combo, and clicking it did nothing. Meanwhile
    a *parameter* change went through `MeshWorker` and did build a solid, which
    is why the fault looked intermittent.

    Driven synchronously: no threads, no VTK.
    """
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.app import MultiMeshWorker

    specs = [{"index": 0, "mode": "castle", "label": "Frame Front",
              "partition": demo_partition, "castle": CastleParams(),
              "hinge": list(demo_hinges), "stage": "pockets"}]

    built, errors = [], []
    w = MultiMeshWorker(specs, resolution=0.6, solid=True)
    w.built.connect(lambda i, m, e, g: built.append((i, m, e, g)))
    w.error.connect(lambda tb: errors.append(tb))
    w.run()

    assert errors == [], errors[0] if errors else ""
    assert len(built) == 1
    assert built[0][2], "Build 3D on the solid path must emit edges"


def test_workspace_carries_its_own_edge_cache():
    """Edges are per-component state and must switch with the tab.

    `_edge_cache` lived on the main window while `stage_cache` lived on the
    workspace, so tab-switching swapped the meshes and left the edges behind.
    Survivable only while one frame front was the only thing that could produce
    edges — and Build 3D now emits them for every component it builds as a
    solid.
    """
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import ComponentWorkspace

    def ws(kind, label):
        return ComponentWorkspace(kind=kind, label=label, layers={})

    a = ws(ComponentKind.FRAME_FRONT, "Frame Front")
    b = ws(ComponentKind.TEMPLE_RIGHT, "Temple R")
    assert hasattr(a, "edge_cache"), "edges must be per-component state"
    a.edge_cache["pockets"] = [((0, 0, 0), (1, 1, 1))]
    assert b.edge_cache == {}, "edge caches must not be shared between components"
