"""M4 tests: the core layer under the parametric castle UI — the teaching
stage builds (BUILDPLAN M4.4) and the op-summary setup sheet (M4.6).

GUI widgets are not tested here (tests run against core only); these cover
the functions the M4 panels drive.
"""
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"

RES = 0.5   # coarse grid — stage tests need topology, not the M2 gate


@pytest.fixture(scope="module")
def demo_inputs():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams(), hinges


def _zone_mask(relief, name: str) -> np.ndarray:
    idx = [z.name for z in relief.partition.zones].index(name)
    return (relief.zone_index == idx) & relief.inside


# ------------------------------------------------------------------ stages

def test_towers_stage_walls_at_ground(demo_inputs):
    from guildmodel.core.relief.castle import STAGE_GROUND_MM, build_castle_stage

    part, castle, hinges = demo_inputs
    relief = build_castle_stage(part, castle, hinges, stage="towers", resolution=RES)
    z = relief.field.z
    assert np.allclose(z[_zone_mask(relief, "endpiece_od")], castle.zones.endpiece_mm)
    assert np.allclose(z[_zone_mask(relief, "bridge")], castle.zones.bridge_mm)
    assert np.allclose(z[_zone_mask(relief, "nosepad_os")], castle.zones.nosepad_mm)
    for wall in ("eyewire_superior_od", "eyewire_inferior_os"):
        assert np.allclose(z[_zone_mask(relief, wall)], STAGE_GROUND_MM)


def test_walls_stage_sharp_terraces(demo_inputs):
    from guildmodel.core.relief.castle import build_castle_stage

    part, castle, hinges = demo_inputs
    relief = build_castle_stage(part, castle, hinges, stage="walls", resolution=RES)
    expected = np.array([
        castle.zones.endpiece_mm, castle.zones.bridge_mm, castle.zones.nosepad_mm,
        castle.zones.eyewire_superior_mm, castle.zones.eyewire_inferior_mm,
    ])
    vals = np.unique(relief.field.z[relief.inside])
    # No footing yet: every inside pixel sits exactly on a terrace plane.
    assert all(np.min(np.abs(expected - v)) < 1e-9 for v in vals)
    assert np.allclose(
        relief.field.z[_zone_mask(relief, "eyewire_superior_os")],
        castle.zones.eyewire_superior_mm,
    )


def test_footing_stage_adds_blends_no_pockets(demo_inputs):
    from guildmodel.core.relief.castle import build_castle_stage

    part, castle, hinges = demo_inputs
    relief = build_castle_stage(part, castle, hinges, stage="footing", resolution=RES)
    z = relief.field.z[relief.inside]
    # Blend surfaces produce heights strictly between the wall and tower planes…
    between = (z > castle.zones.eyewire_superior_mm + 0.05) & (
        z < castle.zones.endpiece_mm - 0.05
    )
    assert between.any()
    # …but the hinge pockets are not cut yet.
    pocket_floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    pocket = _zone_mask(relief, "endpiece_od") & np.zeros_like(relief.inside)
    for poly in hinges:
        from shapely import contains_xy
        hit = contains_xy(poly, relief.Xs.ravel(), relief.Ys.ravel())
        pocket |= hit.reshape(relief.inside.shape) & relief.inside
    assert not np.any(np.isclose(relief.field.z[pocket], pocket_floor))


def test_pockets_stage_is_the_full_relief(demo_inputs):
    from guildmodel.core.relief.castle import build_castle_relief, build_castle_stage

    part, castle, hinges = demo_inputs
    staged = build_castle_stage(part, castle, hinges, stage="pockets", resolution=RES)
    full = build_castle_relief(part, castle, hinges, resolution=RES)
    assert np.array_equal(staged.field.z, full.field.z)


def test_stage_validation(demo_inputs):
    from guildmodel.core.geometry.regions import CastlePartition, Zone
    from guildmodel.core.relief.castle import build_castle_stage

    part, castle, hinges = demo_inputs
    with pytest.raises(ValueError, match="stage"):
        build_castle_stage(part, castle, hinges, stage="moat")

    # Stages need zone *kinds* (they split towers from walls), so the gate is
    # `classified`, not `matched` — a non-standard-but-named layout stages fine.
    unmatched = CastlePartition(body=part.body, zones=part.zones, matched=False)
    build_castle_stage(unmatched, castle, hinges, stage="towers", resolution=RES)

    generic = CastlePartition(
        body=part.body,
        zones=[Zone(f"zone_{i + 1}", "generic", "", z.polygon)
               for i, z in enumerate(part.zones)],
        matched=False,
    )
    with pytest.raises(ValueError, match="castle zones"):
        build_castle_stage(generic, castle, hinges, stage="towers")


def test_stage_does_not_mutate_castle_params(demo_inputs):
    from guildmodel.core.relief.castle import build_castle_stage

    part, castle, hinges = demo_inputs
    before = castle.model_dump()
    build_castle_stage(part, castle, hinges, stage="walls", resolution=RES)
    assert castle.model_dump() == before


# ------------------------------------------------------------------ op summary

def test_path_length_and_summary_rows():
    from guildmodel.core.cam.castle_ops import CamOp, op_summaries

    op = CamOp(name="Perimeter", paths=[
        [(0.0, 0.0, 1.0), (3.0, 4.0, 1.0)],      # 5 mm
        [(0.0, 0.0, 0.4), (0.0, 0.0, 2.4)],      # 2 mm, floor 0.4
    ])
    assert op.path_length_mm() == pytest.approx(7.0)

    rows = op_summaries([op], feed_rate_mmpm=700.0)
    (row,) = rows
    assert row["name"] == "Perimeter"
    assert "Contour" in row["strategy"]
    assert row["paths"] == 2
    assert row["floor_z_mm"] == pytest.approx(0.4)
    assert row["cut_length_mm"] == pytest.approx(7.0)
    assert row["est_minutes"] == pytest.approx(0.01)

    no_feed = op_summaries([op])
    assert "est_minutes" not in no_feed[0]


def test_summary_covers_the_demo_program(demo_inputs):
    import yaml
    from guildmodel.core.cam.castle_ops import generate_castle_program, op_summaries
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo_inputs
    relief = build_castle_relief(part, castle, hinges, resolution=RES)
    tools = yaml.safe_load(
        (ROOT / "src" / "guildmodel" / "config" / "tools.yaml").read_text(encoding="utf-8")
    )
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"])
    rows = op_summaries(ops, feed_rate_mmpm=750.0)
    assert [r["name"] for r in rows] == [
        "Hinge Pockets", "Rough Relief", "Fine Relief", "Eyewires", "Perimeter",
    ]
    assert all(r["strategy"] != "—" for r in rows)
    for r in rows:
        if r["name"] in ("Eyewires", "Perimeter"):
            assert r["floor_z_mm"] == pytest.approx(castle.onion_skin_mm)
        assert r["cut_length_mm"] > 0
        assert r["est_minutes"] > 0
