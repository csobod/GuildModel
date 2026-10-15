"""The fourth axis (BUILDPLAN M26 §11.3): the profile, the post, the stock
flip about the rotary's centerline, the lint and the cut-time model.

A four-axis profile round-trips through YAML and a three-axis one loads
unchanged. The post writes A words to three decimals, commands the indexed
flip before the side's work offset, runs a varying-A stretch in inverse time
and never fits an arc to it, refuses an A word on a three-axis profile and
past the travel, and unwinds at the end. The stock flips about the
centerline bit for bit. The lint names an A word the profile cannot run;
the cut-time model charges a rotary-only move at the rotary's rate.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.project.schema import MachineProfile, RotaryAxis

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"


def test_the_profile_round_trips_with_and_without_a_rotary(tmp_path):
    from guildmodel.core.post.machine import load_machine_profile
    flat = load_machine_profile("guild_cnc", CONFIG)
    assert not flat.has_rotary and flat.axes == "XYZ" and flat.controller == "grbl11"
    four = load_machine_profile("guild_cnc_rotary", CONFIG)
    assert four.has_rotary and four.axes == "XYZA" and four.rotary.about == "X"
    assert four.max_swing_radius_mm(50.0) is None                 # not measured yet
    measured = four.model_copy(update={"spindle_nose_to_table_mm": 88.0})
    assert measured.max_swing_radius_mm(50.0) == pytest.approx(38.0)
    # a v1.8.0 profile, with none of the fields, loads unchanged
    old = {k: v for k, v in yaml.safe_load((CONFIG / "machines" / "guild_cnc.yaml").read_text()).items()}
    assert "rotary" not in old and MachineProfile(**old).rotary is None
    (tmp_path / "machines").mkdir()
    (tmp_path / "machines" / "mine.yaml").write_text(yaml.safe_dump(
        {**old, "name": "mine", "axes": "XYZA", "controller": "fluidnc",
         "rotary": RotaryAxis(direction_sign=-1, travel_deg=400.0).model_dump()}))
    mine = load_machine_profile("mine", tmp_path)
    assert mine.has_rotary and mine.rotary.direction_sign == -1 and mine.rotary.travel_deg == 400.0
    back = MachineProfile.model_validate(yaml.safe_load(yaml.safe_dump(mine.model_dump())))
    assert back == mine


def _post(**kw):
    from guildmodel.core.post.grbl import GRBLPost
    base = dict(job_name="t", material="acetate", tool_diameter_mm=3.175, spindle_rpm=12000,
                feed_rate_mmpm=600, plunge_rate_mmpm=200, safe_z_mm=11.0)
    base.update(kw)
    return GRBLPost(**base)


def test_the_post_commands_the_indexed_flip_before_the_offset_and_unwinds_at_the_end():
    post = _post(axes="XYZA", wcs="G55", index_a_deg=180.0)
    post.header("Anterior Cut (side two)")
    post.spindle_on()
    post.feed(x=1.0, y=2.0, z=3.0)
    post.end_program()
    lines = [ln for ln in post.to_string().splitlines() if ln and not ln.startswith(";")]
    i_a = next(i for i, ln in enumerate(lines) if ln.startswith("G0 A"))
    i_wcs = lines.index("G55  ; work offset for this side")
    assert lines[i_a] == "G0 A180.000" and lines[i_a - 1].startswith("G0 Z11.000")
    assert i_a < i_wcs
    assert lines[-2] == "G53 G0 A0" and lines[-1] == "M30"
    neg = _post(axes="XYZA", index_a_deg=-180.0, rotary_unwind="g28")
    neg.header("s")
    neg.end_program()
    assert "G0 A-180.000" in neg.to_string() and "G28 A0" in neg.to_string()


def test_a_varying_a_stretch_runs_in_inverse_time_and_is_linear():
    post = _post(axes="XYZA", rotary_max_rate_degpm=1800.0)
    post.header("s")
    post.spindle_on()
    # a quarter turn over 10 mm: the rotary needs 90 / 1800 = 0.05 min, the feed 10 / 600 = 0.0167
    post.emit_polyline4([(0.0, 0.0, -1.0, 0.0), (5.0, 0.0, -1.0, 45.0), (10.0, 0.0, -1.0, 90.0)])
    post.end_program()
    text = post.to_string()
    lines = text.splitlines()
    assert any(ln.startswith("G93") for ln in lines) and any(ln.startswith("G94") for ln in lines)
    g93 = [ln for ln in lines if ln.startswith("G1") and " A" in ln]
    assert len(g93) == 2 and all("F" in ln for ln in g93)
    f = float(g93[0].split("F")[1])
    assert f == pytest.approx(1.0 / 0.025, rel=1e-3)        # 45 deg at 1800: 0.025 min
    assert not any(ln.startswith(("G2 ", "G3 ")) for ln in lines)     # no arc on a varying A
    # a constant A rides in G94 at the linear feed
    flat = _post(axes="XYZA")
    flat.header("s")
    flat.emit_polyline4([(0.0, 0.0, -1.0, 180.0), (10.0, 0.0, -1.0, 180.0)])
    t = flat.to_string()
    assert "G93" not in t and "G1 X10.0000 Y0.0000 Z-1.0000 A180.000 F600" in t
    # without G93 support the rotary word rides the linear feed
    no93 = _post(axes="XYZA", supports_g93=False)
    no93.header("s")
    no93.emit_polyline4([(0.0, 0.0, -1.0, 0.0), (5.0, 0.0, -1.0, 45.0)])
    assert "G93" not in no93.to_string() and "A45.000 F600" in no93.to_string()


def test_an_a_word_is_refused_on_a_three_axis_profile_and_past_the_travel():
    post = _post()
    with pytest.raises(ValueError, match="needs a A axis"):
        post.rotary_index(180.0)
    with pytest.raises(ValueError, match="has XYZ"):
        post.emit_polyline4([(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 10.0)])
    bounded = _post(axes="XYZA", rotary_travel_deg=200.0)
    bounded.rotary_index(180.0)                               # within
    with pytest.raises(ValueError, match="past the rotary's travel"):
        bounded.rotary_index(270.0)


def test_the_stock_flips_about_the_rotary_centerline_bit_for_bit():
    from guildmodel.core.stock import DexelStock, ToolShape, cut
    from guildmodel.core.stock.cutting import vertical_poses
    stock = DexelStock.from_box(-6, -4, 6, 4, 0.0, 6.0, 0.5)
    cut(stock, vertical_poses([(2.0, 1.5, 4.0)]), ToolShape(kind="flat", radius_mm=1.0))
    turned = stock.mirrored(0.0, z_flip=6.0, axis="y")
    assert turned.volume() == pytest.approx(stock.volume())
    r, c = turned.cells_of(2.0, -1.5)                         # y negated, x kept
    assert turned.bottom().z[r, c] == pytest.approx(2.0) and turned.top().z[r, c] == pytest.approx(6.0)
    back = turned.mirrored(0.0, z_flip=6.0, axis="y")
    assert np.array_equal(back.count, stock.count)
    live = np.arange(stock.k)[:, None, None] < stock.count[None]
    assert np.allclose(np.where(live, back.z_top, 0), np.where(live, stock.z_top, 0))
    # the indexed-flip transform on a point: (x, y, z) -> (x, 2yc - y, 2zc - z)
    yc, zc = 1.0, 3.0
    about = stock.mirrored(yc, z_flip=2 * zc, axis="y")
    r2, c2 = about.cells_of(2.0, 2 * yc - 1.5)
    assert about.bottom().z[r2, c2] == pytest.approx(2 * zc - 4.0)


def test_the_lint_names_an_a_word_the_profile_cannot_run():
    from guildmodel.core.post.machine import lint_program, load_machine_profile
    flat = load_machine_profile("guild_cnc", CONFIG)
    four = load_machine_profile("guild_cnc_rotary", CONFIG)
    text = "G90\nG21\nG0 Z11.000\nG0 A180.000\nG55\nG1 X1.0 Y1.0 Z-1.0 F600\nM30\n"
    assert any("no rotary" in w for w in lint_program(text, flat))
    assert not any("rotary" in w for w in lint_program(text, four))
    bounded = four.model_copy(update={"rotary": four.rotary.model_copy(update={"travel_deg": 90.0})})
    assert any("past the rotary's travel" in w for w in lint_program(text, bounded))
    no93 = four.model_copy(update={"supports_g93": False})
    assert any("G93" in w for w in lint_program("G93\nG1 X1 A10 F40\nG94\n", no93))


def test_the_cut_time_model_charges_the_rotary():
    from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program
    from guildmodel.core.post.machine import load_machine_profile
    four = load_machine_profile("guild_cnc_rotary", CONFIG)
    dyn = MachineDynamics.from_profile(four)
    assert dyn.rotary_max_rate_degpm == 3600.0
    only_turn = "G90\nG21\n; --- Perimeter ---\nG0 A180.000\nM30\n"
    r = estimate_program(only_turn, dyn)
    assert r.cycle_seconds == pytest.approx(180.0 / 3600.0 * 60.0, rel=0.05)      # 3 s
    # a G93 move takes 1 / F minutes whatever its length
    g93 = "G90\nG21\n; --- Perimeter ---\nG0 X0 Y0 Z-1\nG93\nG1 X10 Y0 Z-1 A90 F20\nG94\nM30\n"
    r2 = estimate_program(g93, dyn)
    assert r2.cycle_seconds == pytest.approx(3.0, rel=0.2)
    # a three-axis program is timed as before
    plain = "G90\nG21\n; --- Perimeter ---\nG0 X0 Y0 Z-1\nG1 X60 Y0 Z-1 F600\nM30\n"
    r3 = estimate_program(plain, dyn)
    assert 5.5 < r3.cycle_seconds < 7.5


def test_a_vertical_pose_through_the_ray_path_equals_the_footprint():
    from guildmodel.core.stock import ToolShape
    for kind, extra in (("flat", {}), ("ball", {}), ("vbit", {"included_angle_deg": 60.0}),
                        ("toroid", {"corner_radius_mm": 0.3})):
        shape = ToolShape(kind=kind, radius_mm=1.5, **extra)
        fp = shape.footprint(0.25)
        xs = fp.di * 0.25
        ys = fp.dj * 0.25
        lo, hi = shape.column_intervals((0.0, 0.0, 2.0), (0.0, 0.0, 1.0), xs, ys)
        assert np.allclose(lo, 2.0 + fp.z_lo, atol=1e-9) and np.allclose(hi, 2.0 + fp.z_hi, atol=1e-9)
    # and a tilted pose cuts through the reference path
    from guildmodel.core.stock import DexelStock, cut
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.25)
    before = stock.volume()
    tilt = np.array([np.sin(np.radians(20.0)), 0.0, np.cos(np.radians(20.0))])
    cut(stock, np.array([[0.0, 0.0, 4.0, *tilt]]), ToolShape(kind="flat", radius_mm=1.0))
    assert stock.volume() < before


# ------------------------------------------------------------- the indexed flip in the planner

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


def _brow(partition):
    from guildmodel.core.project.schema import CastleParams, EdgeFeature
    brow = [z.name for z in partition.zones if z.name.startswith("eyewire_superior")][:1]
    return CastleParams(edge_features=[EdgeFeature(
        id="brow", label="Brow chamfer", face="anterior", edge="outline", zones=brow,
        profile="chamfer", width_mm=2.0, angle_deg=45.0, blend_mm=6.0, mirror=True)])


def test_the_rotary_flip_negates_y_and_z_about_the_centerline(demo):
    from guildmodel.core.cam.two_sided import anterior_setup_relief, flip_pause_text, plan_two_sided
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.core.zmap import castle_relief
    partition, hinges = demo
    castle = _brow(partition)
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3)
    T = castle.stock.blank_thickness_mm
    yc, zc = 1.0, T / 2.0
    two = anterior_setup_relief(relief, castle, flip="rotary", center_y=yc, center_z=zc)
    f, g = relief.field, two.field
    res = f.resolution
    assert g.z.shape == f.z.shape
    # the deepest anterior cut lands at (x, 2 yc - y), the same column, within a cell
    r1, c1 = np.unravel_index(np.argmax(relief.anterior_z), f.z.shape)
    r2, c2 = np.unravel_index(np.argmin(g.z), g.z.shape)
    y1 = f.origin[1] + r1 * res
    y2 = g.origin[1] + r2 * res
    assert c1 == c2 and abs(y2 - (2 * yc - y1)) < res + 1e-9
    # and its height is 2 zc - anterior
    assert g.z.min() == pytest.approx(2 * zc - relief.anterior_z.max(), abs=1e-9)
    assert two.partition.body.bounds[0] == pytest.approx(partition.body.bounds[0], abs=1e-9)   # x kept
    assert two.partition.body.bounds[1] == pytest.approx(2 * yc - partition.body.bounds[3], abs=1e-9)
    # the planner on a four-axis profile: the setups say so, the sign follows the profile
    four = load_machine_profile_for_test()
    job = plan_two_sided(relief, castle, hinges, yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"],
                         CastleCamParams(), yaml.safe_load((CONFIG / "tools.yaml").read_text()),
                         flip="rotary", rotary=four.rotary)
    assert job.two_sided
    s2 = job.setups[1]
    assert s2.flip == "rotary" and s2.a_deg == 180.0 and s2.reprobe == []
    assert any("indexed flip" in n for n in s2.notes)
    assert flip_pause_text(s2).startswith("Indexed flip") and "A180.000" in flip_pause_text(s2)
    neg = four.rotary.model_copy(update={"direction_sign": -1})
    job_neg = plan_two_sided(relief, castle, hinges, yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"],
                             CastleCamParams(), yaml.safe_load((CONFIG / "tools.yaml").read_text()),
                             flip="rotary", rotary=neg)
    assert job_neg.setups[1].a_deg == -180.0
    # the manual flip is untouched
    manual = plan_two_sided(relief, castle, hinges, yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"],
                            CastleCamParams(), yaml.safe_load((CONFIG / "tools.yaml").read_text()))
    assert manual.setups[1].flip == "manual" and manual.setups[1].a_deg is None


def load_machine_profile_for_test():
    from guildmodel.core.post.machine import load_machine_profile
    return load_machine_profile("guild_cnc_rotary", CONFIG)


# ------------------------------------------------------------- the workers

def test_the_workers_post_the_indexed_flip_and_turn_the_stock(demo, tmp_path, monkeypatch):
    """A rotary profile with the blank on the rotary bar: side two begins
    with the A move before its offset and carries no pause; the project
    records the run mode; the simulation turns side one's result about
    the centerline and judges both sides. The same profile with the blank
    on the flat mount still flips by hand."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.gui.app import GCodeWorker, SimWorker
    partition, hinges = demo
    castle = _brow(partition)
    cam = CastleCamParams(machine_name="guild_cnc_rotary")

    def generate(mount):
        done, errs, log = [], [], []
        worker = GCodeWorker(partition.body, castle, {"material_name": "acetate"},
                             partition=partition, hinge_polys=hinges, cam_params=cam)
        worker.kernel = "mesh"
        worker.fixture_mount = mount
        worker.finished.connect(lambda s, rows: done.append((s, rows)))
        worker.error.connect(errs.append)
        worker.progress.connect(log.append)
        worker.run()
        assert errs == [], errs[0] if errs else ""
        return worker, done[0], log

    worker, (summary, rows), log = generate("rotary_bar")
    assert set(worker.programs) == {"posterior_cut.nc", "back_cut.nc"}
    setups = worker.setup_dict["setups"]
    assert [s["flip"] for s in setups] == ["none", "rotary"]
    assert setups[1]["a_deg"] == 180.0 and setups[1]["wcs"] == "G55"
    assert worker.setup_dict["run_mode"] == "rotary_indexed"
    back = worker.programs["back_cut.nc"].splitlines()
    i_a = next(i for i, ln in enumerate(back) if ln.startswith("G0 A180.000"))
    i_wcs = next(i for i, ln in enumerate(back) if ln.startswith("G55"))
    assert i_a < i_wcs, "the rotary turns the blank before the second offset is selected"
    assert not any(ln.startswith("M0") for ln in back), "an indexed flip needs no pause"
    assert any("Indexed flip" in ln for ln in back)
    assert any("G53 G0 A0" in ln or "G28" in ln for ln in back[i_wcs:]), "the rotary unwinds at the end"
    assert not any(" A" in ln.split(";")[0] for ln in worker.programs["posterior_cut.nc"].splitlines()
                   if ln.startswith(("G0 ", "G1 ", "G2 ", "G3 "))), "side one is cut at A0 and writes no A word"
    assert any("Indexed flip" in ln for ln in log)
    # the simulation reads the setup and turns the stock the same way
    sim_done, errs = [], []
    sim = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                    program_text=worker.programs["posterior_cut.nc"],
                    back_program_text=worker.programs["back_cut.nc"],
                    back_setup=setups[1])
    sim.finished.connect(lambda r, lines, plan: sim_done.append((r, lines, plan)))
    sim.error.connect(errs.append)
    sim.run()
    assert errs == [], errs[0] if errs else ""
    report, lines, plan = sim_done[0]
    assert any(ln.startswith("Side one:") for ln in lines) and any(ln.startswith("Side two:") for ln in lines)
    assert report.status() in {"ok", "warn"}, lines
    # on the flat mount the same profile flips by hand, as before
    worker, _, _ = generate("flat")
    setups = worker.setup_dict["setups"]
    assert setups[1]["flip"] == "manual" and worker.setup_dict["run_mode"] == "two_file"
    back = worker.programs["back_cut.nc"]
    assert "flip about machine X" in back and "Indexed flip" not in back
    assert not any(ln.startswith("G0 A") for ln in back.splitlines())


def test_the_project_file_records_the_run_mode(tmp_path):
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import ProjectSchema
    project = ProjectSchema(job_name="four")
    path = tmp_path / "four.gmodel"
    save_gmodel(path, project=project, dxf_bytes=b"dxf", run_mode="rotary_indexed")
    assert load_gmodel(path).run_mode == "rotary_indexed"
    save_gmodel(path, project=project, dxf_bytes=b"dxf")
    assert load_gmodel(path).run_mode == "two_file"
