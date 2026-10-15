"""Stock from a mesh, and the report against it (BUILDPLAN M21 §6.8 task 4).

`DexelStock.from_mesh` keeps every crossing of a column through the model
where `triangle_envelopes` kept the two extremes, so its top is the upper
envelope and its bottom the lower, bit for bit, and its volume is the mesh's.
`compare` then reproduces today's `verify` on the three fixtures — the same
cells uncut and gouged, the same worst figures — and adds the volumes a
heightfield could not give.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.stock import DexelStock, ToolShape, compare, cut, cutting_paths, \
    interval_difference, parse_program, poses_for_run, spacing_for

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())


def _front(name, tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    if name == "demo":
        from guildmodel.core.io_import.dxf import import_curves
        from guildmodel.core.project.schema import ComponentKind
        from guildmodel.gui.component_workspace import ComponentWorkspace, derive_workspace
        layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
        ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="", layers=layers,
                                curves=curves)
        derive_workspace(ws)
        return ws
    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


def _model_mesh(ws):
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.project.schema import CastleParams
    castle = ws.castle_params or CastleParams()
    return castle, to_trimesh(build_castle_model(ws.partition, castle, ws.hinge_polys))


# ------------------------------------------------------------------ from_mesh

def test_from_mesh_is_the_envelopes_and_the_volume(tmp_path_factory):
    from guildmodel.core.zmap import grid_for, triangle_envelopes
    ws = _front("demo", tmp_path_factory)
    _castle, mesh = _model_mesh(ws)
    origin, rows, cols = grid_for(ws.partition.body, 0.2)
    up, dn = triangle_envelopes(mesh.vertices, mesh.faces, origin, rows, cols, 0.2,
                                background=np.nan)
    stock = DexelStock.from_mesh(mesh.vertices, mesh.faces, origin, rows, cols, 0.2)
    has = stock.count > 0
    assert np.array_equal(has, np.isfinite(up))
    assert np.array_equal(stock.top(empty=np.nan).z[has], up[has])
    assert np.array_equal(stock.bottom(empty=np.nan).z[has], dn[has])
    assert stock.volume() == pytest.approx(mesh.volume, rel=0.01)
    # a frame front has no undercut: one interval everywhere
    assert stock.count.max() == 1


def test_from_mesh_keeps_an_undercut_as_two_intervals():
    import trimesh
    # a box with a slot through its side: material above and below the slot
    outer = trimesh.creation.box((10.0, 10.0, 6.0))
    slot = trimesh.creation.box((12.0, 4.0, 2.0))
    body = outer.difference(slot)
    # cell centers off the box's edges by half a cell, so a face on an edge is
    # not counted on both sides (cell-center sampling is exact between centers)
    stock = DexelStock.from_mesh(body.vertices, body.faces, (-6.1, -6.1), 61, 61, 0.2)
    r, c = stock.cells_of(0.0, 0.0)
    col = stock.column(r, c)
    assert len(col) == 2
    assert col[0] == pytest.approx((3.0, 1.0)) and col[1] == pytest.approx((-1.0, -3.0))
    r, c = stock.cells_of(0.0, 4.0)
    assert stock.column(r, c) == [pytest.approx((3.0, -3.0))]
    assert stock.volume() == pytest.approx(body.volume, rel=0.02)


def test_interval_difference_is_a_set_difference():
    a = DexelStock.from_box(-4, -4, 4, 4, 0.0, 6.0, 0.5)
    b = a.copy()
    cut(b, np.array([[0.0, 0.0, 2.0, 0, 0, 1]]), ToolShape.from_tool(
        dict(type="groove", radius_mm=2.75, flute_length_mm=2.0, groove_depth_mm=0.75,
             groove_width_mm=2.0, neck_diameter_mm=3.5)))
    extra = interval_difference(a, b)
    r, c = a.cells_of(2.0, 0.0)                 # the root radius: a 2 mm slot
    assert extra[r, c] == pytest.approx(2.0)
    r, c = a.cells_of(0.0, 0.0)                 # under the neck: cut from the tip up
    assert extra[r, c] == pytest.approx(4.0)
    r, c = a.cells_of(3.5, 0.0)                 # outside the head: untouched
    assert extra[r, c] == 0.0
    assert interval_difference(b, a).max() == 0.0   # nothing in b is outside a


# -------------------------------------------------------------- the report

def test_the_volumes_lie_between_the_shared_bottoms_and_a_column_cut_through_is_a_gouge():
    from guildmodel.core.relief.heightfield import Heightfield
    from guildmodel.core.stock.cutting import vertical_poses
    res = 0.5
    z = np.full((10, 10), 4.0)
    inside = np.ones_like(z, dtype=bool)
    target = DexelStock.from_heightfield(Heightfield(z=z, origin=(0.0, 0.0), resolution=res),
                                         inside=inside, z_bottom=-1.0, k=1)
    stock = DexelStock.from_box(-1e9, -1e9, 1e9, 1e9, -1.0, 5.0, res, origin=(0.0, 0.0),
                                shape=z.shape)
    report = compare(stock, target, inside)
    # one millimeter proud over 10 x 10 cells of 0.25 mm², and nothing under the part
    assert report.uncut_volume_mm3 == pytest.approx(100 * 0.25 * 1.0)
    assert report.gouge_volume_mm3 == 0.0 and report.gouge_cells == 0
    # a plunge below the bottom empties the column: cut through, the deepest gouge there is
    cut(stock, vertical_poses([(2.5, 2.5, -2.0)]), ToolShape(kind="flat", radius_mm=0.6))
    through = compare(stock, target, inside, gouge_rim_margin_mm=0.0)
    assert through.gouge_cells >= 1
    assert through.max_gouge_mm == pytest.approx(5.0)        # from 4.0 down to the bottom at -1


@pytest.mark.parametrize("fixture", ["demo", "aviator", "gabriel"])
def test_the_report_reproduces_the_cut_report_and_adds_the_volumes(fixture, tmp_path_factory):
    from guildmodel.core.cam.castle_ops import (build_tool_settings, generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.core.sim import (ToolProfile, achieved_floor_grouped,
                                     cutting_paths_from_program_grouped, verify)
    from guildmodel.core.zmap import castle_relief

    ws = _front(fixture, tmp_path_factory)
    castle, mesh = _model_mesh(ws)
    res = 0.3
    relief = castle_relief(ws.partition, castle, ws.hinge_polys, kernel="mesh", resolution=res)
    cam = CastleCamParams()
    ops = generate_castle_program(relief, castle, ws.hinge_polys, TOOLS[cam.tool_name],
                                  params=cam, tools_cfg=TOOLS)
    resolved, _ = build_tool_settings(ops, TOOLS, default_feed=600, default_plunge=200,
                                      default_spindle=12000)
    first = resolved[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=first.diameter_mm,
                    spindle_rpm=first.spindle_rpm, feed_rate_mmpm=first.feed_rate_mmpm,
                    plunge_rate_mmpm=first.plunge_rate_mmpm,
                    safe_z_mm=cam.safe_z_for(castle.stock.total_pad_height_mm))
    write_castle_program(ops, post, tool_settings=resolved)
    program = post.to_string()
    f = relief.field
    init_z = castle.stock.total_pad_height_mm + 1.0

    # today: the floor swept from the program and verified against the relief
    groups = [(p, t) for p, t in cutting_paths_from_program_grouped(program)
              if not (t and TOOLS.get(t, {}).get("type") == "groove")]
    profiles = {n: ToolProfile.from_tool(TOOLS[n]) for n in {t for _, t in groups if t}}
    floor = achieved_floor_grouped(groups, profiles, ToolProfile.from_tool(TOOLS["flat_3175"]),
                                   f.origin, f.z.shape, f.resolution, init_z)
    today = verify(floor, np.where(relief.inside, f.z, np.nan), relief.inside, f.origin,
                   f.resolution, partition=ws.partition)

    # the engine: the stock cut from the parsed program, the target from the mesh
    rows, cols = f.z.shape
    stock = DexelStock.from_box(-1e9, -1e9, 1e9, 1e9, -50.0, init_z, res,
                                origin=f.origin, shape=(rows, cols))
    for path, tool in cutting_paths(parse_program(program)):
        t = TOOLS.get(tool) if tool else None
        if t and t.get("type") == "groove":
            continue
        shape = ToolShape.from_tool(t or TOOLS["flat_3175"])
        from guildmodel.core.stock import Run
        run = Run("", tool, True, 0.0, [(x, y, z, 0.0) for x, y, z in path])
        cut(stock, poses_for_run(run, spacing_for(shape, res) if False else res), shape)
    assert np.array_equal(stock.top(empty=init_z).z, floor)
    target = DexelStock.from_mesh(mesh.vertices, mesh.faces, f.origin, rows, cols, res)
    report = compare(stock, target, relief.inside, partition=ws.partition)

    assert report.body_cells == today.completeness.body_cells
    assert report.uncut_cells == today.completeness.uncut_cells
    assert report.max_excess_mm == pytest.approx(today.completeness.max_excess_mm, abs=1e-9)
    assert report.gouge_cells == today.gouge.gouge_cells
    assert report.max_gouge_mm == pytest.approx(today.gouge.max_depth_mm, abs=1e-9)
    assert report.status() == today.status()
    assert np.array_equal(report.uncut_mask, today.completeness.uncut_mask)
    assert report.per_zone == today.completeness.per_zone
    # and what is new: the material left standing, and taken, as volumes
    assert report.uncut_volume_mm3 > 0.0
    assert report.uncut_volume_mm3 >= report.uncut_cells * 0.5 * res * res * 0.9
    back = report.to_cut_report(np.where(relief.inside, f.z, np.nan), floor)
    assert back.status() == today.status() and back.summary_lines()[0].startswith("Cut completeness")
    assert back.summary_lines() == report.summary_lines()          # the volumes ride along
    # a fault is beyond the cut: it fails the verdict whatever the floor says
    faulted = report.to_cut_report(np.where(relief.inside, f.z, np.nan), floor,
                                   faults=["Rapid through stock: 3 positions in Perimeter"])
    assert faulted.status() == "fail"
    assert faulted.summary_lines()[-1].startswith("Rapid through stock")
