"""The UI housekeeping round of 2026-11-02.

Users found controls that did nothing, controls shown twice, and a sidebar
that vanished when the window was minimized and restored. Each test here
pins one of those: the sidebar's wiring, the Program Zero group without its
dead *Fixture* mode and with the shifts that replace it, and the Cut and
Machine tabs showing one control per setting, the active part's.
"""
import os

import pytest


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _new_window():
    """A window, built where the gui marker's scan can see it."""
    from guildmodel.gui.app import MainWindow
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


@pytest.fixture
def window_env(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)
    return None


def _panel(qapp, tmp_path, monkeypatch):
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


# ------------------------------------------------------------- the sidebar


@pytest.mark.gui
def test_sidebar_survives_the_window_hidden_and_shown(qapp, window_env):
    """Minimizing the window hides its children without `hide()` being called
    on them; Qt still reports each dock not-visible. The Parameters action
    used to take that as the maker's word and hide the dock for real, so the
    restored window had no sidebar. `hide()` + `show()` on the window sends
    the same Hide and Show events the minimize does."""
    win = _new_window()
    win.show()
    qapp.processEvents()
    assert not win._right_dock.isHidden()
    assert win._act_sidebar.isChecked()

    win.hide()
    qapp.processEvents()
    assert not win._right_dock.isHidden(), "the dock was hidden for real"
    assert win._act_sidebar.isChecked(), "the action unchecked itself"

    win.show()
    qapp.processEvents()
    assert win._right_dock.isVisible()
    assert win._act_sidebar.isChecked()
    win.close()


@pytest.mark.gui
def test_sidebar_survives_minimize_and_restore(qapp, window_env):
    """The user's own steps; the offscreen platform sends the dock the same
    not-visible / visible pair a desktop does."""
    win = _new_window()
    win.show()
    qapp.processEvents()
    win.showMinimized()
    qapp.processEvents()
    assert not win._right_dock.isHidden()
    win.showNormal()
    qapp.processEvents()
    assert win._right_dock.isVisible()
    assert win._act_sidebar.isChecked()
    win.close()


@pytest.mark.gui
def test_sidebar_action_still_hides_and_shows_the_dock(qapp, window_env):
    win = _new_window()
    win.show()
    qapp.processEvents()
    win._act_sidebar.trigger()                     # a click: off
    qapp.processEvents()
    assert win._right_dock.isHidden()
    assert not win._act_sidebar.isChecked()
    win.hide(); win.show()                         # the window round trip keeps it off
    qapp.processEvents()
    assert win._right_dock.isHidden()
    assert not win._act_sidebar.isChecked()
    win._act_sidebar.trigger()                     # a click: on
    qapp.processEvents()
    assert win._right_dock.isVisible()
    assert win._act_sidebar.isChecked()
    win.close()


# ------------------------------------------------------------ Program Zero


def _stock():
    from guildmodel.core.project.schema import StockDefinition
    return StockDefinition()


def test_a_parts_fixture_zero_reads_as_the_default_datum():
    """*Fixture (design frame)* was the identity offset, the same program as
    the default stock-box datum with the lists grayed (GitHub issue #1,
    BUILDPLAN §11c). A part's `fixture` reads as that datum everywhere a part
    is read; the Worktable keeps `fixture` as raw bed coordinates."""
    from guildmodel.core.project.schema import (
        CastleCamParams, Component, ComponentKind, ProgramZero, Worktable, part_program_zero)
    cam = CastleCamParams(program_zero={"mode": "fixture", "x_ref": "right", "z_ref": "top"})
    assert cam.program_zero == ProgramZero()
    comp = Component(id="f", kind=ComponentKind.FRAME_FRONT,
                     program_zero=ProgramZero(mode="fixture"))
    assert comp.program_zero == ProgramZero()
    assert part_program_zero({"mode": "stock_box", "x_ref": "left"}) == {
        "mode": "stock_box", "x_ref": "left"}
    wt = Worktable(program_zero=ProgramZero(mode="fixture"))
    assert wt.program_zero.mode == "fixture"
    assert wt.bed_work_offset() == (0.0, 0.0, 0.0)


def test_a_fixture_project_posts_the_same_program(tmp_path):
    """The gate §11c.2 asks for: a project saved with `fixture` posts
    byte-identical to 2.0.0, which posted it as the identity offset."""
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import CastleCamParams, ProgramZero, ProjectSchema
    proj = ProjectSchema(job_name="fixture")
    proj.cam_params = CastleCamParams()
    path = tmp_path / "fixture.gmodel"
    save_gmodel(path, project=proj, dxf_bytes=b"dxf")
    # the 2.0.0 file: rewrite the stored zero as fixture mode
    import json, zipfile
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        raw = {n: z.read(n) for n in names}
    pj = next(n for n in names if n.endswith("project.json"))
    doc = json.loads(raw[pj])
    doc["cam_params"]["program_zero"] = {"mode": "fixture", "x_ref": "right",
                                         "y_ref": "top", "z_ref": "top"}
    raw[pj] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, raw[n])
    pz = load_gmodel(path, verify=False).project.cam_params.program_zero   # the hashes are 2.0.0's
    assert pz.mode == "stock_box"
    assert pz.work_offset(_stock()) == (0.0, 0.0, 0.0) == ProgramZero(mode="fixture").work_offset(_stock())
    assert "top face" not in pz.label()          # GuildSend reads the face from the label


def test_the_shift_moves_the_zero_from_the_datum():
    """A pin 10 mm left of the blank's lower-left corner, and a 6 mm spacer
    under the blank with Z0 on the spoilboard."""
    from guildmodel.core.project.schema import ProgramZero, Worktable
    s = _stock()
    pz = ProgramZero(x_ref="left", y_ref="bottom", z_ref="bottom",
                     shift_x_mm=-10.0, shift_z_mm=-6.0)
    assert pz.datum_world(s) == (-95.0, -42.5, -6.0)
    assert pz.work_offset(s) == (95.0, 42.5, 6.0)
    assert pz.is_shifted() and not ProgramZero().is_shifted()
    assert pz.label() == "Stock blank lower-left, bottom face, shifted (-10.00, +0.00, -6.00) mm"
    assert "top face" in ProgramZero(z_ref="top", shift_z_mm=1).label()
    # the bed's X/Y follow a shift too; its Z is never shifted (touched off on the stock)
    wt = Worktable(program_zero=ProgramZero(x_ref="left", y_ref="bottom", shift_x_mm=5.0,
                                            shift_z_mm=-6.0))
    assert wt.bed_work_offset() == (-5.0, 0.0, 0.0)


def test_the_shift_is_posted_as_a_translation():
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import ProgramZero
    off = ProgramZero(shift_x_mm=-10.0, shift_z_mm=-6.0).work_offset(_stock())
    base = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0)
    base.feed(x=1.0, y=2.0, z=-0.5)
    shifted = GRBLPost("z", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0, work_offset=off)
    shifted.feed(x=1.0, y=2.0, z=-0.5)
    g1 = lambda post: next(ln for ln in post.to_string().splitlines() if ln.startswith("G1 "))
    assert g1(base) == "G1 X1.0000 Y2.0000 Z-0.5000 F750"
    assert g1(shifted) == "G1 X11.0000 Y2.0000 Z5.5000 F750"


def test_the_shift_round_trips_through_gmodel_and_the_parts_prefs(tmp_path):
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import CastleCamParams, ProgramZero, ProjectSchema
    from guildmodel.gui import part_defaults
    pz = ProgramZero(x_ref="right", shift_y_mm=2.5, shift_z_mm=-6.0)
    proj = ProjectSchema(job_name="shift")
    proj.cam_params = CastleCamParams(program_zero=pz)
    path = tmp_path / "shift.gmodel"
    save_gmodel(path, project=proj, dxf_bytes=b"dxf")
    assert load_gmodel(path).project.cam_params.program_zero == pz
    prefs = {"part_defaults": {"frame_front": {"program_zero": part_defaults.sparse_zero(pz)}}}
    assert part_defaults.default_program_zero(prefs, "frame_front") == pz
    assert part_defaults.sparse_zero(ProgramZero()) is None
    # a 2.0.0 preference that says fixture reads as the default datum
    prefs = {"part_defaults": {"temple": {"program_zero": {"mode": "fixture"}}}}
    assert part_defaults.default_program_zero(prefs, "temple_right") == ProgramZero()


def test_the_dock_group_has_no_zero_mode_and_round_trips_the_shift(qapp, tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ProgramZero
    p = _panel(qapp, tmp_path, monkeypatch)
    assert not hasattr(p, "pz_mode")
    for cb in (p.pz_x, p.pz_y, p.pz_z):
        assert cb.isEnabled() and cb.toolTip()
    assert [p.pz_z.itemText(i) for i in range(p.pz_z.count())] == [
        "Top of the blank", "Bottom of the blank (the bed)"]
    pz = ProgramZero(x_ref="left", y_ref="top", z_ref="top", shift_x_mm=-10, shift_z_mm=-6)
    p._set_program_zero(pz)
    assert p._program_zero() == pz
    p._set_program_zero(ProgramZero(mode="fixture"))     # a 2.0.0 part
    assert p._program_zero() == ProgramZero()


def test_the_parts_page_picker_round_trips_the_shift(qapp, tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ProgramZero
    from guildmodel.gui.widgets.part_defaults_page import ZeroPicker
    _panel(qapp, tmp_path, monkeypatch)        # the stores, isolated
    pz = ProgramZero(x_ref="right", y_ref="bottom", shift_y_mm=3.0)
    pk = ZeroPicker(pz)
    assert pk.value() == pz
    assert not hasattr(pk, "mode")
    pk.set_value(ProgramZero(mode="fixture"))
    assert pk.value() == ProgramZero()


# ------------------------------------------------- the Cut and Machine tabs


def test_one_onion_skin_and_allowance_per_part_on_the_cut_tab(qapp, tmp_path, monkeypatch):
    """The Cut tab's rows were the front's and showed on every part, while the
    Temple and Base Curve tabs carried their own: a temple showed two onion
    skins, one of them dead. One widget each now, the active part's, read and
    restored with that part as the Holding group's are."""
    from guildmodel.core.project.schema import (
        BaseCurveBlockParams, CastleParams, ComponentKind, TempleParams)
    p = _panel(qapp, tmp_path, monkeypatch)
    for gone in ("temple_onion", "temple_allowance", "block_onion", "block_allowance"):
        assert not hasattr(p, gone)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.set_temple_params(TempleParams(onion_skin_mm=0.7, hand_finishing_allowance_mm=0.25))
    assert (p.onion_skin.value(), p.hand_allowance.value()) == (0.7, 0.25)
    t = p.temple_params()
    assert (t.onion_skin_mm, t.hand_finishing_allowance_mm) == (0.7, 0.25)
    p.set_component_kind(ComponentKind.BASE_CURVE_RIGHT)
    p.set_block_params(BaseCurveBlockParams(onion_skin_mm=0.3, hand_finishing_allowance_mm=0.05))
    b = p.block_params()
    assert (b.onion_skin_mm, b.hand_finishing_allowance_mm) == (0.3, 0.05)
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    p.set_castle_params(CastleParams(onion_skin_mm=0.5, hand_finishing_allowance_mm=0.15))
    c = p.castle_params()
    assert (c.onion_skin_mm, c.hand_finishing_allowance_mm) == (0.5, 0.15)
    # the skin sits with its strategy, and is grayed when the tabs hold the part
    assert p.onion_skin.isEnabled()
    p.hold_strategy.setCurrentIndex(1)
    assert not p.onion_skin.isEnabled() and p.hold_tab_count.isEnabled()
    p.hold_strategy.setCurrentIndex(0)
    assert p.onion_skin.isEnabled() and not p.hold_tab_count.isEnabled()


def test_controls_a_part_never_reads_are_hidden(qapp, tmp_path, monkeypatch):
    """The Machine tab's default tool is the front's (a temple and a block name
    their own tools) and hides on the other parts, by the rule of 2026-10-17;
    the two-sided setup is the front's and, since the temple's outer face is
    cut too (2026-11-02), the temple's, and hides on a block alone."""
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(qapp, tmp_path, monkeypatch)
    p.show()
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    assert not p.cam_tool.isHidden() and not p._cam_tool_label.isHidden()
    assert not p._two_sided_group.isHidden()
    assert p.two_sided.itemText(0) == "Auto (when the front face is cut)"
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    assert p.cam_tool.isHidden() and p._cam_tool_label.isHidden()
    assert not p._two_sided_group.isHidden()
    assert p.two_sided.itemText(0) == "Auto (when the outer face is cut)"
    assert not p.machine.isHidden()
    p.set_component_kind(ComponentKind.BASE_CURVE_LEFT)
    assert p.cam_tool.isHidden() and p._two_sided_group.isHidden()


def test_the_profile_fallback_group_is_gone_and_the_fallback_reads_the_shared_controls(
        qapp, tmp_path, monkeypatch):
    from guildmodel.core.project.schema import HoldingParams
    p = _panel(qapp, tmp_path, monkeypatch)
    assert "Profile fallback  (no SCULPT)" not in p._folds
    for gone in ("tool_profile", "stepdown_profile", "tab_count", "tab_width", "tab_height"):
        assert not hasattr(p, gone)
    # what the fallback worker is handed: the default tool, the Cut tab's
    # depth per pass and the Holding group
    from guildmodel.gui.app import MainWindow
    p.cam_tool.setCurrentText("flat_3175")
    p.contour_stepdown.setValue(1.2)
    p.onion_skin.setValue(0.3)
    p.set_holding_params(HoldingParams(strategy="skin", tab_count=4, tab_width_mm=3.0,
                                       tab_height_mm=1.0))
    fake = type("W", (), {"params": p})()
    got = MainWindow._collect_gcode_params(fake)
    assert got["profile_tool_name"] == "flat_3175"
    assert got["stepdown_profile"] == 1.2
    assert got["onion_skin"] == 0.3
    assert got["tab_count"] == 0                      # the skin holds the part
    p.set_holding_params(HoldingParams(strategy="tabs", tab_count=3, tab_width_mm=2.5,
                                       tab_height_mm=0.8))
    got = MainWindow._collect_gcode_params(fake)
    assert (got["tab_count"], got["tab_width"], got["tab_height"]) == (3, 2.5, 0.8)


def test_the_clearances_sit_on_machine_and_tool_under_the_beds_name(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFormLayout
    p = _panel(qapp, tmp_path, monkeypatch)
    form = p.safe_z_clearance.parentWidget().layout()
    assert isinstance(form, QFormLayout)
    labels = [form.itemAt(r, QFormLayout.ItemRole.LabelRole).widget().text()
              for r in range(form.rowCount())]
    assert labels == ["Machine:", "Tool:", "Safe-Z clearance:", "Hold-down height:"]
    assert form.labelForField(p.hold_down_height).text() == "Hold-down height:"
    assert p.machine.parentWidget() is p.safe_z_clearance.parentWidget()
    assert "Material && Allowance" in p._folds and "Material && Allowances" not in p._folds
