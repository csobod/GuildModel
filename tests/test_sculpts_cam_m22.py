"""Sculpts and the CAM (BUILDPLAN M22 §7.5).

A sculpt on the back lands in the Z-map the CAM posts, its footprint joins
the feature band so the Features pass finishes it at its cusp stepover, and
the Sculpt Finish op, off unless ticked, rides a ball over the footprint at
a finer one. A sculpt on the front changes nothing the posterior program
cuts: the bytes are identical with one present.
"""
from pathlib import Path

import numpy as np
import pytest
import trimesh
import yaml
from shapely.geometry import Point

from guildmodel.core.project.schema import (CastleCamParams, CastleParams, SculptFeature,
                                            SculptMount)

ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _dome_bytes(radius=2.5):
    sph = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    dome = trimesh.intersections.slice_mesh_plane(sph, plane_normal=[0, 0, 1],
                                                  plane_origin=[0, 0, 0], cap=True)
    return trimesh.exchange.stl.export_stl(dome)


def _sculpted(demo, face="posterior"):
    """A castle with one dome on the given face, placed on the plain model."""
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.model.sculpt import (default_overlap, flat_back, load_sculpt,
                                              mount_transform, sag_under, snap_target)
    partition, hinges = demo
    castle = CastleParams()
    host = to_trimesh(build_castle_model(partition, castle, hinges))
    data = _dome_bytes()
    src = load_sculpt(data, "dome.stl")
    back = flat_back(src.mesh)[0]
    # on the left eyewire's brow, where the terrace is one level
    zone = next(z for z in partition.zones if z.name.startswith("eyewire_superior"))
    c = zone.polygon.representative_point()
    target = snap_target(host, face, (c.x, c.y))
    overlap = default_overlap(sag_under(host, back, src.mesh,
                                        mount_transform(back, target, overlap_mm=0.0), target))
    feature = SculptFeature(
        id="crest", source_name="dome.stl", source_sha256=src.sha256,
        mount=SculptMount(face=face, point=[float(v) for v in target.point],
                          normal=[float(v) for v in target.normal], overlap_mm=overlap),
    ).with_transform(mount_transform(back, target, overlap_mm=overlap))
    castle.sculpts = [feature]
    return castle, {src.sha256: data}, Point(c.x, c.y)


def _program(partition, hinges, castle, sources, params=None):
    from guildmodel.core.cam.castle_ops import (build_tool_settings, generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.zmap import castle_relief
    params = params or CastleCamParams()
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3,
                           sculpt_sources=sources)
    tool = TOOLS["flat_3175"]
    ops = generate_castle_program(relief, castle, hinges, tool, params=params, tools_cfg=TOOLS)
    ops = params.enabled_ops(ops)
    ts, _ = build_tool_settings(ops, TOOLS, default_feed=600, default_plunge=200,
                                default_spindle=12000)
    f0 = ts[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm,
                    safe_z_mm=params.safe_z_for(castle.stock.total_pad_height_mm))
    write_castle_program(ops, post, tool_settings=ts, contour_op_names=CASTLE_CONTOUR_OPS)
    return relief, ops, post.to_string()


def test_a_posterior_sculpt_lands_in_the_relief_and_its_footprint_joins_the_band(demo):
    partition, hinges = demo
    castle, sources, at = _sculpted(demo)
    relief, ops, _ = _program(partition, hinges, castle, sources)
    assert len(relief.sculpt_footprints) == 1
    shadow = relief.sculpt_footprints[0]
    assert shadow.contains(at) and shadow.area == pytest.approx(np.pi * 2.5 ** 2, rel=0.05)
    f = relief.field
    r = int(round((at.y - f.origin[1]) / f.resolution))
    c = int(round((at.x - f.origin[0]) / f.resolution))
    plain_relief, _, _ = _program(partition, hinges, CastleParams(), {})
    assert f.z[r, c] > plain_relief.field.z[r, c] + 2.0      # the dome stands on the terrace
    assert relief.feature_band is not None and relief.feature_band[r, c]
    assert relief.feature_max_slope_deg >= 75.0
    assert any(op.name == "Features" for op in ops)
    assert not any(op.name == "Sculpt Finish" for op in ops)  # off unless ticked


def test_the_sculpt_finish_op_rides_the_footprint_when_ticked(demo):
    from guildmodel.core.cam.castle_ops import CASTLE_OP_TIERS, sculpt_stepover
    from guildmodel.core.cam.cuttime import _CANON
    partition, hinges = demo
    castle, sources, at = _sculpted(demo)
    params = CastleCamParams(op_enabled={"Sculpt Finish": True})
    assert params.is_op_enabled("Sculpt Finish") and not CastleCamParams().is_op_enabled("Sculpt Finish")
    relief, ops, text = _program(partition, hinges, castle, sources, params)
    names = [op.name for op in ops]
    assert "Sculpt Finish" in names
    assert names.index("Features") < names.index("Sculpt Finish") < names.index("Eyewires")
    op = next(o for o in ops if o.name == "Sculpt Finish")
    assert op.tool["type"] == "ball"                           # ball_1mm by default
    shadow = relief.sculpt_footprints[0].buffer(op.tool["radius_mm"] + 0.5)
    pts = np.array([p for path in op.paths for p in path])
    assert len(pts) > 50
    assert all(shadow.contains(Point(x, y)) for x, y in pts[:, :2])
    # a 1 mm ball at a 15 um cusp wants 0.24 mm, under the grid's finest step
    from guildmodel.core.cam.castle_ops import FEATURE_STEP_MIN_MM, SCULPT_CUSP_MM
    h = SCULPT_CUSP_MM
    assert sculpt_stepover(op.tool) == pytest.approx(
        max(FEATURE_STEP_MIN_MM, 2.0 * np.sqrt(h * (2.0 * 0.5 - h))))
    assert sculpt_stepover(dict(type="ball", radius_mm=1.0)) == pytest.approx(
        2.0 * np.sqrt(h * (2.0 - h)))                           # a 2 mm ball: 0.345 mm
    assert any("Sculpt Finish" in t for t in CASTLE_OP_TIERS)
    assert ("sculpt", "Sculpt Finish") in _CANON
    assert "Sculpt Finish" in text


def test_anterior_is_not_cut(demo):
    partition, hinges = demo
    castle, sources, _ = _sculpted(demo, face="anterior")
    relief, ops, with_sculpt = _program(partition, hinges, castle, sources)
    _, _, plain = _program(partition, hinges, CastleParams(), {})
    assert with_sculpt == plain
    assert relief.sculpt_footprints == []
    assert not castle.cuts_posterior_features()
