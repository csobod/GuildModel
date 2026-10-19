"""Two-sided machining of a flat blank (BUILDPLAN M24 §9.4; the anterior
first since 2.0), on the demo.

A front that takes nothing off the anterior posts one setup, byte-identical
with before. A front with a brow chamfer posts two, in the maker's order
(2026-10-17): the anterior first, in G55, front face up while the blank is
still a flat slab, mirrored about the blank's center line and re-zeroed on the
fixture plane, cutting its chamfer and nothing of the posterior's; then the
flip, and the posterior in G54, the one-sided program, through-cuts and onion
skin. The stock carried across is bit for bit reversible; the anterior
program begins with G55, and one file carries both setups around the flip's
pause GuildSend parses; the simulation of both reads the stored programs.
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
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
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
    assert not job.two_sided and job.relief_anterior is None and job.anterior == []
    assert [s.model_dump() for s in job.setups] == [
        Setup(side="posterior", wcs="G54", program="posterior_cut.nc", stock_top_mm=10.0).model_dump()]
    direct = generate_castle_program(plain, castle, hinges, TOOLS["flat_3175"],
                                     params=CastleCamParams(), tools_cfg=TOOLS)
    assert [(op.name, len(op.paths)) for op in job.posterior] == [(op.name, len(op.paths)) for op in direct]
    assert all(np.array_equal(np.asarray(a.paths[0]), np.asarray(b.paths[0]))
               for a, b in zip(job.posterior, direct) if a.paths)


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
    # the stack turns, the pad block into its spacer's cut-out (2026-10-17)
    from guildmodel.core.cam.two_sided import flip_height
    T = flip_height(castle.stock)
    assert T == castle.stock.total_pad_height_mm
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


def test_the_anterior_goes_first_and_the_posterior_is_the_one_sided_program(demo, reliefs):
    """The maker's order (2026-10-17): the anterior first, front face up, its
    chamfer and nothing that is the posterior's; then the flip, and the
    posterior exactly as a one-sided job cuts it, through-cuts and onion skin."""
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.cam.two_sided import THROUGH_CUT_OPS, plan_two_sided
    partition, hinges = demo
    _, brow = reliefs
    castle = _brow(partition)
    job = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"], CastleCamParams(), TOOLS,
                         flip_axis_x_mm=201.146)
    assert job.two_sided
    front = [op.name for op in job.anterior]
    assert "Features" in front and not (set(front) & (THROUGH_CUT_OPS | {"Component Pockets"}))
    # the chamfer is cut to its foot, past the edge, where the stock is still uncut
    target = float(job.relief_anterior.field.z[job.relief_anterior.inside].min())
    deepest = min(float(np.min([q[2] for path in op.paths for q in path])) for op in job.anterior)
    assert deepest == pytest.approx(target, abs=0.05)
    assert job.relief_anterior.uncut_beyond_edge
    # the posterior is the one-sided program, op for op and path for path
    direct = generate_castle_program(brow, castle, hinges, TOOLS["flat_3175"],
                                     params=CastleCamParams(), tools_cfg=TOOLS)
    assert [(op.name, len(op.paths)) for op in job.posterior] == [(op.name, len(op.paths)) for op in direct]
    assert job.posterior[-1].name == "Perimeter" and "Component Pockets" in [op.name for op in job.posterior]
    perimeter = job.posterior[-1]
    zs = np.array([q[2] for path in perimeter.paths for q in path])
    assert zs.min() == pytest.approx(castle.onion_skin_mm, abs=1e-9)    # the onion skin
    assert not job.castle_anterior.stock.use_pad_block
    assert job.castle_anterior.holding == castle.holding
    a, b = job.setups
    assert (a.side, a.wcs, a.program, a.flip, a.stock_top_mm) == ("anterior", "G55", "anterior_cut.nc", "none", 10.0)
    assert any("spacer" in n for n in a.notes)
    assert (b.side, b.wcs, b.program, b.flip, b.stock_top_mm) == ("posterior", "G54", "posterior_cut.nc", "manual", 10.0)
    assert b.flip_axis_x_mm == 201.146 and b.reprobe == []
    probed = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"],
                            CastleCamParams(probe_block=True), TOOLS)
    assert probed.setups[-1].reprobe == ["Z"]
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


def test_the_anterior_program_begins_in_g55_and_one_file_pauses_for_the_flip(demo, reliefs):
    from guildmodel.core.cam.castle_ops import build_tool_settings, write_castle_program
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.cam.two_sided import FLIP_PAUSE, flip_pause_text, plan_two_sided
    from guildmodel.core.post.grbl import GRBLPost
    partition, hinges = demo
    _, brow = reliefs
    castle = _brow(partition)
    params = CastleCamParams(probe_block=True)
    job = plan_two_sided(brow, castle, hinges, TOOLS["flat_3175"], params, TOOLS, flip_axis_x_mm=201.146)
    ts, _ = build_tool_settings(job.anterior + job.posterior, TOOLS, default_feed=600,
                                default_plunge=200, default_spindle=12000)
    pause = flip_pause_text(job.setups[1])
    assert pause.startswith(FLIP_PAUSE) and "front face down" in pause
    assert "G54" in pause and "201.146" in pause and "re-probe Z" in pause

    def post(name, wcs, preamble=()):
        f0 = ts[job.anterior[0].tool_name]
        return GRBLPost(job_name=name, material="acetate", tool_diameter_mm=f0.diameter_mm,
                        spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                        plunge_rate_mmpm=f0.plunge_rate_mmpm,
                        safe_z_mm=params.safe_z_for(10.0), wcs=wcs, preamble=list(preamble))

    front = post("anterior_cut", "G55")
    write_castle_program(job.anterior, front, side="Anterior Cut", tool_settings=ts,
                         contour_op_names=CASTLE_CONTOUR_OPS)
    lines = front.to_string().splitlines()
    modal = [ln for ln in lines if not ln.startswith(";") and ln.strip()]
    assert modal[:4] == ["G90  ; absolute mode", "G21", "G17  ; XY arc plane", "G55  ; work offset for this side"]
    assert lines[-1] == "M30"
    # the posterior after the flip: probed down from where the tool was left,
    # G54's Z set to the blank's back plus the plate (the 2.0 bug hunt)
    back = post("posterior_cut", "G54")
    probe = back.probe_z_block(float(castle.stock.blank_thickness_mm), 6.0, wcs_slot=1)
    i = probe.index("G38.2 Z-25.0 F100")
    assert probe[i - 1] == "G91" and probe[i + 1] == "G90"
    assert probe[i + 2] == f"G10 L20 P1 Z{castle.stock.blank_thickness_mm + 6.0:.3f}"
    # one file: the anterior, the spindle off, the flip's pause, then the
    # posterior naming its own offset and changing back to its own tool
    one = post("two_sided_cut", "G55")
    write_castle_program(job.anterior, one, side="Anterior Cut", tool_settings=ts,
                         contour_op_names=CASTLE_CONTOUR_OPS, end=False, pause=pause)
    rest = post("two_sided_cut", "G54", preamble=probe)
    write_castle_program(job.posterior, rest, side="Posterior Cut", tool_settings=ts,
                         contour_op_names=CASTLE_CONTOUR_OPS, start=False,
                         current_tool=job.anterior[-1].tool_name)
    single = (one.to_string() + rest.to_string()).splitlines()
    assert single.count("M30") == 1 and sum(ln.startswith("; Side:") for ln in single) == 2
    k = single.index("; " + pause)
    assert single[k + 1] == "M0" and "M5" in single[k - 3:k]
    assert single[k + 2].startswith("; Side:") and single[k + 3] == "G54  ; work offset for this side"
    assert "G38.2 Z-25.0 F100" in single[k:]
    if job.anterior[-1].tool_name != job.posterior[0].tool_name:
        assert any(ln.startswith("; --- Tool Change") for ln in single[k:k + 12])
    from guildmodel.gui.app import split_two_sided
    a_text, p_text = split_two_sided("\n".join(single))
    assert "; " + pause in a_text and p_text.startswith("G90\nG21\nG17\n; Side:")


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
    assert set(worker.programs) == {"anterior_cut.nc", "posterior_cut.nc"}
    setups = worker.setup_dict["setups"]
    assert [s["wcs"] for s in setups] == ["G55", "G54"] and worker.setup_dict["two_sided"]
    assert [s["side"] for s in setups] == ["anterior", "posterior"]
    assert worker.setup_dict["run_mode"] == "two_file"
    assert setups[1]["flip_axis_x_mm"] == pytest.approx(201.146)
    front, back = worker.programs["anterior_cut.nc"], worker.programs["posterior_cut.nc"]
    assert "G55" in front and "G55" not in back
    assert "--- Perimeter ---" in back and "--- Perimeter ---" not in front
    assert "--- Component Pockets ---" not in front and "; After anterior_cut.nc: Flip stock" in back
    # without the probe, the posterior says where its Z0 is after the turn:
    # the bed, with the default zero on the blank's bottom
    assert "; Z0: the bed, as for the anterior; the flip does not move it" in back
    assert "; Re-zero Z: touch off" not in back
    # and what the anterior leaves of the onion skin: the brow's stretch of
    # the perimeter, said, not warned
    assert any("onion skin along" in ln and "of the perimeter" in ln for ln in log)
    summary, rows = done[0]
    assert "Two-sided job" in summary and rows[0]["name"].startswith("Anterior · ")
    # the inspector colors every row and names its tool from the overlay: the
    # anterior's ops are on it under their rows' names, after the posterior's,
    # which keep their colors
    overlay = {e["name"]: e for e in worker.op_overlay}
    assert all(row["name"] in overlay for row in rows), [r["name"] for r in rows]
    assert not worker.op_overlay[0]["name"].startswith("Anterior")
    assert all(e["tool"] for e in worker.op_overlay if e["name"].startswith("Anterior · "))
    # the simulation reads both stored programs: the anterior, the flip, the posterior
    from guildmodel.core.stock.playback import SetupsPlan
    from guildmodel.gui.app import frame_programs

    def simulate(programs):
        posterior, anterior = frame_programs(programs)
        got = []
        sim = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                        program_text=posterior, anterior_program_text=anterior,
                        anterior_setup=setups[0])
        sim.finished.connect(lambda r, lines, plan: got.append((r, lines, plan)))
        sim.error.connect(errs.append)
        sim.run()
        assert errs == [], errs[0] if errs else ""
        return got[0]

    report, lines, plan = simulate(worker.programs)
    assert any(ln.startswith("Anterior:") for ln in lines) and any(ln.startswith("Posterior:") for ln in lines)
    assert report.status() in {"ok", "warn"}, lines
    assert isinstance(plan, SetupsPlan) and len(plan.flip_indices) == 1
    f = plan.flip_indices[0]
    assert plan.flip_label_at(f).startswith("Flip")
    assert plan.label_at(f - 1).startswith("Anterior · ") and not plan.label_at(plan.n_positions - 1).startswith("Anterior")
    assert plan.stock.resolution == pytest.approx(0.15)
    # one file, pausing for the flip: the same two setups, the same verdict
    one = GCodeWorker(partition.body, castle, {"material_name": "acetate"}, partition=partition,
                      hinge_polys=hinges, cam_params=cam.model_copy(update={"two_sided_output": "one_file"}))
    one.kernel = "mesh"
    one.error.connect(errs.append)
    one.run()
    assert errs == [], errs[0] if errs else ""
    assert set(one.programs) == {"two_sided_cut.nc"} and one.setup_dict["run_mode"] == "single_file"
    assert [s["program"] for s in one.setup_dict["setups"]] == ["two_sided_cut.nc"] * 2
    text = one.programs["two_sided_cut.nc"]
    assert text.count("M30") == 1 and "; Flip stock and re-register on dowel pins" in text
    report1, lines1, _ = simulate(one.programs)
    assert lines1 == lines


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
    assert (cp.two_sided, cp.two_sided_output, cp.probe_block) == ("auto", "two_files", False)
    p.set_cam_params(CastleCamParams(two_sided="on", two_sided_output="one_file", probe_block=True))
    cp = p.cam_params()
    assert (cp.two_sided, cp.two_sided_output, cp.probe_block) == ("on", "one_file", True)
    p.two_sided.setCurrentIndex(1)                       # off greys the rest
    assert not p.two_sided_output.isEnabled() and p.cam_params().two_sided == "off"


def test_an_older_file_with_through_cuts_side_opens_without_it():
    """`through_cuts_side` moved the through-cuts to side two, cut last; the
    posterior makes them since 2.0, and a file that carries the choice opens
    without it."""
    cp = CastleCamParams.model_validate({"two_sided": "on", "through_cuts_side": "two"})
    assert cp.two_sided == "on" and "through_cuts_side" not in cp.model_dump()


def test_a_top_face_zero_is_touched_off_again_after_the_flip(demo, tmp_path, monkeypatch):
    """With the program zero on the blank's top face, the face on top changes
    at the flip: the posterior says to touch off on the blank's back."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.project.schema import ProgramZero
    from guildmodel.gui.app import GCodeWorker
    partition, hinges = demo
    errs = []
    worker = GCodeWorker(partition.body, _brow(partition), {"material_name": "acetate"},
                         partition=partition, hinge_polys=hinges,
                         cam_params=CastleCamParams(program_zero=ProgramZero(z_ref="top")))
    worker.kernel = "mesh"
    worker.error.connect(errs.append)
    worker.run()
    assert errs == [], errs[0] if errs else ""
    back = worker.programs["posterior_cut.nc"]
    assert "; Re-zero Z: touch off on the blank's back" in back and "it is Z0 in this offset" in back
    assert "; Z0: the bed" not in back


def test_the_anterior_says_what_it_leaves_of_the_onion_skin(demo, reliefs):
    """The posterior's through-cuts stop an onion skin above the front face,
    and the anterior, cut first, takes material off that same face. The brow
    chamfer takes the skin off part of the perimeter, which the rest still
    holds; an anterior bezel takes it off the whole of each lens opening, and
    the opening's core comes loose when the eyewires cut through."""
    from guildmodel.core.cam.two_sided import skin_hold_notes, skin_holds
    from guildmodel.core.project.schema import EyewireBezelParams, HoldingParams
    from guildmodel.core.zmap import castle_relief
    partition, hinges = demo
    plain, brow = reliefs
    cam = CastleCamParams()
    assert skin_holds(plain, CastleParams(), cam) == []
    holds = skin_holds(brow, _brow(partition), cam)
    rim = [h for h in holds if h.ring == "perimeter"]
    assert len(rim) == 1 and 0.0 < rim[0].held < 1.0 and rim[0].deepest_mm > 0.45
    notes = skin_hold_notes(holds)
    assert not any(warn for warn, _ in notes)
    assert any("of the perimeter; it holds on the rest." in line for _, line in notes)
    # on tabs, the perimeter's hold is the tabs' height
    tabbed = _brow(partition).model_copy(update={"holding": HoldingParams(strategy="tabs")})
    rim_t = [h for h in skin_holds(brow, tabbed, cam) if h.ring == "perimeter"]
    assert rim_t and rim_t[0].tabs and rim_t[0].hold_mm == pytest.approx(1.0)
    castle = CastleParams(eyewire_bezel=EyewireBezelParams(enabled=True, face="anterior"))
    bezel = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3)
    holds = skin_holds(bezel, castle, cam)
    lens = [h for h in holds if h.ring == "opening"]
    assert len(lens) == 2 and all(h.held == 0.0 for h in lens), [(h.held, h.deepest_mm) for h in lens]
    warns = [line for warn, line in skin_hold_notes(holds) if warn]
    assert len(warns) == 2 and all(
        "its core comes loose when the posterior's Eyewires cut through." in w for w in warns)
    # with the eyewires off nothing cuts the openings through, and no skin is lost
    off = cam.model_copy(update={"op_enabled": {**cam.op_enabled, "Eyewires": False}})
    assert not any(h.ring == "opening" for h in skin_holds(bezel, castle, off))


def test_the_anterior_paths_are_drawn_back_in_the_design_frame():
    """The 2D view shows the design frame; the anterior setup's paths are
    mirrored about the flip line, or about the rotary's centerline, and the
    same mirror takes them back."""
    from guildmodel.core.cam.two_sided import mirror_points, mirror_polygon
    from shapely.geometry import Polygon
    assert mirror_points([(1.0, 2.0)]) == [(-1.0, 2.0)]
    assert mirror_points([(1.0, 2.0)], 5.0) == [(9.0, 2.0)]
    assert mirror_points([(1.0, 2.0)], 3.0, "y") == [(1.0, 4.0)]
    pts = [(1.5, -2.0), (7.25, 3.0)]
    assert mirror_points(mirror_points(pts, 4.0), 4.0) == pts
    tri = Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 2.0)])
    assert mirror_polygon(tri, 1.0).equals(Polygon(mirror_points(tri.exterior.coords, 1.0)))
