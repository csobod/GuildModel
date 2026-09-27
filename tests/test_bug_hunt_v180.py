"""The 2026-09-26 bug hunt before v1.8.0: the core half.

Seven read-only reviews over the whole program, one slice each, before the
release workflows were turned on. Every fix that landed is pinned here or
in ``test_bug_hunt_v180_gui``, so it fails on its own if it comes back:

- the post refuses a rapid plane that is not above every cut (the bed
  program's safe Z was derived from the fixture's nominal stock);
- the profile-only fallback closes its rings (the last segment of every
  pass was never cut);
- a hand-edited clearance of 0, a pocket angle past the slider, a NaN in
  the forming block, and a negative projection through `with_base_curve`
  are all refused or folded, never posted;
- the schema no longer reaches the forming package, and the AST gate sees
  the aliases and relative imports it used to miss;
- a tilt no depth can hold leaves the depth range whole;
- press rows are read strictly, and the row cache follows the files;
- the ``.gmodel`` keeps every component's program set.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon

ROOT = Path(__file__).parents[1]


def _post(safe_z: float):
    from guildmodel.core.post.grbl import GRBLPost
    return GRBLPost(job_name="hunt", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
                    safe_z_mm=safe_z)


def test_the_post_refuses_a_rapid_plane_inside_the_stock():
    post = _post(13.0)
    post.header("Front")
    post.emit_polyline([(0, 0, 12.0), (5, 0, 12.0), (5, 5, 12.0), (0, 0, 12.0)])
    with pytest.raises(ValueError, match="safe Z"):
        post.emit_polyline([(0, 0, 13.5), (5, 0, 13.5), (5, 5, 13.5), (0, 0, 13.5)])
    with pytest.raises(ValueError, match="safe Z"):
        post.feed(x=1.0, y=1.0, z=13.0)
    with pytest.raises(ValueError, match="safe Z"):
        post.arc(1.0, 1.0, 14.0, 0.5, 0.0, ccw=True)


def test_profile_passes_close_their_rings():
    from guildmodel.core.cam.profile import profile_cut

    outline = Polygon([(0, 0), (40, 0), (40, 20), (0, 20)],
                      holes=[[(10, 5), (20, 5), (20, 15), (10, 15)]])
    passes = profile_cut(outline, tool_radius_mm=1.0, stock_thickness_mm=4.0,
                         stepdown_mm=2.0, tab_count=0)
    assert passes
    for polylines in passes:
        for pts in polylines:
            assert len(pts) >= 4
            assert pts[0][:2] == pytest.approx(pts[-1][:2]), "the ring is open"


def test_hand_edited_values_the_machine_must_never_see_are_refused():
    from pydantic import ValidationError

    from guildmodel.core.project.schema import (CastleCamParams, CastleParams,
                                                FormingMetadata, TempleParams)

    with pytest.raises(ValidationError):
        CastleCamParams(safe_z_clearance_mm=0.0)
    with pytest.raises(ValidationError):
        CastleCamParams(link_clearance_mm=-2.0)
    with pytest.raises(ValidationError):
        CastleParams(hinge_pocket_angle_deg=20.0)          # the slider stops at 15
    with pytest.raises(ValidationError):
        TempleParams(hinge_pocket_angle_deg=-20.0)
    with pytest.raises(ValidationError):
        FormingMetadata.model_validate_json('{"bridge_projection_mm": NaN}')
    with pytest.raises(ValidationError):
        FormingMetadata.model_validate_json('{"base_radius_mm": Infinity}')
    # a copy runs the validators: the die only presses forward
    f = FormingMetadata().with_base_curve(4.0, 164.0, bridge_projection_mm=-3.0)
    assert f.bridge_projection_mm == 0.0 and f.is_flat is False


def test_the_schema_and_the_cam_never_load_the_forming_package():
    """The schema used to import `core.forming` lazily for 530 / D, which the
    CAM (which imports the schema) could reach through any call to
    `with_base_curve` without an import statement of its own — invisible
    to the AST gate. The convention lives with the schema now, and this is
    the runtime check the gate cannot be."""
    code = (
        "import importlib, pkgutil, sys\n"
        "import guildmodel.core.cam as cam\n"
        "import guildmodel.core.post, guildmodel.core.zmap\n"
        "import guildmodel.core.project.schema as schema\n"
        "for m in pkgutil.walk_packages(cam.__path__, 'guildmodel.core.cam.'):\n"
        "    importlib.import_module(m.name)\n"
        "schema.FormingMetadata().with_base_curve(4.0, 164.0)\n"
        "print(sorted(m for m in sys.modules if m.startswith('guildmodel.core.forming')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=ROOT, check=True)
    assert out.stdout.strip() == "[]", out.stdout


def test_a_tilt_no_depth_can_hold_leaves_the_depth_range_whole():
    """A negative angle whose rise passes the ceiling used to collapse the
    depth range to a single value *above* the ceiling. The angle is the
    lever that is out; the depth keeps its plain range."""
    from guildmodel.core.project.limits import pocket_limits

    out = pocket_limits(1.0, -10.0, 0.4, 6.0, "a 0.9 mm endpiece", "inferior")
    depth, angle = out["hinge_pocket_depth_mm"], out["hinge_pocket_angle_deg"]
    assert (depth.low, depth.high) == (0.0, 0.4)
    assert angle.low > -10.0                     # -10° is outside the angle's own range


def test_press_rows_are_read_strictly_and_follow_the_file(tmp_path, monkeypatch, caplog):
    from guildmodel.core.forming import presses

    user = tmp_path / "presses.yaml"
    monkeypatch.setattr(presses, "_USER", user)
    monkeypatch.setattr(presses, "_cache", None)
    shipped = presses.shipped()[0].label
    user.write_text(
        f"{shipped}:\n  _deleted: 'false'\n"          # a string is not the flag
        "Big die:\n  base_curve: 4\n  radius_mm: -5\n  face_form_deg: 160\n"
        "Flat:\n  base_curve: 2\n  face_form_deg: 170\n"   # the combo's own row
        "Broken:\n  base_curve: abc\n  face_form_deg: 160\n",
        encoding="utf-8")
    rows = {p.label: p for p in presses.effective()}
    assert shipped in rows
    assert rows["Big die"].radius_mm == pytest.approx(530.0 / 4.0)   # not a negative die
    assert "Flat" not in rows and "Broken" not in rows
    assert any("Broken" in r.message for r in caplog.records)

    user.write_text("Big die:\n  base_curve: 6\n  radius_mm: 90\n  face_form_deg: 160\n"
                    "# rewritten\n", encoding="utf-8")
    assert presses.find("Big die").radius_mm == 90.0    # the cache saw the new file


def test_the_bundle_keeps_every_components_program(tmp_path):
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import ProjectSchema

    path = tmp_path / "p.gmodel"
    save_gmodel(path, project=ProjectSchema(),
                programs={"frame_front.nc": "; front"},
                component_artifacts={
                    "front": {"programs": {"frame_front.nc": "; front"}, "setup": {"a": 1}},
                    "Temple R/L": {"programs": {"temple_right.nc": "; temple"},
                                   "machine": {"name": "m"}, "report": {"ok": True}}})
    bundle = load_gmodel(path)
    assert bundle.programs == {"frame_front.nc": "; front"}       # the hand-off job, unchanged
    front = bundle.component_artifacts["front"]
    assert front["programs"] == {"frame_front.nc": "; front"} and front["setup"] == {"a": 1}
    temple = bundle.component_artifacts["Temple R_L"]             # one path segment
    assert temple["programs"] == {"temple_right.nc": "; temple"}
    assert temple["machine"] == {"name": "m"} and temple["report"] == {"ok": True}


def test_a_missing_feed_rate_is_refused_before_it_posts_f0():
    """GRBL halts on the first G1 of a program with F0 (error 22); the post
    refuses to write the word and names the cause instead."""
    from guildmodel.core.post.grbl import GRBLPost

    post = GRBLPost(job_name="hunt", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=0, plunge_rate_mmpm=0, safe_z_mm=20.0)
    post.header("Front")
    with pytest.raises(ValueError, match="feed rate"):
        post.feed(x=1.0, y=1.0, z=1.0)
    with pytest.raises(ValueError, match="feed rate"):
        post.plunge(1.0)
    post.feed(x=1.0, y=1.0, z=1.0, feed=750)             # an explicit feed is fine


# ------------------------------------------------ the maker's six, 2026-09-26

def _cam_post(feed=1200.0, plunge=450.0, spindle=10000, safe_z=20.0):
    from guildmodel.core.post.grbl import GRBLPost
    return GRBLPost(job_name="bed", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=spindle, feed_rate_mmpm=feed, plunge_rate_mmpm=plunge,
                    safe_z_mm=safe_z)


def test_each_op_on_a_bed_program_posts_its_own_feeds():
    """Two parts share one program and one tool but not one material: the
    ops carry their component's context (`OpCut`), the post adopts it as
    each op begins, and a spindle speed that differs is re-issued."""
    from guildmodel.core.cam.castle_ops import CamOp, OpCut, write_castle_program
    from guildmodel.core.cam.layout import transform_ops

    square = [(0, 0, 5.0), (10, 0, 5.0), (10, 10, 5.0), (0, 10, 5.0), (0, 0, 5.0)]
    front = CamOp("Frame Front: Perimeter", [list(square)], tool={"name": "flat_3175"},
                  cut=OpCut(1200.0, 450.0, 10000, 1.5, "ramp", 8.0))
    block = CamOp("Block: Block Profile", [[(x + 30, y, z) for x, y, z in square]],
                  tool={"name": "flat_3175"},
                  cut=OpCut(600.0, 200.0, 12000, 0.75, "plunge", 8.0))
    moved = transform_ops([block], 5.0, 0.0)[0]
    assert moved.cut == block.cut, "the layout dropped the op's context"

    post = _cam_post()
    write_castle_program([front, moved], post, contour_op_names=set())
    text = post.to_string()
    front_part = text.split("--- Block: Block Profile ---")[0]
    block_part = text.split("--- Block: Block Profile ---")[1]
    assert "F1200" in front_part and "F600" not in front_part
    assert "F600" in block_part and "F1200" not in block_part
    assert "M3 S12000" in block_part and "M3 S12000" not in front_part


def test_a_components_ops_are_stamped_with_its_own_material():
    """`stamp_cut_settings` follows the single-part precedence — the tool's
    own tools.yaml feeds when set, else the component's material's — and
    `_spec_cam` resolves a block's overrides to acetal's clamp, not the
    project's acetate."""
    from guildmodel.core.cam.castle_ops import CamOp, stamp_cut_settings
    from guildmodel.core.post.machine import clamp_cam_to_machine, load_machine_profile
    from guildmodel.core.project.schema import CastleCamParams, ComponentCamOverrides
    from guildmodel.gui.app import _spec_cam

    import yaml
    config = ROOT / "src" / "guildmodel" / "config"
    mats = yaml.safe_load((config / "materials.yaml").read_text(encoding="utf-8"))
    tools = yaml.safe_load((config / "tools.yaml").read_text(encoding="utf-8"))
    tools = tools.get("tools", tools)
    machine = load_machine_profile("guild_cnc", config)
    cam = CastleCamParams()

    acetate = _spec_cam({"cam_overrides": None}, cam, machine, mats, "acetate")
    acetal = _spec_cam({"cam_overrides": ComponentCamOverrides(material="acetal")},
                       cam, machine, mats, "acetate")
    assert acetal[2] == "acetal" and acetate[2] == "acetate"
    assert acetal[1].feed_rate_mmpm < acetate[1].feed_rate_mmpm
    assert acetal[0].contour_stepdown_mm <= acetate[0].contour_stepdown_mm

    op = CamOp("Block Profile", [[(0, 0, 1.0), (1, 0, 1.0)]], tool=tools["flat_3175"])
    stamp_cut_settings([op], tools, acetal[0], acetal[1], machine=machine)
    assert op.cut is not None
    assert op.cut.feed_rate_mmpm == acetal[1].feed_rate_mmpm
    assert op.cut.contour_stepdown_mm == acetal[0].contour_stepdown_mm

    # a tool with its own feeds keeps them
    own = dict(tools["flat_3175"], name="own", feed_rate_mmpm=333.0)
    op2 = CamOp("Block Profile", [[(0, 0, 1.0), (1, 0, 1.0)]], tool=own)
    stamp_cut_settings([op2], {**tools, "own": own}, acetal[0], acetal[1], machine=machine)
    assert op2.cut.feed_rate_mmpm == 333.0


def test_an_opening_the_tool_cannot_enter_is_said():
    from guildmodel.core.cam.castle_ops import CamOp, contour_op, op_notes
    from guildmodel.core.project.schema import CastleCamParams

    hole = Polygon([(0, 0), (2.4, 0), (2.4, 2.4), (0, 2.4)])
    op = contour_op("Holes", [hole], "inside", 3.175 / 2, 0.1, 10.0, 0.4,
                    CastleCamParams())
    assert isinstance(op, CamOp) and not op.paths
    notes = op_notes([op])
    assert len(notes) == 1 and "skipped" in notes[0] and "smaller tool" in notes[0]
    assert "2.4 x 2.4" in notes[0]


def test_a_tabbed_release_pass_ramps_in():
    """A pass that rises over its tabs is not constant-Z, and used to be
    refused the ramped lead-in for that: a straight slot-plunge to the
    floor instead. The ramp is an offset above the path's own z."""
    post = _cam_post()
    post.header("t")
    floor, tab = 0.0, 1.0
    # a 40 mm square at the floor with one raised tab on its far side
    loop = [(0, 0, floor), (40, 0, floor), (40, 20, tab), (40, 24, tab), (40, 40, floor),
            (0, 40, floor), (0, 0, floor)]
    post.emit_polyline(loop, ramp_height=1.5, ramp_angle_deg=8.0)
    lines = post.to_string().splitlines()
    feeds = [ln for ln in lines if ln.startswith("G1")]
    zs = []
    for ln in feeds:
        for w in ln.split():
            if w.startswith("Z"):
                zs.append(float(w[1:]))
    assert zs[0] == pytest.approx(1.5)                      # down to the ramp start
    descent = [z for z in zs if 0.0 < z < 1.5]
    assert descent, "no ramp: the pass plunged straight to the floor"
    assert any(abs(z - tab) < 1e-6 for z in zs), "the lap lost the tab"
    assert not any(z < floor - 1e-6 for z in zs)


def test_a_reserved_shortcut_is_a_conflict():
    from guildmodel.gui.shortcuts import RESERVED_SHORTCUTS, find_conflicts

    assert "Ctrl+Q" in RESERVED_SHORTCUTS and "Ctrl+," in RESERVED_SHORTCUTS
    assert find_conflicts({"build": "F5", "gcode": "Ctrl+G"}) == {}
    assert find_conflicts({"build": "Ctrl+Q"}) == {"Ctrl+Q": ["build", "Quit"]}
    assert find_conflicts({"build": "Ctrl+,", "fit": "Ctrl+,"})["Ctrl+,"] == [
        "build", "fit", "Preferences"]


def test_the_stores_follow_their_files(tmp_path, monkeypatch):
    from guildmodel.gui import material_store, tool_store

    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    before = tool_store.effective()
    assert "flat_3175" in before
    (tmp_path / "tools.yaml").write_text(
        "mine:\n  name: mine\n  diameter_mm: 1.0\n  kind: flat\n", encoding="utf-8")
    assert "mine" in tool_store.effective()
    (tmp_path / "materials.yaml").write_text("acetate:\n  feed_rate_mmpm: 777\n",
                                             encoding="utf-8")
    assert material_store.effective()["acetate"]["feed_rate_mmpm"] == 777
    # callers get their own copies
    tool_store.effective()["flat_3175"]["diameter_mm"] = -1
    assert tool_store.effective()["flat_3175"]["diameter_mm"] != -1


def test_the_offset_rings_are_not_closed_twice():
    """Found at release, after the whole suite had passed: closing the rings
    inside `pocketing._inward_offsets` (for `pocket_paths`) gave the hinge
    pockets and the relief — which close their own copies — a doubled point
    at every ring's seam. Nothing failed; the ramp was redistributed and
    every front's posted program changed from v1.7.0's. A zero-length move
    is the fingerprint."""
    import yaml

    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.cam.pocketing import pocket_paths
    from guildmodel.core.project.schema import CastleCamParams, CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    import tempfile, zipfile
    fix = Path(__file__).parent / "fixtures" / "gabriel"
    tmp = Path(tempfile.mkdtemp()) / "g.gdraw"
    with zipfile.ZipFile(tmp, "w") as zf:
        for f in sorted(fix.iterdir()):
            zf.write(f, f.name)
    front = next(w for w in build_workspaces_from_gdraw(tmp)[0] if w.castle_ready)
    cfg = ROOT / "src" / "guildmodel" / "config"
    tools = yaml.safe_load((cfg / "tools.yaml").read_text(encoding="utf-8"))
    tools = tools.get("tools", tools)
    castle = CastleParams()
    relief = build_castle_relief(front.partition, castle, front.hinge_polys, resolution=CUT_RES_MM)
    ops = generate_castle_program(relief, castle, front.hinge_polys, tools["flat_3175"],
                                  params=CastleCamParams(), tools_cfg=tools)
    for op in ops:
        for path in op.paths:
            for a, b in zip(path, path[1:]):
                assert a != b, f"{op.name}: a zero-length move at {a}"

    # and the public pocket's rings are closed, once
    rings = pocket_paths(Polygon([(0, 0), (20, 0), (20, 10), (0, 10)]), 1.0, 2.0, 1.0, 1.0)[0]
    for ring in rings:
        assert ring[0] == ring[-1] and ring[-2] != ring[-1]
