"""Two-sided machining of a flat blank (BUILDPLAN M24 §9.4), on the demo.

A front that takes nothing off the anterior posts one setup, byte-identical
with before. A front with a brow chamfer posts two: side one the posterior
less the through-cuts, side two the anterior in G55 after the flip, mirrored
about the blank's center line and re-zeroed on the fixture plane, the
through-cuts last and the part released on tabs. The stock carried across is
side one's result flipped, bit for bit reversible; the back program begins
with G55, the flip pause GuildSend parses and the probe block when asked;
the simulation of both sides reads the stored programs.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.project.schema import CastleCamParams, CastleParams, EdgeFeature, Setup

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


def _brow(partition) -> CastleParams:
    brow = [z.name for z in partition.zones if z.name.startswith("eyewire_superior")][:1]
    return CastleParams(edge_features=[EdgeFeature(
        id="brow", label="Brow chamfer", face="anterior", edge="outline", zones=brow,
        profile="chamfer", width_mm=2.0, angle_deg=45.0, blend_mm=6.0, mirror=True)])


@pytest.fixture(scope="module")
def reliefs(demo):
    from guildmodel.core.zmap import castle_relief
    partition, hinges = demo
    plain = castle_relief(partition, CastleParams(), hinges, kernel="mesh", resolution=0.3)
    brow = castle_relief(partition, _brow(partition), hinges, kernel="mesh", resolution=0.3)
    return plain, brow


def test_a_front_with_nothing_on_the_anterior_posts_one_setup_as_before(demo, reliefs):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.cam.two_sided import anterior_setup_relief, needs_second_side, plan_two_sided
    partition, hinges = demo
    plain, _ = reliefs
    castle = CastleParams()
    assert not needs_second_side(plain)
    assert anterior_setup_relief(plain, castle) is None
    job = plan_two_sided(plain, castle, hinges, TOOLS["flat_3175"], CastleCamParams(), TOOLS)
    assert not job.two_sided and job.relief_two is None
    assert [s.model_dump() for s in job.setups] == [
        Setup(side="posterior", wcs="G54", program="posterior_cut.nc", stock_top_mm=10.0).model_dump()]
    direct = generate_castle_program(plain, castle, hinges, TOOLS["flat_3175"],
                                     params=CastleCamParams(), tools_cfg=TOOLS)
    assert [(op.name, len(op.paths)) for op in job.side_one] == [(op.name, len(op.paths)) for op in direct]
    assert all(np.array_equal(np.asarray(a.paths[0]), np.asarray(b.paths[0]))
               for a, b in zip(job.side_one, direct) if a.paths)


def test_the_anterior_is_a_relief_of_its_own_mirrored_and_rezeroed(demo, reliefs):
    from guildmodel.core.cam.two_sided import anterior_setup_relief, needs_second_side
    partition, _ = demo
    _, brow = reliefs
    castle = _brow(partition)
    assert needs_second_side(brow) and castle.cuts_anterior()
    two = anterior_setup_relief(brow, castle)
    assert two is not None
    f, g = brow.field, two.field
    res = f.resolution
    assert g.z.shape == f.z.shape and g.resolution == res
    T = castle.stock.blank_thickness_mm
    # the deepest anterior cut lands at the mirrored position, the same row, within a cell
    r1, c1 = np.unravel_index(np.argmax(brow.anterior_z), f.z.shape)
    r2, c2 = np.unravel_index(np.argmin(g.z), g.z.shape)
    x1 = f.origin[0] + c1 * res
    x2 = g.origin[0] + c2 * res
    assert r1 == r2 and abs(x2 + x1) < res + 1e-9
    assert g.z.min() == pytest.approx(T - brow.anterior_z.max(), abs=1e-9)
    assert g.z.max() == pytest.approx(T)
    # where the front is untouched the target is the new top; the band is the chamfer
    assert two.feature_band is not None and two.feature_band.sum() == (brow.anterior_z > 0.05).sum()
    assert two.feature_max_slope_deg == pytest.approx(45.0)
    assert two.inside.sum() == brow.inside.sum()
    assert two.partition.body.area == pytest.approx(partition.body.area, rel=1e-9)
    assert two.partition.body.bounds[0] == pytest.approx(-partition.body.bounds[2], abs=1e-9)
    assert two.anterior is None and two.groove is None


def test_two_sides_split_the_work_and_the_through_cuts_go_last(demo, reliefs):
    from guildmodel.core.cam.two_sided import THROUGH_CUT_OPS, plan_two_sided
    partition, hinges = demo
    _, brow = reliefs
    castle = _brow(partition)
    job = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"], CastleCamParams(), TOOLS,
                         flip_axis_x_mm=201.146)
    assert job.two_sided
    one = [op.name for op in job.side_one]
    two = [op.name for op in job.side_two]
    assert "Hinge Pockets" in one and not (set(one) & THROUGH_CUT_OPS)
    assert "Features" in two and two[-1] == "Perimeter" and "Eyewires" in two
    assert two.index("Features") < two.index("Eyewires") < two.index("Perimeter")
    assert "Hinge Pockets" not in two
    # released on tabs: the perimeter runs to the fixture plane, never below
    perimeter = next(op for op in job.side_two if op.name == "Perimeter")
    zs = np.array([p[2] for path in perimeter.paths for p in path])
    assert zs.min() == pytest.approx(0.0, abs=1e-9)
    assert job.castle_two.holding.strategy == "tabs" and not job.castle_two.stock.use_pad_block
    s1, s2 = job.setups
    assert (s1.side, s1.wcs, s1.program, s1.stock_top_mm) == ("posterior", "G54", "posterior_cut.nc", 10.0)
    assert (s2.side, s2.wcs, s2.program, s2.flip, s2.stock_top_mm) == ("anterior", "G55", "back_cut.nc", "manual", 6.0)
    assert s2.flip_axis_x_mm == 201.146 and s2.reprobe == ["Z"]
    # kept on side one when asked, with the skin
    keep = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"],
                          CastleCamParams(through_cuts_side="one"), TOOLS)
    assert "Perimeter" in [op.name for op in keep.side_one]
    assert not (set(op.name for op in keep.side_two) & THROUGH_CUT_OPS)
    # and off means one setup whatever the front carries
    off = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"], CastleCamParams(two_sided="off"), TOOLS)
    assert not off.two_sided


def test_the_stock_flips_bit_for_bit_and_clips_to_the_blank():
    from guildmodel.core.stock import DexelStock, ToolShape, cut
    from guildmodel.core.stock.cutting import vertical_poses
    stock = DexelStock.from_box(-6, -4, 6, 4, 0.0, 6.0, 0.5)
    groove = ToolShape.from_tool(dict(type="groove", radius_mm=2.0, flute_length_mm=2.0,
                                      groove_depth_mm=0.75, groove_width_mm=1.5, neck_diameter_mm=2.5))
    cut(stock, vertical_poses([(1.0, 0.0, 2.0), (2.0, 0.0, 2.0)]), groove)        # an undercut
    cut(stock, vertical_poses([(-3.0, 1.0, 4.0)]), ToolShape(kind="flat", radius_mm=1.0))
    assert stock.undercut().any()
    flipped = stock.mirrored(0.0, z_flip=6.0)
    assert flipped.volume() == pytest.approx(stock.volume())
    assert flipped.origin[0] == pytest.approx(-(stock.origin[0] + (stock.shape[1] - 1) * 0.5))
    back = flipped.mirrored(0.0, z_flip=6.0)
    assert np.array_equal(back.count, stock.count)
    live = np.arange(stock.k)[:, None, None] < stock.count[None]
    assert np.allclose(np.where(live, back.z_top, 0), np.where(live, stock.z_top, 0))
    assert np.allclose(np.where(live, back.z_bot, 0), np.where(live, stock.z_bot, 0))
    # the flat tool's pocket at x = -3 is at x = +3 after the flip, open from below
    r, c = flipped.cells_of(3.0, 1.0)
    assert flipped.bottom().z[r, c] == pytest.approx(2.0)    # 6 - 4
    assert flipped.top().z[r, c] == pytest.approx(6.0)
    # clipping to the blank drops the box above it and the slab under it
    box = DexelStock.from_box(-1e9, -1e9, 1e9, 1e9, -50.0, 11.0, 0.5, origin=stock.origin, shape=stock.shape)
    clipped = box.clipped(0.0, np.full(stock.shape, 6.0))
    assert clipped.volume() == pytest.approx(stock.shape[0] * stock.shape[1] * 0.25 * 6.0)
    assert np.all(clipped.count == 1)


def test_the_back_program_begins_in_g55_with_the_pause_and_the_probe(demo, reliefs):
    from guildmodel.core.cam.castle_ops import build_tool_settings, write_castle_program
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.cam.two_sided import FLIP_PAUSE, flip_pause_text, plan_two_sided
    from guildmodel.core.post.grbl import GRBLPost
    partition, hinges = demo
    _, brow = reliefs
    castle = _brow(partition)
    params = CastleCamParams()
    job = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"], params, TOOLS, flip_axis_x_mm=201.146)
    ts, _ = build_tool_settings(job.side_two, TOOLS, default_feed=600, default_plunge=200,
                                default_spindle=12000)
    f0 = ts[job.side_two[0].tool_name]
    post = GRBLPost(job_name="back_cut", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm,
                    safe_z_mm=params.safe_z_for(job.castle_two.stock.total_pad_height_mm), wcs="G55")
    pause = flip_pause_text(job.setups[1])
    assert pause.startswith(FLIP_PAUSE) and "G55" in pause and "201.146" in pause and "re-probe Z" in pause
    post.preamble = ["; " + pause] + post.probe_z_block()
    write_castle_program(job.side_two, post, side="Anterior Cut (side two)", tool_settings=ts,
                         contour_op_names=CASTLE_CONTOUR_OPS)
    text = post.to_string()
    lines = text.splitlines()
    modal = [ln for ln in lines if not ln.startswith(";") and ln.strip()]
    assert modal[:4] == ["G90  ; absolute mode", "G21", "G17  ; XY arc plane", "G55  ; work offset for this side"]
    assert "G38.2 Z-25.0 F100" in text and "G10 L20 P2 Z0" in text
    assert any(ln.startswith("; " + FLIP_PAUSE) for ln in lines)
    assert "; Side: Anterior Cut (side two)" in text and text.rstrip().endswith("M30")
    # the posterior program never writes a work offset: it is G54 as before
    one = GRBLPost(job_name="posterior_cut", material="acetate", tool_diameter_mm=3.175,
                   spindle_rpm=12000, feed_rate_mmpm=600, plunge_rate_mmpm=200, safe_z_mm=11.0)
    one.header("Posterior Cut")
    assert "G5" not in one.to_string().replace("G54", "")
    assert "G54" not in one.to_string()
    # a single-file program carries both sides around one pause
    both = GRBLPost(job_name="both", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=12000, feed_rate_mmpm=600, plunge_rate_mmpm=200, safe_z_mm=11.0)
    write_castle_program(job.side_one, both, side="Posterior Cut", contour_op_names=CASTLE_CONTOUR_OPS, end=False)
    both.spindle_off()
    both.program_pause(pause)
    both.wcs = "G55"
    both._lines.append("G55")
    write_castle_program(job.side_two, both, side="Anterior Cut (side two)",
                         contour_op_names=CASTLE_CONTOUR_OPS, start=False)
    single = both.to_string()
    assert single.count("M0") == 1 and single.count("M30") == 1 and single.count("; Side:") == 2


def test_the_workers_post_and_simulate_both_sides(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import GCodeWorker, SimWorker
    partition, hinges = demo
    castle = _brow(partition)
    cam = CastleCamParams()
    done, errs, log = [], [], []
    worker = GCodeWorker(partition.body, castle, {"material_name": "acetate"},
                         partition=partition, hinge_polys=hinges, cam_params=cam)
    worker.kernel = "mesh"
    worker.finished.connect(lambda s, rows: done.append((s, rows)))
    worker.error.connect(errs.append)
    worker.progress.connect(log.append)
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert set(worker.programs) == {"posterior_cut.nc", "back_cut.nc"}
    setups = worker.setup_dict["setups"]
    assert [s["wcs"] for s in setups] == ["G54", "G55"] and worker.setup_dict["two_sided"]
    assert setups[1]["flip_axis_x_mm"] == pytest.approx(201.146)
    assert "G55" in worker.programs["back_cut.nc"] and "G55" not in worker.programs["posterior_cut.nc"]
    assert "Perimeter" not in worker.programs["posterior_cut.nc"]
    assert "--- Perimeter ---" in worker.programs["back_cut.nc"]
    summary, rows = done[0]
    assert "Two-sided job" in summary and any(r["name"].startswith("Side two") for r in rows)
    # the simulation reads both stored programs and reports both sides
    sim_done = []
    sim = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                    program_text=worker.programs["posterior_cut.nc"],
                    back_program_text=worker.programs["back_cut.nc"])
    sim.finished.connect(lambda r, lines, plan: sim_done.append((r, lines, plan)))
    sim.error.connect(errs.append)
    sim.run()
    assert errs == [], errs[0] if errs else ""
    report, lines, plan = sim_done[0]
    assert any(ln.startswith("Side one:") for ln in lines) and any(ln.startswith("Side two:") for ln in lines)
    assert report.status() in {"ok", "warn"}, lines
    assert plan.stock.resolution == pytest.approx(0.15)


def test_the_cut_tab_carries_the_two_sided_choice(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    cp = p.cam_params()
    assert (cp.two_sided, cp.through_cuts_side, cp.probe_block) == ("auto", "two", False)
    p.set_cam_params(CastleCamParams(two_sided="on", through_cuts_side="one", probe_block=True))
    cp = p.cam_params()
    assert (cp.two_sided, cp.through_cuts_side, cp.probe_block) == ("on", "one", True)
    p.two_sided.setCurrentIndex(1)                       # off greys the rest
    assert not p.through_cuts_side.isEnabled() and p.cam_params().two_sided == "off"
