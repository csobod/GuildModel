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
