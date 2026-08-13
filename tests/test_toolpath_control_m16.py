"""Toolpath control: holding strategy, cut direction, lead-in, per-op enable,
per-component CAM overrides (BUILDPLAN M16).

The four gaps the M15 audit found and deliberately did not close, closed here.
Each was a decision the program made *for* the maker with no way to say otherwise:

  * the part was always held by an onion skin — `cam/tabs.py` had existed since
    the first milestone, wired only to the legacy no-SCULPT profile fallback;
  * every contour ran climb, hardcoded in `contour_op`;
  * every through-cut pass took the ramped lead-in, and a zero ramp angle asked
    for the *opposite* (ramp the whole lap), so a straight entry was unreachable;
  * a program was all-or-nothing — `op_tools` picked a tool per operation but
    nothing could leave one out;
  * `cam_params` was project-global, so a base-curve block in acetal inherited
    the acetate frame's depth per pass.
"""
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon

from guildmodel.core.cam.block_ops import generate_block_program
from guildmodel.core.cam.castle_ops import (
    NoOperationsError, contour_op, contour_passes, require_ops,
    tab_height_for, tab_height_warning,
)
from guildmodel.core.cam.component import resolve_component_cam
from guildmodel.core.cam.temple_ops import generate_temple_program
from guildmodel.core.post.machine import load_machine_profile
from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleCamParams, Component, ComponentCamOverrides,
    ComponentKind, HoldingParams, TempleParams,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())

OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
SQUARE = Polygon([(-20, -20), (20, -20), (20, 20), (-20, 20)])


def _op(ops, name):
    return next(op for op in ops if op.name == name)


def _all_z(op):
    return [p[2] for path in op.paths for p in path]


def _ring_is_ccw(path):
    return bool(sum(path[i][0] * path[i + 1][1] - path[i + 1][0] * path[i][1]
                    for i in range(len(path) - 1)) > 0)


# ------------------------------------------------------------- holding strategy

def test_skin_is_the_default_and_stops_above_the_bottom():
    t = TempleParams()
    assert t.holding.strategy == "skin"
    prof = _op(generate_temple_program(OUTLINE, [], t, TOOLS), "Temple Profile")
    assert min(_all_z(prof)) == pytest.approx(t.onion_skin_mm)


def test_tabs_cut_through_to_the_bottom_face():
    t = TempleParams(holding=HoldingParams(strategy="tabs"))
    prof = _op(generate_temple_program(OUTLINE, [], t, TOOLS), "Temple Profile")
    assert min(_all_z(prof)) == pytest.approx(0.0)


def test_tabs_never_cut_below_the_bottom_face():
    """The fixture's blank zone and hold-down screws live under the stock — a
    through-cut that dives past z=0 cuts the fixture, not the part."""
    for strat in ("skin", "tabs"):
        t = TempleParams(holding=HoldingParams(strategy=strat, tab_height_mm=2.0))
        for op in generate_temple_program(OUTLINE, [], t, TOOLS):
            assert min(_all_z(op)) >= -1e-9, (strat, op.name)


def test_the_last_pass_rises_over_each_tab():
    h = HoldingParams(strategy="tabs", tab_count=4, tab_height_mm=1.0)
    prof = _op(generate_temple_program(
        OUTLINE, [], TempleParams(holding=h), TOOLS), "Temple Profile")
    last = prof.paths[-1]
    zs = [p[2] for p in last]
    assert min(zs) == pytest.approx(0.0)          # cutting through between tabs
    assert max(zs) == pytest.approx(1.0)          # riding over the bridges
    # four bridges → four separate runs at tab height
    risen = [z > 0.5 for z in zs]
    groups = sum(1 for a, b in zip(risen, risen[1:]) if not a and b)
    assert groups == 4


def test_only_the_last_pass_is_tabbed():
    """The passes above the tab tops would be cutting air at tab height."""
    h = HoldingParams(strategy="tabs", tab_count=4, tab_height_mm=1.0)
    prof = _op(generate_temple_program(
        OUTLINE, [], TempleParams(holding=h), TOOLS), "Temple Profile")
    for path in prof.paths[:-1]:
        assert len({round(p[2], 6) for p in path}) == 1, "a depth pass is not flat"


def test_zero_tab_count_falls_back_to_a_plain_through_cut():
    h = HoldingParams(strategy="tabs", tab_count=0)
    prof = _op(generate_temple_program(
        OUTLINE, [], TempleParams(holding=h), TOOLS), "Temple Profile")
    # tabs_on() is False, so this is the skin strategy's stack — stopping at the skin
    assert min(_all_z(prof)) == pytest.approx(TempleParams().onion_skin_mm)


def test_inside_contours_never_get_tabs():
    """A tabbed waste slug is a loose piece for the cutter to catch; the eyewire /
    hole slug drops into the fixture either way, so inside cuts keep the skin."""
    ring = Polygon([(-60, -5), (60, -5), (60, 5), (-60, 5)],
                   [[(-10, -2), (10, -2), (10, 2), (-10, 2)]])
    t = TempleParams(holding=HoldingParams(strategy="tabs"))
    ops = generate_temple_program(ring, [], t, TOOLS)
    holes = _op(ops, "Holes")
    assert min(_all_z(holes)) == pytest.approx(t.onion_skin_mm)
    assert min(_all_z(_op(ops, "Temple Profile"))) == pytest.approx(0.0)


def test_tab_height_cannot_exceed_the_final_pass_depth():
    """The pass above has already removed everything higher, so a 3 mm tab under a
    1.5 mm final pass is a 1.5 mm tab whatever the G-code claims."""
    passes = contour_passes(4.0, 0.0, 1.5)             # [2.5, 1.0, 0.0]
    assert tab_height_for(passes, 4.0, 3.0) == pytest.approx(1.0)
    assert tab_height_for(passes, 4.0, 0.5) == pytest.approx(0.5)
    assert tab_height_warning(passes, 4.0, 3.0) is not None
    assert tab_height_warning(passes, 4.0, 0.5) is None


def test_tabbed_toolpath_respects_the_clamped_tab_height():
    h = HoldingParams(strategy="tabs", tab_height_mm=3.0)
    prof = _op(generate_temple_program(
        OUTLINE, [], TempleParams(holding=h), TOOLS), "Temple Profile")
    last = prof.paths[-1]                              # the tabbed pass
    assert max(p[2] for p in last) == pytest.approx(1.0)    # clamped, not 3.0


def test_block_and_frame_carry_the_strategy_too():
    b = BaseCurveBlockParams(holding=HoldingParams(strategy="tabs"))
    ops = generate_block_program(SQUARE, b, TOOLS, CastleCamParams())
    assert min(_all_z(_op(ops, "Block Profile"))) == pytest.approx(0.0)


# --------------------------------------------------------------- cut direction

def test_climb_is_the_default_and_conventional_reverses_every_ring():
    climb = _op(generate_temple_program(
        OUTLINE, [], TempleParams(), TOOLS,
        params=CastleCamParams(cut_direction="climb")), "Temple Profile")
    conv = _op(generate_temple_program(
        OUTLINE, [], TempleParams(), TOOLS,
        params=CastleCamParams(cut_direction="conventional")), "Temple Profile")
    assert CastleCamParams().cut_direction == "climb"
    # outside contour: climb runs CW, conventional CCW
    assert not _ring_is_ccw(climb.paths[0])
    assert _ring_is_ccw(conv.paths[0])
    # same geometry, opposite direction — a pure reversal, not a different path
    assert len(climb.paths) == len(conv.paths)
    assert {(round(p[0], 6), round(p[1], 6)) for p in climb.paths[0]} == \
           {(round(p[0], 6), round(p[1], 6)) for p in conv.paths[0]}


def test_direction_flips_inside_contours_the_other_way():
    """Inside and outside must stay opposite, or the wall finish is inconsistent."""
    for direction, want_inside_ccw in (("climb", True), ("conventional", False)):
        params = CastleCamParams(cut_direction=direction)
        op = contour_op("Eyewires", [SQUARE], "inside", 1.5, 0.1, 6.0, 0.4, params)
        assert _ring_is_ccw(op.paths[0]) is want_inside_ccw, direction


# ------------------------------------------------------------------- lead-in

def test_plunge_lead_in_emits_no_ramp():
    """A zero ramp ANGLE means "ramp the whole lap" — the opposite request — so
    before this control a straight entry was unreachable."""
    from guildmodel.core.cam.castle_ops import build_tool_settings, write_castle_program
    from guildmodel.core.post.grbl import GRBLPost

    def post_with(lead_in):
        ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS)
        ts, _ = build_tool_settings(ops, TOOLS, default_feed=1200,
                                    default_plunge=450, default_spindle=10000)
        post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                        spindle_rpm=10000, feed_rate_mmpm=1200, plunge_rate_mmpm=450,
                        safe_z_mm=9.0, feed_plane_mm=5.0)
        write_castle_program(ops, post, side="Temple", arc_tol_mm=0.0,
                             contour_op_names={"Temple Profile"},
                             tool_settings=ts, contour_lead_in=lead_in)
        return post.to_string()

    ramped, plunged = post_with("ramp"), post_with("plunge")

    import re
    _WORD = re.compile(r"([XYZ])(-?\d+\.?\d*)")

    def ramping_moves(nc):
        """Feed moves that descend *while* traveling in XY — the signature of a
        ramp. Every cutting move carries a Z word, so the discriminator has to be
        a Z that CHANGES across a move that also changes X or Y."""
        n, z = 0, None
        for line in nc.splitlines():
            if not line.startswith("G1 "):
                continue
            got = {k: float(v) for k, v in _WORD.findall(line)}
            if "Z" in got:
                moved_xy = "X" in got or "Y" in got
                if z is not None and abs(got["Z"] - z) > 1e-9 and moved_xy:
                    n += 1
                z = got["Z"]
        return n

    assert ramping_moves(ramped) > 0
    assert ramping_moves(plunged) == 0
    assert len(plunged) < len(ramped)          # and it is the shorter program


def test_lead_in_defaults_to_ramp():
    assert CastleCamParams().contour_lead_in == "ramp"


# --------------------------------------------------------- per-operation enable

def test_ops_are_all_enabled_by_default_and_old_projects_load_unchanged():
    cam = CastleCamParams()
    assert cam.op_enabled == {}
    assert cam.is_op_enabled("Perimeter") and cam.is_op_enabled("anything")


def test_disabling_an_op_removes_it_from_the_program():
    full = generate_temple_program(OUTLINE, [(-40, 0), (-20, 0)] and
                                   [[(-40, 0), (-20, 0)]], TempleParams(), TOOLS)
    assert {op.name for op in full} == {"Engraving", "Temple Profile"}
    without = generate_temple_program(
        OUTLINE, [[(-40, 0), (-20, 0)]], TempleParams(), TOOLS,
        params=CastleCamParams(op_enabled={"Engraving": False}))
    assert {op.name for op in without} == {"Temple Profile"}


def test_disabling_the_profile_leaves_the_part_in_the_blank():
    ops = generate_temple_program(
        OUTLINE, [], TempleParams(), TOOLS,
        params=CastleCamParams(op_enabled={"Temple Profile": False}))
    assert ops == []


def test_block_ops_can_be_skipped_individually():
    b = BaseCurveBlockParams()
    ops = generate_block_program(SQUARE, b, TOOLS,
                                 CastleCamParams(op_enabled={"Drill Holes": False}))
    assert [op.name for op in ops] == ["Block Profile"]


def test_an_empty_program_raises_a_sentence_not_an_indexerror():
    """The posting paths index `ops[0]` for the first tool — switching everything
    off used to surface as an IndexError traceback."""
    with pytest.raises(NoOperationsError) as exc:
        require_ops([], "This temple")
    assert "This temple" in str(exc.value)
    assert "switched off" in str(exc.value)
    assert require_ops(["op"]) == ["op"]


# ------------------------------------------------- per-component CAM overrides

def test_empty_overrides_change_nothing():
    cam = CastleCamParams(contour_stepdown_mm=1.5)
    ov = ComponentCamOverrides()
    assert ov.is_empty()
    assert ov.apply(cam) is cam


def test_overrides_layer_onto_the_project_params():
    cam = CastleCamParams(contour_stepdown_mm=1.5, cut_direction="climb")
    out = ComponentCamOverrides(contour_stepdown_mm=0.6,
                                cut_direction="conventional").apply(cam)
    assert out.contour_stepdown_mm == 0.6
    assert out.cut_direction == "conventional"
    assert cam.contour_stepdown_mm == 1.5          # the project params are untouched


def test_material_is_not_applied_as_a_cam_field():
    """`material` selects the preset the post clamps against; it is not a field on
    CastleCamParams, and pushing it there would raise."""
    out = ComponentCamOverrides(material="acetal").apply(CastleCamParams())
    assert not hasattr(out, "material")


def test_a_block_in_acetal_is_clamped_by_acetal_not_the_project_material():
    """The audit finding: the standard job is acetate parts plus acetal forming
    blocks, and acetal's depth-of-cut ceiling is half acetate's."""
    machine = load_machine_profile("guild_cnc", CONFIG)
    project_cam = CastleCamParams(contour_stepdown_mm=2.0)   # fine for acetate

    frame = Component(id="f", kind=ComponentKind.FRAME_FRONT)
    cam_f, _c, mat_f, name_f = resolve_component_cam(
        project_cam, frame, machine=machine, mats_cfg=MATS, material_name="acetate")
    assert name_f == "acetate"
    assert cam_f.contour_stepdown_mm == pytest.approx(2.0)

    block = Component(id="b", kind=ComponentKind.BASE_CURVE_RIGHT,
                      cam_overrides=ComponentCamOverrides(material="acetal"))
    cam_b, clamp_b, mat_b, name_b = resolve_component_cam(
        project_cam, block, machine=machine, mats_cfg=MATS, material_name="acetate")
    assert name_b == "acetal"
    assert mat_b["max_doc_mm"] == 2.0
    assert cam_b.contour_stepdown_mm <= mat_b["max_doc_mm"]


def test_overrides_reach_the_component_generator():
    from guildmodel.core.cam.component import ComponentGeometry, build_component_ops

    comp = Component(id="t", kind=ComponentKind.TEMPLE_RIGHT,
                     cam_overrides=ComponentCamOverrides(contour_stepdown_mm=0.5))
    prog = build_component_ops(
        comp, ComponentGeometry(outline=OUTLINE), TOOLS,
        cam_params=CastleCamParams(contour_stepdown_mm=2.0))
    depths = {round(p[2], 3) for op in prog.ops if op.name == "Temple Profile"
              for path in op.paths for p in path}
    assert len(depths) >= 7        # 3.6 mm at 0.5 mm, not at 2.0 mm


def test_component_round_trips_its_overrides():
    comp = Component(id="b", kind=ComponentKind.BASE_CURVE_LEFT,
                     cam_overrides=ComponentCamOverrides(material="acetal",
                                                         contour_stepdown_mm=0.9))
    again = Component(**comp.model_dump())
    assert again.cam_overrides.material == "acetal"
    assert again.cam_overrides.contour_stepdown_mm == 0.9
    # a component saved before M16 has no overrides key and must still load
    raw = comp.model_dump()
    raw.pop("cam_overrides")
    assert Component(**raw).cam_overrides.is_empty()


# ------------------------------------------------ insert_tabs, rewritten (M16)

def test_tabs_survive_long_straight_segments():
    """The bug wiring tabs to a real contour exposed: two tabs falling on one
    segment merged into a single raised run, because the drop back to cutting
    depth between them was only emitted at the segment's END. On a buffered
    profile — 140 mm straight runs — four 3 mm tabs became two 80 mm ones."""
    from guildmodel.core.cam.tabs import insert_tabs

    # one long segment per side: exactly the shape of a buffered profile
    ring = [(-70, -6), (70, -6), (70, 6), (-70, 6), (-70, -6)]
    out = insert_tabs(ring, 4, 3.0, 1.0, 0.0)
    risen = [z > 0.5 for _, _, z in out]
    assert sum(1 for a, b in zip(risen, risen[1:]) if not a and b) == 4


def test_tab_boundary_on_a_vertex_does_not_swallow_later_tabs():
    """The other half of the same defect: an event landing exactly on a vertex was
    skipped, and the cursor stalled on it, dropping every tab after it."""
    from guildmodel.core.cam.tabs import insert_tabs

    # vertices every 10 mm on a 400 mm loop: tab centers land squarely on them
    ring = [(float(d), 0.0) for d in range(0, 201, 10)] + \
           [(float(d), 10.0) for d in range(200, -1, -10)] + [(0.0, 0.0)]
    out = insert_tabs(ring, 4, 4.0, 1.0, 0.0)
    risen = [z > 0.5 for _, _, z in out]
    assert sum(1 for a, b in zip(risen, risen[1:]) if not a and b) == 4


def test_tab_width_is_independent_of_point_spacing():
    """A tab must come out the same size on a coarse path and a dense one."""
    from guildmodel.core.cam.tabs import insert_tabs

    def flat_run_mm(pts):
        out = insert_tabs(pts, 1, 6.0, 1.0, 0.0)
        run, prev = 0.0, None
        for x, y, z in out:
            if prev is not None and z > 0.99 and prev[2] > 0.99:
                run += ((x - prev[0]) ** 2 + (y - prev[1]) ** 2) ** 0.5
            prev = (x, y, z)
        return run

    coarse = [(0.0, 0.0), (100.0, 0.0)]
    dense = [(float(d) / 2, 0.0) for d in range(0, 201)]
    assert flat_run_mm(coarse) == pytest.approx(6.0, abs=0.05)
    assert flat_run_mm(dense) == pytest.approx(6.0, abs=0.05)


def test_tabs_never_overlap_however_extreme_the_settings():
    """A tab wider than its own spacing would leave one continuous uncut rim —
    the part held by everything instead of by tabs."""
    from guildmodel.core.cam.tabs import insert_tabs

    out = insert_tabs([(0.0, 0.0), (40.0, 0.0)], 4, 999.0, 1.0, 0.0)
    heights = [z for _, _, z in out]
    assert min(heights) == pytest.approx(0.0)     # it still comes back down
    risen = [z > 0.5 for z in heights]
    assert sum(1 for a, b in zip(risen, risen[1:]) if not a and b) == 4


def test_zero_tabs_returns_a_flat_pass():
    from guildmodel.core.cam.tabs import insert_tabs
    out = insert_tabs([(0.0, 0.0), (10.0, 0.0)], 0, 3.0, 1.0, 0.4)
    assert out == [(0.0, 0.0, 0.4), (10.0, 0.0, 0.4)]


# ------------------------------------------------------------------ the panel

def _panel(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


def test_panel_round_trips_every_new_control(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    cam = CastleCamParams(cut_direction="conventional", contour_lead_in="plunge",
                          op_enabled={"Perimeter": False})
    p.set_cam_params(cam)
    out = p.cam_params()
    assert out.cut_direction == "conventional"
    assert out.contour_lead_in == "plunge"
    assert out.is_op_enabled("Perimeter") is False
    assert out.is_op_enabled("Eyewires") is True

    h = HoldingParams(strategy="tabs", tab_count=6, tab_width_mm=2.5, tab_height_mm=0.8)
    p.set_holding_params(h)
    assert p.holding_params() == h

    ov = ComponentCamOverrides(material="acetal", contour_stepdown_mm=0.9)
    p.set_cam_overrides(ov)
    assert p.cam_overrides().material == "acetal"
    assert p.cam_overrides().contour_stepdown_mm == 0.9


def test_ramp_angle_grays_out_on_a_plunge_lead_in(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    p.contour_lead_in.setCurrentIndex(1)               # Plunge
    assert not p.contour_ramp_angle.isEnabled()
    p.contour_lead_in.setCurrentIndex(0)               # Ramp
    assert p.contour_ramp_angle.isEnabled()


def test_operations_list_is_kind_aware(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    p.show()
    p.set_component_kind(ComponentKind.BASE_CURVE_RIGHT)
    p.setCurrentIndex(p._tab_cut)                  # the group lives on the Cut tab
    assert p.op_checks["Drill Holes"].isVisible()
    assert not p.op_checks["Eyewires"].isVisible()
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    p.setCurrentIndex(p._tab_cut)
    assert p.op_checks["Eyewires"].isVisible()
    assert not p.op_checks["Drill Holes"].isVisible()


def test_effective_cam_params_applies_the_active_overrides(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    p.set_cam_params(CastleCamParams(contour_stepdown_mm=1.5))
    p.set_cam_overrides(ComponentCamOverrides(material="acetal",
                                              contour_stepdown_mm=0.6))
    assert p.effective_cam_params().contour_stepdown_mm == 0.6
    assert p.effective_material_name() == "acetal"
    # …and with no overrides the component inherits the project's
    p.set_cam_overrides(None)
    assert p.effective_cam_params().contour_stepdown_mm == 1.5
    assert p.effective_material_name() == p.material_name()
