"""Per-component 3D for temples + base-curve blocks (BUILDPLAN M7 prerequisite).

Temples and base-curve blocks are flat blanks (no castle relief). `core/relief/flat.py`
builds the same heightfield structure the castle mesher consumes, so `build_castle_mesh`
turns them into watertight solids: an extruded outline, blind HINGE pockets + ENGRAVING
grooves on a temple, and a base-curve block with the lens footprint scribed on top and
the M4 holes as real through-holes. These tests run headless (shapely + numpy + trimesh).
"""
import json
import math
import sys

import pytest
from shapely.geometry import Polygon, box

from guildcam.core.project.schema import BaseCurveBlockParams, TempleParams
from guildcam.core.relief.castle import build_castle_mesh
from guildcam.core.relief.flat import (
    build_block_relief, build_temple_relief, temple_core_guide, temple_snap_offset,
)

RES = 0.4   # coarse for fast tests


# ------------------------------------------------------------------ temple

def _temple_outline():
    # a 120 × 24 temple, long axis x, drawn off the origin
    return box(10.0, 5.0, 130.0, 29.0)


def test_temple_relief_extrudes_to_thickness():
    t = TempleParams()
    relief = build_temple_relief(_temple_outline(), t, resolution=RES)
    z = relief.field.z[relief.inside]
    assert z.max() == pytest.approx(t.blank_thickness_mm)        # 4 mm top
    assert z.min() == pytest.approx(t.blank_thickness_mm)        # no features yet


def test_temple_hinge_pocket_carves_one_mm():
    t = TempleParams()
    hinge = [box(115.0, 11.0, 127.0, 23.0)]                      # pocket near the hinge end
    relief = build_temple_relief(_temple_outline(), t, hinge_polys=hinge, resolution=RES)
    z = relief.field.z[relief.inside]
    assert z.min() == pytest.approx(t.blank_thickness_mm - t.hinge_pocket_depth_mm)  # 3 mm
    assert relief.pocket_polys                                   # walled → rim-conformed


def test_temple_engraving_grooves_are_shallow():
    t = TempleParams()
    engraving = [[(30.0, 17.0), (90.0, 17.0)]]
    relief = build_temple_relief(_temple_outline(), t, engraving_curves=engraving,
                                 resolution=RES)
    z = relief.field.z[relief.inside]
    assert z.min() == pytest.approx(t.blank_thickness_mm - t.engrave_depth_mm)  # 3.7 mm


def test_temple_mesh_is_watertight_solid():
    t = TempleParams()
    hinge = [box(115.0, 11.0, 127.0, 23.0)]
    relief = build_temple_relief(_temple_outline(), t, hinge_polys=hinge, resolution=RES)
    mesh = build_castle_mesh(relief)
    assert mesh.is_watertight
    assert mesh.volume > 0
    zlo, zhi = mesh.bounds[0][2], mesh.bounds[1][2]
    assert (zlo, zhi) == pytest.approx((0.0, t.blank_thickness_mm))


def test_temple_snap_offset_butts_hinge_end_and_centres_width():
    t = TempleParams()
    outline = _temple_outline()                                 # x 10..130, y 5..29
    hinge = [box(115.0, 11.0, 127.0, 23.0)]                     # hinge on the +x end
    dx, dy = temple_snap_offset(outline, hinge, t.blank_length_mm)
    # width centred on the blank
    assert dy == pytest.approx(-(5.0 + 29.0) / 2.0)
    # hinge (+x) extreme lands on +blank_length/2
    assert 130.0 + dx == pytest.approx(t.blank_length_mm / 2.0)


def test_temple_core_guide_runs_from_hinge_end():
    t = TempleParams()
    outline = box(10.0, 5.0, 160.0, 29.0)                      # 150 mm long → 135 fits
    hinge = [box(145.0, 11.0, 157.0, 23.0)]                    # hinge on the +x end
    guide = temple_core_guide(outline, hinge, t)
    gx0, gy0, gx1, gy1 = guide.bounds
    assert (gy1 - gy0) == pytest.approx(t.core_guide_width_mm)   # 2 mm wide
    assert gx1 == pytest.approx(160.0)                          # starts at the hinge (+x) end
    assert (gx1 - gx0) == pytest.approx(t.core_guide_length_mm)  # 135 mm long


def test_core_guide_length_clamps_to_outline():
    t = TempleParams(core_guide_length_mm=200.0)               # longer than the part
    outline = _temple_outline()                                # 120 long
    guide = temple_core_guide(outline, [], t)
    gx0, _, gx1, _ = guide.bounds
    assert (gx1 - gx0) == pytest.approx(120.0)                 # clamped to the outline span


# ------------------------------------------------------------------ base-curve block

def _lens():
    # a rounded-ish lens interior, ~40 × 28
    return Polygon([(0, 0), (40, 2), (42, 18), (38, 28), (4, 26), (-2, 12)])


def test_block_relief_is_the_lens_shape():
    b = BaseCurveBlockParams()                                 # 4.7625 mm thick
    relief = build_block_relief(_lens(), b, resolution=RES)
    z = relief.field.z[relief.inside]
    assert z.max() == pytest.approx(b.blank_thickness_mm)
    assert z.min() == pytest.approx(b.blank_thickness_mm)      # flat top, no scribe
    # the body is the lens shape (centred), not a 70 × 70 box
    lx0, ly0, lx1, ly1 = _lens().bounds
    x0, y0, x1, y1 = relief.partition.body.bounds
    assert (x1 - x0) == pytest.approx(lx1 - lx0, abs=0.01)
    assert (y1 - y0) == pytest.approx(ly1 - ly0, abs=0.01)
    assert (x0 + x1) == pytest.approx(0.0, abs=1e-6)           # centred on origin


def test_block_mesh_has_three_through_holes():
    b = BaseCurveBlockParams()
    relief = build_block_relief(_lens(), b, resolution=RES)
    mesh = build_castle_mesh(relief)
    assert mesh.is_watertight
    # a slab (genus 0) with 3 cylindrical through-holes is genus 3: V−E+F = 2−2·3
    assert mesh.euler_number == -4
    zlo, zhi = mesh.bounds[0][2], mesh.bounds[1][2]
    assert (zlo, zhi) == pytest.approx((0.0, b.blank_thickness_mm))


# ------------------------------------------------------------------ GUI dispatch (guarded)

def _make_model_gdraw(path):
    import json
    import zipfile
    from xml.etree import ElementTree as ET
    ns = "http://www.w3.org/2000/svg"

    def line(layer, pts, closed=False):
        return {"kind": "line", "layer": layer, "closed": closed,
                "nodes": [{"x": x, "y": y} for x, y in pts]}

    def svg(state):
        ET.register_namespace("", ns)
        root = ET.Element(f"{{{ns}}}svg")
        ET.SubElement(root, f"{{{ns}}}metadata").text = json.dumps(state)
        return ET.tostring(root, xml_declaration=True, encoding="utf-8")

    front = {"forming": {"apical_radius_mm": 88.0},
             "curves": [
                 line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], True),
                 line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], True),
                 line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], True),
                 line("SCULPT", [(0, -20), (0, 20)]), line("SCULPT", [(30, -20), (30, 20)])]}
    temple_r = {"curves": [
        line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], True),
        line("HINGE", [(60, -4), (68, -4), (68, 4), (60, 4)], True),
        line("ENGRAVING", [(-40, 0), (40, 0)])]}
    states = {"front": front, "temple_r": temple_r, "temple_l": {"curves": []},
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", svg(st))
    return path


def test_build_3d_dispatch_wired_for_temple_and_block(tmp_path, monkeypatch):
    """A temple tab → flat 'temple' build; a base-curve tab → 'block' build; Build
    3D is enabled for both. Skipped without a Qt platform (no VTK render here)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from guildcam.core.project.schema import ComponentKind

    try:
        QApplication.instance() or QApplication([])
        from guildcam.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                      # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    win._load_model(_make_model_gdraw(tmp_path / "model.gdraw"))
    by_kind = {w.kind: i for i, w in enumerate(win._workspaces)}

    win._activate_workspace(by_kind[ComponentKind.TEMPLE_RIGHT])
    assert win._flat_build_mode() == "temple"
    assert win._act_build.isEnabled()
    assert win._flat_stock().blank_length_mm == pytest.approx(170.0)

    bc = by_kind.get(ComponentKind.BASE_CURVE_RIGHT, by_kind.get(ComponentKind.BASE_CURVE_LEFT))
    win._activate_workspace(bc)
    assert win._flat_build_mode() == "block"
    assert win._act_build.isEnabled()
    assert win._flat_stock().blank_thickness_mm == pytest.approx(4.7625)

    win._activate_workspace(by_kind[ComponentKind.FRAME_FRONT])
    assert win._flat_build_mode() is None                        # castle path


def test_open_drawing_rename_and_view_persistence(tmp_path, monkeypatch):
    """The menu says 'Open Drawing…'; Build 3D targets every buildable component;
    the active view follows tab switches and the 3D reflects the active tab."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from guildcam.core.project.schema import ComponentKind

    try:
        QApplication.instance() or QApplication([])
        from guildcam.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                      # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    assert win._act_open_model.text() == "Open Drawing…"

    win._load_model(_make_model_gdraw(tmp_path / "model.gdraw"))
    # stub the VTK render so the view logic is exercised without a GPU
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.clear = lambda: None
    by_kind = {w.kind: i for i, w in enumerate(win._workspaces)}

    # Build 3D targets: the temple + both base-curve blocks (the synthetic frame
    # isn't a *matched* castle, so it's excluded — same gate as a single frame).
    targets = win._buildable_workspaces()
    assert by_kind[ComponentKind.TEMPLE_RIGHT] in targets
    assert by_kind[ComponentKind.BASE_CURVE_RIGHT] in targets
    assert by_kind[ComponentKind.BASE_CURVE_LEFT] in targets

    # view tracking: 3D persists, the Worktable page doesn't overwrite it. The bed
    # is shown outside _switch_view (its own page), so the remembered component view
    # (3D) is untouched — and the merged viewer keeps 3D model + cut sim on one page.
    win._activate_workspace(by_kind[ComponentKind.FRAME_FRONT])
    win._switch_view(1)
    assert win._last_component_view == 1
    assert win.stack.currentIndex() == 1 and win.view3d.mode() == "model"
    win._switch_view(2)                                          # cut-sim mode, same VTK page
    assert win.stack.currentIndex() == 1 and win.view3d.mode() == "sim"
    win._switch_view(1)
    win.stack.setCurrentIndex(win._worktable_page_index)         # peek at the bed
    assert win._last_component_view == 1                         # unchanged by the bed page

    # a built mesh for the frame + a temple; none for the base-curve
    win._activate_workspace(by_kind[ComponentKind.FRAME_FRONT])
    win._switch_view(1)
    win._stage_cache[win._stage] = object()                     # fake frame mesh
    assert win._has_active_3d()
    win._workspaces[by_kind[ComponentKind.TEMPLE_RIGHT]].stage_cache["flat"] = object()

    win._activate_workspace(by_kind[ComponentKind.TEMPLE_RIGHT])
    assert win.stack.currentIndex() == 1                        # 3D persisted (mesh exists)

    bc = by_kind[ComponentKind.BASE_CURVE_RIGHT]
    win._activate_workspace(bc)
    assert win.stack.currentIndex() == 0                        # fell back to 2D (not built)


def test_multi_mesh_worker_builds_all_in_one_pass(tmp_path, monkeypatch):
    """Build 3D builds every component in ONE worker/thread (no per-component thread
    churn — that was crashing). Driven synchronously here: no threads, no VTK."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildcam.gui.app import MultiMeshWorker

    specs = [
        {"index": 1, "mode": "temple", "label": "Temple R",
         "outline": _temple_outline(), "temple": TempleParams(),
         "hinge": [box(115.0, 11.0, 127.0, 23.0)], "engraving": [[(30.0, 17.0), (90.0, 17.0)]]},
        {"index": 3, "mode": "block", "label": "Base Curve R",
         "lens": _lens(), "block": BaseCurveBlockParams()},
    ]
    w = MultiMeshWorker(specs, resolution=0.6)
    built, done, errors = [], [], []
    w.built.connect(lambda i, m, g: built.append((i, m, g)))
    w.finished.connect(lambda: done.append(True))
    w.error.connect(lambda tb: errors.append(tb))
    w.run()

    assert errors == []
    assert done == [True]
    assert [b[0] for b in built] == [1, 3]                      # both, in order
    assert all(b[1].is_watertight for b in built)              # watertight solids
    assert built[0][2] is not None                             # temple carries a core guide
    assert built[1][2] is None                                 # block does not


def test_startup_with_saved_cam_params_does_not_raise(tmp_path, monkeypatch):
    """Persisted CAM params are restored at startup, firing cam_changed → the
    program-zero/stock markers, which read the geometry state. Regression: that
    state must exist before signals connect (was 'AttributeError: _is_temple')."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    prefs_dir = tmp_path / ".guildcam"
    prefs_dir.mkdir(parents=True, exist_ok=True)
    (prefs_dir / "prefs.json").write_text(json.dumps(
        {"cam_params": {"tool_name": "flat_3175"}, "material_name": "acetate"}))

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    recorded: list = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *a: recorded.append(a)      # PySide routes swallowed slot errors here
    try:
        from guildcam.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                            # pragma: no cover
        sys.excepthook = old_hook
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    finally:
        sys.excepthook = old_hook

    assert recorded == []                              # no swallowed startup exception
    assert win._active_is_flat() is False              # geometry state exists + callable
    win._update_program_zero_marker()                  # the path that crashed at startup


def _drive_sim(worker):
    done, errs = [], []
    worker.finished.connect(lambda rep, lines: done.append(rep))
    worker.error.connect(lambda tb: errs.append(tb))
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert len(done) == 1
    return done[0]


def test_flat_sim_worker_simulates_temple_and_block(tmp_path, monkeypatch):
    """Cut simulation now runs on flat parts (BUILDPLAN M7): the FlatSimWorker builds
    the relief target, posts the program, sweeps the tools, and verifies — reaching
    the flat top + features. Driven synchronously here: no threads, no VTK."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildcam.gui.app import FlatSimWorker
    from guildcam.core.project.schema import CastleCamParams

    # a temple with engraving (no hinge pocket → the program cuts what it targets)
    rep_t = _drive_sim(FlatSimWorker(
        "temple", outline=_temple_outline(), temple=TempleParams(),
        engraving=[[(30.0, 17.0), (90.0, 17.0)]], cam_params=CastleCamParams(),
        material_name="acetate", resolution=0.8))
    assert rep_t.completeness.uncut_fraction < 0.05    # flat top + groove reached
    assert rep_t.floor.shape == rep_t.target.shape     # a renderable CutReport

    rep_b = _drive_sim(FlatSimWorker(
        "block", lens=_lens(), block=BaseCurveBlockParams(),
        cam_params=CastleCamParams(), material_name="acetate", resolution=0.8))
    assert rep_b.completeness.uncut_fraction < 0.05    # flat lens shape reached


def test_flat_sim_worker_temple_mills_hinge_pocket(monkeypatch):
    """With HINGE geometry the temple program now mills the pocket, so the sim
    target (which carves it) is still reached — model, sim, and G-code agree on
    the recess (BUILDPLAN M7: temple hinge-pocket CAM gap closed)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildcam.gui.app import FlatSimWorker
    from guildcam.core.project.schema import CastleCamParams

    hinge = [box(115.0, 11.0, 127.0, 23.0)]            # a 12 × 12 recess near the hinge end
    rep = _drive_sim(FlatSimWorker(
        "temple", outline=_temple_outline(), temple=TempleParams(), hinge_polys=hinge,
        engraving=[[(30.0, 17.0), (90.0, 17.0)]], cam_params=CastleCamParams(),
        material_name="acetate", resolution=0.8))
    # the pocket floor is cut by the program → the target is reached almost everywhere
    # (a thin tool-radius band at the pocket walls is the only honest leftover)
    assert rep.completeness.uncut_fraction < 0.10
