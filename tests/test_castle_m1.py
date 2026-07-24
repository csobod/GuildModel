"""M1 tests: posterior flip, castle zone partitioning, castle schema.

Ground truth is the committed Demo Project reference set
(tests/fixtures/demo/); these are the M1 acceptance tests from
BUILDPLAN.md.
"""
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

DEMO_DXF = Path(__file__).parents[1] / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf"


# ---------------------------------------------------------------- M1.2: flip

def test_posterior_flip_negates_x_only():
    from guildmodel.core.io_import.dxf import import_dxf

    anterior = import_dxf(DEMO_DXF, posterior=False)
    posterior = import_dxf(DEMO_DXF)  # default posterior=True

    for layer in ("OUTLINE", "LENS", "SCULPT", "HINGE", "REF"):
        assert len(anterior[layer]) == len(posterior[layer])
    a = anterior["OUTLINE"][0]
    p = posterior["OUTLINE"][0]
    assert len(a) == len(p)
    for (ax, ay), (px, py) in zip(a[:50], p[:50]):
        assert px == pytest.approx(-ax)
        assert py == pytest.approx(ay)


def test_posterior_flip_is_involution():
    from guildmodel.core.io_import.dxf import import_dxf

    once = import_dxf(DEMO_DXF)
    twice = [(-x, y) for x, y in once["OUTLINE"][0]]
    raw = import_dxf(DEMO_DXF, posterior=False)
    for (rx, ry), (tx, ty) in zip(raw["OUTLINE"][0], twice):
        assert rx == pytest.approx(tx)
        assert ry == pytest.approx(ty)


# ----------------------------------------------------- M1.3: demo partition

@pytest.fixture(scope="module")
def demo_partition():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO_DXF)
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    return partition_zones(outline, lenses, raw["SCULPT"])


def test_demo_partitions_into_nine_labeled_zones(demo_partition):
    assert demo_partition.matched is True
    assert len(demo_partition.zones) == 9
    names = {z.name for z in demo_partition.zones}
    assert names == {
        "endpiece_od", "endpiece_os", "bridge", "nosepad_od", "nosepad_os",
        "eyewire_superior_od", "eyewire_superior_os",
        "eyewire_inferior_od", "eyewire_inferior_os",
    }


def test_demo_zone_positions(demo_partition):
    # Posterior coordinates: OD on +x, superior on +y.
    assert demo_partition.zone("endpiece_od").polygon.centroid.x > 40
    assert demo_partition.zone("endpiece_os").polygon.centroid.x < -40
    bridge = demo_partition.zone("bridge").polygon
    assert bridge.bounds[0] < 0 < bridge.bounds[2]   # crosses centerline
    sup = demo_partition.zone("eyewire_superior_od").polygon.centroid.y
    inf = demo_partition.zone("eyewire_inferior_od").polygon.centroid.y
    assert sup > inf
    for side in ("od", "os"):
        assert abs(demo_partition.zone(f"nosepad_{side}").polygon.centroid.x) < 20


def test_demo_zones_cover_body_without_overlap(demo_partition):
    total = sum(z.polygon.area for z in demo_partition.zones)
    assert total == pytest.approx(demo_partition.body.area, rel=0.01)
    zones = demo_partition.zones
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            assert a.polygon.intersection(b.polygon).area < 0.1


def test_demo_edges_all_canonical(demo_partition):
    assert len(demo_partition.edges) == 10
    from collections import Counter
    canon = Counter(e.canonical for e in demo_partition.edges)
    assert canon == {
        "endpiece_superior": 2, "endpiece_inferior": 2,
        "bridge_superior": 2, "nosepad_superior": 2, "nosepad_inferior": 2,
    }
    for e in demo_partition.edges:
        assert e.side in ("od", "os")
        assert len(e.zone_names) == 2


# ------------------------------------------------ M1.3: generic fallback

def _rect(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_nonstandard_cut_count_is_classified_but_not_matched():
    """A non-standard cut count is not the reference castle, but the zones are
    still named against the lenses — so it builds. `matched` stays narrow."""
    from guildmodel.core.geometry.regions import partition_zones

    outline = _rect(-50, -20, 50, 20)
    lenses = [Point(-25, 0).buffer(12), Point(25, 0).buffer(12)]
    cuts = [
        [(-40, -21), (-40, 21)],
        [(0, -21), (0, 21)],
        [(40, -21), (40, 21)],
    ]
    part = partition_zones(outline, lenses, cuts)
    assert part.matched is False
    assert part.classified is True
    assert len(part.zones) == 4
    assert all(z.kind != "generic" for z in part.zones)


def test_zones_fall_back_to_generic_without_lenses_to_reason_from():
    """No LENS openings means no anatomical reference frame — the zones get
    positional names and the castle refuses to build without explicit heights."""
    from guildmodel.core.geometry.regions import partition_zones

    outline = _rect(-50, -20, 50, 20)
    cuts = [
        [(-40, -21), (-40, 21)],
        [(0, -21), (0, 21)],
        [(40, -21), (40, 21)],
    ]
    part = partition_zones(outline, [], cuts)
    assert part.matched is False
    assert part.classified is False
    assert all(z.kind == "generic" for z in part.zones)
    assert [z.name for z in part.zones] == [f"zone_{i + 1}" for i in range(4)]
    assert all(e.name.startswith("edge_") for e in part.edges)


def test_no_cuts_yields_single_generic_zone():
    from guildmodel.core.geometry.regions import partition_zones

    outline = _rect(-50, -20, 50, 20)
    part = partition_zones(outline, [Point(0, 0).buffer(10)], [])
    assert part.matched is False
    assert len(part.zones) == 1
    assert part.zones[0].polygon.interiors  # lens hole preserved


# ------------------------------------------------------- M1.4: castle schema

def test_castle_schema_demo_defaults():
    from guildmodel.core.project.schema import CastleParams

    c = CastleParams()
    assert c.zones.endpiece_mm == 5.5
    assert c.zones.bridge_mm == 5.3
    assert c.zones.nosepad_mm == 10.0
    assert c.zones.eyewire_superior_mm == 4.8
    assert c.zones.eyewire_inferior_mm == 4.2
    assert c.zones.for_kind("eyewire_superior") == 4.8
    f = c.footing.for_edge("endpiece_superior")
    assert (f.exterior_mm, f.interior_mm) == (32.0, 48.0)
    f = c.footing.for_edge("nosepad_superior")
    assert (f.exterior_mm, f.interior_mm) == (6.0, 4.0)
    assert c.hinge_pocket_depth_mm == 1.0
    assert c.onion_skin_mm == 0.4
    assert c.hand_finishing_allowance_mm == 0.1
    assert c.stock.blank_length_mm == 170.0
    assert c.stock.blank_width_mm == 85.0
    assert c.stock.total_pad_height_mm == 10.0
    assert c.stock.pad_block_length_mm == 45.0


def test_castle_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    proj = ProjectSchema(job_name="Castle RT")
    proj.castle.zones.bridge_mm = 5.0
    proj.castle.footing.bridge_superior.exterior_mm = 20.0
    proj.castle.stock.pad_block_dy_mm = -3.5
    path = tmp_path / "castle.guildmodel"
    save_project(proj, path)
    back = load_project(path)
    assert back.castle.zones.bridge_mm == 5.0
    assert back.castle.footing.bridge_superior.exterior_mm == 20.0
    assert back.castle.stock.pad_block_dy_mm == -3.5
    # untouched fields keep demo defaults
    assert back.castle.zones.nosepad_mm == 10.0
    assert back.castle.footing.endpiece_inferior.interior_mm == 32.0
