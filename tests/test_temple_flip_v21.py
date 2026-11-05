"""A temple turns over its length (2.1), and its simulation shows the flip.

The front turns over about the fixture's vertical line, its X mirrored, the
pins above and below the blank. A temple blank is a long strip: it turns
over its length, Y mirrored about the blank's center line, the pins at
either end in the waste margin, so the hinge end stays at the end it was,
against the stop. The fixture's zone can still ask for the front's flip.
The temple's simulation runs both setups with the flip between, as the
front's has since 2.0, and a one-file temple program is simulated at all.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml
from shapely.geometry import box

from guildmodel.core.project.schema import CastleCamParams, Setup, TempleParams

ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())
FIXTURE = yaml.safe_load((ROOT / "src/guildmodel/config/fixtures/guild_cnc.yaml").read_text())


def test_a_temple_zone_turns_over_its_length_unless_the_fixture_says_otherwise():
    from guildmodel.core.cam.two_sided import temple_flip_line
    assert temple_flip_line(FIXTURE, "temple_right") == ("y", pytest.approx(71.781))
    assert temple_flip_line(FIXTURE, "temple_left") == ("y", pytest.approx(37.780))
    # a zone without the line: its horizontal center; one that names the
    # front's flip: that; a zone the fixture does not place: no line
    bare = {"blank_zones": {"t": {"x_mm": 10.0, "y_mm": 20.0, "width_mm": 100.0, "height_mm": 30.0}}}
    assert temple_flip_line(bare, "t") == ("y", pytest.approx(35.0))
    x_flip = {"blank_zones": {"t": {**bare["blank_zones"]["t"], "flip_axis_x_mm": 60.0}}}
    assert temple_flip_line(x_flip, "t") == ("x", 60.0)
    assert temple_flip_line(FIXTURE, "nowhere") == ("y", None)
    assert temple_flip_line({}, "temple_right") == ("y", None)


def test_the_anterior_relief_is_the_outer_face_turned_over_its_length():
    from guildmodel.core.cam.two_sided import temple_anterior_relief
    from guildmodel.core.relief.flat import build_temple_relief
    outline = box(-70.0, -6.0, 70.0, 6.0)
    t = TempleParams()
    relief = build_temple_relief(outline, t, [], [], resolution=0.5)
    T = t.blank_thickness_mm
    # a seat's worth taken off the outer face, off the center line
    a = np.zeros_like(relief.field.z)
    r, c = relief.field.world_to_pixel(-40.0, 3.0)
    a[r - 2:r + 3, c - 2:c + 3] = 0.8
    relief.anterior = a
    ra = temple_anterior_relief(relief, outline, T, mirror="y", mirror_at=0.0)
    assert ra.field.z.shape == relief.field.z.shape
    assert float(np.nanmax(ra.field.z)) == pytest.approx(T)
    # the dip is at the same end, its Y mirrored, measured down from the outer face
    assert ra.field.z[ra.field.world_to_pixel(-40.0, -3.0)] == pytest.approx(T - 0.8)
    assert ra.field.z[ra.field.world_to_pixel(-40.0, 3.0)] == pytest.approx(T)
    assert ra.inside[ra.field.world_to_pixel(0.0, 0.0)]
    assert ra.partition.body.bounds == pytest.approx(outline.bounds)   # symmetric about y = 0
    # the front's flip, when a zone asks for it: X mirrored
    rx = temple_anterior_relief(relief, outline, T, mirror="x", mirror_at=0.0)
    assert rx.field.z[rx.field.world_to_pixel(40.0, 3.0)] == pytest.approx(T - 0.8)
    assert rx.field.z[rx.field.world_to_pixel(-40.0, 3.0)] == pytest.approx(T)


def test_the_flip_pause_names_the_face_and_the_line():
    from guildmodel.core.cam.two_sided import flip_pause_text
    temple = Setup(side="posterior", wcs="G54", program="temple_cut.nc", flip="manual",
                   part="temple", mirror="y", flip_axis_y_mm=71.781, reprobe=["Z"])
    assert flip_pause_text(temple) == (
        "Flip stock and re-register on dowel pins; hinge face up; "
        "flip about machine Y 71.781 mm, over its length; then G54; re-probe Z")
    assert temple.flip_line_mm == 71.781 and temple.mirror_at_mm == 0.0
    front = Setup(side="posterior", flip="manual", flip_axis_x_mm=201.146)
    assert flip_pause_text(front) == (
        "Flip stock and re-register on dowel pins; front face down on the bed; "
        "flip about machine X 201.146 mm; then G54")
    # a sheet from 2.0 reads with the front's flip
    old = Setup.model_validate({"side": "posterior", "flip": "manual", "flip_axis_x_mm": 201.146})
    assert old.part == "front" and old.mirror == "x" and old.flip_line_mm == 201.146


def test_temple_programs_come_as_two_files_or_one():
    from guildmodel.gui.app import temple_programs
    assert temple_programs({}) == (None, None)
    assert temple_programs({"temple_cut.nc": "P"}) == ("P", None)
    assert temple_programs({"temple_cut.nc": "P", "temple_anterior_cut.nc": "A"}) == ("P", "A")
    one = ("; Side: Anterior Cut\nG55\nG1 X1\nM0 (Flip stock)\n"
           "; Side: Temple (after the flip)\nG54\nG1 X2\nM30\n")
    posterior, anterior = temple_programs({"temple_two_sided_cut.nc": one})
    assert anterior.startswith("; Side: Anterior Cut") and "G1 X2" not in anterior
    assert posterior.startswith("G90\nG21\nG17\n; Side: Temple") and "G1 X1" not in posterior


def test_two_sided_is_auto_for_the_front_and_the_temples(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind, ProjectSchema
    assert CastleCamParams().two_sided == "auto"
    assert ProjectSchema().cam_params.two_sided == "auto"
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    for kind in (ComponentKind.FRAME_FRONT, ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        p.set_component_kind(kind)
        assert p.two_sided.currentIndex() == 0
        assert p.two_sided.currentText().startswith("Auto")
        assert p.cam_params().two_sided == "auto"
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    assert "outer face" in p.two_sided.currentText()
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    assert "front face" in p.two_sided.currentText()


def _seated_temple():
    """A temple with one seat on its outer face, off the center line."""
    from guildmodel.core.geometry.inlays import ordered, reconcile
    outline = box(-70.0, -6.0, 70.0, 6.0)
    hinge = box(55.0, -3.0, 65.0, 3.0)
    seat = box(-50.0, -4.0, -30.0, 2.0)
    polys = ordered([seat], [])
    t = TempleParams(snap_to_blank_end=False)
    t.inlays = reconcile([], polys, [])
    assert t.inlays[0].face == "anterior"
    return outline, [hinge], polys, t


def _post(cam, outline, hinges, polys, t):
    from guildmodel.gui.app import GCodeWorker
    done, errs = [], []
    w = GCodeWorker(outline, None, {"material_name": "acetate"}, cam_params=cam,
                    hinge_polys=hinges, inlay_polys=polys, temple=t, is_temple=True)
    w.finished.connect(lambda s, rows: done.append((s, rows)))
    w.error.connect(errs.append)
    w.run()
    assert errs == [], errs[0] if errs else ""
    return w


def _simulate(outline, hinges, polys, t, program, anterior, setup):
    from guildmodel.gui.app import FlatSimWorker
    done, errs = [], []
    w = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinges,
                      inlay_polys=polys, cam_params=CastleCamParams(), resolution=0.3,
                      program_text=program, anterior_program_text=anterior,
                      anterior_setup=setup)
    w.finished.connect(lambda r, lines, plan: done.append((r, lines, plan)))
    w.error.connect(errs.append)
    w.run()
    assert errs == [], errs[0] if errs else ""
    return done[0]


def test_the_temple_simulation_plays_both_setups_with_the_flip_between(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import temple_programs
    outline, hinges, polys, t = _seated_temple()
    w = _post(CastleCamParams(), outline, hinges, polys, t)
    assert set(w.programs) == {"temple_anterior_cut.nc", "temple_cut.nc"}
    posterior, anterior = temple_programs(w.programs)
    setup_a = next(s for s in w.setup_dict["setups"] if s["side"] == "anterior")
    assert setup_a["mirror"] == "y" and setup_a["part"] == "temple"

    report, lines, plan = _simulate(outline, hinges, polys, t, posterior, anterior, setup_a)
    assert getattr(plan, "is_setups", False) and len(plan.plans) == 2
    assert plan.names == ["Anterior", ""]
    # the flip turns the blank over its length: about a line along X through
    # the blank's center line, at half its thickness
    assert len(plan.flips) == 1
    assert plan.flips[0]["axis"] == "x"
    assert plan.flips[0]["point"] == pytest.approx((0.0, 0.0, t.blank_thickness_mm / 2.0))
    assert "over its length" in plan.flips[0]["label"]
    assert plan.flip_indices == [plan.plans[0].n_positions]
    assert any(ln.startswith("Anterior:") for ln in lines)
    assert any(ln.startswith("Posterior:") for ln in lines)
    assert report.status() in {"ok", "warn"}, lines
    assert not any("Anterior: the cut is incomplete" in f for f in report.faults)
    # the seat is cut on the outer face, which lies on the bed for the temple
    # program: the final stock's underside is raised a seat's depth there,
    # at the seat's own place in the design frame, and nowhere else
    final = plan.plans[-1].keyframes[-1][1]
    ox, oy = final.origin
    res = final.resolution

    def under(x, y):
        r, c = int(round((y - oy) / res)), int(round((x - ox) / res))
        return float(np.nan_to_num(final.z_bot[-1][r, c], nan=0.0))

    assert under(-40.0, -1.0) == pytest.approx(1.0, abs=0.05)
    assert under(-40.0, 4.5) == pytest.approx(0.0, abs=0.05)
    assert under(0.0, 0.0) == pytest.approx(0.0, abs=0.05)

    # one file: split and simulated the same
    one = _post(CastleCamParams(two_sided_output="one_file"), outline, hinges, polys, t)
    assert set(one.programs) == {"temple_two_sided_cut.nc"}
    posterior1, anterior1 = temple_programs(one.programs)
    assert posterior1 and anterior1
    report1, lines1, plan1 = _simulate(outline, hinges, polys, t, posterior1, anterior1,
                                       next(s for s in one.setup_dict["setups"]
                                            if s["side"] == "anterior"))
    assert getattr(plan1, "is_setups", False) and plan1.flips[0]["axis"] == "x"
    assert report1.status() == report.status()

    # the temple program alone, as before: one plan, no flip
    report0, lines0, plan0 = _simulate(outline, hinges, polys, t, posterior, None, None)
    assert not getattr(plan0, "is_setups", False)
    assert not any(ln.startswith("Anterior:") for ln in lines0)
