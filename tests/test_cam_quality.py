"""CAM-quality gates (post-M4.6 deep-dive vs Demo Program.nc):

  * eyewires finish one ring through its full depth stack before the next
    (ring-major), not depth-major alternation between the two lenses;
  * relief (Rough/Fine) is contour-parallel (boundary-offset rings following
    the frame), not an axis-aligned raster;
  * arc fitting emits GRBL-valid G2/G3 on the curved passes;
  * the through-cut contours enter with a ramped lead-in, not a straight
    slot-plunge to depth.
"""
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildcam" / "config"


@pytest.fixture(scope="module")
def program():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.project.schema import CastleParams
    from guildcam.core.relief.castle import build_castle_relief
    from guildcam.core.cam.castle_ops import generate_castle_program

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    tool = yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"]
    ops = {op.name: op for op in generate_castle_program(relief, castle, hinges, tool)}
    return ops, castle


@pytest.fixture(scope="module")
def posted(program):
    from guildcam.core.cam.castle_ops import write_castle_program
    from guildcam.core.post.grbl import GRBLPost

    ops, castle = program
    post = GRBLPost(
        job_name="q", material="acetate", tool_diameter_mm=3.175,
        spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
        safe_z_mm=castle.stock.total_pad_height_mm + 5.0,
    )
    write_castle_program(list(ops.values()), post)
    return post.to_string()


# ------------------------------------------------------------------ ordering

def test_eyewires_ring_major(program):
    """Each lens is finished through its full depth stack before the next."""
    ops, _ = program
    sides = []
    for p in ops["Eyewires"].paths:
        cx = sum(pt[0] for pt in p) / len(p)
        sides.append("OD" if cx > 0 else "OS")
    # one contiguous block per lens (exactly one OD->OS or OS->OD switch),
    # not alternating at every depth (which would be 7 switches for 8 passes)
    switches = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    assert switches == 1, f"expected ring-major (1 switch), got {sides}"
    assert len(ops["Eyewires"].paths) == 8     # 2 lenses x 4 depth passes


# ------------------------------------------------------------------ relief pattern

@pytest.mark.parametrize("op_name", ["Fine Relief", "Rough Relief"])
def test_relief_is_contour_parallel_not_raster(program, op_name):
    """Contour-parallel paths drift in both X and Y; a raster would hold Y
    (or X) constant for the vast majority of moves."""
    ops, _ = program
    paths = [np.asarray(p) for p in ops[op_name].paths if len(p) >= 3]
    assert paths, f"no {op_name} paths"
    dY = np.concatenate([np.abs(np.diff(p[:, 1])) for p in paths])
    dX = np.concatenate([np.abs(np.diff(p[:, 0])) for p in paths])
    const_axis = max((dY < 1e-3).mean(), (dX < 1e-3).mean())
    assert const_axis < 0.2, f"{op_name} looks raster-like ({const_axis:.0%} axis-aligned)"


# ------------------------------------------------------------------ arc fitting

def test_fit_arcs_recovers_a_circle():
    from guildcam.core.post.arcfit import fit_arcs

    t = np.linspace(0.0, np.pi / 2, 40)          # quarter circle, ccw
    cx, cy, r = 5.0, -3.0, 10.0
    pts = [(cx + r * np.cos(a), cy + r * np.sin(a), 2.0) for a in t]
    moves = fit_arcs(pts, tol_mm=0.01)
    assert any(m[0] == "arc" for m in moves)
    arc = next(m for m in moves if m[0] == "arc")
    (fcx, fcy), ccw = arc[2], arc[3]
    assert abs(fcx - cx) < 0.05 and abs(fcy - cy) < 0.05
    assert ccw is True


def test_fit_arcs_keeps_straight_lines():
    from guildcam.core.post.arcfit import fit_arcs

    pts = [(float(i), 0.0, 1.0) for i in range(10)]
    moves = fit_arcs(pts, tol_mm=0.01)
    assert all(m[0] == "line" for m in moves)


def test_posted_arcs_are_grbl_valid(posted):
    """Every G2/G3 must have start/end radius agreement well under GRBL's
    arc tolerance (~0.05 mm)."""
    assert "G2 " in posted or "G3 " in posted, "no arcs emitted"
    cx = cy = None
    worst = 0.0
    for line in posted.splitlines():
        s = line.strip()
        mx = re.search(r"X(-?[\d.]+)", s)
        my = re.search(r"Y(-?[\d.]+)", s)
        nx = float(mx.group(1)) if mx else cx
        ny = float(my.group(1)) if my else cy
        if s.startswith(("G2", "G3")) and cx is not None:
            i = float(re.search(r"I(-?[\d.]+)", s).group(1))
            j = float(re.search(r"J(-?[\d.]+)", s).group(1))
            r_start = (i * i + j * j) ** 0.5
            r_end = (((cx + i) - nx) ** 2 + ((cy + j) - ny) ** 2) ** 0.5
            worst = max(worst, abs(r_start - r_end))
        cx, cy = nx, ny
    assert worst < 0.05, f"arc radius mismatch {worst*1000:.1f} micron"


# ------------------------------------------------------------------ ramped lead-in

def test_contours_have_ramped_lead_in(posted):
    """Through-cut contours must not slot-plunge straight to depth: pure
    vertical G1 plunges only descend through air to the ramp-start height
    (one stepdown above the cut), never to the onion-skin floor."""
    eye = posted.split("--- Eyewires ---")[1].split("--- Perimeter ---")[0]
    vertical_plunge_zs = []
    for line in eye.splitlines():
        s = line.strip()
        if s.startswith("G1") and "Z" in s and "X" not in s and "Y" not in s:
            vertical_plunge_zs.append(float(re.search(r"Z(-?[\d.]+)", s).group(1)))
    assert vertical_plunge_zs, "no entry moves found"
    # skin floor is 0.4; ramp start for that pass is ~0.4+stepdown -> never 0.4
    assert min(vertical_plunge_zs) > 0.5, (
        f"straight plunge reached {min(vertical_plunge_zs)} (should ramp to depth)"
    )
