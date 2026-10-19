"""Sculpts on screen (BUILDPLAN M22 §7.4), without a MainWindow.

The Sculpts group on the Model tab keeps the records and says when one
moved; the viewer's handle puts pyvista's affine widget on the placed sculpt
and hands the drag back once; the build spec carries the STL bytes to the
mesh kernel, which bakes them in.
"""
import numpy as np
import pytest
import trimesh

from guildmodel.core.project.schema import CastleParams, SculptFeature, SculptMount

pytest.importorskip("PySide6.QtWidgets")


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
    assert "Sculpts  (your own meshes, embossed or debossed)" in p._folds
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
    p.sc_op.setCurrentIndex(1)
    p.sc_mirror.setChecked(True)
    assert p.sculpts()[1].op == "deboss" and p.sculpts()[1].mirror
    assert heard == ["castle", "castle"]
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

class _Widget:
    def __init__(self):
        self.removed = False

    def remove(self):
        self.removed = True


class _Plotter:
    def __init__(self):
        self.actors: dict = {}
        self.widgets: list = []
        self.renders = 0

    def clear(self):
        self.actors.clear()

    def add_mesh(self, mesh, name=None, **kw):
        self.actors[name or f"actor{len(self.actors)}"] = mesh
        return object()

    def add_affine_transform_widget(self, actor, release_callback=None, **kw):
        w = _Widget()
        w.release = release_callback
        self.widgets.append(w)
        return w

    def remove_actor(self, name, render=True):
        self.actors.pop(name, None)

    def reset_camera(self, render=False):
        pass

    def render(self):
        self.renders += 1


@pytest.fixture
def viewer(qapp, monkeypatch):
    from guildmodel.gui.widgets.viewer_3d import Viewer3D

    def fake_ensure(self):
        if self._plotter is None:
            self._plotter = _Plotter()
        return True
    monkeypatch.setattr(Viewer3D, "_ensure_plotter", fake_ensure)
    monkeypatch.setattr(Viewer3D, "_safe_render", lambda self: self._plotter.render())
    monkeypatch.setattr(Viewer3D, "_apply_scene_lights", lambda self: None)
    return Viewer3D()


def test_the_handle_attaches_fires_release_once_and_comes_down(viewer):
    v = viewer
    dome = trimesh.creation.icosphere(subdivisions=2, radius=3.0)
    got = []
    v.show_sculpt_handle(dome, got.append)
    assert v.sculpt_handle_active and "sculptHandle" in v._plotter.actors
    assert len(v._plotter.widgets) == 1
    M = np.eye(4)
    M[:3, 3] = [1.0, 2.0, 3.0]
    v._plotter.widgets[0].release(M)
    assert len(got) == 1 and np.allclose(got[0], M)
    # a second show replaces the first: one widget live, the old one removed
    v.show_sculpt_handle(dome, got.append)
    assert v._plotter.widgets[0].removed and len(v._plotter.widgets) == 2
    v.clear_sculpt_handle()
    assert not v.sculpt_handle_active and "sculptHandle" not in v._plotter.actors
    assert v._plotter.widgets[1].removed
    v._plotter.widgets[1].release(M)                 # a late release is dropped
    assert len(got) == 1


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
    assert spec["sculpt_sources"][src.sha256] == data        # the bytes are left as they came
    # the raster kernel does not know sculpts, and says nothing
    raster, _, _ = build_component_mesh(spec, resolution=0.3, kernel="raster")
    assert raster.volume == pytest.approx(
        build_component_mesh(demo_spec, resolution=0.3, kernel="raster")[0].volume)
