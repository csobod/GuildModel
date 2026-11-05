"""Sculpts on screen (BUILDPLAN M22 §7.4, the drag redone in §7.8), without
a MainWindow.

The Sculpts group on the Model tab keeps the records and says when one
moved; the viewer's overlay slides the placed sculpt over the model under
the cursor and hands the placement back once; the build spec carries the
STL bytes to the mesh kernel, which bakes them in.
"""
import numpy as np
import pytest
import trimesh

from guildmodel.core.project.schema import CastleParams, SculptFeature, SculptMount

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QEvent, Qt                          # noqa: E402
from PySide6.QtWidgets import QWidget                          # noqa: E402


@pytest.fixture
def qapp(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _feature(i=1, **kw):
    base = dict(id=f"sculpt_{i}", label=f"Crest {i}", source_name="dome.stl",
                source_sha256="a" * 64, triangles=2686,
                mount=SculptMount(face="posterior", point=[1.0, 2.0, 4.0],
                                  normal=[0.0, 0.0, 1.0], overlap_mm=0.05))
    base.update(kw)
    return SculptFeature(**base)


# ------------------------------------------------------------- the panel

def test_the_sculpts_group_keeps_the_records_and_rides_the_castle_params(qapp):
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    from guildmodel.gui.widgets.params_panel import SCULPTS_FOLD
    assert SCULPTS_FOLD in p._folds and p._folds[SCULPTS_FOLD].header.text() == "Embossing"
    assert p.castle_params().sculpts == []
    heard = []
    p.castle_changed.connect(lambda: heard.append("castle"))
    row = p.add_sculpt(_feature())
    assert row == 0 and heard == ["castle"]
    assert p.sculpt_list.count() == 1 and "Crest 1" in p.sculpt_list.item(0).text()
    assert p.castle_params().sculpts[0].id == "sculpt_1"
    # a second with the same id gets its own
    p.add_sculpt(_feature(label="Twin"))
    assert [f.id for f in p.sculpts()] == ["sculpt_1", "sculpt_2"]
    # the editor edits the record's own fields and says the castle changed
    p.sculpt_list.setCurrentRow(1)
    heard.clear()
    moved = []
    p.sculpt_mount_changed.connect(lambda row, requery: moved.append((row, requery)))
    p.sc_op.setCurrentIndex(1)
    p.sc_mirror.setChecked(True)
    assert p.sculpts()[1].op == "deboss" and p.sculpts()[1].mirror
    # the op switch flips the mount and asks the window to re-place it (which
    # rebuilds); the mirror is the record's own and says the castle changed
    assert heard == ["castle"] and moved == [(1, False)]
    assert "deboss" in p.sculpt_list.item(1).text() and "⇔" in p.sculpt_list.item(1).text()
    # restoring from params brings every record back
    castle = CastleParams(sculpts=[_feature(3)])
    p.set_castle_params(castle)
    assert [f.id for f in p.sculpts()] == ["sculpt_3"]
    assert p.sc_label.text() == "Crest 3"


def test_a_mount_edit_says_which_row_moved_and_whether_the_face_did(qapp):
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    moved = []
    p.sculpt_mount_changed.connect(lambda row, face: moved.append((row, face)))
    castle_heard = []
    p.castle_changed.connect(lambda: castle_heard.append(1))
    p.add_sculpt(_feature())
    castle_heard.clear()
    p.sc_scale.setValue(2.0)
    assert moved == [(0, False)] and p.sculpts()[0].scale == 2.0
    assert castle_heard == []                        # the window rebuilds after the snap
    p.sc_face.setCurrentIndex(1)                     # anterior
    assert moved[-1] == (0, True) and p.sculpts()[0].mount.face == "anterior"
    p.sc_flush.setChecked(True)
    assert p.sculpts()[0].mount.flush and p.sculpts()[0].mount.overlap_mm == 0.0
    assert not p.sc_overlap.isEnabled()
    # the window writes the placed record back without a signal
    placed = p.sculpts()[0].with_transform(np.diag([1.0, 1.0, 1.0, 1.0])).model_copy(
        update={"mount": p.sculpts()[0].mount.model_copy(update={"overlap_mm": 0.3})})
    moved.clear()
    p.set_sculpt(0, placed)
    assert moved == [] and p.sculpts()[0].mount.overlap_mm == 0.3
    asked = []
    p.sculpt_resnap_requested.connect(asked.append)
    p.sc_resnap.click()
    assert asked == [0]
    handle = []
    p.sculpt_handle_requested.connect(lambda r, on: handle.append((r, on)))
    p.sc_handle.setChecked(True)
    p.sc_handle.setChecked(False)
    assert handle == [(0, True), (0, False)]


# ------------------------------------------------------------- the viewer

class _Actor:
    def __init__(self):
        self.user_matrix = np.eye(4)


class _Plotter(QWidget):
    """Enough of a QtInteractor for the overlay: a widget the event filter
    sees, actors by name, a camera and a renderer the pick never reaches
    (the pick itself is replaced in the tests)."""

    def __init__(self):
        super().__init__()
        self.actors: dict = {}
        self.renders = 0
        self.renderer = object()
        self.camera = type("Cam", (), {"position": (0.0, 0.0, 100.0)})()
        self.resize(400, 300)

    def clear(self):
        self.actors.clear()

    def add_mesh(self, mesh, name=None, **kw):
        a = _Actor()
        self.actors[name or f"actor{len(self.actors)}"] = a
        return a

    def remove_actor(self, name, render=True):
        self.actors.pop(name, None)

    def reset_camera(self, render=False):
        pass

    def render(self):
        self.renders += 1

    def set_background(self, *a, **k):
        pass

    def enable_anti_aliasing(self):
        pass


@pytest.fixture
def viewer(qapp, monkeypatch):
    from guildmodel.gui.widgets.viewer_3d import Viewer3D

    def fake_ensure(self):
        if self._plotter is None:
            self._plotter = _Plotter()
            self._plotter.installEventFilter(self)
        return True
    monkeypatch.setattr(Viewer3D, "_ensure_plotter", fake_ensure)
    monkeypatch.setattr(Viewer3D, "_safe_render", lambda self: self._plotter.render())
    monkeypatch.setattr(Viewer3D, "_apply_scene_lights", lambda self: None)
    return Viewer3D()


def _mouse(kind, x, y, button=Qt.MouseButton.LeftButton):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    buttons = button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons,
                       Qt.KeyboardModifier.NoModifier)


def test_the_overlay_drags_over_the_surface_and_commits_once(viewer, monkeypatch):
    """A press on the overlay takes the mouse from the camera; every move
    casts the cursor on the model and previews the placement with the grab
    offset; the release commits once; a press beside it passes through."""
    v = viewer
    v._ensure_plotter()
    dome = trimesh.creation.icosphere(subdivisions=2, radius=3.0)
    model_actor = _Actor()
    v._model_actor = model_actor
    hits = {"overlay": None, "model": None}

    def fake_pick(self, x, y, actors):
        a = actors[0]
        key = "overlay" if a is self._sculpt_actor else "model"
        h = hits[key]
        return None if h is None else (np.asarray(h[0], float), np.asarray(h[1], float), a)
    monkeypatch.setattr(type(v), "_pick", fake_pick)

    previews, commits = [], []

    def preview(point, normal, offset):
        previews.append((point.copy(), normal.copy(), offset.copy()))
        M = np.eye(4)
        M[:3, 3] = point
        return M

    def commit(point, normal, offset):
        commits.append((point.copy(), normal.copy(), offset.copy()))

    v.show_sculpt_overlay(dome, anchor=[1.0, 2.0, 4.0], preview=preview, commit=commit)
    assert v.sculpt_overlay_active and "sculptHandle" in v._plotter.actors
    pl = v._plotter
    # a press beside the overlay is the camera's
    hits["overlay"] = None
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseButtonPress, 10, 10)) is False
    assert v._sculpt_drag is None
    # a press on it starts the drag with the anchor's offset from the grab
    hits["overlay"] = ([0.5, 2.0, 4.0], [0, 0, 1])
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseButtonPress, 10, 10)) is True
    assert v._sculpt_drag is not None and np.allclose(v._sculpt_drag["offset"], [0.5, 0, 0])
    # a move over the model previews the placement under the cursor
    hits["model"] = ([7.0, 8.0, 4.0], [0, 0, 1])
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseMove, 20, 20)) is True
    assert len(previews) == 1 and np.allclose(previews[0][0], [7, 8, 4])
    assert np.allclose(previews[0][2], [0.5, 0, 0])
    assert np.allclose(v._sculpt_actor.user_matrix[:3, 3], [7, 8, 4])
    # a move off the model keeps the last preview and still owns the mouse
    hits["model"] = None
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseMove, 30, 30)) is True
    assert len(previews) == 1
    # the release commits the last hit once
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseButtonRelease, 30, 30)) is True
    assert len(commits) == 1 and np.allclose(commits[0][0], [7, 8, 4])
    assert v._sculpt_drag is None
    # a release with nothing in flight passes through
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseButtonRelease, 30, 30)) is False
    # clearing takes the overlay down, and a later event is nobody's
    v.clear_sculpt_overlay()
    assert not v.sculpt_overlay_active and "sculptHandle" not in pl.actors
    hits["overlay"] = ([0.5, 2.0, 4.0], [0, 0, 1])
    assert v.eventFilter(pl, _mouse(QEvent.Type.MouseButtonPress, 10, 10)) is False


def test_pick_surface_reads_the_model_under_a_point(viewer, monkeypatch):
    v = viewer
    v._ensure_plotter()
    assert v.pick_surface(v._plotter.rect().center()) is None      # no model yet
    v._model_actor = _Actor()
    monkeypatch.setattr(type(v), "_pick", lambda self, x, y, actors: (
        np.array([1.0, 2.0, 3.0]), np.array([0.0, 0.0, 1.0]), actors[0]))
    hit = v.pick_surface(v._plotter.rect().center())
    assert hit is not None and np.allclose(hit[0], [1, 2, 3]) and np.allclose(hit[1], [0, 0, 1])
    # a point outside the plotter is off the model
    from PySide6.QtCore import QPoint
    assert v.pick_surface(QPoint(-50, -50)) is None


def test_display_coordinates_flip_y(viewer):
    from PySide6.QtCore import QPoint
    v = viewer
    v._ensure_plotter()
    v._plotter.resize(400, 300)
    x, y = v._display_xy(QPoint(10, 20))
    assert x == pytest.approx(10 * v._plotter.devicePixelRatioF())
    assert y == pytest.approx((300 - 20 - 1) * v._plotter.devicePixelRatioF())


# ------------------------------------------------------------- the build

@pytest.fixture(scope="module")
def demo_spec():
    from pathlib import Path
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    root = Path(__file__).parents[1]
    raw = import_dxf(root / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    return {"mode": "castle", "partition": partition_zones(outline, lenses, raw["SCULPT"]),
            "castle": CastleParams(), "hinge": hinges, "stage": "pockets", "inlay": []}


def test_the_spec_carries_the_bytes_and_the_mesh_kernel_bakes_them(demo_spec):
    from guildmodel.core.model.sculpt import (default_overlap, flat_back, load_sculpt,
                                              mount_transform, sag_under, snap_target)
    from guildmodel.gui.mesh_build import build_component_mesh

    plain, _, _ = build_component_mesh(demo_spec, resolution=0.3, kernel="mesh")
    sph = trimesh.creation.icosphere(subdivisions=3, radius=3.0)
    dome = trimesh.intersections.slice_mesh_plane(sph, plane_normal=[0, 0, 1],
                                                  plane_origin=[0, 0, 0], cap=True)
    data = trimesh.exchange.stl.export_stl(dome)
    src = load_sculpt(data, "dome.stl")
    back = flat_back(src.mesh)[0]
    at = np.asarray(plain.bounds).mean(axis=0)[:2]
    target = snap_target(plain, "posterior", at)
    overlap = default_overlap(sag_under(plain, back, src.mesh,
                                        mount_transform(back, target, overlap_mm=0.0), target))
    feature = SculptFeature(id="crest", source_name="dome.stl", source_sha256=src.sha256,
                            mount=SculptMount(face="posterior", point=[float(at[0]), float(at[1]),
                                                                       float(target.point[2])],
                                              normal=[0.0, 0.0, 1.0], overlap_mm=overlap)
                            ).with_transform(mount_transform(back, target, overlap_mm=overlap))
    castle = CastleParams(sculpts=[feature])
    spec = dict(demo_spec, castle=castle, sculpt_sources={src.sha256: data})
    with_sculpt, _, _ = build_component_mesh(spec, resolution=0.3, kernel="mesh")
    assert with_sculpt.is_watertight
    assert with_sculpt.volume > plain.volume + 0.9 * src.volume
    # the surface without the sculpt rides along, for the snaps and the drag
    host = with_sculpt.metadata["sculpt_host"]
    assert host.volume == pytest.approx(plain.volume, rel=1e-6)
    assert "sculpt_host" not in plain.metadata
    assert spec["sculpt_sources"][src.sha256] == data        # the bytes are left as they came
    # the raster kernel does not know sculpts, and says nothing
    raster, _, _ = build_component_mesh(spec, resolution=0.3, kernel="raster")
    assert raster.volume == pytest.approx(
        build_component_mesh(demo_spec, resolution=0.3, kernel="raster")[0].volume)
