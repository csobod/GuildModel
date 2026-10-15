"""The stock engine behind the views (BUILDPLAN M21 §6.8 tasks 6 and 7),
without a MainWindow.

The viewer plays a `StockPlan` as it played a `RemovalPlan`: the block scene,
a scrub, a tick of play, the solid at a pause where there is an undercut. The
component sim workers read a stored program at the posting grid and hand
back today's verdict with the volumes; the bed worker cuts ``worktable.nc``
once for both the verdict and the playback.
"""
import numpy as np
import pytest
from shapely.geometry import box

from guildmodel.core.project.schema import CastleCamParams, TempleParams
from guildmodel.core.stock import DexelStock, Run, ToolShape
from guildmodel.core.stock.playback import build_stock_plan

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _groove_plan():
    stock = DexelStock.from_box(-6, -6, 6, 6, 0.0, 6.0, 0.25)
    flat = ToolShape(kind="flat", radius_mm=1.0)
    groove = ToolShape.from_tool(dict(type="groove", radius_mm=2.75, flute_length_mm=2.0,
                                      groove_depth_mm=0.75, groove_width_mm=2.0,
                                      neck_diameter_mm=3.5))
    runs = [(Run("Pocket", "flat_2mm", True, 600.0, [(-4, 0, 4.0, 0), (4, 0, 4.0, 0)]), flat),
            (Run("Pocket", "flat_2mm", False, 0.0, [(4, 0, 4.0, 0), (0, 0, 10.0, 0)]), flat),
            (Run("Lens Groove", "groove_drageoir", True, 300.0,
                 [(0, 0, 2.0, 0), (0.5, 0, 2.0, 0)]), groove)]
    plan = build_stock_plan(runs, stock, keyframes=3)
    plan.op_tool_geom = {"Pocket": {"type": "flat", "radius_mm": 1.0},
                         "Lens Groove": {"type": "groove", "radius_mm": 2.75}}
    return plan


class _Actor:
    def __init__(self):
        self.visible, self.pos, self.color = True, None, None

    def SetVisibility(self, on):            # noqa: N802
        self.visible = bool(on)

    def SetPosition(self, *p):              # noqa: N802
        self.pos = p

    def GetProperty(self):                  # noqa: N802
        return self

    def SetColor(self, *c):                 # noqa: N802
        self.color = c


class _Plotter:
    """What the viewer asks of its plotter, without a GL context: VTK opens a
    real X window for one under the offscreen platform and the process dies."""
    def __init__(self):
        self.actors: dict = {}
        self.renders = 0

    def clear(self):
        self.actors.clear()

    def add_mesh(self, mesh, name=None, **kw):
        a = _Actor()
        self.actors[name or f"actor{len(self.actors)}"] = (mesh, a)
        return a

    def remove_actor(self, name, render=True):
        self.actors.pop(name, None)

    def reset_camera(self, render=False):
        pass

    def render(self):
        self.renders += 1

    def set_background(self, *a, **k):
        pass

    camera_position = None


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
    v = Viewer3D()
    v.set_mode("sim")
    return v


def test_the_viewer_plays_a_stock_plan(viewer):
    v = viewer
    plan = _groove_plan()
    v.set_plan(plan)
    assert v._removal_grid is not None and v._removal_n == plan.stock.count.size
    assert not v._chk_solid.isHidden()                     # the groove is an undercut
    assert "stockSolid" in v._plotter.actors               # at rest: the solid, slot and all
    rest = v._floor.copy()
    assert np.array_equal(rest, plan.final_top())
    # a scrub draws the sheet, so dragging stays quick; at the start, the uncut block
    v._on_scrub(0)
    assert "stockBlock" in v._plotter.actors and v._solid_actor is None
    assert np.array_equal(v._floor, plan.stock_top)
    v._play_speed = max(1.0, plan.n_positions / 4)
    v._toggle_play()                                       # play from the start
    v._advance_play()
    assert (v._floor <= plan.stock_top + 1e-6).all() and (v._floor < plan.stock_top).any()
    assert "stockSolid" not in v._plotter.actors           # no solid while playing
    v._toggle_play()                                       # pause: the solid appears
    assert v._solid_actor is not None and "stockSolid" in v._plotter.actors
    v._chk_solid.setChecked(False)                         # and goes with the toggle
    assert v._solid_actor is None and "stockBlock" in v._plotter.actors
    v._on_scrub(plan.n_positions)
    assert np.array_equal(v._floor, rest)
    # the tool rides the path and takes the op's geometry
    assert v._tool_actor is not None and v._tool_op == plan.label_at(plan.n_positions - 1)


def test_the_block_tints_the_undercut(viewer):
    from guildmodel.core.stock.surface import elevation_colors
    v = viewer
    plan = _groove_plan()
    v.set_plan(plan)
    colors = v._block_colors(plan)
    plain = elevation_colors(v._removal_grid.points[:, 2], v._removal_zmax)
    n = v._removal_n
    assert (colors[:n] != plain[:n]).any(axis=1).any()
    assert not (colors[n:] != plain[n:]).any()


def _temple_setup():
    outline = box(-70.0, -6.0, 70.0, 6.0)
    hinge = box(55.0, -3.0, 65.0, 3.0)
    return outline, [hinge], TempleParams()


def test_the_flat_worker_reads_a_stored_program_and_adds_the_volumes(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from guildmodel.gui.app import FlatSimWorker
    outline, hinges, t = _temple_setup()
    done, errs = [], []
    first = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinges,
                          cam_params=CastleCamParams(), resolution=0.3)
    first.finished.connect(lambda r, lines, plan: done.append((r, lines, plan)))
    first.error.connect(errs.append)
    first.run()
    assert errs == [], errs[0] if errs else ""
    report, lines, plan = done[0]
    assert report.status() in {"ok", "warn", "fail"}
    assert any("mm³" in line for line in lines)              # the volumes a heightfield could not give
    assert plan.n_positions > 0 and plan.stock.resolution == 0.3
    # the stored program is simulated at the posting grid, regenerating nothing
    import yaml
    from pathlib import Path
    from guildmodel.core.cam.castle_ops import build_tool_settings, write_castle_program
    from guildmodel.core.cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.relief.flat import place_temple_on_blank
    tools = yaml.safe_load((Path(__file__).parents[1] / "src/guildmodel/config/tools.yaml").read_text())
    # the program the tab stores is of the temple placed on its blank, as the worker places it
    placed, placed_hinges, _ = place_temple_on_blank(
        outline, hinges, [], t.blank_length_mm, stock_side=t.stock_side,
        snap=t.snap_to_blank_end, origin_from_drawing=t.origin_from_drawing)
    ops = generate_temple_program(placed, [], t, tools, hinge_polys=placed_hinges)
    ts, _ = build_tool_settings(ops, tools, default_feed=600, default_plunge=200,
                                default_spindle=12000)
    f0 = ts[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm, safe_z_mm=9.0)
    write_castle_program(ops, post, tool_settings=ts, contour_op_names=TEMPLE_CONTOUR_OPS)
    done.clear()
    second = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinges,
                           cam_params=CastleCamParams(), resolution=0.3,
                           program_text=post.to_string())
    second.finished.connect(lambda r, lines, plan: done.append((r, lines, plan)))
    second.error.connect(errs.append)
    second.run()
    assert errs == [], errs[0] if errs else ""
    report2, lines2, plan2 = done[0]
    assert plan2.stock.resolution == 0.15 and report2.resolution == 0.15
    assert "Hinge Pockets" in plan2.op_tool_geom and "Temple Profile" in plan2.op_tool_geom
    assert report2.status() == report.status() == "ok"      # the same verdict, read off the program
    assert report2.gouge.gouge_cells == 0
    assert not report2.faults and lines2 == report2.summary_lines()
    assert "mm³" in lines2[0]
    standing = float(lines2[0].split("mm³")[0].split(",")[-1])
    assert standing < 5.0                                   # the corners a flat tool leaves, not a slab
    # a rapid dragged through the temple at 1 mm is a fault, and fails the verdict
    bad = post.to_string().replace("M30", "G0 X-20.0 Y0.0 Z8.0\nG0 Z1.0\nG0 X20.0 Y0.0\nG0 Z8.0\nM30")
    done.clear()
    third = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinges,
                          cam_params=CastleCamParams(), resolution=0.3, program_text=bad)
    third.finished.connect(lambda r, lines, plan: done.append((r, lines, plan)))
    third.error.connect(errs.append)
    third.run()
    assert errs == [], errs[0] if errs else ""
    report3, lines3, plan3 = done[0]
    assert report3.status() == "fail"
    assert any(line.startswith("Rapid through stock") for line in lines3)
    assert plan3.n_positions > plan2.n_positions                 # the rapid plays, carving nothing
