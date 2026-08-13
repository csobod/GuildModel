"""Depth-per-pass control across every component kind (BUILDPLAN M15).

The field report: a temple's G-code took the whole blank in one full-depth pass
and there was no way to change it. Three separate things caused that, and each
gets a test here.

  1. The requested depth per pass defaulted to 4.0 mm ("cut as deep as acetate
     allows", M12.4, never validated on the machine). A 4 mm temple blank with a
     0.4 mm onion skin is 3.6 mm of cut — one pass.
  2. The only widget that set it lived in the frame-only "Cut Strategy" group,
     which `set_component_kind` hid for temples and base-curve blocks. The value
     still reached the generator; the maker just could not see or change it.
  3. `_generate_temple` / `_generate_block` never ran `clamp_cam_to_machine`, so
     neither the machine's nor the material's depth-of-cut ceiling applied, and
     the post got an unclamped arc tolerance on top (the other half of
     INCIDENT-2026-07-29, which fixed only the worktable paths).

Blind pockets and engraving had the same shape of problem — the pocket floor was
cleared in one full-depth cascade no matter how deep, and an engraving groove was
one plunge to depth — so they are covered here too.
"""
from pathlib import Path

import yaml
from shapely.geometry import Polygon

from guildmodel.core.cam.block_ops import generate_block_program
from guildmodel.core.cam.castle_ops import (
    contour_passes, hinge_pocket_op, pocket_levels,
)
from guildmodel.core.cam.temple_ops import engrave_op, generate_temple_program
from guildmodel.core.post.machine import clamp_cam_to_machine, load_machine_profile
from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleCamParams, TempleParams,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())

OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
ENGRAVING = [[(-40, 0), (-30, 3), (-20, 0)]]
HINGE = [Polygon([(-60, -4), (-50, -4), (-50, 4), (-60, 4)])]


def _profile_paths(ops, name):
    return [p for op in ops if op.name == name for p in op.paths]


def _depths(paths):
    """The distinct Z levels a set of single-depth contour passes sits at."""
    return sorted({round(p[0][2], 6) for p in paths})


# ------------------------------------------------------- 1. the shipped defaults

def test_default_temple_blank_is_not_one_full_depth_pass():
    """The regression the field hit: a stock temple must not be a single pass."""
    t, cam = TempleParams(), CastleCamParams()
    passes = contour_passes(t.blank_thickness_mm, t.onion_skin_mm,
                            cam.contour_stepdown_mm)
    assert len(passes) > 1, "a default temple still cuts its whole depth in one pass"
    deepest = max(t.blank_thickness_mm - passes[0], cam.contour_stepdown_mm)
    assert deepest <= cam.contour_stepdown_mm + 1e-9


def test_shipped_acetate_doc_ceiling_is_conservative():
    """M12.4's 4.0 mm ceiling let a whole 4 mm blank through in one bite."""
    assert MATS["acetate"]["max_doc_mm"] <= 2.0
    assert MATS["acetate"]["contour_stepdown_mm"] <= 2.0
    # Every shipped material's everyday request stays inside its own ceiling.
    for name, mat in MATS.items():
        assert mat["contour_stepdown_mm"] <= mat["max_doc_mm"], name


def test_generated_temple_profile_has_several_depth_passes():
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS)
    depths = _depths(_profile_paths(ops, "Temple Profile"))
    assert len(depths) >= 3
    assert depths[0] == TempleParams().onion_skin_mm       # finishes at the skin
    # and no single pass bites deeper than the requested stepdown
    top = TempleParams().blank_thickness_mm
    steps = [a - b for a, b in zip([top] + depths[:0:-1], depths[::-1])]
    assert max(steps) <= CastleCamParams().contour_stepdown_mm + 1e-9


# ------------------------------------------- 2. the control reaches the generator

def test_stepdown_actually_changes_the_temple_pass_count():
    """The control must be live, not decorative — this is what the hidden widget
    prevented the maker from doing."""
    coarse = generate_temple_program(
        OUTLINE, [], TempleParams(), TOOLS, params=CastleCamParams(contour_stepdown_mm=2.0))
    fine = generate_temple_program(
        OUTLINE, [], TempleParams(), TOOLS, params=CastleCamParams(contour_stepdown_mm=0.5))
    assert (len(_depths(_profile_paths(fine, "Temple Profile")))
            > len(_depths(_profile_paths(coarse, "Temple Profile"))))


def test_block_profile_honors_the_stepdown_too():
    b = BaseCurveBlockParams()
    lens = Polygon([(-20, -15), (20, -15), (20, 15), (-20, 15)])
    ops = generate_block_program(lens, b, TOOLS, CastleCamParams(contour_stepdown_mm=1.0))
    depths = _depths(_profile_paths(ops, "Block Profile"))
    assert len(depths) >= 4                       # 4.7625 mm blank at 1.0 mm
    assert depths[0] == b.onion_skin_mm


# --------------------------------------------------------- 3. the clamp seam

def test_clamp_applies_the_material_ceiling_before_ops_are_built():
    """A maker who types 6 mm gets the material's ceiling, not 6 mm."""
    machine = load_machine_profile("guild_cnc", CONFIG)
    cam, clamp = clamp_cam_to_machine(
        CastleCamParams(contour_stepdown_mm=6.0), machine, MATS["acetate"])
    assert cam.contour_stepdown_mm == MATS["acetate"]["max_doc_mm"]
    assert any("stepdown" in w for w in clamp.warnings)
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS, params=cam)
    depths = _depths(_profile_paths(ops, "Temple Profile"))
    assert len(depths) > 1


def test_clamp_linearizes_on_a_controller_without_arcs():
    """The temple post used to be handed cam.arc_tolerance_mm directly, so a
    no-arc controller still received G2/G3."""
    machine = load_machine_profile("grbl_no_arc", CONFIG)
    _cam, clamp = clamp_cam_to_machine(
        CastleCamParams(arc_tolerance_mm=0.02), machine, MATS["acetate"])
    assert clamp.arc_tol_mm == 0.0


# ------------------------------------------------------------- blind pockets

def test_pocket_levels_end_exactly_on_the_floor():
    levels = pocket_levels(5.0, 1.0, 1.5)
    assert levels[-1] == 1.0
    assert all(a > b for a, b in zip(levels, levels[1:]))
    assert max(a - b for a, b in zip([5.0] + levels[:-1], levels)) <= 1.5 + 1e-9


def test_pocket_levels_degenerate_stepdown_does_not_hang():
    assert pocket_levels(5.0, 1.0, 0.0) == [1.0]
    assert pocket_levels(5.0, 1.0, -3.0) == [1.0]


def test_deep_pocket_is_cleared_in_levels_not_one_cascade():
    """The floor cascade used to run once, at full depth, however deep the pocket."""
    params = CastleCamParams(pocket_stepdown_mm=0.5)
    deep = hinge_pocket_op(HINGE, floor_z=1.0, start_z=6.5,
                           tool_radius_mm=1.0, params=params)
    shallow = hinge_pocket_op(HINGE, floor_z=6.0, start_z=6.5,
                              tool_radius_mm=1.0, params=params)
    deep_levels = {round(z, 6) for path in deep.paths for _, _, z in path}
    shallow_levels = {round(z, 6) for path in shallow.paths for _, _, z in path}
    assert len(deep_levels) > len(shallow_levels)
    assert min(deep_levels) == 1.0                # still finishes at the floor


def test_shallow_pocket_still_posts_the_historical_single_level():
    """A recess no deeper than one stepdown must be untouched by the change."""
    t = TempleParams()
    params = CastleCamParams()
    floor = t.blank_thickness_mm - t.hinge_pocket_depth_mm
    op = hinge_pocket_op(HINGE, floor_z=floor, start_z=t.blank_thickness_mm + 0.5,
                         tool_radius_mm=1.0, params=params)
    assert op.paths
    # one level: the deepest Z appears once as the cascade floor, never revisited
    # after a climb back to a shallower cutting level.
    for path in op.paths:
        zs = [z for _, _, z in path]
        assert zs.index(min(zs)) <= len(zs) - 1
        assert all(b <= a + 1e-9 for a, b in zip(zs, zs[1:])), "single level must only descend"


# ---------------------------------------------------------------- engraving

def test_shallow_engraving_is_still_one_pass():
    t = TempleParams()
    op = engrave_op(ENGRAVING, t.blank_thickness_mm - t.engrave_depth_mm, TOOLS["engrave_vbit"],
                    top_z=t.blank_thickness_mm, stepdown_mm=t.engrave_stepdown_mm)
    assert len(op.paths) == len(ENGRAVING)


def test_deep_engraving_is_split_into_passes():
    """A 1.5 mm channel with a 0.5 mm V-bit is what snaps engraving tools."""
    op = engrave_op(ENGRAVING, 2.5, TOOLS["engrave_vbit"],
                    top_z=4.0, stepdown_mm=0.5)
    assert len(op.paths) == len(ENGRAVING) * 3
    depths = _depths(op.paths)
    assert depths[0] == 2.5                       # finishes at the requested depth
    assert max(a - b for a, b in zip([4.0] + depths[:0:-1], depths[::-1])) <= 0.5 + 1e-9


def test_engrave_stepdown_reaches_the_generated_program():
    t = TempleParams(engrave_depth_mm=1.5, engrave_stepdown_mm=0.5)
    ops = generate_temple_program(OUTLINE, ENGRAVING, t, TOOLS)
    engraving = next(op for op in ops if op.name == "Engraving")
    assert len(_depths(engraving.paths)) == 3


# ------------------------------------------------------- the panel exposes it

def _panel(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


def test_depth_controls_stay_visible_on_every_component_kind(tmp_path, monkeypatch):
    """The bug: these lived in the frame-only strategy group and vanished on a
    temple, leaving no way to set the depth per pass for the part being cut."""
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(tmp_path, monkeypatch)
    p.show()
    for kind in ComponentKind:
        p.set_component_kind(kind)
        # Cut and Machine are universal tabs, so selecting them is always allowed;
        # what changed is that these controls no longer hide *within* them.
        p.setCurrentIndex(p._tab_cut)
        assert p.contour_stepdown.isVisible(), kind
        assert p.pocket_stepdown.isVisible(), kind
        p.setCurrentIndex(p._tab_machine)
        assert p.contour_ramp_angle.isVisible(), kind
        assert p.arc_tolerance.isVisible(), kind
        # the frame's relief strategy stays frame-only
        assert p.relief_stepover.isVisible() == (kind == ComponentKind.FRAME_FRONT), kind


def test_pass_readout_warns_when_the_whole_depth_is_one_bite(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(tmp_path, monkeypatch)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.temple_onion.setValue(0.4)

    # A 2 mm blank at the 2 mm ceiling is one full-depth bite — the shape of the
    # failure the maker hit, kept inside the material limit so this exercises the
    # warning rather than the cap.
    p.temple_blank_thickness.setValue(2.0)
    p.contour_stepdown.setValue(2.0)
    assert "1 pass" in p._passes_lbl.text()
    assert "one bite" in p._passes_lbl.text()

    p.contour_stepdown.setValue(0.5)
    assert "4 passes" in p._passes_lbl.text()
    assert "one bite" not in p._passes_lbl.text()


def test_cam_params_round_trip_keeps_fields_with_no_widget(tmp_path, monkeypatch):
    """`_build_project_schema` saves this snapshot back into the project, so a
    rebuilt-from-scratch model silently reset every unexposed field on Save."""
    p = _panel(tmp_path, monkeypatch)
    tuned = CastleCamParams(
        ramp_step_mm=0.25, pocket_stepover_mm=0.7, relief_link_gap_mm=1.0,
        link_retracts=False, screw_head_diameter_mm=9.0,
    )
    p.set_cam_params(tuned)
    out = p.cam_params()
    assert out.ramp_step_mm == 0.25
    assert out.pocket_stepover_mm == 0.7
    assert out.relief_link_gap_mm == 1.0
    assert out.link_retracts is False
    assert out.screw_head_diameter_mm == 9.0
    # …while the fields the panel does own still come from the widgets
    p.contour_stepdown.setValue(0.8)
    assert p.cam_params().contour_stepdown_mm == 0.8


def test_capped_readout_reports_the_depth_that_will_be_cut(tmp_path, monkeypatch):
    """Over-set the request and the read-out must show the CLAMPED result — the
    post applies the material/machine ceiling, so reporting the request would
    mis-state an old project by a whole pass."""
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(tmp_path, monkeypatch)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.temple_blank_thickness.setValue(4.0)
    p.temple_onion.setValue(0.4)
    p.contour_stepdown.setValue(6.0)                 # far over acetate's 2.0 ceiling
    text = p._passes_lbl.text()
    assert "capped" in text
    assert "2 passes" in text                        # 3.6 mm at the 2.0 mm ceiling


# ------------------------------------------------- the upgrade actually takes

def test_prefs_retire_the_m124_stepdown(tmp_path, monkeypatch):
    """Prefs are restored over the schema defaults on every launch, so lowering
    the shipped default alone would have changed nothing for an existing user:
    their stored 4.0 would keep cutting temples in one pass."""
    import json
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({
        "cam_params": {"contour_stepdown_mm": 4.0, "ramp_step_mm": 0.6},
    }), encoding="utf-8")
    cam = prefs_mod.load()["cam_params"]
    assert "contour_stepdown_mm" not in cam           # falls back to the new default
    assert cam["ramp_step_mm"] == 0.6                 # everything else untouched
    assert CastleCamParams(**cam).contour_stepdown_mm == CastleCamParams().contour_stepdown_mm


def test_prefs_keep_a_deliberately_tuned_stepdown(tmp_path, monkeypatch):
    """Anything below the old default was a real choice — leave it alone."""
    import json
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({
        "cam_params": {"contour_stepdown_mm": 0.8},
    }), encoding="utf-8")
    assert prefs_mod.load()["cam_params"]["contour_stepdown_mm"] == 0.8
