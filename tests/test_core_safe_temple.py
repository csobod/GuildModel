"""Core-safe temple cutting + core-aligned worktable nesting (2026-07-09).

A temple blank carries an injected metal core running its length to the butt end.
The workflow snaps the butt flush to one short edge of the blank (snap default ON),
so:

  * the **Temple Profile never crosses the snapped blank end** — a closed lap would
    drag the cutter through the core and dull it (`clip_op_at_blank_end`);
  * nesting places a snapped temple **by its blank frame** (blank center → zone
    center), so the core end stays registered against the zone end exactly how the
    blank slides into its slot (`BedPart.place_by_origin`);
  * `temple_snap_transform` exposes the design→blank rigid transform so the 2D view
    back-projects the blank box / datum / toolpath onto the drawing;
  * every model component seeds its OWN `ProgramZero`, so per-component zeros never
    inherit whatever was last on screen.
"""
import pytest
from shapely.geometry import Polygon

from guildmodel.core.cam.castle_ops import CamOp
from guildmodel.core.cam.temple_ops import (
    TEMPLE_CONTOUR_OPS, clip_op_at_blank_end, generate_temple_program,
)
from guildmodel.core.project.schema import BedRole, TempleParams, Worktable, WorktableZone
from guildmodel.core.relief.flat import place_temple_on_blank, temple_snap_transform

TOOLS = {
    "flat_3175": {"diameter_mm": 3.175, "radius_mm": 1.5875, "type": "flat"},
    "flat_2mm": {"diameter_mm": 2.0, "radius_mm": 1.0, "type": "flat"},
    "engrave_vbit": {"diameter_mm": 0.5, "radius_mm": 0.25, "type": "vbit",
                     "included_angle_deg": 30.0},
}


def _temple():
    outline = Polygon([(-60, -6), (60, -6), (60, 6), (-60, 6)])   # long axis x
    hinge = [Polygon([(50, -5), (58, -5), (58, 5), (50, 5)])]      # hinge at +x
    eng = [[(-40.0, 0.0), (40.0, 0.0)]]
    return outline, hinge, eng


# ------------------------------------------------------------ snap transform

def test_snap_transform_matches_place_temple_on_blank():
    outline, hinge, eng = _temple()
    for side in ("right", "left"):
        flipped, dx, dy = temple_snap_transform(
            outline, hinge, 170.0, stock_side=side, snap=True)
        placed, _, _ = place_temple_on_blank(
            outline, hinge, eng, 170.0, stock_side=side, snap=True)
        sgn = -1.0 if flipped else 1.0
        xs = [sgn * x + dx for x, _ in outline.exterior.coords]
        ys = [sgn * y + dy for _, y in outline.exterior.coords]
        want = (min(xs), min(ys), max(xs), max(ys))
        assert placed.bounds == pytest.approx(want)


def test_snap_transform_identity_when_off():
    outline, hinge, _ = _temple()
    assert temple_snap_transform(outline, hinge, 170.0, snap=False) == (False, 0.0, 0.0)


# ------------------------------------------------------------ profile clip

def _ring(z=0.4):
    # closed 30-wide ring straddling the +85 blank end (85 ± 5)
    return [(80, -10, z), (90, -10, z), (90, 10, z), (80, 10, z), (80, -10, z)]


def test_clip_opens_ring_at_blank_end():
    op = CamOp("Temple Profile", tool=TOOLS["flat_3175"])
    op.paths.append(_ring())
    out = clip_op_at_blank_end(op, 170.0, "right")
    assert len(out.paths) == 1                       # seam re-joined: ONE open cut
    path = out.paths[0]
    assert all(x <= 85.0 + 1e-6 for x, _y, _z in path)   # tool center never past the end
    # open: starts and ends ON the blank-end plane, on either side of the butt
    assert path[0][0] == pytest.approx(85.0)
    assert path[-1][0] == pytest.approx(85.0)
    assert path[0][1] != pytest.approx(path[-1][1])      # not a closed lap
    assert {p[2] for p in path} == {0.4}                 # constant-Z pass preserved


def test_clip_left_side_mirrors():
    op = CamOp("Temple Profile", tool=TOOLS["flat_3175"])
    op.paths.append([(-90, -10, 0.4), (-80, -10, 0.4), (-80, 10, 0.4),
                     (-90, 10, 0.4), (-90, -10, 0.4)])
    out = clip_op_at_blank_end(op, 170.0, "left")
    assert len(out.paths) == 1
    assert all(x >= -85.0 - 1e-6 for x, _y, _z in out.paths[0])


def test_clip_keeps_paths_entirely_inside():
    op = CamOp("Temple Profile", tool=TOOLS["flat_3175"])
    inside = [(0, 0, 1.0), (10, 0, 1.0), (10, 5, 1.0), (0, 5, 1.0), (0, 0, 1.0)]
    op.paths.append(inside)
    out = clip_op_at_blank_end(op, 170.0, "right")
    assert out.paths == [inside]


def test_snapped_program_never_crosses_the_core_end():
    outline, hinge, eng = _temple()
    t = TempleParams()                                   # snap ON by default now
    assert t.snap_to_blank_end is True
    o, h, e = place_temple_on_blank(outline, hinge, eng, t.blank_length_mm,
                                    stock_side=t.stock_side, snap=True)
    ops = generate_temple_program(o, e, t, TOOLS, hinge_polys=h)
    profile = next(op for op in ops if op.name in TEMPLE_CONTOUR_OPS)
    half = t.blank_length_mm / 2.0
    for path in profile.paths:
        assert all(x <= half + 1e-6 for x, _y, _z in path)
        # open passes: no closed lap around the butt
        assert not (abs(path[0][0] - path[-1][0]) < 1e-9
                    and abs(path[0][1] - path[-1][1]) < 1e-9)
    # hinge pockets + engraving still cut (they sit inside the blank)
    assert {op.name for op in ops} >= {"Hinge Pockets", "Engraving"}


def test_unsnapped_program_keeps_closed_profile():
    outline, hinge, eng = _temple()
    t = TempleParams(snap_to_blank_end=False)
    ops = generate_temple_program(outline, eng, t, TOOLS, hinge_polys=hinge)
    profile = next(op for op in ops if op.name in TEMPLE_CONTOUR_OPS)
    for path in profile.paths:
        assert (abs(path[0][0] - path[-1][0]) < 1e-9
                and abs(path[0][1] - path[-1][1]) < 1e-9)   # closed laps as before


# ------------------------------------------------------------ core-aligned nesting

def _rect_zone(zid, role, x0, y0, x1, y1):
    return WorktableZone(id=zid, role=role,
                         polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_snapped_temple_nests_by_blank_frame():
    """place_by_origin maps the blank center onto the zone center, so the butt/core
    end (at +L/2 in the blank frame) lands registered against the zone's end."""
    from guildmodel.core.cam.layout import BedPart, nest_components_on_worktable

    bed = Worktable(zones=[_rect_zone("zt", BedRole.TEMPLE_RIGHT, 10, 10, 180, 40)])
    t = TempleParams()
    outline, hinge, eng = _temple()
    o, h, e = place_temple_on_blank(outline, hinge, eng, t.blank_length_mm,
                                    stock_side="right", snap=True)
    ops = generate_temple_program(o, e, t, TOOLS, hinge_polys=h)
    part = BedPart("temple_right", "Temple R", "", ops,
                   set(TEMPLE_CONTOUR_OPS), set(), place_by_origin=True)
    nest = nest_components_on_worktable([part], bed)
    assert len(nest.placements) == 1
    pl = nest.placements[0]
    zone_cx, zone_cy = (10 + 180) / 2.0, (10 + 40) / 2.0
    assert (pl.dx, pl.dy) == (pytest.approx(zone_cx), pytest.approx(zone_cy))
    # the butt end (blank +85) sits at the zone's +x end — core registered there
    max_x = max(x for op in pl.ops for p in op.paths for x, _y, _z in p)
    assert max_x == pytest.approx(zone_cx + t.blank_length_mm / 2.0, abs=2.0)


def test_bbox_centerd_nesting_unchanged_for_frames():
    from guildmodel.core.cam.layout import BedPart, nest_components_on_worktable

    bed = Worktable(zones=[_rect_zone("zf", BedRole.FRAME_FRONT, 0, 0, 100, 60)])
    op = CamOp("Perimeter", tool=TOOLS["flat_3175"])
    op.paths.append([(0, 0, 1.0), (20, 0, 1.0), (20, 10, 1.0), (0, 10, 1.0), (0, 0, 1.0)])
    part = BedPart("frame_front", "Front", "", [op], {"Perimeter"}, set())
    nest = nest_components_on_worktable([part], bed)
    from guildmodel.core.cam.layout import ops_bbox_center
    assert ops_bbox_center(nest.placements[0].ops) == (pytest.approx(50), pytest.approx(30))


# ------------------------------------------------------------ per-component zero seed

def _make_model_gdraw(tmp_path):
    """A minimal .gdraw with a frame front + one temple (for workspace tests)."""
    import json
    import zipfile
    from xml.etree import ElementTree as ET

    ns = "http://www.w3.org/2000/svg"

    def svg(state):
        ET.register_namespace("", ns)
        root = ET.Element(f"{{{ns}}}svg")
        meta = ET.SubElement(root, f"{{{ns}}}metadata")
        meta.text = json.dumps(state)
        return ET.tostring(root, xml_declaration=True, encoding="utf-8")

    def line(layer, pts, closed=False):
        return {"kind": "line", "layer": layer, "closed": closed,
                "nodes": [{"x": x, "y": y} for x, y in pts]}

    states = {
        "front": {"curves": [
            line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
            line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
            line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
        ]},
        "temple_r": {"curves": [
            line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True)]},
        "temple_l": {"curves": []},
        "hinge": {"curves": []},
    }
    path = tmp_path / "model.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", svg(st))
    return path


def test_workspaces_seed_their_own_program_zero(tmp_path):
    """Every model component starts with its OWN ProgramZero object — zeros set on
    one tab can never leak into a component that was merely visited (2026-07-09)."""
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    workspaces, _ = build_workspaces_from_gdraw(_make_model_gdraw(tmp_path))
    zeros = [ws.program_zero for ws in workspaces]
    assert all(z is not None for z in zeros)
    assert len({id(z) for z in zeros}) == len(zeros)      # independent objects


@pytest.mark.gui
def test_gui_program_zero_never_leaks_between_tabs(tmp_path, monkeypatch):
    """Set a zero on the frame, visit the temple: the temple shows its OWN datum
    (the default), not the frame's — and each survives the round trip (2026-07-09;
    previously a first visit inherited whatever zero was on screen)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    from guildmodel.core.project.schema import ProgramZero
    win._load_model(_make_model_gdraw(tmp_path))
    p = win.params

    default = ProgramZero()
    p._set_program_zero(ProgramZero(mode="stock_box", x_ref="right",
                                    y_ref="top", z_ref="top"))
    p.cam_changed.emit()

    win._activate_workspace(1)                                # temple R
    pz = p._program_zero()
    assert (pz.x_ref, pz.y_ref, pz.z_ref) == (default.x_ref, default.y_ref, default.z_ref)

    win._activate_workspace(0)                                # back to the frame
    pz = p._program_zero()
    assert (pz.x_ref, pz.y_ref, pz.z_ref) == ("right", "top", "top")
