"""Lens bevel groove (V1) — the drageoir V in each eyewire wall.

Contract under test, on the Demo Project front:
  * schema: off by default, round-trips;
  * relief: with the groove on the mask holes are the UNDERSIZED apertures
    (rim lip = lens − depth), the lip annulus is inside the body with a real
    zone height, and the original lens contours are kept for the groove;
  * mesh: stays watertight, gains the lip volume, and its wall apex reaches
    the original LENS contour; the groove-off path is untouched;
  * CAM: the Eyewires channel widens so the 6 mm head can descend; the Lens
    Groove op is one constant-Z climb loop per lens whose cutting edge lands
    ON the lens contour, ordered after Eyewires and before Perimeter;
  * post + sim: the posted program announces the drageoir so the grouped
    path extraction can exclude its side-cutting moves from the top-down
    Z-buffer sweep;
  * warnings: form-tool mismatch and flank overflow are flagged.
"""
import math
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Point, Polygon

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"


@pytest.fixture(scope="module")
def parts():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, hinges


def _castle(groove: bool):
    from guildmodel.core.project.schema import CastleParams, LensGrooveParams
    c = CastleParams()
    if groove:
        c.lens_groove = LensGrooveParams(enabled=True)
    return c


@pytest.fixture(scope="module")
def relief_off(parts):
    from guildmodel.core.relief.castle import build_castle_relief
    part, hinges = parts
    return build_castle_relief(part, _castle(False), hinges, resolution=0.3)


@pytest.fixture(scope="module")
def relief_on(parts):
    from guildmodel.core.relief.castle import build_castle_relief
    part, hinges = parts
    return build_castle_relief(part, _castle(True), hinges, resolution=0.3)


@pytest.fixture(scope="module")
def tools_cfg():
    return yaml.safe_load((CONFIG / "tools.yaml").read_text())


# ------------------------------------------------------------------ schema


def test_schema_default_off_and_roundtrip():
    from guildmodel.core.project.schema import CastleParams, LensGrooveParams
    c = CastleParams()
    assert c.lens_groove.enabled is False
    g = LensGrooveParams(enabled=True, anterior_offset_mm=1.2, depth_mm=0.6,
                         width_mm=1.8, tool="groove_drageoir")
    c2 = CastleParams(**{**c.model_dump(), "lens_groove": g.model_dump()})
    assert c2.lens_groove.depth_mm == 0.6 and c2.lens_groove.enabled


def test_shipped_drageoir_tool(tools_cfg):
    t = tools_cfg["groove_drageoir"]
    assert t["type"] == "groove"
    # Supplier's published profile: the CUTTING diameter is the V apex Ø5.5
    # (the 6 mm is the shank); root Ø4.0 = apex − 2×form depth.
    assert t["diameter_mm"] == 5.5
    assert t["groove_depth_mm"] == 0.75 and t["groove_width_mm"] == 2.0
    from guildmodel.core.cam.tooling import ToolSpec
    spec = ToolSpec.from_dict(t)
    d = spec.to_tool_dict()
    assert d["groove_depth_mm"] == 0.75 and d["neck_diameter_mm"] == 3.5


# ------------------------------------------------------------------ relief


def test_relief_off_is_untouched(relief_off, parts):
    part, _ = parts
    assert relief_off.groove is None
    assert relief_off.mask_body_override is None
    assert relief_off.mask_body is part.body


def test_relief_on_undersizes_holes_and_keeps_lenses(relief_on, parts):
    part, _ = parts
    g = relief_on.groove
    assert g is not None and g.depth_mm == 0.75
    assert len(relief_on.groove_lens_polys) == 2
    lens_area = sum(p.area for p in relief_on.groove_lens_polys)
    hole_area = sum(Polygon(r).area for r in relief_on.mask_body.interiors)
    assert hole_area < lens_area          # apertures are the undersized lip
    # the lip annulus is real material with a real zone height
    inside_orphans = (relief_on.inside & (relief_on.zone_index < 0)).sum()
    assert inside_orphans == 0


# ------------------------------------------------------------------ mesh


def test_mesh_watertight_with_lip_and_apex_on_lens(relief_on, relief_off):
    from guildmodel.core.relief.castle import build_castle_mesh
    m_off = build_castle_mesh(relief_off)
    m_on = build_castle_mesh(relief_on)
    assert m_off.is_watertight and m_on.is_watertight
    assert m_on.volume > m_off.volume     # the lip adds more than the V removes
    # apex vertices pushed onto the original LENS contours at the groove height
    g = relief_on.groove
    lens = relief_on.groove_lens_polys[0]
    near_apex = [
        v for v in m_on.vertices
        if abs(v[2] - g.anterior_offset_mm) < 0.15
        and abs(lens.exterior.distance(Point(v[0], v[1]))) < 0.05
    ]
    assert near_apex, "no mesh vertices on the lens contour at apex height"


# ------------------------------------------------------------------ CAM


@pytest.fixture(scope="module")
def ops_on(relief_on, parts, tools_cfg):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    _, hinges = parts
    return generate_castle_program(
        relief_on, _castle(True), hinges, tools_cfg["flat_3175"],
        tools_cfg=tools_cfg)


@pytest.fixture(scope="module")
def ops_off(relief_off, parts, tools_cfg):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    _, hinges = parts
    return generate_castle_program(
        relief_off, _castle(False), hinges, tools_cfg["flat_3175"],
        tools_cfg=tools_cfg)


def test_op_order_and_presence(ops_on, ops_off):
    names_on = [op.name for op in ops_on]
    names_off = [op.name for op in ops_off]
    assert "Lens Groove" not in names_off
    assert names_on.index("Eyewires") < names_on.index("Lens Groove")
    assert names_on.index("Lens Groove") < names_on.index("Perimeter")


def test_eyewire_channel_widens(ops_on, ops_off):
    ew_on = next(op for op in ops_on if op.name == "Eyewires")
    ew_off = next(op for op in ops_off if op.name == "Eyewires")
    assert len(ew_on.paths) > len(ew_off.paths)


def test_groove_op_geometry(ops_on, relief_on, tools_cfg):
    op = next(op for op in ops_on if op.name == "Lens Groove")
    assert op.tool["type"] == "groove"
    assert len(op.paths) == 2                       # one loop per lens
    g = relief_on.groove
    t = tools_cfg["groove_drageoir"]
    tip_z = g.anterior_offset_mm - t["groove_width_mm"] / 2.0
    head_r = t["radius_mm"]
    for path, lens in zip(op.paths, relief_on.groove_lens_polys):
        zs = {p[2] for p in path}
        assert len(zs) == 1                          # one constant-Z pass
        assert next(iter(zs)) == pytest.approx(tip_z)
        assert path[0] == path[-1]                   # radial entry = exit point
        ring = path[1:-1]
        # loop rides head_r inside the lens: the cutting edge lands ON the lens
        dists = [lens.exterior.distance(Point(p[0], p[1])) for p in ring]
        assert min(dists) == pytest.approx(head_r, abs=0.15)
        assert all(lens.contains(Point(p[0], p[1])) for p in ring)


def test_posted_program_announces_drageoir(ops_on, tools_cfg, relief_on):
    from guildmodel.core.cam.castle_ops import (
        build_tool_settings, write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.sim.paths import cutting_paths_from_program_grouped

    settings, _ = build_tool_settings(
        ops_on, tools_cfg, default_feed=1200, default_plunge=450,
        default_spindle=10000)
    assert "groove_drageoir" in settings
    post = GRBLPost(job_name="g", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=1200,
                    plunge_rate_mmpm=450, safe_z_mm=12.0)
    write_castle_program(ops_on, post, tool_settings=settings)
    text = post.to_string()
    assert "Lens Groove" in text
    groups = cutting_paths_from_program_grouped(text)
    tags = {t for _, t in groups}
    assert "groove_drageoir" in tags
    # the sim-side exclusion drops exactly those moves
    kept = [(p, t) for p, t in groups
            if not (t and tools_cfg.get(t, {}).get("type") == "groove")]
    assert all(t != "groove_drageoir" for _, t in kept)
    assert len(kept) < len(groups)


def test_groove_kernel_stamps_nothing(tools_cfg):
    """The side-cutting form is an undercut a Z-buffer can't represent — its
    sweep kernel must be EMPTY so no sim view (floor verify, playback block,
    bed sim) ever false-carves the rim lip from above."""
    import numpy as np
    from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor
    prof = ToolProfile.from_tool(tools_cfg["groove_drageoir"])
    di, dj, dz = prof.kernel(0.3)
    assert len(di) == 0 and len(dj) == 0 and len(dz) == 0
    # a full sweep along a groove loop leaves the floor untouched
    floor = achieved_floor([[(5.0, 5.0, 1.5), (25.0, 5.0, 1.5)]], prof,
                           (0.0, 0.0), (100, 100), 0.3, init_z=8.0)
    assert np.all(floor == 8.0)


def test_verify_groove_op_geometrically(ops_on, relief_on, tools_cfg):
    from guildmodel.core.cam.castle_ops import verify_groove_op
    g_op = next(op for op in ops_on if op.name == "Lens Groove")
    g = relief_on.groove
    tool = tools_cfg["groove_drageoir"]
    assert verify_groove_op(g_op, relief_on.groove_lens_polys, g, tool) == []

    # tamper: shift one loop's Z — the constant-Z check must flag it
    import copy
    bad = copy.deepcopy(g_op)
    bad.paths[0] = [(x, y, z + 0.4) for x, y, z in bad.paths[0]]
    issues = verify_groove_op(bad, relief_on.groove_lens_polys, g, tool)
    assert any("constant-Z" in w for w in issues)

    # tamper: shrink one loop inward — the apex-on-contour check must flag it
    bad2 = copy.deepcopy(g_op)
    cx = sum(p[0] for p in bad2.paths[0]) / len(bad2.paths[0])
    cy = sum(p[1] for p in bad2.paths[0]) / len(bad2.paths[0])
    bad2.paths[0] = [(cx + (x - cx) * 0.9, cy + (y - cy) * 0.9, z)
                     for x, y, z in bad2.paths[0]]
    issues2 = verify_groove_op(bad2, relief_on.groove_lens_polys, g, tool)
    assert any("apex" in w for w in issues2)


def test_removal_plan_carries_groove_rings():
    from guildmodel.core.sim.playback import RemovalPlan
    import numpy as np
    plan = RemovalPlan(stock_top=np.zeros((2, 2)), origin=(0.0, 0.0),
                       resolution=1.0, positions=np.zeros((0, 3)),
                       seg_bounds=[0], seg_kernel=[], seg_label=[])
    assert plan.groove_rings == []


def test_groove_warnings(tools_cfg):
    from guildmodel.core.cam.castle_ops import groove_warnings
    from guildmodel.core.project.schema import LensGrooveParams
    g = LensGrooveParams(enabled=True)
    assert groove_warnings(g, tools_cfg["groove_drageoir"], wall_top_z=4.0) == []
    warns = groove_warnings(g, tools_cfg["flat_3175"], wall_top_z=4.0)
    assert any("groove-type" in w for w in warns)
    deep = LensGrooveParams(enabled=True, depth_mm=1.5)
    assert any("exceeds the tool form" in w
               for w in groove_warnings(deep, tools_cfg["groove_drageoir"], 4.0))
    high = LensGrooveParams(enabled=True, anterior_offset_mm=3.5)
    assert any("wall top" in w
               for w in groove_warnings(high, tools_cfg["groove_drageoir"], 4.0))
