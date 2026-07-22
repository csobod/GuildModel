"""Collision-aware pass linking (BUILDPLAN M8).

Between cutting passes the post may retract only to a low clearance plane instead
of the full safe Z — but NEVER when the hop would pass over a work-holding screw
standing proud of the stock. The headline test replays the posted program and
asserts no low traverse ever passes within tool-contact distance of a screw.
"""
import math
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOL_R = 3.175 / 2.0
SCREW_R = 7.0 / 2.0


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.cam.castle_ops import (
        generate_castle_program, work_holding_keepouts)
    from guildmodel.core.project.schema import CastleParams, CastleCamParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle, cam = CastleParams(), CastleCamParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"])
    keep = work_holding_keepouts(relief.partition.body, castle.stock, TOOL_R)
    return castle, cam, ops, keep


def _post(castle, cam, ops, keep, *, link):
    from guildmodel.core.cam.castle_ops import write_castle_program
    from guildmodel.core.post.grbl import GRBLPost
    top = castle.stock.total_pad_height_mm
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
                    safe_z_mm=top + 5, feed_plane_mm=top + 1)
    if link:
        post.link_clearance_z_mm = top + cam.link_clearance_mm
        post.link_keepouts = tuple(keep)
    write_castle_program(ops, post)
    return post.to_string()


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def test_keepouts_are_corners_plus_lens_centres(demo):
    castle, _, _, keep = demo
    assert len(keep) == 6                        # 4 blank corners + 2 lens centres
    hl, hw = castle.stock.blank_length_mm / 2, castle.stock.blank_width_mm / 2
    corners = {(round(hl), round(hw)), (round(-hl), round(hw)),
               (round(hl), round(-hw)), (round(-hl), round(-hw))}
    assert corners <= {(round(x), round(y)) for x, y, _ in keep}
    assert keep[0][2] == pytest.approx(SCREW_R + TOOL_R + 2.0)   # screw+tool+margin


def test_no_low_traverse_passes_under_a_screw(demo):
    """THE safety gate: every low (below-screw-top) rapid clears every screw."""
    castle, cam, ops, keep = demo
    gcode = _post(castle, cam, ops, keep, link=True)
    screw_top = castle.stock.total_pad_height_mm + 5.0      # ~where the heads end
    x = y = z = 0.0
    worst = 9e9
    for ln in gcode.splitlines():
        if ln[:2] not in ("G0", "G1"):
            continue
        w = dict(re.findall(r"([XYZ])(-?[\d.]+)", ln))
        nx, ny, nz = float(w.get("X", x)), float(w.get("Y", y)), float(w.get("Z", z))
        if ln.startswith("G0") and (nx != x or ny != y) and min(z, nz) < screw_top - 1e-6:
            for cx, cy, _ in keep:
                worst = min(worst, _seg_dist(cx, cy, x, y, nx, ny) - (SCREW_R + TOOL_R))
        x, y, z = nx, ny, nz
    assert worst >= 0.0, f"a low traverse passes under a screw (edge gap {worst:.2f} mm)"


def test_linking_cuts_full_retracts_and_off_matches_legacy(demo):
    castle, cam, ops, keep = demo
    top = castle.stock.total_pad_height_mm
    full = f"G0 Z{top + 5:.4f}"
    low = f"G0 Z{top + cam.link_clearance_mm:.4f}"
    off = _post(castle, cam, ops, keep, link=False)
    on = _post(castle, cam, ops, keep, link=True)
    assert low not in off                        # linking off = the original behaviour
    assert on.count(full) < off.count(full)      # linking replaces most full retracts
    assert on.count(low) > 0                      # …with low hops where it's clear
    # some full retracts remain — the screw-crossing hops kept the safe height
    assert on.count(full) > 0


def test_near_screw_forces_safe_z_clear_hop_stays_low():
    from guildmodel.core.post.grbl import GRBLPost
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
                    safe_z_mm=20.0)
    post.link_clearance_z_mm = 11.5
    post.link_keepouts = ((0.0, 0.0, 5.0),)      # one screw at the origin
    # hop straight across the screw -> must retract to safe Z
    post._last_xy = (-10.0, 0.0)
    post._link_retract(10.0, 0.0)
    assert "Z20.0000" in post.to_string()
    # hop well clear of the screw -> low clearance
    post2 = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                     spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
                     safe_z_mm=20.0)
    post2.link_clearance_z_mm = 11.5
    post2.link_keepouts = ((0.0, 0.0, 5.0),)
    post2._last_xy = (-10.0, 20.0)
    post2._link_retract(10.0, 20.0)
    assert "Z11.5000" in post2.to_string() and "Z20.0000" not in post2.to_string()
