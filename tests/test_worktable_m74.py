"""The interactive worktable: a user-defined bed from DXF (BUILDPLAN M7.4).

A bed drawn in CAD is polygonized into candidate regions the maker tags by role
(frame-front / temple R-L / base-curve R-L / keep-out); the built-in Guild fixture
loads into the same `Worktable` model as the default bed, and bridges back onto the
M6.5 layout machinery via `to_fixture_dict()` so nesting/clearance keep working.
These tests cover the DXF intake, tag/untag, the fixture equivalence, and both the
`.bed` and `.gcam` round-trips.
"""
from pathlib import Path

import pytest
import yaml

from guildcam.core.project.schema import (
    BedRole, ProjectSchema, Worktable, WorktableZone, kind_for_role,
    role_for_kind, ComponentKind,
)
from guildcam.core.cam.worktable import (
    WorktableError, build_worktable_from_dxf, default_worktable, load_bed,
    polygonize_bed, read_bed_linework, save_bed,
)
from guildcam.core.cam.layout import (
    BedPart, bed_clearance_violations, build_bed_program, place_ops_at_zone,
    zone_center,
)
from guildcam.core.cam.castle_ops import CamOp

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildcam" / "config"
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())


# ------------------------------------------------------------------ DXF intake

def _bed_dxf(path: Path) -> Path:
    """A tiny synthetic bed: two rectangular blank zones + two screw circles."""
    import ezdxf
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    # frame zone 10..180 x, 100..185 y; temple zone 10..180 x, 50..80 y
    msp.add_lwpolyline([(10, 100), (180, 100), (180, 185), (10, 185)], close=True)
    msp.add_lwpolyline([(10, 50), (180, 50), (180, 80), (10, 80)], close=True)
    # two hold-down screws (circles)
    msp.add_circle((95, 92), 5.0)
    msp.add_circle((95, 40), 5.0)
    doc.saveas(path)
    return path


def test_read_bed_linework_collects_polylines_and_circles(tmp_path):
    segs, circles = read_bed_linework(_bed_dxf(tmp_path / "bed.dxf"))
    assert len(segs) == 2                       # two closed rectangles
    assert len(circles) == 2                    # two screw circles
    assert all(r == pytest.approx(5.0) for _, _, r in circles)


def test_polygonize_bed_yields_regions_with_circle_radii(tmp_path):
    segs, circles = read_bed_linework(_bed_dxf(tmp_path / "bed.dxf"))
    faces = polygonize_bed(segs, circles)
    assert len(faces) == 4                       # 2 rectangles + 2 circles
    radii = sorted(r for _, r in faces if r is not None)
    assert radii == pytest.approx([5.0, 5.0])    # the two circles carry a radius
    assert sum(1 for _, r in faces if r is None) == 2   # rectangles: polygon-only


def test_build_worktable_from_dxf_is_all_untagged(tmp_path):
    wt = build_worktable_from_dxf(_bed_dxf(tmp_path / "bed.dxf"))
    assert len(wt.zones) == 4
    assert wt.untagged() == wt.zones             # nothing tagged on import
    assert wt.placement_zones() == []
    assert wt.keep_outs() == []
    assert wt.source_dxf == "bed.dxf"
    # work area spans the geometry's positive quadrant
    assert wt.work_area_width_mm == pytest.approx(180.0)
    assert wt.work_area_height_mm == pytest.approx(185.0)


def test_empty_dxf_raises(tmp_path):
    import ezdxf
    p = tmp_path / "empty.dxf"
    ezdxf.new("R2000").saveas(p)
    with pytest.raises(WorktableError):
        build_worktable_from_dxf(p)


# ------------------------------------------------------------------ tagging

def test_tag_and_untag_round_trip(tmp_path):
    wt = build_worktable_from_dxf(_bed_dxf(tmp_path / "bed.dxf"))
    first = wt.zones[0].id
    wt.set_role(first, BedRole.FRAME_FRONT)
    assert wt.zone(first).role is BedRole.FRAME_FRONT
    assert wt.zone(first).label == "Frame Front"
    assert wt.zone(first) in wt.placement_zones()
    # re-tag as keep-out, then clear
    wt.set_role(first, BedRole.KEEP_OUT)
    assert wt.zone(first) in wt.keep_outs()
    assert wt.zone(first) not in wt.placement_zones()
    wt.set_role(first, BedRole.UNASSIGNED)
    assert wt.zone(first) in wt.untagged()


def test_role_kind_mapping_is_consistent():
    for kind in ComponentKind:
        role = role_for_kind(kind)
        assert role.value == kind.value
        assert kind_for_role(role) is kind
    assert kind_for_role(BedRole.KEEP_OUT) is None
    assert kind_for_role(BedRole.UNASSIGNED) is None


# ------------------------------------------------------------------ default bed

def test_default_worktable_matches_the_guild_fixture():
    wt = default_worktable()
    assert len(wt.placement_zones()) == 5        # front + 2 temples + 2 bc templates
    assert len(wt.keep_outs()) == 24             # the hold-down screws
    assert {z.role for z in wt.placement_zones()} == {
        BedRole.FRAME_FRONT, BedRole.TEMPLE_RIGHT, BedRole.TEMPLE_LEFT,
        BedRole.BASE_CURVE_RIGHT, BedRole.BASE_CURVE_LEFT,
    }
    # screw rings carry the fixture radius
    assert all(z.radius_mm == pytest.approx(5.0) for z in wt.keep_outs())
    # a zone's bbox reproduces the fixture rectangle
    front = wt.zone("front")
    fz = FIXTURE["blank_zones"]["front"]
    x0, y0, x1, y1 = front.bbox()
    assert (x0, y0) == pytest.approx((fz["x_mm"], fz["y_mm"]))
    assert (x1 - x0, y1 - y0) == pytest.approx((fz["width_mm"], fz["height_mm"]))
    # front-zone pass-through keys survive (two-sided flip axis + nosepad sub-zone)
    assert front.extra["flip_axis_x_mm"] == pytest.approx(fz["flip_axis_x_mm"])
    assert "nosepad_sub_zone" in front.extra
    assert front.stock_thickness_mm == pytest.approx(6.0)


def test_to_fixture_dict_reproduces_zones_and_screws():
    wt = Worktable.from_fixture_dict(FIXTURE)
    derived = wt.to_fixture_dict()
    # same blank-zone keys + geometry as the YAML fixture
    assert set(derived["blank_zones"]) == set(FIXTURE["blank_zones"])
    for key, z in FIXTURE["blank_zones"].items():
        d = derived["blank_zones"][key]
        for f in ("x_mm", "y_mm", "width_mm", "height_mm"):
            assert d[f] == pytest.approx(z[f])
    # screws + radius reproduce
    assert len(derived["hold_down_screws"]) == len(FIXTURE["hold_down_screws"])
    assert derived["hold_down_screw_radius_mm"] == pytest.approx(5.0)
    orig = sorted((s["x"], s["y"]) for s in FIXTURE["hold_down_screws"])
    got = sorted((s["x"], s["y"]) for s in derived["hold_down_screws"])
    for (ox, oy), (gx, gy) in zip(orig, got):
        assert (gx, gy) == pytest.approx((ox, oy))


def test_m65_layout_machinery_re_passes_through_the_worktable():
    """The M6.5 nesting + clearance run on the bridged fixture dict unchanged."""
    derived = Worktable.from_fixture_dict(FIXTURE).to_fixture_dict()

    # zone_center / place_ops_at_zone identical to the YAML fixture
    assert zone_center(derived, "bc_template_right") == pytest.approx(
        zone_center(FIXTURE, "bc_template_right"))

    op = CamOp("P", paths=[[(0.0, 0.0, 0.0), (20.0, 10.0, 0.0)]],
               tool={**TOOLS["flat_3175"], "name": "flat_3175"})
    p_fix, off_fix = place_ops_at_zone([op], FIXTURE, "front")
    p_der, off_der = place_ops_at_zone([op], derived, "front")
    assert off_der == pytest.approx(off_fix)

    # build a 1-part bed on each → same placement offset
    part = BedPart("frame_front", "Frame", "front", [op], set(), set())
    bed_fix = build_bed_program([part], FIXTURE)
    bed_der = build_bed_program(
        [BedPart("frame_front", "Frame", "front", [op], set(), set())], derived)
    assert bed_der.placements[0].x_mm == pytest.approx(bed_fix.placements[0].x_mm)
    assert bed_der.placements[0].y_mm == pytest.approx(bed_fix.placements[0].y_mm)

    # a cutting point parked on a screw is flagged through the derived bed too
    near = CamOp("Cut", paths=[[(126.146, 180.273, 0.0)]],   # a front screw centre
                 tool={**TOOLS["flat_3175"], "name": "flat_3175"})
    assert bed_clearance_violations([near], derived) != []
    assert bed_clearance_violations([near], FIXTURE) != []


# ------------------------------------------------------------------ persistence

def test_bed_yaml_round_trip(tmp_path):
    wt = default_worktable()
    p = tmp_path / "guild.bed"
    save_bed(wt, p)
    back = load_bed(p)
    assert back.name == wt.name
    assert len(back.zones) == len(wt.zones)
    assert {z.role for z in back.placement_zones()} == {
        z.role for z in wt.placement_zones()}
    assert back.zone("front").extra["flip_axis_x_mm"] == pytest.approx(
        wt.zone("front").extra["flip_axis_x_mm"])


def test_worktable_round_trips_through_gcam(tmp_path):
    from guildcam.core.project.gcam import save_gcam, load_gcam
    proj = ProjectSchema(job_name="Bed")
    proj.worktable = default_worktable()
    path = tmp_path / "wt.gcam"
    save_gcam(path, project=proj, dxf_bytes=b"dxf")
    back = load_gcam(path).project.worktable
    assert back is not None
    assert len(back.placement_zones()) == 5
    assert len(back.keep_outs()) == 24
    assert back.zone("front").role is BedRole.FRAME_FRONT


def test_worktable_defaults_to_none_on_legacy_projects():
    assert ProjectSchema().worktable is None


# ------------------------------------------------------------------ GUI smoke (guarded)

def test_worktable_tab_loads_bed_and_tags_a_region(tmp_path, monkeypatch):
    """The Worktable tab loads the Guild bed, the canvas + list show its regions,
    and re-tagging a region updates the model. Skipped without a Qt/VTK platform."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildcam.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                      # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    # Open the Worktable tab from a cold start → the bar gets a single Worktable tab
    win._on_show_worktable()
    assert win.stack.currentIndex() == win._worktable_page_index
    win._on_load_default_bed()
    assert win._worktable is not None
    assert win._bed_region_list.count() == len(win._worktable.zones)   # 5 + 24

    # tag a known untagged region (force one to untagged, then re-tag via the model)
    untag = win._worktable.untagged()
    assert untag == []                          # the Guild bed is fully role-tagged
    # re-tag the front zone as a keep-out and back, exercising the handler path
    win.bed_canvas.set_selected("front")
    win._select_bed_region("front")
    idx = win._bed_role_combo.findData(BedRole.KEEP_OUT.value)
    win._bed_role_combo.setCurrentIndex(idx)    # fires _on_bed_role_changed
    assert win._worktable.zone("front").role is BedRole.KEEP_OUT
    assert win._worktable.zone("front") in win._worktable.keep_outs()
