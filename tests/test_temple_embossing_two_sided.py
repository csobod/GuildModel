"""A temple's meshes and its second side (2026-11-02): what the front has had,
where a temple can take it.

A mesh debossed on the hinge face is baked into the temple's solid and cut
into the map the program and the simulation read, by an Embossing op on the
temple's ball nose, in the first tier beside the pockets. One debossed on the
outer face goes into the anterior map, which a one-sided job models and never
posts, and a two-sided job cuts first: the outer face up, mirrored about the
blank's center line, in G55, then the flip, then the temple program as a
one-sided job posts it. An emboss stands above the blank's face and is
modeled only, with a note. The worker posts two files or one with the flip's
pause, and lists the setups GuildSend reads.
"""
from pathlib import Path

import numpy as np
import pytest
import trimesh
import yaml
from shapely.geometry import Polygon, box

from guildmodel.core.project.schema import (CastleCamParams, InlayFeature, SculptFeature,
                                            SculptMount, TempleParams)

ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())
OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])


def _dome_bytes(radius=2.5):
    sph = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    dome = trimesh.intersections.slice_mesh_plane(sph, plane_normal=[0, 0, 1],
                                                  plane_origin=[0, 0, 0], cap=True)
    return trimesh.exchange.stl.export_stl(dome)


@pytest.fixture(scope="module")
def dome():
    from guildmodel.core.model.sculpt import flat_back, load_sculpt
    data = _dome_bytes()
    src = load_sculpt(data, "dome.stl")
    src.back = flat_back(src.mesh)[0]
    return data, src


def _temple_with(dome, placements, *, op="deboss", depth=0.6, temple=None):
    """A temple with one dome per (face, x) placement, snapped on the plain
    temple's solid as the window snaps them."""
    from guildmodel.core.model.sculpt import mount_transform, snap_target
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_mesh
    from guildmodel.core.relief.flat import build_temple_relief
    data, src = dome
    temple = temple or TempleParams()
    relief = build_temple_relief(OUTLINE, temple, resolution=CUT_RES_MM)
    host = build_castle_mesh(relief)
    feats = []
    for face, x in placements:
        target = snap_target(host, face, (x, 0.0))
        flip = op == "deboss"
        T = mount_transform(src.back, target, overlap_mm=depth, flip=flip,
                            height_mm=src.height_mm)
        feats.append(SculptFeature(
            id=f"{op}_{face}_{int(x)}", label=face, source_name="dome.stl",
            source_sha256=src.sha256, height_mm=src.height_mm, extent_mm=src.extent_mm,
            op=op, mount=SculptMount(face=face, point=[float(v) for v in target.point],
                                     normal=[float(v) for v in target.normal],
                                     overlap_mm=depth, flip=flip)).with_transform(T))
    temple = temple.model_copy(update={"sculpts": feats})
    return temple, relief, {src.sha256: data}


def test_a_deboss_on_either_face_is_baked_and_in_the_maps(dome):
    from guildmodel.core.relief.flat import emboss_flat_relief
    temple, relief, sources = _temple_with(dome, [("posterior", 20.0), ("anterior", -20.0)])
    baked = emboss_flat_relief(relief, temple.resolved_sculpts(), sources)
    assert baked.notes == []
    assert baked.mesh.is_watertight and baked.host.is_watertight
    assert baked.mesh.volume < baked.host.volume - 5.0        # two imprints taken out
    r = baked.relief
    T = temple.blank_thickness_mm
    assert len(r.sculpt_footprints) == 1 and len(r.anterior_sculpt_footprints) == 1
    # the hinge face's map dips under the deboss, the outer face's rises
    assert r.field.z[r.field.world_to_pixel(20.0, 0.0)] == pytest.approx(T - 0.6, abs=0.05)
    assert r.anterior is not None
    assert r.anterior[r.field.world_to_pixel(-20.0, 0.0)] == pytest.approx(0.6, abs=0.05)
    # and nowhere else: the rest of the part is the plain temple
    assert float(np.nanmax(r.field.z)) == pytest.approx(T)
    far = r.field.world_to_pixel(50.0, 0.0)
    assert r.field.z[far] == pytest.approx(T) and r.anterior[far] == 0.0


def test_an_emboss_is_modeled_and_not_cut(dome):
    from guildmodel.core.relief.flat import emboss_flat_relief
    temple, relief, sources = _temple_with(dome, [("posterior", 20.0)], op="emboss", depth=0.05)
    baked = emboss_flat_relief(relief, temple.resolved_sculpts(), sources)
    assert baked.mesh.volume > baked.host.volume + 5.0        # the dome stands on the solid
    assert baked.relief.sculpt_footprints == []               # nothing for the program
    assert float(np.nanmax(baked.relief.field.z)) == pytest.approx(temple.blank_thickness_mm)
    assert any("modeled and not cut" in n for n in baked.notes)


def test_the_temple_program_cuts_the_hinge_face_deboss_on_its_ball(dome):
    from guildmodel.core.cam.temple_ops import TEMPLE_OP_TIERS, generate_temple_program
    from guildmodel.core.relief.flat import emboss_flat_relief
    temple, relief, sources = _temple_with(dome, [("posterior", 20.0), ("anterior", -20.0)])
    r = emboss_flat_relief(relief, temple.resolved_sculpts(), sources).relief
    ops = generate_temple_program(OUTLINE, [], temple, TOOLS, CastleCamParams(), relief=r)
    names = [o.name for o in ops]
    assert names == ["Embossing", "Temple Profile"]
    emboss = ops[0]
    assert emboss.tool_name == "ball_1mm" == TempleParams().emboss_tool
    pts = np.array([p for path in emboss.paths for p in path])
    T = temple.blank_thickness_mm
    assert T - 0.65 <= pts[:, 2].min() <= T - 0.5 and pts[:, 2].max() < T
    assert 15.0 < pts[:, 0].min() and pts[:, 0].max() < 25.0    # the hinge face's only
    assert "Embossing" in TEMPLE_OP_TIERS[0]
    # off, or without the relief, the program is the plain temple's
    off = CastleCamParams(op_enabled={"Embossing": False})
    assert [o.name for o in generate_temple_program(OUTLINE, [], temple, TOOLS, off, relief=r)] == ["Temple Profile"]
    assert [o.name for o in generate_temple_program(OUTLINE, [], temple, TOOLS)] == ["Temple Profile"]


def test_the_outer_face_is_the_anterior_setup_mirrored_in_g55(dome):
    from guildmodel.core.cam.temple_ops import generate_temple_program
    from guildmodel.core.cam.two_sided import plan_temple_two_sided, temple_flip_line
    from guildmodel.core.relief.flat import emboss_flat_relief
    temple, relief, sources = _temple_with(dome, [("anterior", -20.0)])
    r = emboss_flat_relief(relief, temple.resolved_sculpts(), sources).relief
    cam = CastleCamParams()
    posterior = generate_temple_program(OUTLINE, [], temple, TOOLS, cam, relief=r)
    assert [o.name for o in posterior] == ["Temple Profile"]    # nothing of the outer face
    fixture = yaml.safe_load((ROOT / "src/guildmodel/config/fixtures/guild_cnc.yaml").read_text())
    mirror, axis = temple_flip_line(fixture, "temple_right")
    # the temple turns over its length (2.1): Y mirrored about the zone's
    # horizontal center line, the hinge end staying at its end
    assert mirror == "y" and axis == pytest.approx(56.781 + 15.0)
    job = plan_temple_two_sided(r, temple, posterior, cam, TOOLS, outline=OUTLINE,
                                mirror=mirror, flip_axis_mm=axis)
    assert job.two_sided and [o.name for o in job.anterior] == ["Embossing"]
    pts = np.array([p for path in job.anterior[0].paths for p in path])
    T = temple.blank_thickness_mm
    assert -25.0 < pts[:, 0].min() and pts[:, 0].max() < -15.0  # the same end of the blank
    assert T - 0.65 <= pts[:, 2].min() and pts[:, 2].max() < T   # the outer face as the top
    assert [(s.side, s.wcs, s.program, s.flip) for s in job.setups] == [
        ("anterior", "G55", "temple_anterior_cut.nc", "none"),
        ("posterior", "G54", "temple_cut.nc", "manual")]
    assert all(s.part == "temple" and s.mirror == "y" for s in job.setups)
    assert all(s.flip_axis_y_mm == pytest.approx(axis) and s.flip_axis_x_mm is None
               for s in job.setups)
    assert all(s.flip_line_mm == pytest.approx(axis) for s in job.setups)
    # off: one setup; a temple with nothing on its outer face: one setup
    assert not plan_temple_two_sided(r, temple, posterior, cam.model_copy(update={"two_sided": "off"}),
                                     TOOLS, outline=OUTLINE).two_sided
    plain = TempleParams()
    r0 = emboss_flat_relief(relief, [], {}).relief
    assert not plan_temple_two_sided(r0, plain, posterior, cam, TOOLS, outline=OUTLINE).two_sided
    forced = plan_temple_two_sided(r0, plain, posterior, cam.model_copy(update={"two_sided": "on"}),
                                   TOOLS, outline=OUTLINE)
    assert not forced.two_sided and any("nothing to cut" in n for n in forced.notes)


def test_an_outer_face_seat_is_the_anterior_setups_pocket():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    from guildmodel.core.cam.two_sided import plan_temple_two_sided
    from guildmodel.core.geometry.inlays import ordered, reconcile
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.relief.flat import build_temple_relief
    outline = box(-80.0, -6.0, 60.0, 6.0)
    seat = box(-40.0, -4.0, -10.0, 2.0)      # off the center line: its mirror shows
    polys = ordered([seat], [])
    t = TempleParams()
    t.inlays = reconcile([], polys, [])
    assert t.inlays[0].face == "anterior"
    relief = build_temple_relief(outline, t, [], [], inlay_polys=polys, resolution=CUT_RES_MM)
    cam = CastleCamParams()
    posterior = generate_temple_program(outline, [], t, TOOLS, cam, inlay_polys=polys, relief=relief)
    assert [o.name for o in posterior] == ["Temple Profile"]
    job = plan_temple_two_sided(relief, t, posterior, cam, TOOLS, outline=outline, inlay_polys=polys)
    assert job.two_sided and [o.name for o in job.anterior] == ["Inlays"]
    pts = np.array([p for path in job.anterior[0].paths for p in path])
    # turned over its length: the seat stays at its end, its Y mirrored
    assert -40.0 - 1.0 <= pts[:, 0].min() and pts[:, 0].max() <= -10.0 + 1.0
    assert -2.0 - 1.0 <= pts[:, 1].min() and pts[:, 1].max() <= 4.0 + 1.0
    assert pts[:, 1].mean() > 0.0
    assert pts[:, 2].min() == pytest.approx(t.blank_thickness_mm - 1.0, abs=0.05)


def test_the_worker_posts_the_outer_face_first_in_two_files_or_one(dome, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import GCodeWorker
    temple, _relief, sources = _temple_with(dome, [("posterior", 20.0), ("anterior", -20.0)],
                                            temple=TempleParams(snap_to_blank_end=False))

    def run(cam):
        done, errs, log = [], [], []
        w = GCodeWorker(OUTLINE, None, {"material_name": "acetate"}, cam_params=cam,
                        temple=temple, is_temple=True, sculpt_sources=sources)
        w.finished.connect(lambda s, rows: done.append((s, rows)))
        w.error.connect(errs.append)
        w.progress.connect(log.append)
        w.run()
        assert errs == [], errs[0] if errs else ""
        return w, done[0], log

    w, (summary, rows), log = run(CastleCamParams())
    assert set(w.programs) == {"temple_anterior_cut.nc", "temple_cut.nc"}
    setups = w.setup_dict["setups"]
    assert [s["wcs"] for s in setups] == ["G55", "G54"] and w.setup_dict["two_sided"]
    assert [s["program"] for s in setups] == ["temple_anterior_cut.nc", "temple_cut.nc"]
    assert w.setup_dict["run_mode"] == "two_file"
    assert setups[1]["flip_axis_y_mm"] == pytest.approx(56.781 + 15.0)
    assert setups[1]["flip_axis_x_mm"] is None and setups[1]["mirror"] == "y"
    assert w.setup_dict["flip_mirror"] == "y"
    assert w.setup_dict["flip_axis_y_mm"] == pytest.approx(71.781)
    assert w.setup_dict["flip_axis_x_mm"] is None
    front, back = w.programs["temple_anterior_cut.nc"], w.programs["temple_cut.nc"]
    assert "G55" in front and "G55" not in back
    assert "hinge face up; flip about machine Y 71.781 mm, over its length; then G54" in back
    assert "--- Embossing ---" in front and "--- Embossing ---" in back    # one deboss each
    assert "--- Temple Profile ---" in back and "--- Temple Profile ---" not in front
    assert "; After temple_anterior_cut.nc: Flip stock" in back
    assert any("Embossing: 1 deboss(es) on the hinge face, 1 on the outer face" in ln for ln in log)
    assert "Two-sided job" in summary and rows[0]["name"].startswith("Anterior · ")
    overlay = {e["name"] for e in w.op_overlay}
    assert "Anterior · Embossing" in overlay and "Embossing" in overlay

    one, (summary1, _), _ = run(CastleCamParams(two_sided_output="one_file"))
    assert set(one.programs) == {"temple_two_sided_cut.nc"}
    assert one.setup_dict["run_mode"] == "single_file"
    assert [s["program"] for s in one.setup_dict["setups"]] == ["temple_two_sided_cut.nc"] * 2
    text = one.programs["temple_two_sided_cut.nc"]
    assert text.count("M30") == 1 and "; Flip stock and re-register on dowel pins" in text
    assert text.index("--- Embossing ---") < text.index("Flip stock") < text.index("--- Temple Profile ---")

    # off: the temple program alone, the outer face's deboss noted
    off, _, log_off = run(CastleCamParams(two_sided="off"))
    assert set(off.programs) == {"temple_cut.nc"} and not off.setup_dict["two_sided"]
    assert len(off.setup_dict["setups"]) == 1


def test_the_dock_gives_a_temple_its_meshes_and_its_second_side(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.widgets.params_panel import (EMBOSSING_TEMPLE_FOLD, SCULPTS_FOLD,
                                                     ParamsPanel)
    p = ParamsPanel()
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    assert p.embossing is p.embossing_temple and p.embossing.host == "temple"
    assert not p._two_sided_group.isHidden()                  # the flip, for a temple too
    assert "Embossing" in [n for n, cb in p.op_checks.items() if not cb.isHidden()]
    assert p._folds[EMBOSSING_TEMPLE_FOLD].header.text() == "Embossing"
    f = SculptFeature(id="m1", label="crest", op="deboss", mount=SculptMount(face="anterior"))
    p.embossing.add_sculpt(f)
    p.temple_emboss_tool.setCurrentText("ball_2mm")
    t = p.temple_params()
    assert [s.id for s in t.sculpts] == ["m1"] and t.emboss_tool == "ball_2mm"
    # the front's records are its own
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    assert p.embossing is p.embossing_front and p.castle_params().sculpts == []
    assert p._two_sided_group.isHidden() is False
    p.set_component_kind(ComponentKind.BASE_CURVE_RIGHT)
    assert p._two_sided_group.isHidden()                      # a block never flips
    # and the temple's come back with its params
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.set_temple_params(TempleParams(sculpts=[f, f.model_copy(update={"id": "m2"})],
                                     emboss_tool="ball_1mm"))
    assert [s.id for s in p.temple_params().sculpts] == ["m1", "m2"]
    assert p._folds[SCULPTS_FOLD] is not p._folds[EMBOSSING_TEMPLE_FOLD]
