"""Program zero from the stock box (BUILDPLAN M6.2).

A maker touches off work zero on the stock blank, not the design/fixture frame.
The chosen datum becomes a rigid post-time offset so geometry / CLS / sim stay in
the design frame (the M2/M3 envelopes and the cut simulator are unaffected) while
the posted program zeroes where the operator set it.
"""
import math
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildcam.core.project.schema import (
    CastleParams, CastleCamParams, ProgramZero, ProjectSchema, StockDefinition,
)
from guildcam.core.cam.castle_ops import generate_castle_program, write_castle_program
from guildcam.core.post.grbl import GRBLPost

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildcam" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())


# ------------------------------------------------------------------ offset math

def test_default_is_stock_box_lower_left_top():
    pz = ProgramZero()
    assert pz.mode == "stock_box"
    assert (pz.x_ref, pz.y_ref, pz.z_ref) == ("left", "bottom", "top")


def test_work_offset_for_each_datum():
    s = StockDefinition()        # 170 x 85 x 6, blank centred on the origin
    hl, hw, t = 85.0, 42.5, 6.0
    cases = {
        ("left", "bottom", "top"): (hl, hw, -t),       # default
        ("right", "top", "bottom"): (-hl, -hw, 0.0),
        ("center", "center", "top"): (0.0, 0.0, -t),
        ("center", "center", "bottom"): (0.0, 0.0, 0.0),
    }
    for (x, y, z), expect in cases.items():
        off = ProgramZero(mode="stock_box", x_ref=x, y_ref=y, z_ref=z).work_offset(s)
        assert off == pytest.approx(expect), (x, y, z, off)
        # no negative zero leaks into the offset
        assert all(not (v == 0.0 and math.copysign(1, v) < 0) for v in off)


def test_fixture_mode_is_identity():
    s = StockDefinition()
    assert ProgramZero(mode="fixture").work_offset(s) == (0.0, 0.0, 0.0)
    # the datum even with non-default refs is ignored in fixture mode
    assert ProgramZero(mode="fixture", x_ref="right").work_offset(s) == (0.0, 0.0, 0.0)


def test_datum_world_corners():
    s = StockDefinition()
    assert ProgramZero(x_ref="left", y_ref="bottom", z_ref="bottom").datum_world(s) \
        == (-85.0, -42.5, 0.0)
    assert ProgramZero(x_ref="right", y_ref="top", z_ref="top").datum_world(s) \
        == (85.0, 42.5, 6.0)


def test_label_names_the_datum():
    assert "lower-left" in ProgramZero().label()
    assert "top face" in ProgramZero().label()
    assert "Fixture" in ProgramZero(mode="fixture").label()


# ------------------------------------------------------------------ post offset

_COORD = re.compile(r"([XYZIJ])(-?\d+\.?\d*)")


def _first_g1(text):
    for ln in text.splitlines():
        if ln.startswith("G1 "):
            d = {m[0]: float(m[1]) for m in _COORD.findall(ln)}
            return d
    return {}


def test_post_applies_offset_to_coordinates():
    off = (85.0, 42.5, -6.0)
    base = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0)
    base.feed(x=0.0, y=0.0, z=0.0)
    shifted = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0,
                       work_offset=off)
    shifted.feed(x=0.0, y=0.0, z=0.0)
    b, s = _first_g1(base.to_string()), _first_g1(shifted.to_string())
    assert (s["X"], s["Y"], s["Z"]) == pytest.approx((b["X"] + 85.0,
                                                      b["Y"] + 42.5, b["Z"] - 6.0))


def test_post_offset_leaves_arc_ij_unchanged():
    off = (85.0, 42.5, -6.0)
    p = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0,
                 work_offset=off)
    p.arc(10.0, 0.0, 0.0, -10.0, 0.0, ccw=True)
    d = {m[0]: float(m[1]) for m in _COORD.findall(
        [ln for ln in p.to_string().splitlines() if ln.startswith("G3")][0])}
    assert (d["X"], d["Y"]) == pytest.approx((95.0, 42.5))   # endpoint shifted
    assert (d["I"], d["J"]) == pytest.approx((-10.0, 0.0))   # centre offset NOT


def test_safe_z_is_offset():
    off = (0.0, 0.0, -6.0)
    p = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0,
                 work_offset=off)
    p.header("Posterior Cut")
    p.end_program()
    zs = [float(m.group(1)) for m in re.finditer(r"G0 Z(-?\d+\.?\d*)", p.to_string())]
    assert zs and all(z == pytest.approx(9.0) for z in zs)   # 15 - 6


# ------------------------------------------------------------------ end-to-end + sim

@pytest.fixture(scope="module")
def demo_ops():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.relief.castle import build_castle_relief

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"])
    return castle, ops


def _posted(ops, castle, offset):
    post = GRBLPost("posterior_cut", "acetate", 3.175, 10000, 750, 333,
                    safe_z_mm=castle.stock.total_pad_height_mm + 5.0, work_offset=offset)
    write_castle_program(ops, post)
    return post.to_string()


def test_stock_box_zero_lands_part_in_positive_quadrant(demo_ops):
    castle, ops = demo_ops
    off = ProgramZero().work_offset(castle.stock)     # lower-left/top
    text = _posted(ops, castle, off)
    xs, ys = [], []
    for ln in text.splitlines():
        if ln[:2] in ("G1", "G2", "G3"):
            d = {m[0]: float(m[1]) for m in _COORD.findall(ln)}
            if "X" in d:
                xs.append(d["X"])
            if "Y" in d:
                ys.append(d["Y"])
    # lower-left blank corner at zero -> all cutting XY within the blank, >= ~0
    assert min(xs) >= -0.5 and min(ys) >= -0.5
    assert max(xs) <= castle.stock.blank_length_mm + 0.5
    assert max(ys) <= castle.stock.blank_width_mm + 0.5


def test_offset_is_pure_translation_vs_fixture(demo_ops):
    """The cut shape is identical to fixture mode — only translated."""
    castle, ops = demo_ops
    off = ProgramZero().work_offset(castle.stock)
    fix = _posted(ops, castle, (0.0, 0.0, 0.0))
    box = _posted(ops, castle, off)

    def g1_xyz(text):
        out = []
        for ln in text.splitlines():
            if ln.startswith("G1 "):
                d = {m[0]: float(m[1]) for m in _COORD.findall(ln)}
                if {"X", "Y"} <= d.keys():
                    out.append((d["X"], d["Y"], d.get("Z", 0.0)))
        return out

    a, b = g1_xyz(fix), g1_xyz(box)
    assert len(a) == len(b) and a
    for (ax, ay, az), (bx, by, bz) in zip(a, b):
        assert (bx - ax, by - ay, bz - az) == pytest.approx((85.0, 42.5, -6.0), abs=1e-3)


def test_sim_unaffected_by_program_zero(demo_ops):
    """The simulator runs in the design frame (offset 0), so completeness does
    not depend on where work zero is set."""
    from guildcam.core.relief.castle import build_castle_relief
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.sim import (
        ToolProfile, achieved_floor, cutting_paths_from_ops, verify)

    castle, ops = demo_ops
    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    f = relief.field
    floor = achieved_floor(cutting_paths_from_ops(ops), ToolProfile.from_tool(TOOLS["flat_3175"]),
                           f.origin, f.z.shape, f.resolution, init_z=12.0)
    rep = verify(floor, np.where(relief.inside, f.z, np.nan), relief.inside,
                 f.origin, f.resolution, partition=part)
    # ops are in the design frame regardless of program_zero; sim reads them
    assert rep.status() in ("ok", "warn")


# ------------------------------------------------------------------ round-trip

def test_program_zero_round_trips_through_gcam(tmp_path):
    from guildcam.core.project.gcam import save_gcam, load_gcam
    proj = ProjectSchema(job_name="PZ")
    proj.cam_params = CastleCamParams(
        program_zero=ProgramZero(mode="stock_box", x_ref="right", y_ref="top", z_ref="bottom"))
    path = tmp_path / "pz.gcam"
    save_gcam(path, project=proj, dxf_bytes=b"dxf")
    pz = load_gcam(path).project.cam_params.program_zero
    assert (pz.mode, pz.x_ref, pz.y_ref, pz.z_ref) == ("stock_box", "right", "top", "bottom")
