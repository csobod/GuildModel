"""The 2.1 bug hunt (2026-11-03): what three reviews of the 2026-11-01/02
rounds found, fixed and held here.

Two-sided is the open part's own choice; a temple's meshes never mirror and
its face list speaks of hinge face and outer face; the drag's overlay is put
away when its row goes; a source shared by several meshes is repaired once;
the repair record's counters say what happened; a simplified sculpt keeps
the back it had; the temple planner survives an empty tool library.
"""
import numpy as np
import pytest
import trimesh
from shapely.geometry import box

from guildmodel.core.project.schema import (CastleCamParams, ComponentCamOverrides,
                                            SculptFeature, SculptMount, TempleParams)


def _qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_two_sided_is_the_parts_own_choice():
    cam = CastleCamParams()
    assert cam.two_sided == "auto"
    ov = ComponentCamOverrides(two_sided="off", two_sided_output="one_file")
    assert ov.apply(cam).two_sided == "off" and ov.apply(cam).two_sided_output == "one_file"
    assert ComponentCamOverrides().apply(cam) is cam           # nothing set: inherits
    assert ComponentCamOverrides().is_empty()
    # a 2.0 project's overrides carry no two-sided field and read as inheriting
    old = ComponentCamOverrides.model_validate({"material": "acetal"})
    assert old.two_sided is None and old.apply(cam).two_sided == "auto"


def test_the_panel_keeps_each_parts_two_sided_apart(tmp_path, monkeypatch):
    _qapp(monkeypatch)
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    p.set_cam_params(CastleCamParams())                       # the project: Auto
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    p.set_cam_overrides(None)
    assert p.two_sided.currentIndex() == 0
    # the front switched Off: its own override, the project's default untouched
    p.two_sided.setCurrentIndex(1)
    assert p.cam_overrides().two_sided == "off"
    assert p.cam_params().two_sided == "auto"
    assert p.effective_cam_params().two_sided == "off"
    front_ov = p.cam_overrides()
    # the temple opens with its own (none yet): the project's Auto
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.set_cam_overrides(ComponentCamOverrides())
    assert p.two_sided.currentIndex() == 0
    assert p.cam_overrides().two_sided == "auto"
    assert p.effective_cam_params().two_sided == "auto"
    p.two_sided_output.setCurrentIndex(1)
    assert p.cam_overrides().two_sided_output == "one_file"
    # back to the front: still Off, two files
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    p.set_cam_overrides(front_ov)
    assert p.two_sided.currentIndex() == 1 and p.two_sided_output.currentIndex() == 0
    assert not p.two_sided_output.isEnabled() and not p.probe_block.isEnabled()
    # a project whose default is On shows On where a part has no choice of its own
    p.set_cam_params(CastleCamParams(two_sided="on"))
    p.set_cam_overrides(None)
    assert p.two_sided.currentIndex() == 2 and p.cam_params().two_sided == "on"


def test_a_temples_meshes_never_mirror_and_its_faces_have_their_own_names(monkeypatch):
    f = SculptFeature(id="m1", label="crest", op="deboss", mirror=True,
                      mount=SculptMount(face="anterior"))
    t = TempleParams(sculpts=[f, f.model_copy(update={"id": "m2", "enabled": False})])
    resolved = t.resolved_sculpts()
    assert [s.id for s in resolved] == ["m1"] and not resolved[0].mirror
    assert t.sculpts[0].mirror                                 # the record keeps what it was
    _qapp(monkeypatch)
    from guildmodel.gui.widgets.embossing_group import EmbossingGroup
    temple = EmbossingGroup("temple")
    assert temple.sc_mirror.isHidden()
    assert [temple.sc_face.itemText(i) for i in range(temple.sc_face.count())] == [
        "Hinge face (top)", "Outer face (bottom)", "Edge"]
    assert "flip setup" not in temple.sc_face.toolTip()
    temple.set_sculpts([f])
    assert "outer face" in temple.sculpt_list.item(0).text()
    front = EmbossingGroup("front")
    assert not front.sc_mirror.isHidden()
    assert front.sc_face.itemText(1) == "Anterior (front)"
    assert "flip setup" not in front.sc_face.toolTip()
    front.set_sculpts([f])
    assert "front" in front.sculpt_list.item(0).text()


def test_the_drag_is_put_away_when_its_row_goes(monkeypatch):
    _qapp(monkeypatch)
    from guildmodel.gui.widgets.embossing_group import EmbossingGroup
    g = EmbossingGroup("front")
    a = SculptFeature(id="a", label="a", mount=SculptMount(face="posterior"))
    b = a.model_copy(update={"id": "b", "label": "b"})
    g.set_sculpts([a, b])
    asked = []
    g.handle_requested.connect(lambda row, on: asked.append((row, on)))
    g.sculpt_list.setCurrentRow(0)
    g.sc_handle.setChecked(True)
    assert asked == [(0, True)]
    # selecting another row releases the drag, whatever the loading guard
    g.sculpt_list.setCurrentRow(1)
    assert asked[-1] == (0, False) and not g.sc_handle.isChecked()
    # removing the dragged row releases it too
    g.sc_handle.setChecked(True)
    assert asked[-1] == (1, True)
    g._on_sculpt_remove()
    assert (1, False) in asked[-2:] and not g.sc_handle.isChecked()
    assert [f.id for f in g.sculpts()] == ["a"]
    # and so does a fresh list of records
    g.sc_handle.setChecked(True)
    n = len(asked)
    g.set_sculpts([a])
    assert asked[n] == (0, False) and not g.sc_handle.isChecked()
    # nothing is said when no drag was on
    n = len(asked)
    g.set_sculpts([a, b])
    assert len(asked) == n


def _box_stl(size=4.0):
    return trimesh.exchange.stl.export_stl(trimesh.creation.box((size, size, 1.5)))


def test_a_shared_source_is_repaired_once_for_a_flat_part(monkeypatch):
    from guildmodel.core.model import sculpt as sculpt_mod
    from guildmodel.core.model.sculpt import flat_back, load_sculpt, mount_transform, snap_target
    from guildmodel.core.relief import flat as flat_mod
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_mesh
    from guildmodel.core.relief.flat import build_temple_relief, emboss_flat_relief
    data = _box_stl()
    src = load_sculpt(data, "box.stl")
    src.back = flat_back(src.mesh)[0]
    outline = box(-70.0, -6.0, 70.0, 6.0)
    t = TempleParams()
    relief = build_temple_relief(outline, t, resolution=CUT_RES_MM)
    host = build_castle_mesh(relief)
    feats = []
    for x in (-40.0, -20.0, 20.0):
        target = snap_target(host, "posterior", (x, 0.0))
        T = mount_transform(src.back, target, overlap_mm=0.5, flip=True, height_mm=src.height_mm)
        feats.append(SculptFeature(
            id=f"d{int(x)}", source_name="box.stl", source_sha256=src.sha256,
            height_mm=src.height_mm, extent_mm=src.extent_mm, op="deboss",
            mount=SculptMount(face="posterior", point=[float(v) for v in target.point],
                              normal=[float(v) for v in target.normal], overlap_mm=0.5,
                              flip=True)).with_transform(T))
    calls = []
    real = sculpt_mod.load_sculpt

    def counted(*a, **k):
        calls.append(a[1] if len(a) > 1 else k.get("name"))
        return real(*a, **k)

    monkeypatch.setattr(sculpt_mod, "load_sculpt", counted)
    baked = emboss_flat_relief(relief, feats, {src.sha256: data})
    assert len(calls) == 1                                     # one source, one repair
    assert len(baked.relief.sculpt_footprints) == 3            # three imprints all the same
    assert baked.mesh.volume < baked.host.volume


def test_the_repair_record_counts_what_happened():
    from guildmodel.core.model.sculpt import _construct, load_sculpt
    b = trimesh.creation.box((4.0, 4.0, 1.5))
    v, f = np.asarray(b.vertices), np.asarray(b.faces)
    info = {"flipped": 0}
    assert _construct(v, f, info) is not None and info["flipped"] == 0
    info = {"flipped": 0}
    assert _construct(v, f[:, ::-1], info) is not None and info["flipped"] == 1
    # a sheet with no volume is nothing, and not counted as turned over
    info = {"flipped": 0}
    flat = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    assert _construct(flat, np.array([[0, 1, 2], [0, 2, 3]]), info) is None
    assert info["flipped"] == 0
    src = load_sculpt(trimesh.exchange.stl.export_stl(b.copy().invert()), "inv.stl")
    assert src.flipped == 1 and any("inside-out" in n for n in src.notes())
    plain = load_sculpt(trimesh.exchange.stl.export_stl(b), "box.stl")
    assert plain.flipped == 0 and not any("inside-out" in n for n in plain.notes())


def test_a_simplified_sculpt_keeps_the_back_it_had():
    from guildmodel.core.model.sculpt import flat_back, load_sculpt
    # a wedge: a large sloped face and a small flat bottom; the bottom is the back
    m = trimesh.creation.box((10.0, 10.0, 1.0))
    m.vertices[m.vertices[:, 2] > 0, 2] += np.where(m.vertices[m.vertices[:, 2] > 0, 0] > 0, 6.0, 0.0)
    m = trimesh.Trimesh(m.vertices, m.faces, process=True)
    src = load_sculpt(trimesh.exchange.stl.export_stl(m), "wedge.stl")
    cands = flat_back(src.mesh)
    bottom = min(cands, key=lambda c: float(c.normal[2]))      # the one that faces down
    src.back = bottom
    out = src.simplified(0.2)
    assert out.back is not None
    assert float(np.asarray(out.back.normal) @ np.asarray(bottom.normal)) > 0.99


def test_one_plane_in_pieces_is_one_back_whatever_its_normals_rounding():
    from guildmodel.core.model.sculpt import flat_back
    # two blocks whose bottoms share one plane, the normals nudged a hair apart
    a = trimesh.creation.box((4.0, 4.0, 2.0)).apply_translation((-3.0, 0.0, 1.0))
    b = trimesh.creation.box((4.0, 4.0, 2.0)).apply_translation((3.0, 0.0, 1.0))
    m = trimesh.util.concatenate([a, b])
    cands = flat_back(m)
    bottoms = [c for c in cands if c.normal[2] < -0.99]
    assert len(bottoms) == 1 and bottoms[0].area == pytest.approx(32.0, rel=1e-3)


def test_the_temple_planner_without_a_tool_library_posts_the_temple_alone():
    from guildmodel.core.cam.two_sided import plan_temple_two_sided
    from guildmodel.core.geometry.inlays import ordered, reconcile
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.relief.flat import build_temple_relief
    outline = box(-80.0, -6.0, 60.0, 6.0)
    polys = ordered([box(-40.0, -3.0, -10.0, 3.0)], [])
    t = TempleParams()
    t.inlays = reconcile([], polys, [])
    relief = build_temple_relief(outline, t, [], [], inlay_polys=polys, resolution=CUT_RES_MM)
    job = plan_temple_two_sided(relief, t, [], CastleCamParams(), None, outline=outline,
                                inlay_polys=polys)
    assert not job.two_sided and any("No tool library" in n for n in job.notes)
