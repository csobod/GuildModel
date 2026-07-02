"""M13.3 CAM tests: the posterior features are actually MACHINED.

The feature-finish band adds fine contour rings confined to the feature bands
at a cusp-derived stepover (the standard 0.9 mm stepover leaves ~0.52 mm facet
ridges on a 30° chamfer — over the sim's 0.5 mm completeness tolerance). Gates:
the fine op gains band rings; the band facets shrink to the cusp target (the
motivating with/without comparison); the through-cut contours are byte-equal
features-on vs off; the demo with ALL features on, fine pass on a ball, sims
green end to end; and the groove reach warning names a fitting ball.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, hinges


@pytest.fixture(scope="module")
def tools():
    return yaml.safe_load((CONFIG / "tools.yaml").read_text())


def _castle(splay=False, bezel=False, groove=False):
    from guildmodel.core.project.schema import CastleParams

    c = CastleParams()
    c.pad_splay.enabled = splay
    c.eyewire_bezel.enabled = bezel
    c.bridge_relief.enabled = groove
    return c


def _build(demo, castle, res=0.3):
    from guildmodel.core.relief.castle import build_castle_relief

    part, hinges = demo
    return build_castle_relief(part, castle, hinges, resolution=res)


def _band_excess(relief, ops, profiles_by_name, default_profile, erode_mm=0.0):
    """Max leftover stock over the feature band after sweeping the program.

    `erode_mm` shrinks the band away from the body boundary: within a fine-tool
    radius of a rim no flat tool can finish a downhill chamfer (its trailing
    edge rides the slope behind), so the facet gate measures the band interior
    — the rim strip is the reach warning's territory, not the stepover's."""
    from guildmodel.core.sim import achieved_floor_grouped

    f = relief.field
    groups = [(p, op.tool_name) for op in ops for p in op.paths]
    floor = achieved_floor_grouped(
        groups, profiles_by_name, default_profile,
        f.origin, f.z.shape, f.resolution, init_z=12.0)
    band = relief.feature_band
    if erode_mm > 0.0:
        from scipy.ndimage import distance_transform_edt
        dist_in = distance_transform_edt(relief.inside, sampling=f.resolution)
        band = band & (dist_in > erode_mm)
    return float((floor - f.z)[band].max())


# ------------------------------------------------------------------ band rings

def test_fine_op_gains_feature_band_rings(demo, tools):
    from guildmodel.core.cam.castle_ops import generate_castle_program

    part, hinges = demo
    off = generate_castle_program(_build(demo, _castle()), _castle(),
                                  hinges, tools["flat_3175"])
    on = generate_castle_program(_build(demo, _castle(splay=True, bezel=True)),
                                 _castle(splay=True, bezel=True),
                                 hinges, tools["flat_3175"])
    fine_off = next(op for op in off if op.name == "Fine Relief")
    fine_on = next(op for op in on if op.name == "Fine Relief")
    assert len(fine_on.paths) > len(fine_off.paths)
    # no new ops — the five-op program shape is unchanged
    assert [op.name for op in on] == [op.name for op in off]


def test_band_rings_shrink_chamfer_facets(demo, tools):
    """The motivating gate: without the feature-finish band the flat tool
    leaves ~stepover*tan(30°) ≈ 0.5 mm facet ridges on the chamfers; with it
    the leftover drops to the cusp target."""
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.sim import ToolProfile

    castle = _castle(splay=True, bezel=True)
    relief = _build(demo, castle)
    part, hinges = demo
    tool = tools["flat_3175"]
    prof = ToolProfile.from_tool(tool)

    erode = tool["radius_mm"] + 2 * 0.3        # rim strip = flat-tool territory
    ops_with = generate_castle_program(relief, castle, hinges, tool)
    excess_with = _band_excess(relief, ops_with, {}, prof, erode_mm=erode)

    # strip the band -> relief_ops falls back to the plain 0.9 mm rings
    relief.feature_band, saved = None, relief.feature_band
    ops_without = generate_castle_program(relief, castle, hinges, tool)
    relief.feature_band = saved
    excess_without = _band_excess(relief, ops_without, {}, prof, erode_mm=erode)

    assert excess_with <= 0.35
    assert excess_without > excess_with + 0.1


def test_contours_byte_equal_features_on_vs_off(demo, tools):
    from guildmodel.core.cam.castle_ops import generate_castle_program

    part, hinges = demo
    tool = tools["flat_3175"]
    ops_off = generate_castle_program(_build(demo, _castle()), _castle(),
                                      hinges, tool)
    ops_on = generate_castle_program(
        _build(demo, _castle(splay=True, bezel=True, groove=True)),
        _castle(splay=True, bezel=True, groove=True), hinges, tool)
    for name in ("Eyewires", "Perimeter"):
        a = next(op for op in ops_off if op.name == name)
        b = next(op for op in ops_on if op.name == name)
        assert a.paths == b.paths


# ------------------------------------------------------------------ end to end

def test_all_features_on_sim_green_with_ball_fine(demo, tools):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.core.sim import ToolProfile, achieved_floor_grouped, verify

    castle = _castle(splay=True, bezel=True, groove=True)
    relief = _build(demo, castle)
    part, hinges = demo
    tool = tools["flat_3175"]
    params = CastleCamParams(op_tools={"Fine Relief": "ball_2mm"})
    ops = generate_castle_program(relief, castle, hinges, tool,
                                  params=params, tools_cfg=tools)

    profiles = {name: ToolProfile.from_tool({**t, "name": name})
                for name, t in tools.items()}
    f = relief.field
    groups = [(p, op.tool_name) for op in ops for p in op.paths]
    floor = achieved_floor_grouped(groups, profiles, ToolProfile.from_tool(tool),
                                   f.origin, f.z.shape, f.resolution, init_z=12.0)
    target = np.where(relief.inside, f.z, np.nan)
    report = verify(floor, target, relief.inside, f.origin, f.resolution,
                    partition=part)
    msg = "\n".join(report.summary_lines())
    assert report.completeness.uncut_fraction <= 0.04, msg
    assert report.gouge.gouge_fraction <= 0.01, msg
    # With a ball fine tool the band finishes tight right up to the rims —
    # only the outermost half-kerf cell ring is excluded (0.7 mm ~ 2 cells;
    # the boundary cell's target is sampled on the rim edge itself and every
    # house gate treats that ring leniently, cf. verify's gouge rim margin).
    excess = _band_excess(relief, ops, profiles, ToolProfile.from_tool(tool),
                          erode_mm=0.7)
    assert excess <= 0.35, f"band excess {excess:.2f} mm"


# ------------------------------------------------------------------ reach

def test_groove_reach_warning_for_flat_fine_tool(demo, tools):
    from guildmodel.core.cam.castle_ops import (
        feature_reach_warnings, generate_castle_program,
    )
    from guildmodel.core.project.schema import CastleCamParams

    castle = _castle(groove=True)
    relief = _build(demo, castle)
    part, hinges = demo
    tool = tools["flat_3175"]

    ops = generate_castle_program(relief, castle, hinges, tool)
    warns = feature_reach_warnings(castle, ops, tools)
    assert len(warns) == 1
    assert warns[0].suggested == "ball_2mm"
    assert "ball" in warns[0].message()

    # a fitting ball raises nothing
    params = CastleCamParams(op_tools={"Fine Relief": "ball_2mm"})
    ops_ball = generate_castle_program(relief, castle, hinges, tool,
                                       params=params, tools_cfg=tools)
    assert feature_reach_warnings(castle, ops_ball, tools) == []

    # features off raise nothing either
    assert feature_reach_warnings(_castle(), ops, tools) == []

    # a chamfer on a flat fine tool warns about the rim toe (ball suggested)
    bezel = _castle(bezel=True)
    warns = feature_reach_warnings(bezel, ops, tools)
    assert len(warns) == 1
    assert "rim" in warns[0].message() and warns[0].suggested == "ball_2mm"
    assert feature_reach_warnings(bezel, ops_ball, tools) == []
