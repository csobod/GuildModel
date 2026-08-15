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
DEMO = ROOT / "tests" / "fixtures" / "demo"
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

def test_feature_band_rings_are_their_own_op(demo, tools):
    """The band rings are a **Features** op, not extra Fine Relief passes.

    They were Fine Relief's until 2026-08-11, which meant they were cut with
    whatever tool finished the terraces. The maker's everyday intent is the
    opposite — a ball for the chamfers and scoops, an end mill for the hinges,
    the footing and the sculpting — and that needs its own op to hang a tool on.
    """
    from guildmodel.core.cam.castle_ops import generate_castle_program

    part, hinges = demo
    off = generate_castle_program(_build(demo, _castle()), _castle(),
                                  hinges, tools["flat_3175"])
    on = generate_castle_program(_build(demo, _castle(splay=True, bezel=True)),
                                 _castle(splay=True, bezel=True),
                                 hinges, tools["flat_3175"])
    assert "Features" not in [op.name for op in off]
    features = next(op for op in on if op.name == "Features")
    assert features.paths
    # The op sits between the fine pass it measures from and the eyewires that
    # open the apertures — where these rings ran inside Fine Relief.
    names = [op.name for op in on]
    assert names.index("Fine Relief") < names.index("Features") < names.index("Eyewires")
    # Everything else is the program it always was.
    assert [n for n in names if n != "Features"] == [op.name for op in off]


def test_a_zone_at_stock_height_is_reported_as_an_uncut_cap(demo):
    """The nosepad protrusion a maker sees, explained before the cut.

    The relief passes skip every cell already at stock height — cutting them
    removes nothing and makes the rings weave in and out of the cap — so such a
    zone comes off as raw blank standing proud of everything machined around it.
    **The shipped defaults coincide exactly**: nosepad 10.0 mm on a 6.0 mm blank
    plus a 4.0 mm pad block, which is 87 uncut cells per nosepad on the demo
    frame. Not a modeling error — every kernel agrees the tower is that tall —
    but the maker has no way to know it before the part is in their hand.
    """
    from guildmodel.core.cam.castle_ops import unmachined_top_warnings
    from guildmodel.core.project.schema import CastleParams

    part, hinges = demo
    default = CastleParams()
    assert default.zones.nosepad_mm == default.stock.total_pad_height_mm

    warned = unmachined_top_warnings(_build(demo, default), default)
    assert {w.zone for w in warned} == {"nosepad_od", "nosepad_os"}
    assert all(w.cells > 0 for w in warned)
    assert "stand proud" in warned[0].message()

    # Dropping the tower a few tenths gives the tool something to face.
    lowered = CastleParams()
    lowered.zones.nosepad_mm = 9.7
    assert unmachined_top_warnings(_build(demo, lowered), lowered) == []


def test_features_op_takes_its_own_tool(demo, tools):
    """Pinning a ball to Features re-cuts the band on the ball's own
    cutter-location surface — not the flat's, which would put it through the
    chamfer — and makes the job read as multi-tool so the post emits the
    change."""
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.project.schema import CastleCamParams

    part, hinges = demo
    castle = _castle(splay=True, bezel=True)
    relief = _build(demo, castle)

    plain = CastleCamParams()
    pinned = CastleCamParams(op_tools={"Features": "ball_2mm"})
    assert "ball_2mm" not in plain.tools_in_use()
    assert "ball_2mm" in pinned.tools_in_use()

    a = generate_castle_program(relief, castle, hinges, tools["flat_3175"],
                                params=plain, tools_cfg=tools)
    b = generate_castle_program(relief, castle, hinges, tools["flat_3175"],
                                params=pinned, tools_cfg=tools)
    fa = next(op for op in a if op.name == "Features")
    fb = next(op for op in b if op.name == "Features")
    assert fa.tool_name == "flat_3175"          # unassigned: follows Fine Relief
    assert fb.tool_name == "ball_2mm"
    assert fa.paths != fb.paths


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


# ------------------------------------------------- feature stepover vs the grid

def test_feature_stepover_never_finer_than_the_posting_grid(demo, tools):
    """A steep splay must not drive the band stepover below two grid cells.

    Corner Optical's Hyde Park frame (pad splay at 59.7°) drove
    `cusp / tan(slope)` to 0.088 mm, under a floor that was a bare 0.12 mm — both
    below `CUT_RES_MM`. Rings spaced finer than the surface they sample stop
    tracing the chamfer and trace the grid's quantization instead: that program
    posted 966 Z reversals and 1152 mm of Z travel in Features, on rings that are
    the chamfer's level curves and should barely move in Z at all.
    """
    import math

    from guildmodel.core.cam.castle_ops import (
        CUT_RES_MM, FEATURE_CUSP_MM, FEATURE_STEP_MIN_MM,
    )

    assert FEATURE_STEP_MIN_MM >= 2.0 * CUT_RES_MM

    # the formula's own output at a Hyde-Park-steep splay, before the floor
    steep = math.radians(59.7)
    assert FEATURE_CUSP_MM / math.tan(steep) < CUT_RES_MM      # sub-cell
    f_step = max(FEATURE_STEP_MIN_MM, FEATURE_CUSP_MM / math.tan(steep))
    assert f_step >= 2.0 * CUT_RES_MM

    # a gentle chamfer still gets the cusp-derived step, not the floor
    gentle = math.radians(20.0)
    assert FEATURE_CUSP_MM / math.tan(gentle) > FEATURE_STEP_MIN_MM


def test_steep_splay_band_does_not_sawtooth(demo, tools):
    """The band rings on a steep splay stay near their own level curve.

    Every other fixture in this repo is a bare castle — no splay, so no feature
    band, so nothing to measure. That blind spot is why the Hyde Park sawtooth
    survived four releases. This one turns the splay up steep on purpose.
    """
    import math

    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    part, hinges = demo
    castle = _castle(splay=True)
    castle.pad_splay.angle_center_deg = 59.7
    castle.pad_splay.angle_middle_deg = 58.0
    relief = build_castle_relief(part, castle, hinges, resolution=CUT_RES_MM)
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"])

    feat = next((op for op in ops if op.name == "Features"), None)
    if feat is None or not feat.paths:
        pytest.skip("no feature band on this fixture")

    reversals = xy = 0
    for path in feat.paths:
        prev_dz = 0.0
        for (x0, y0, z0), (x1, y1, z1) in zip(path, path[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            if d <= 1e-9:
                continue
            xy += d
            dz = z1 - z0
            if dz and prev_dz and (dz > 0) != (prev_dz > 0):
                reversals += 1
            prev_dz = dz
    per100 = 100.0 * reversals / xy if xy else 0.0
    # Measured on this fixture: 40.9 per 100 mm with the old sub-cell 0.12 floor,
    # 23.9 with the shipped one. The gate sits between them rather than near
    # either — the residual is still high because feature rings crossing the
    # nosepad tower wall are not what the stepover controls (slope-masking the
    # relief owns that), so tighten this only when that lands.
    assert per100 < 32.0, f"{per100:.1f} Z reversals per 100 mm in Features"


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
