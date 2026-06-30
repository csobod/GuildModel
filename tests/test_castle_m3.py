"""M3 tests: the five-operation posterior CAM recipe and its gate against
Demo Program.nc (BUILDPLAN M3.6).

The gate checks structural invariants — op order, floor depths, pass stacks,
XY envelopes, onion skin, allowance, ramp entry, fixture clearance — not
byte equality: GuildModel's relief pattern is raster (vs Fusion's
constant-stepover contours) and its rough pass is stock-aware by design.
"""
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"

TOOL_R = 3.175 / 2.0


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


@pytest.fixture(scope="module")
def program(demo_inputs):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo_inputs
    relief = build_castle_relief(part, castle, hinges, resolution=0.2)
    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"])
    return {op.name: op for op in ops}, [op.name for op in ops], relief


# ------------------------------------------------------------------ config

def test_demo_tool_and_feeds_in_config():
    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    t = tools["flat_3175"]
    assert t["diameter_mm"] == 3.175 and t["type"] == "flat" and t["flutes"] == 1
    mats = yaml.safe_load((CONFIG / "materials.yaml").read_text(encoding="utf-8"))
    m = mats["acetate"]
    # M12.3: feed is chip-load-derived (0.12 mm/tooth x 10k x 1-flute = 1200).
    assert (m["spindle_rpm"], m["feed_rate_mmpm"], m["plunge_rate_mmpm"]) == (10000, 1200, 450)


# ------------------------------------------------------------------ structure

def test_op_order(program):
    _, names, _ = program
    assert names == ["Hinge Pockets", "Rough Relief", "Fine Relief", "Eyewires", "Perimeter"]


def test_contour_pass_stack():
    from guildmodel.core.cam.castle_ops import contour_passes

    assert contour_passes(10.0, 0.4, 2.5) == [7.5, 5.0, 2.5, 0.4]
    assert contour_passes(6.0, 0.4, 2.5) == [3.5, 1.0, 0.4]
    assert contour_passes(2.0, 0.4, 2.5) == [0.4]


# ------------------------------------------------------------------ op invariants

def test_hinge_pockets_floor_and_ramp(program, demo_inputs):
    ops, _, _ = program
    _, castle, hinges = demo_inputs
    op = ops["Hinge Pockets"]
    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm   # 4.5
    zs = np.array([p[2] for path in op.paths for p in path])
    assert zs.min() == pytest.approx(floor, abs=1e-6)
    assert zs.max() <= castle.stock.blank_thickness_mm + 0.5 + 1e-6
    # ramp entry: no step down bigger than the ramp increment (no plunge)
    for path in op.paths:
        dz = np.diff([p[2] for p in path])
        assert dz.min() > -0.61, "vertical plunge detected in pocket entry"
    # toolpath stays inside the hinge outline by ~tool radius
    hb = np.array([h.bounds for h in hinges])
    bx = op.xy_bounds()
    assert bx[0] >= hb[:, 0].min() + TOOL_R - 0.3
    assert bx[2] <= hb[:, 2].max() - TOOL_R + 0.3


def test_rough_relief_stock_aware(program, demo_inputs):
    ops, _, _ = program
    _, castle, _ = demo_inputs
    op = ops["Rough Relief"]
    zmin, zmax = op.z_range()
    # min = lowest terrace + axial stock (4.2 + 2.0), as in the reference NC.
    # Bilinear CL sampling lands path points between grid cells, so the floor can
    # sit a fraction below the on-grid value — negligible on a roughing pass that
    # leaves 2 mm for the finish, and never below the 4.2 final surface.
    assert zmin == pytest.approx(4.2 + 2.0, abs=0.15)
    assert zmin > 4.2          # rough never reaches the final surface (no gouge)
    # Contour linking (M11) lets the cutter ride over a thin cap at stock height to keep
    # one continuous sweep instead of retract+plunging across it, so zmax may touch (but
    # never exceed) the stock top. Confinement to the pad-block zone is what keeps the
    # pass from air-cutting the whole blank — the bounds check below enforces it.
    assert zmax <= castle.stock.total_pad_height_mm + 1e-6
    bx = op.xy_bounds()
    half = castle.stock.pad_block_length_mm / 2.0
    assert bx[0] >= -half - TOOL_R - 0.5 and bx[2] <= half + TOOL_R + 0.5


def test_relief_paths_are_sweeps_not_drill_holes(program):
    """Contour linking (M11): the cut mask used to shatter each ring into tiny stub
    paths — a retract+plunge to cut ~nothing, all over the rough + start of fine.
    Linking small gaps + dropping sub-mm runs means every kept path is a real sweep."""
    from shapely.geometry import LineString
    ops, _, _ = program
    for name in ("Rough Relief", "Fine Relief"):
        lens = [LineString([(p[0], p[1]) for p in path]).length
                for path in ops[name].paths if len(path) >= 2]
        stubs = [round(L, 2) for L in lens if L < 0.8]
        assert not stubs, f"{name} still has stub paths: {stubs}"


def test_fine_relief_full_surface(program, demo_inputs):
    ops, _, relief = program
    _, castle, _ = demo_inputs
    op = ops["Fine Relief"]
    zmin, zmax = op.z_range()
    top = castle.stock.total_pad_height_mm
    assert zmin == pytest.approx(4.2, abs=0.01)
    # Finishes the real relief up to just below the stock surface, but skips every
    # flat top already at stock height (the nosepad tower caps + the outside band):
    # cutting those removes nothing and just makes the rings peck in and out of the
    # cap. So the fine envelope tops out a hair below the stock surface (M8).
    assert zmax < top
    assert zmax == pytest.approx(top - 0.05, abs=0.1)
    body = relief.partition.body
    bx = op.xy_bounds()
    assert bx[0] == pytest.approx(body.bounds[0], abs=TOOL_R + 0.8)
    assert bx[2] == pytest.approx(body.bounds[2], abs=TOOL_R + 0.8)


def test_fine_relief_never_gouges(program):
    """Tool center z must clear the target surface everywhere on the path."""
    ops, _, relief = program
    f = relief.field
    for path in ops["Fine Relief"].paths:
        pts = np.asarray(path)
        ci = np.clip(((pts[:, 0] - f.origin[0]) / f.resolution).round().astype(int), 0, f.z.shape[1] - 1)
        ri = np.clip(((pts[:, 1] - f.origin[1]) / f.resolution).round().astype(int), 0, f.z.shape[0] - 1)
        target = f.z[ri, ci]
        inside = relief.inside[ri, ci]
        assert (pts[inside, 2] >= target[inside] - 0.02).all()


def test_contour_ops_passes_and_skin(program, demo_inputs):
    ops, _, _ = program
    _, castle, _ = demo_inputs
    for name in ("Eyewires", "Perimeter"):
        zs = sorted({round(p[2], 3) for path in ops[name].paths for p in path})
        assert zs == [0.4, 2.5, 5.0, 7.5]
        assert min(zs) == castle.onion_skin_mm      # the skin, never zero


def test_contour_allowance_offsets(program, demo_inputs):
    from shapely.geometry import Point, Polygon

    ops, _, relief = program
    _, castle, _ = demo_inputs
    body = relief.partition.body
    offset = TOOL_R + castle.hand_finishing_allowance_mm

    outline = Polygon(body.exterior)
    for path in ops["Perimeter"].paths[:1]:
        d = [outline.exterior.distance(Point(p[0], p[1])) for p in path[::20]]
        assert min(d) >= offset - 0.02

    lenses = [Polygon(r) for r in body.interiors]
    for path in ops["Eyewires"].paths[:1]:
        d = [min(ln.exterior.distance(Point(p[0], p[1])) for ln in lenses) for p in path[::20]]
        assert min(d) >= offset - 0.02


# ------------------------------------------------------------------ fixture + post

def test_fixture_clearance_demo(program):
    from guildmodel.core.cam.castle_ops import fixture_clearance_violations

    ops, names, _ = program
    fixture = yaml.safe_load(
        (CONFIG / "fixtures" / "guild_cnc.yaml").read_text(encoding="utf-8")
    )
    v = fixture_clearance_violations([ops[n] for n in names], fixture, TOOL_R)
    assert v == []


def test_grbl_program_lint(program, demo_inputs, tmp_path):
    from guildmodel.core.cam.castle_ops import write_castle_program
    from guildmodel.core.post.grbl import GRBLPost

    ops, names, _ = program
    _, castle, _ = demo_inputs
    post = GRBLPost(
        job_name="lint", material="acetate", tool_diameter_mm=3.175,
        spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
        safe_z_mm=castle.stock.total_pad_height_mm + 5.0,
    )
    write_castle_program([ops[n] for n in names], post)
    text = post.to_string()

    assert "G21" in text and "G90" in text
    assert "M3 S10000" in text and "M30" in text
    assert "nan" not in text.lower()
    for n in names:
        assert f"; --- {n} ---" in text
    feeds = {float(m) for m in re.findall(r"F([\d.]+)", text)}
    assert feeds == {750.0, 333.0}
    cut_z = [float(m) for m in re.findall(r"G1 .*?Z(-?[\d.]+)", text)]
    assert min(cut_z) == pytest.approx(0.4)         # onion skin is the floor
    rapid_z = [float(m) for m in re.findall(r"G0 Z(-?[\d.]+)", text)]
    assert min(rapid_z) >= castle.stock.total_pad_height_mm + 5.0 - 1e-6


# ------------------------------------------------------------------ the NC gate

def _held_cut_zs(section: str, min_moves: int = 50) -> list[float]:
    """Modal-state parse: Z levels held while feeding (the depth passes)."""
    from collections import Counter

    z = None
    mode = None       # modal motion mode: G-words persist across lines
    counts: Counter = Counter()
    for line in section.splitlines():
        s = line.strip()
        g = re.match(r"G(\d+)", s)
        if g:
            mode = int(g.group(1))
        m = re.search(r"Z(-?[\d.]+)", s)
        if m:
            z = round(float(m.group(1)), 3)
        if mode == 1 and z is not None and re.search(r"[XY](-?[\d.]+)", s):
            counts[z] += 1
    return sorted(zv for zv, n in counts.items() if n >= min_moves)


def test_against_reference_nc(program):
    """Structural cross-check against the user's proven Fusion program."""
    ops, _, _ = program
    ref = (DEMO / "Demo Program.nc").read_text(errors="replace")

    # reference hinge floor == ours
    hinge_section = ref.split("(Hinge Pockets)")[1].split("(Rough Scallop)")[0]
    ref_floor = min(float(m) for m in re.findall(r"Z(-?[\d.]+)", hinge_section))
    zmin, _ = ops["Hinge Pockets"].z_range()
    assert zmin == pytest.approx(ref_floor, abs=1e-6)        # 4.5

    # reference contour pass stack == ours (eyewires section, held Z values)
    eye_section = ref.split("(Eyewires)")[1].split("(Perimeter)")[0]
    ref_passes = _held_cut_zs(eye_section)
    ours = sorted({round(p[2], 3) for path in ops["Eyewires"].paths for p in path})
    assert ours == ref_passes == [0.4, 2.5, 5.0, 7.5]

    # rough floor: reference min Z 6.2 == ours (lowest terrace + 2)
    rough_section = ref.split("(Rough Scallop)")[1].split("(Fine Scallop)")[0]
    ref_rough_min = min(
        float(m) for m in re.findall(r"Z(-?[\d.]+)", rough_section)
    )
    assert ops["Rough Relief"].z_range()[0] == pytest.approx(ref_rough_min, abs=0.15)

    # fine envelope: reference 4.2..10.0 == ours
    fine_section = ref.split("(Fine Scallop)")[1].split("(Eyewires)")[0]
    ref_fine = [float(m) for m in re.findall(r"Z(-?[\d.]+)", fine_section)]
    ref_fine_cut = [z for z in ref_fine if z < 15]           # drop retracts
    zmin, zmax = ops["Fine Relief"].z_range()
    assert zmin == pytest.approx(min(ref_fine_cut), abs=0.05)
    # We skip the zero-material skim cuts at the stock top that the reference (Fusion)
    # still emits, so our fine envelope tops out just below the stock surface (M8).
    assert zmax < max(ref_fine_cut)
