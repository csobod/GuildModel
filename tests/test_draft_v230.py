"""The draft view and the blueprint (2.3; research section 6), the core
half: the drawing's two new blocks read, the tip bend in GuildModel's
frame, the hinge filled in from the pocket, the assembly's angles and
checks, the measures, the sheets, and the files they are written to.

A synthetic front stands in for a drawing: a rectangle with two square
lenses, a pocket near each end; the temples are bars with a pocket at the
hinge end. The numbers are small enough to check by hand.
"""
import json
import math
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from shapely.geometry import Polygon

from guildmodel.core.io_import.gdraw import TABS, build_project_from_gdraw, read_gdraw
from guildmodel.core.project.schema import (BlueprintSettings, CastleParams,
                                            ComponentKind, DraftHinge, DraftParams,
                                            FormingMetadata, HingeKind, TempleParams,
                                            TipBendParams, default_tolerances)

_SVG_NS = "http://www.w3.org/2000/svg"
SCRATCH = Path(__file__).parent / "corpus"


# ------------------------------------------------------------------ files

def _line(layer, pts, closed=False, **extra):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts], **extra}


def _front_state(thermoform=None, kinds=("Hinges", "Hinges")):
    state = {"mirror": {"x": 0.0, "enabled": False},
             "guides": {"construction": {"crest_height_mm": 6.5, "crest_width_mm": 12.0}},
             "curves": [
        _line("OUTLINE", [(-70, -22), (70, -22), (70, 22), (-70, 22)], closed=True),
        _line("LENS", [(20, -15), (60, -15), (60, 15), (20, 15)], closed=True),
        _line("LENS", [(-60, -15), (-20, -15), (-20, 15), (-60, 15)], closed=True),
        _line("COMPONENT", [(62, -5), (66, -5), (66, 5), (62, 5)], closed=True,
              component_kind=kinds[0]),
        _line("COMPONENT", [(-66, -5), (-62, -5), (-62, 5), (-66, 5)], closed=True,
              component_kind=kinds[1]),
    ]}
    if thermoform is not None:
        state["thermoform"] = thermoform
    return state


def _temple_state(tip_bend=None, drop_up=False):
    # the right temple as GuildDraw draws it: the hinge end at min x, a
    # square butt, the drop toward +y (down in the y-down scene); the left
    # is its mirror about the core line
    sign = -1.0 if drop_up else 1.0
    state = {"mirror": {"enabled": False}, "curves": [
        _line("OUTLINE", [(-80, -4 * sign), (60, -4 * sign), (60, 4 * sign), (-80, 4 * sign)],
              closed=True),
        _line("COMPONENT", [(-76, -2), (-68, -2), (-68, 2), (-76, 2)], closed=True,
              component_kind="Hinges"),
    ]}
    if tip_bend is not None:
        state["tip_bend"] = tip_bend
    return state


def _gdraw(path, states):
    ET.register_namespace("", _SVG_NS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab in TABS:
            root = ET.Element(f"{{{_SVG_NS}}}svg")
            ET.SubElement(root, f"{{{_SVG_NS}}}metadata").text = json.dumps(
                states.get(tab, {"curves": []}))
            zf.writestr(f"{tab}.svg", ET.tostring(root, xml_declaration=True,
                                                  encoding="utf-8"))
    return path


THERMOFORM = {"base_curve": 4.0, "base_radius_mm": 144.0, "face_form_wrap_deg": 16.03,
              "bridge_projection_mm": 3.0, "press_preset": "SBT base 4 / lens 4",
              "radius_rule": 530.0, "sheet_thickness_mm": 6.0, "neutral_fraction": 0.25}
TIP_BEND = {"length_to_bend_mm": 100.0, "drop_angle_deg": 45.0, "bend_radius_mm": 12.0}


# ------------------------------------------------------------------ the reader

def test_a_file_without_the_blocks_seeds_flat_and_straight(tmp_path):
    path = _gdraw(tmp_path / "old.gdraw", {"front": _front_state(),
                                           "temple_r": _temple_state(),
                                           "temple_l": _temple_state(drop_up=True)})
    doc = read_gdraw(path)
    assert doc.workspaces["front"].thermoform is None
    assert doc.workspaces["temple_r"].tip_bend is None
    gp = build_project_from_gdraw(path)
    front = gp.project.frame_front()
    assert front.forming.is_flat and front.forming.press_preset == ""
    for comp in gp.project.components_of_kind(ComponentKind.TEMPLE_RIGHT):
        assert comp.temple.tip_bend == TipBendParams()


def test_thermoform_seeds_the_fronts_forming(tmp_path):
    path = _gdraw(tmp_path / "new.gdraw", {"front": _front_state(THERMOFORM),
                                           "temple_r": _temple_state(TIP_BEND),
                                           "temple_l": _temple_state(TIP_BEND, drop_up=True)})
    ws = read_gdraw(path).workspaces["front"]
    assert ws.thermoform["base_curve"] == 4.0 and ws.thermoform["neutral_fraction"] == 0.25
    assert ws.guides["construction"]["crest_height_mm"] == 6.5
    assert ws.component_kinds == ["Hinges", "Hinges"]
    gp = build_project_from_gdraw(path)
    f = gp.project.frame_front().forming
    assert f.base_curve == 4.0 and f.base_radius_mm == 144.0
    assert f.face_form_wrap_deg == pytest.approx(16.03)
    assert f.bridge_projection_mm == 3.0 and f.press_preset == "SBT base 4 / lens 4"
    assert f.neutral_fraction == 0.25
    # the drawing's own nose-fit values ride along as before
    assert f.apical_radius_mm == 0.0
    for kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        tb = gp.project.component(kind).temple.tip_bend
        assert (tb.length_to_bend_mm, tb.drop_angle_deg, tb.bend_radius_mm) == (100.0, 45.0, 12.0)
    assert gp.components[0].component_kinds == ["Hinges", "Hinges"]


def test_an_unknown_press_label_is_dropped_and_a_bad_number_takes_the_default(tmp_path):
    tf = {**THERMOFORM, "press_preset": "Somebody else's press", "bridge_projection_mm": "x",
          "face_form_wrap_deg": 99.0}
    path = _gdraw(tmp_path / "odd.gdraw", {"front": _front_state(tf)})
    f = build_project_from_gdraw(path).project.frame_front().forming
    assert f.press_preset == "" and f.base_curve == 4.0 and f.base_radius_mm == 144.0
    assert f.bridge_projection_mm == 0.0
    assert f.face_form_wrap_deg == 30.0, "held to GuildDraw's own bound"


def test_a_radius_of_zero_takes_the_rule(tmp_path):
    tf = {"base_curve": 2.0, "base_radius_mm": 0.0, "radius_rule": 600.0}
    path = _gdraw(tmp_path / "rule.gdraw", {"front": _front_state(tf)})
    f = build_project_from_gdraw(path).project.frame_front().forming
    assert f.base_radius_mm == pytest.approx(300.0)


def test_the_project_round_trips_the_new_fields():
    from guildmodel.core.project.schema import ProjectSchema
    p = ProjectSchema()
    p.draft = DraftParams(splay_deg=2.5, hinge=DraftHinge(kind=HingeKind.SPRING, barrels=7),
                          blueprint=BlueprintSettings(paper="a3", owner="X"))
    p.temple = TempleParams(tip_bend=TipBendParams(drop_angle_deg=42.0))
    p.forming = FormingMetadata(neutral_fraction=0.5, pantoscopic_tilt_deg=9.0)
    q = ProjectSchema.model_validate_json(p.model_dump_json())
    assert q.draft.hinge.kind == HingeKind.SPRING and q.draft.hinge.barrels == 7
    assert q.draft.blueprint.paper == "a3" and q.draft.blueprint.owner == "X"
    assert len(q.draft.blueprint.tolerances) == len(default_tolerances())
    assert q.temple.tip_bend.drop_angle_deg == 42.0
    assert q.forming.neutral_fraction == 0.5 and q.forming.pantoscopic_tilt_deg == 9.0
    # a file from before: every default
    old = ProjectSchema.model_validate_json('{"job_name": "old"}')
    assert old.draft == DraftParams() and old.temple.tip_bend == TipBendParams()


def test_the_models_hold_their_fields_to_bounds():
    assert DraftHinge(barrels=4).barrels == 5
    assert DraftHinge(screw_thread="M3").screw_thread == "M1.4"
    assert DraftHinge(open_deg=400).open_deg == 180.0
    assert BlueprintSettings(paper="b5").paper == "letter"
    assert DraftParams(splay_deg=99).splay_deg == 30.0
    assert FormingMetadata(neutral_fraction=-1).neutral_fraction == 0.0


# ------------------------------------------------------------------ the tip bend

def test_the_bend_matches_the_research_geometry():
    from guildmodel.core.draft import TipBend
    tb = TipBend.resolve(TipBendParams(length_to_bend_mm=103.0, drop_angle_deg=50.0,
                                       bend_radius_mm=15.0), -80.0, 140.0, down=-1.0)
    d = math.radians(50.0)
    s1 = 103.0 - 15.0 * d / 2
    s2 = 140.0 - 103.0 - 15.0 * d / 2
    assert tb.straight_mm == pytest.approx(s1) and tb.tail_mm == pytest.approx(s2)
    x, y = tb.tip()
    # section 5.3: x = s1 + r sin d + s2 cos d; the drop r(1 - cos d) + s2 sin d
    assert x - (-80.0) == pytest.approx(s1 + 15.0 * math.sin(d) + s2 * math.cos(d))
    assert tb.tip_drop_mm == pytest.approx(15.0 * (1 - math.cos(d)) + s2 * math.sin(d))
    assert y == pytest.approx(-tb.tip_drop_mm), "the right temple drops toward -y"
    ex, ey = tb.ear_point()
    assert ex - (-80.0) == pytest.approx(s1 + 15.0 * math.sin(d / 2))
    assert tb.drop_mm == 37.0 and tb.out_of_range() is None


def test_auto_length_and_out_of_range():
    from guildmodel.core.draft import DEFAULT_DROP_MM, TipBend
    tb = TipBend.resolve(TipBendParams(), -80.0, 140.0)
    assert tb.length_to_bend_mm == 140.0 - DEFAULT_DROP_MM
    bad = TipBend.resolve(TipBendParams(length_to_bend_mm=139.0, bend_radius_mm=40.0), 0.0, 140.0)
    assert bad.out_of_range() and "runs past the tip" in bad.out_of_range()
    assert np.allclose(bad.map_points([[100.0, 0.0]]), [[100.0, 0.0]]), "drawn straight"
    straight = TipBend.resolve(TipBendParams(drop_angle_deg=0.0), 0.0, 140.0)
    assert straight.is_straight and not straight.applies


def test_each_temple_drops_toward_its_own_side():
    from guildmodel.core.draft import resolve_tip_bend
    right = Polygon([(-80, -4), (60, -4), (60, 4), (-80, 4)])
    pocket = [Polygon([(-76, -2), (-68, -2), (-68, 2), (-76, 2)])]
    params = TipBendParams(length_to_bend_mm=100.0)
    r = resolve_tip_bend(params, right, pocket, ComponentKind.TEMPLE_RIGHT)
    l = resolve_tip_bend(params, right, pocket, ComponentKind.TEMPLE_LEFT)
    assert r.x_hinge == -80.0 and r.along == 1.0
    assert r.tip()[1] < 0.0 < l.tip()[1], "the right drops to -y, the left to +y"
    assert r.tip()[0] == pytest.approx(l.tip()[0])
    # a temple drawn with its hinge at +x is the same part turned
    turned = Polygon([(-60, -4), (80, -4), (80, 4), (-60, 4)])
    tp = [Polygon([(68, -2), (76, -2), (76, 2), (68, 2)])]
    t = resolve_tip_bend(params, turned, tp, ComponentKind.TEMPLE_RIGHT)
    assert t.x_hinge == 80.0 and t.along == -1.0 and t.down == 1.0
    assert t.tip()[0] == pytest.approx(-r.tip()[0]) and t.tip()[1] == pytest.approx(-r.tip()[1])


# ------------------------------------------------------------------ the hinge

def _front_polys():
    outline = Polygon([(-70, -22), (70, -22), (70, 22), (-70, 22)])
    lens_od = Polygon([(20, -15), (60, -15), (60, 15), (20, 15)])
    lens_os = Polygon([(-60, -15), (-20, -15), (-20, 15), (-60, 15)])
    pockets = [Polygon([(62, -5), (66, -5), (66, 5), (62, 5)]),
               Polygon([(-66, -5), (-62, -5), (-62, 5), (-66, 5)])]
    return outline, lens_od, lens_os, pockets


def test_the_pocket_is_read_against_the_outline():
    from guildmodel.core.draft import fit_pocket
    outline, _od, _os, pockets = _front_polys()
    fit = fit_pocket(pockets[0], outline, (1.0, 0.0))
    assert fit.found and fit.datum == pytest.approx((70.0, 0.0))
    assert fit.setback_mm == pytest.approx(4.0)
    assert fit.along_axis_mm == pytest.approx(10.0) and fit.across_mm == pytest.approx(4.0)
    left = fit_pocket(pockets[1], outline, (-1.0, 0.0))
    assert left.datum == pytest.approx((-70.0, 0.0)) and left.setback_mm == pytest.approx(4.0)
    nowhere = fit_pocket(pockets[0], None, (1.0, 0.0))
    assert not nowhere.found and nowhere.setback_mm == 0.0


def test_the_hinge_is_filled_from_the_pocket():
    from guildmodel.core.draft import fill_hinge, fit_pocket, hinge_detail
    from guildmodel.core.draft.hinges import knuckle_split, screw_length
    outline, _od, _os, pockets = _front_polys()
    fit = fit_pocket(pockets[0], outline, (1.0, 0.0))
    fill = fill_hinge(DraftHinge(), fit, None, 1.0, 1.0)
    assert fill.width_mm == pytest.approx(9.8) and fill.plate_length_mm == pytest.approx(4.0)
    assert (fill.barrels_front, fill.barrels_temple) == (3, 2)
    assert fill.screw_length_mm == 10.5 and fill.screw_text == "M1.4 × 10.5, H2"
    assert knuckle_split(3) == (2, 1) and knuckle_split(7) == (4, 3)
    assert screw_length(6.8) == 7.5 and screw_length(7.0) == 7.5
    assert "rivets" in fill.installation_text
    spring = fill_hinge(DraftHinge(kind=HingeKind.SPRING), fit, None, 1.0, 1.0)
    assert "spring box" in spring.installation_text
    det = hinge_detail(spring)
    assert det["elevation"]["visible"] and det["plan"]["center"]
    assert any("spring box" in t for _x, _y, t in det["elevation"]["labels"])
    cleat = hinge_detail(fill_hinge(DraftHinge(kind=HingeKind.HEAT_SET), fit, None, 1.0, 1.0))
    assert cleat["elevation"]["hidden"], "the cleats' teeth are hidden in the acetate"


# ------------------------------------------------------------------ the assembly

def _inputs(forming=None, floor_angle=0.0, temple_angle=0.0, with_temples=True):
    from guildmodel.core.draft import FrontInput, TempleInput
    outline, lens_od, lens_os, pockets = _front_polys()
    castle = CastleParams(hinge_pocket_angle_deg=floor_angle)
    fi = FrontInput(outline=outline, lens_od=lens_od, lens_os=lens_os, hinge_polys=pockets,
                    component_kinds=["Hinges", "Hinges"], castle=castle,
                    forming=forming or FormingMetadata(), job_name="synthetic")
    temples = []
    if with_temples:
        for kind, sign in ((ComponentKind.TEMPLE_RIGHT, -1.0), (ComponentKind.TEMPLE_LEFT, 1.0)):
            # as the intake leaves them: the right's drop toward -y, the left's +y
            outline_t = Polygon([(-80, -4), (60, -4), (60, 4), (-80, 4)])
            pocket = [Polygon([(-76, -2), (-68, -2), (-68, 2), (-76, 2)])]
            temples.append(TempleInput(kind=kind, outline=outline_t, hinge_polys=pocket,
                                       params=TempleParams(hinge_pocket_angle_deg=temple_angle)))
    return fi, temples


def test_a_flat_front_hangs_its_temples_square():
    from guildmodel.core.draft import build_assembly
    fi, temples = _inputs()
    asm = build_assembly(fi, temples, DraftParams())
    R, L = asm.right, asm.left
    assert R is not None and L is not None
    for s in (R, L):
        assert s.surface_turn_deg == pytest.approx(0.0, abs=1e-6)
        assert s.surface_tilt_deg == pytest.approx(0.0, abs=1e-6)
        assert s.side_from_hinge_deg == pytest.approx(0.0, abs=1e-6)
        assert s.splay_from_hinge_deg == pytest.approx(0.0, abs=1e-6)
    # the axis a temple's thickness inside the endpiece's end face, on its
    # back face; the temple's outer face flush with the edge
    assert R.axis_point[0] == pytest.approx(66.0) and L.axis_point[0] == pytest.approx(-66.0)
    assert float(R.temple.outer_ring[:, 0].max()) == pytest.approx(70.0, abs=0.05)
    assert R.axis_point[2] == pytest.approx(fi.castle.zones.endpiece_mm)
    # the temples run straight back (+z), 140 mm less the drop, and drop down
    for s in (R, L):
        t = s.temple
        assert t is not None and len(t.outer_ring) >= 4
        assert t.tip[2] > 100.0 and t.tip[1] < s.axis_point[1] - 20.0
        # the ear point sits a length to bend along the core: the inward
        # bend's chord is a hair shorter than its arc
        assert np.linalg.norm(t.ear_point - s.axis_point) == pytest.approx(
            t.bend.length_to_bend_mm, abs=1.0)
        assert t.ear_point[2] > 0.9 * t.bend.length_to_bend_mm
        # the inward bend turns the tip toward the center line
        assert abs(t.tip[0]) < abs(s.axis_point[0]) - 10.0
        assert not t.butt_cut, "square to the back face: nothing to cut"
    assert R.temple.tip[0] == pytest.approx(-L.temple.tip[0])
    assert all(c.ok for c in asm.checks), [c for c in asm.checks if not c.ok]
    assert {c.name for c in asm.checks} >= {"Angle of side, L against R", "Splay symmetric",
                                            "Four-point touch", "Tips on a common plane",
                                            "No X-ing", "Folded temple R", "Folded temple L"}


def test_the_hinge_alone_is_the_floor_the_slant_and_the_stop():
    from guildmodel.core.draft import build_assembly
    fi, temples = _inputs(floor_angle=5.0, temple_angle=2.0)
    draft = DraftParams(hinge=DraftHinge(slant_deg=6.0, open_deg=95.0))
    asm = build_assembly(fi, temples, draft)
    for s in asm.ordered_sides():
        assert s.side_from_hinge_deg == pytest.approx(11.0, abs=1e-6)
        assert s.splay_from_hinge_deg == pytest.approx(5.0 - 2.0, abs=1e-6)
        assert s.floor_angle_for_target == pytest.approx(0.0 - 6.0)


def test_the_targets_hang_the_temples_and_cut_the_butt():
    from guildmodel.core.draft import build_assembly
    forming = FormingMetadata(pantoscopic_tilt_deg=8.0)
    fi, temples = _inputs(forming=forming)
    asm = build_assembly(fi, temples, DraftParams(splay_deg=3.0))
    R = asm.right
    assert R.side_target_deg == 8.0 and R.splay_target_deg == 3.0
    assert R.panto_cut_deg == pytest.approx(8.0) and R.splay_cut_deg == pytest.approx(3.0)
    # the temple's direction: 8 degrees down, 3 degrees out, along its core
    core = R.temple.core
    d = core[10] - core[0]
    assert math.degrees(math.atan2(-d[1], d[2])) == pytest.approx(8.0, abs=0.05)
    assert math.degrees(math.atan2(d[0], d[2])) == pytest.approx(3.0, abs=0.05)
    assert R.temple.butt_cut, "the butt swung into the back face and was cut"
    assert asm.left.temple.butt_cut
    assert asm.left.temple.ear_point[0] == pytest.approx(-R.temple.ear_point[0])


def test_a_formed_front_turns_its_endpieces():
    from guildmodel.core.draft import build_assembly
    forming = FormingMetadata().with_base_curve(4.0, 163.97, radius_mm=144.0)
    fi, temples = _inputs(forming=forming)
    asm = build_assembly(fi, temples, DraftParams())
    R, L = asm.right, asm.left
    assert R.surface_turn_deg == pytest.approx(L.surface_turn_deg, abs=1e-6)
    assert 15.0 < R.surface_turn_deg < 30.0, "section 2.8: about 14 degrees plus the face form"
    assert R.splay_from_hinge_deg == pytest.approx(-R.surface_turn_deg)
    assert R.splay_cut_deg == pytest.approx(R.surface_turn_deg)
    # the endpieces came back toward the wearer
    assert R.axis_point[2] > fi.castle.zones.endpiece_mm + 5.0
    assert R.temple.butt_cut
    assert all(c.ok for c in asm.checks), [c for c in asm.checks if not c.ok]


def test_the_neutral_surface_moves_the_formed_front():
    from guildmodel.core.draft import build_assembly
    fi, temples = _inputs(forming=FormingMetadata().with_base_curve(4.0, 180.0))
    a0 = build_assembly(fi, temples, DraftParams())
    fi.forming = fi.forming.model_copy(update={"neutral_fraction": 0.5})
    a1 = build_assembly(fi, temples, DraftParams())
    p = np.array([[60.0, 0.0, 0.0]])
    assert not np.allclose(a0.form(p), a1.form(p))
    assert a0.fmap(p).tolist() == a1.fmap(p).tolist(), "the map itself is untouched"


def test_a_bridge_component_is_not_a_hinge_and_a_missing_pocket_is_said():
    from guildmodel.core.draft import build_assembly
    fi, temples = _inputs()
    fi.component_kinds = ["Hinges", "Bridges"]
    asm = build_assembly(fi, temples, DraftParams())
    assert asm.right.pocket is not None and asm.left.pocket is None
    assert any("left" in n for n in asm.notes)


def test_the_temple_meshes_are_closed_solids():
    from guildmodel.core.draft import build_assembly
    fi, temples = _inputs(forming=FormingMetadata(pantoscopic_tilt_deg=8.0))
    asm = build_assembly(fi, temples, DraftParams(splay_deg=2.0))
    meshes = asm.temple_meshes()
    assert len(meshes) == 2
    for m in meshes:
        assert m.is_watertight and m.volume > 100.0
    # the inset tucks the temple toward the center; the butt gap stands it off
    tucked = build_assembly(fi, temples, DraftParams(hinge=DraftHinge(temple_inset_mm=2.0)))
    assert tucked.right.axis_point[0] == pytest.approx(asm.right.axis_point[0] - 2.0)
    gapped = build_assembly(fi, temples, DraftParams(hinge=DraftHinge(axis_offset_mm=1.0)))
    assert gapped.right.axis_point[2] == pytest.approx(asm.right.axis_point[2] + 1.0)


# ------------------------------------------------------------------ the measures

def test_the_measures_of_a_flat_front_are_the_flat_values():
    from guildmodel.core.draft import build_assembly, measure
    fi, temples = _inputs()
    asm = build_assembly(fi, temples, DraftParams())
    m = measure(asm)
    assert m.get("a").value == pytest.approx(40.0) and m.get("b").value == pytest.approx(30.0)
    assert m.get("dbl").value == pytest.approx(40.0)
    assert m.get("bcd").value == pytest.approx(80.0)
    assert m.get("front_width").value == pytest.approx(140.0)
    assert m.get("frontal_width").value == pytest.approx(132.0), "dowel to dowel, 4 mm in each side"
    assert m.get("overall").value == pytest.approx(140.0)
    assert m.get("drop").value == pytest.approx(37.0)
    assert m.marking == "40□40-140"
    assert m.get("a").status == "LOCKED" and m.get("side_R").status == "TARGET"
    assert m.get("tip_spread").status == "OPEN"
    # a 15 degree inward bend from 40 % of the length to bend narrows the
    # tips against the hinges
    assert m.get("tip_spread").value < m.get("frontal_width").value - 15.0
    assert m.get("temple_thickness").value == pytest.approx(4.0)
    assert m.get("inward_angle").value == 15.0
    assert m.get("temple_height_butt").value == pytest.approx(8.0, abs=0.2)
    assert m.get("a").tagged.endswith("[L]")


# ------------------------------------------------------------------ the sheets

@pytest.fixture
def assembled():
    from guildmodel.core.draft import build_assembly, measure
    forming = FormingMetadata(pantoscopic_tilt_deg=8.0).with_base_curve(4.0, 163.97, radius_mm=144.0)
    fi, temples = _inputs(forming=forming)
    asm = build_assembly(fi, temples, DraftParams(splay_deg=2.0))
    return asm, measure(asm)


def test_two_sheets_compose_and_fit_the_page(assembled):
    from guildmodel.core.draft import compose_sheets
    asm, m = assembled
    sheets = compose_sheets(asm, m, BlueprintSettings(owner="Shop"), job_name="synthetic",
                            material="acetate", issue_date="2026-11-04")
    assert [s.number for s in sheets] == [1, 2]
    s1, s2 = sheets
    assert s1.height > s1.width, "portrait by default: the views stack down the page"
    keys = {p.view.key for p in s1.placed}
    assert keys >= {"front", "plan", "side", "hinge", "notes", "tables"}
    assert s1.scale in (1.0, 2.0 / 3.0, 0.5, 0.4, 0.2)
    # third angle: the plan above the front, the side below
    plan = next(p for p in s1.placed if p.view.key == "plan")
    front = next(p for p in s1.placed if p.view.key == "front")
    side = next(p for p in s1.placed if p.view.key == "side")
    assert plan.y < front.y < side.y
    for p in s1.placed:
        assert 0 <= p.x and p.x + p.width <= s1.width + 1e-6
        assert 0 <= p.y and p.y + p.height <= s1.height + 1e-6
    texts = " ".join(t.text for t in s1.texts)
    assert "Shop" in texts and "synthetic" in texts and "1 / 2" in texts
    assert s2.scale == 1.0 and {p.view.key for p in s2.placed} == {"plan", "side"}
    assert not s2.clipped


def test_the_settings_choose_the_views_the_projection_and_the_scale(assembled):
    from guildmodel.core.draft import compose_sheets
    asm, m = assembled
    st = BlueprintSettings(projection="first", view_side=False, view_hinge=False,
                           sheet_template=False, scale=0.5, paper="a3", orientation="landscape")
    sheets = compose_sheets(asm, m, st)
    assert len(sheets) == 1
    s1 = sheets[0]
    assert s1.scale == 0.5 and s1.width > s1.height
    keys = {p.view.key for p in s1.placed}
    assert "side" not in keys and "hinge" not in keys and "front" in keys
    # first angle: the plan below the front, its temples running down
    plan = next(p for p in s1.placed if p.view.key == "plan")
    front = next(p for p in s1.placed if p.view.key == "front")
    assert plan.y > front.y
    big = compose_sheets(asm, m, BlueprintSettings(paper="a3"))[0]
    assert big.scale == 1.0, "A3 portrait holds the stack at 1:1"


def test_a_small_page_crops_the_template_and_says_so(assembled):
    from guildmodel.core.draft import compose_sheets
    from guildmodel.core.project.schema import PAPER_SIZES
    asm, m = assembled
    PAPER_SIZES["tiny"] = ("Tiny", 100.0, 120.0)
    try:
        st = BlueprintSettings()
        st.paper = "tiny"
        sheets = compose_sheets(asm, m, st)
        assert sheets[1].clipped
        assert any("cropped" in t.text for t in sheets[1].texts)
    finally:
        del PAPER_SIZES["tiny"]


def test_the_files_are_written(assembled, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.draft import compose_sheets
    from guildmodel.core.draft.dxf_out import write_dxf
    from guildmodel.gui.draft_render import export_pdf, export_svg, render_png
    asm, m = assembled
    sheets = compose_sheets(asm, m, BlueprintSettings(), job_name="synthetic")
    img = render_png(sheets[0], dpi=60)
    assert img.width() > 0
    dark = sum(1 for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)
               if img.pixelColor(x, y).lightness() < 128)
    assert dark > 50, "something was drawn"
    pdf = tmp_path / "b.pdf"
    export_pdf(pdf, sheets)
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") >= 2 or b"/Count 2" in data
    svg = tmp_path / "b.svg"
    export_svg(svg, sheets[0])
    assert b"<svg" in svg.read_bytes()
    dxf = tmp_path / "b.dxf"
    write_dxf(dxf, sheets)
    import ezdxf
    doc = ezdxf.readfile(str(dxf))
    ents = list(doc.modelspace())
    assert len(ents) > 100
    assert {e.dxf.layer for e in ents} >= {"VISIBLE", "DIM", "TEXT", "BORDER"}
    assert doc.header["$INSUNITS"] == 4


def test_the_depth_test_hides_what_lies_behind():
    """`draft.hidden`: an edge behind a box is dropped where the box covers
    it, kept where it does not; unordered segments chain into polylines."""
    import trimesh
    from guildmodel.core.draft.hidden import DepthView, chain_segments, split_by_visibility
    plate = trimesh.creation.box((100, 60, 2))
    plate.apply_translation((0, 0, 10))
    box = trimesh.creation.box((20, 20, 20))
    proj = lambda P: np.column_stack([np.asarray(P)[:, 0], np.asarray(P)[:, 1],   # noqa: E731
                                      -np.asarray(P)[:, 2]])
    dv = DepthView(proj)
    dv.add(plate.vertices, plate.faces)
    dv.add(box.vertices, box.faces)
    seen, hidden = split_by_visibility(np.array([[-50.0, 0.0, 9.0], [50.0, 0.0, 9.0]]), dv)
    assert len(seen) == 2 and len(hidden) == 1
    assert hidden[0][0][0] == pytest.approx(-10.0, abs=0.6) and hidden[0][-1][0] == pytest.approx(10.0, abs=0.6)
    # a point on the plate's own face is visible (the surface's own depth)
    assert dv.visible(np.array([[40.0, 20.0, 9.0]]))[0]
    assert not dv.visible(np.array([[0.0, 0.0, 9.0]]))[0]
    chains = chain_segments(np.array([[[0, 0, 0], [1, 0, 0]], [[1, 0, 0], [2, 0, 0]],
                                      [[5, 0, 0], [6, 0, 0]]], float))
    assert [len(c) for c in chains] == [3, 2]


def test_a_built_front_draws_its_own_edges(tmp_path):
    """With the front's built mesh the views are edge renderings of the
    formed solid with hidden lines removed: the plan and the side view
    carry many more strokes than the composed fallback, and nothing of the
    temples' hidden faces."""
    pytest.importorskip("PySide6.QtWidgets")
    from guildmodel.core.draft import build_assembly, compose_sheets, measure
    from guildmodel.gui.mesh_build import build_component_mesh
    import zipfile
    fixtures = Path(__file__).parent / "fixtures" / "gabriel"
    if not fixtures.is_dir():
        pytest.skip("no gabriel fixture")
    path = tmp_path / "gabriel.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(fixtures.iterdir()):
            zf.write(f, f.name)
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    wss, _ = build_workspaces_from_gdraw(path)
    front = wss[0]
    spec = {"mode": "castle", "kind": "frame_front", "label": "Frame Front",
            "partition": front.partition, "castle": front.castle_params,
            "hinge": list(front.hinge_polys), "stage": "pockets"}
    mesh, _edges, _core = build_component_mesh(spec, resolution=0.3, kernel="mesh")
    forming = front.forming.with_base_curve(4.0, 163.97, radius_mm=144.0, pantoscopic_tilt_deg=8.0)
    from guildmodel.core.draft import FrontInput, TempleInput
    fi = FrontInput(outline=front.outline_poly, lens_od=front.lens_od, lens_os=front.lens_os,
                    hinge_polys=front.hinge_polys, component_kinds=front.component_kinds,
                    partition=front.partition, castle=front.castle_params, forming=forming,
                    boxing=front.boxing, guides=front.guides, mesh=mesh)
    temples = [TempleInput(kind=ws.kind, outline=ws.outline_poly, hinge_polys=ws.hinge_polys,
                           params=ws.temple_params)
               for ws in wss if ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)]
    asm = build_assembly(fi, temples, DraftParams())
    assert asm.has_solid and asm.front_mesh.is_watertight and len(asm.front_edges) > 10
    m = measure(asm)
    sheets = compose_sheets(asm, m, BlueprintSettings(paper="a3"))
    s1 = sheets[0]
    plan = next(p for p in s1.placed if p.view.key == "plan").view
    side = next(p for p in s1.placed if p.view.key == "side").view
    assert len(plan.strokes) > 60 and len(side.strokes) > 30
    # the hidden runs that are drawn are the pockets' alone, dashed
    assert any(st.style == "hidden" for st in plan.strokes)
    assert all(st.style in ("visible", "hidden", "center", "dim", "thin") for st in plan.strokes)
    fi.mesh = None
    bare = build_assembly(fi, temples, DraftParams())
    assert not bare.has_solid
    bare_sheets = compose_sheets(bare, measure(bare), BlueprintSettings(paper="a3"))
    bare_plan = next(p for p in bare_sheets[0].placed if p.view.key == "plan").view
    assert len(bare_plan.strokes) < len(plan.strokes)


def test_the_forming_panel_speaks_per_side():
    pytest.importorskip("PySide6.QtWidgets")
    from guildmodel.gui.widgets.forming_panel import included, per_side
    assert per_side(163.97) == pytest.approx(8.015)
    assert included(per_side(163.97)) == pytest.approx(163.97)
    assert per_side(180.0) == 0.0


# ------------------------------------------------------------------ the corpus

_CORPUS = sorted(SCRATCH.glob("*.gdraw")) if SCRATCH.is_dir() else []


@pytest.mark.skipif(not _CORPUS, reason="no corpus")
def test_a_library_design_assembles_and_measures():
    """The planted corpus has no 2.3 blocks: every design seeds flat; a copy
    with the blocks injected reads them; every design assembles with the
    SBT base-4 row and composes both sheets."""
    from guildmodel.core.draft import build_assembly, compose_sheets, measure
    from guildmodel.core.draft import FrontInput, TempleInput
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    for path in _CORPUS[:3]:
        wss, _ = build_workspaces_from_gdraw(path)
        front = wss[0]
        assert front.forming.is_flat
        forming = front.forming.with_base_curve(4.0, 163.97, radius_mm=144.0,
                                                bridge_projection_mm=4.0,
                                                pantoscopic_tilt_deg=8.0)
        fi = FrontInput(outline=front.outline_poly, lens_od=front.lens_od, lens_os=front.lens_os,
                        hinge_polys=front.hinge_polys, component_kinds=front.component_kinds,
                        partition=front.partition, castle=front.castle_params, forming=forming,
                        boxing=front.boxing, guides=front.guides)
        temples = [TempleInput(kind=ws.kind, outline=ws.outline_poly, hinge_polys=ws.hinge_polys,
                               params=ws.temple_params)
                   for ws in wss if ws.kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT)]
        asm = build_assembly(fi, temples, DraftParams(splay_deg=2.0))
        assert asm.right is not None and asm.left is not None
        assert asm.right.pocket is not None and asm.right.pocket.found
        m = measure(asm)
        assert m.marking and 35.0 < m.get("a").value < 70.0
        sheets = compose_sheets(asm, m, BlueprintSettings())
        assert len(sheets) == 2 and sheets[0].scale >= 0.2
