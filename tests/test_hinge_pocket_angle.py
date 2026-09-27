"""The hinge pocket angle: a tilted pocket floor, the same in every kernel.

The front keeps the set depth along the pocket's superior edge and tilts toward
inferior (pantoscopic tilt at the hinge); a temple keeps it along the anterior,
hinge-end edge and tilts toward posterior (splay). At 0° nothing may change.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from shapely import contains_xy
from shapely.geometry import Polygon, box

from guildmodel.core.cam.castle_ops import hinge_pocket_op
from guildmodel.core.geometry.pocket_floor import (
    castle_pocket_floors, pocket_span, temple_pocket_floors)
from guildmodel.core.project.limits import (MIN_POCKET_FLOOR_MM, castle_limits,
                                            temple_limits)
from guildmodel.core.project.schema import (CastleCamParams, CastleParams,
                                            TempleParams)

DEMO = Path(__file__).parents[1] / "tests" / "fixtures" / "demo"
CONFIG = Path(__file__).parents[1] / "src" / "guildmodel" / "config"

#: A 10 x 6 mm pocket: superior edge at y = 3, inferior at y = -3.
POCKET = box(-60.0, -3.0, -50.0, 3.0)


def _castle(angle: float, depth: float = 1.0) -> CastleParams:
    return CastleParams(hinge_pocket_depth_mm=depth, hinge_pocket_angle_deg=angle)


# ------------------------------------------------------------------ the plane

def test_front_floor_holds_the_depth_on_the_superior_edge():
    castle = _castle(5.0)
    (_, floor), = castle_pocket_floors([POCKET], castle)
    fixed = castle.zones.endpiece_mm - 1.0
    assert floor.z(-55.0, 3.0) == pytest.approx(fixed)
    assert floor.z(-60.0, 3.0) == pytest.approx(fixed)           # no x dependence
    assert floor.z(-55.0, -3.0) == pytest.approx(fixed - 6.0 * math.tan(math.radians(5)))
    assert floor.extremes(POCKET) == pytest.approx(
        (fixed - 6.0 * math.tan(math.radians(5)), fixed))


def test_negative_angle_raises_the_inferior_edge():
    (_, floor), = castle_pocket_floors([POCKET], _castle(-3.0))
    assert floor.z(-55.0, -3.0) > floor.z(-55.0, 3.0)


def test_zero_angle_is_exactly_flat():
    castle = _castle(0.0)
    (_, floor), = castle_pocket_floors([POCKET], castle)
    assert floor.flat
    assert floor.z(-55.0, -3.0) == castle.zones.endpiece_mm - 1.0


def test_each_pocket_pivots_on_its_own_superior_edge():
    lower = box(50.0, -8.0, 60.0, -2.0)
    pairs = castle_pocket_floors([POCKET, lower], _castle(4.0))
    fixed = CastleParams().zones.endpiece_mm - 1.0
    assert pairs[0][1].z(-55.0, 3.0) == pytest.approx(fixed)
    assert pairs[1][1].z(55.0, -2.0) == pytest.approx(fixed)


def test_temple_pivots_on_the_hinge_end_whichever_way_it_points():
    """The anterior edge is the one nearer the hinge end: +x for a temple whose
    hinge is at +x, -x after the snap's 180° turn puts it at -x."""
    t = TempleParams(hinge_pocket_depth_mm=1.0, hinge_pocket_angle_deg=5.0)
    fixed = t.blank_thickness_mm - 1.0
    drop = 10.0 * math.tan(math.radians(5.0))

    outline = box(-80.0, -6.0, 60.0, 6.0)             # hinge end at +x
    pocket = box(45.0, -3.0, 55.0, 3.0)
    (_, floor), = temple_pocket_floors([pocket], t, outline)
    assert floor.z(55.0, 0.0) == pytest.approx(fixed)
    assert floor.z(45.0, 0.0) == pytest.approx(fixed - drop)
    assert floor.z(50.0, 3.0) == pytest.approx(floor.z(50.0, -3.0))   # no roll

    outline = box(-60.0, -6.0, 80.0, 6.0)             # hinge end at -x
    pocket = box(-55.0, -3.0, -45.0, 3.0)
    (_, floor), = temple_pocket_floors([pocket], t, outline)
    assert floor.z(-55.0, 0.0) == pytest.approx(fixed)
    assert floor.z(-45.0, 0.0) == pytest.approx(fixed - drop)


# ------------------------------------------------------------------ raster

@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _pocket_cells(field, poly):
    rows, cols = field.z.shape
    ox, oy = field.origin
    gx, gy = np.meshgrid(ox + np.arange(cols) * field.resolution,
                         oy + np.arange(rows) * field.resolution)
    m = contains_xy(poly, gx.ravel(), gy.ravel()).reshape(rows, cols)
    return m, gx, gy


def test_castle_relief_zero_angle_is_unchanged(demo):
    from guildmodel.core.relief.castle import build_castle_relief

    part, hinges = demo
    before = build_castle_relief(part, CastleParams(), hinges, resolution=0.4)
    after = build_castle_relief(part, _castle(0.0), hinges, resolution=0.4)
    assert np.array_equal(before.field.z, after.field.z)


def test_castle_relief_floor_follows_the_plane(demo):
    from guildmodel.core.relief.castle import build_castle_relief

    part, hinges = demo
    castle = _castle(6.0)
    relief = build_castle_relief(part, castle, hinges, resolution=0.2)
    for poly, floor in castle_pocket_floors(hinges, castle):
        m, gx, gy = _pocket_cells(relief.field, poly)
        m &= relief.inside
        assert m.any()
        np.testing.assert_allclose(relief.field.z[m], floor.z(gx[m], gy[m]),
                                   atol=1e-9)
        # superior cells higher than inferior ones
        ys = gy[m]
        zs = relief.field.z[m]
        assert zs[ys > np.median(ys)].mean() > zs[ys < np.median(ys)].mean()


def test_temple_relief_floor_follows_the_plane():
    from guildmodel.core.relief.flat import build_temple_relief

    t = TempleParams(hinge_pocket_depth_mm=1.0, hinge_pocket_angle_deg=4.0)
    outline = box(-80.0, -6.0, 60.0, 6.0)
    pocket = box(45.0, -3.0, 55.0, 3.0)
    relief = build_temple_relief(outline, t, [pocket], resolution=0.1)
    (_, floor), = temple_pocket_floors([pocket], t, outline)
    m, gx, gy = _pocket_cells(relief.field, pocket)
    m &= relief.inside
    np.testing.assert_allclose(relief.field.z[m], floor.z(gx[m], gy[m]), atol=1e-9)


# ------------------------------------------------------------------ solids

def _expected_cut(poly: Polygon, floor, top: float) -> float:
    """Volume between a plane and `top` over `poly`: area x mean height, and the
    mean of a plane over a polygon is its value at the centroid."""
    c = poly.centroid
    return poly.area * (top - floor.z(c.x, c.y))


@pytest.mark.parametrize("angle", [0.0, 7.5, -4.0])
def test_mesh_pocket_cutter_is_the_prism_above_the_plane(angle):
    from guildmodel.core.model.build import hinge_pockets

    castle = _castle(angle)
    top = 8.0
    (cutter,) = hinge_pockets([POCKET], castle, top)
    (_, floor), = castle_pocket_floors([POCKET], castle)
    assert cutter.volume() == pytest.approx(_expected_cut(POCKET, floor, top), rel=1e-9)
    lo = cutter.bounding_box()[2]
    assert lo == pytest.approx(floor.extremes(POCKET)[0], abs=1e-9)


@pytest.mark.parametrize("angle", [0.0, 7.5, -4.0])
def test_occ_pocket_cutter_matches_the_mesh(angle):
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.solid.features import hinge_pocket_cutters
    from guildmodel.core.solid.occ import volume

    castle = _castle(angle)
    top = 8.0
    (cutter,) = hinge_pocket_cutters([POCKET], castle, top)
    (_, floor), = castle_pocket_floors([POCKET], castle)
    assert volume(cutter) == pytest.approx(_expected_cut(POCKET, floor, top), rel=1e-6)


# ------------------------------------------------------------------ CAM

def test_zero_angle_posts_the_historical_path():
    params = CastleCamParams()
    castle = _castle(0.0)
    floor_z = castle.zones.endpiece_mm - 1.0
    old = hinge_pocket_op([POCKET], floor_z, 6.5, 1.0, params)
    new = hinge_pocket_op([POCKET], floor_z, 6.5, 1.0, params,
                          floors=[f for _, f in castle_pocket_floors([POCKET], castle)])
    assert old.paths == new.paths


@pytest.mark.parametrize("angle", [5.0, -5.0])
def test_tilted_pocket_path_never_gouges_and_reaches_the_floor(angle):
    """Every point stays at or above the floor under the tool's uphill edge, and
    the last pass lies on that surface: it gets as deep as the plane allows."""
    params = CastleCamParams()
    castle = _castle(angle, depth=2.0)
    r = 1.0
    (_, floor), = castle_pocket_floors([POCKET], castle)
    lift = r * abs(floor.slope)
    op = hinge_pocket_op([POCKET], floor.z_fixed, castle.stock.blank_thickness_mm + 0.5,
                         r, params, floors=[floor])
    pts = np.array([p for path in op.paths for p in path])
    safe = floor.z(pts[:, 0], pts[:, 1]) + lift
    assert (pts[:, 2] >= safe - 1e-6).all()
    on_floor = np.isclose(pts[:, 2], safe, atol=1e-6)
    assert on_floor.sum() > 10
    # The finishing pass spans the slope: points on the floor surface cover
    # nearly the whole pocket height, less the tool radius at each side.
    ys = pts[on_floor, 1]
    assert ys.max() - ys.min() == pytest.approx(6.0 - 2 * r, abs=0.3)


def test_flat_pocket_has_no_finishing_pass():
    from guildmodel.core.cam.castle_ops import tilted_floor_finish

    castle = _castle(0.0)
    (_, floor), = castle_pocket_floors([POCKET], castle)
    op = hinge_pocket_op([POCKET], floor.z_fixed, 6.5, 1.0, CastleCamParams(),
                         floors=[floor])
    assert len(op.paths) == 1
    tilted = castle_pocket_floors([POCKET], _castle(5.0))[0][1]
    assert tilted_floor_finish(POCKET, tilted, 1.0, 0.25)


def test_finishing_lines_are_level_and_run_along_the_contours():
    from guildmodel.core.cam.castle_ops import tilted_floor_finish

    (_, floor), = castle_pocket_floors([POCKET], _castle(5.0))
    paths = tilted_floor_finish(POCKET, floor, 1.0, 0.25)
    assert len(paths) == 1                     # a box: one unbroken zigzag
    pts = np.array(paths[0])
    lines = pts.reshape(-1, 2, 3)              # (start, end) per contour line
    assert np.allclose(lines[:, 0, 1], lines[:, 1, 1])   # front contours run in x
    assert np.allclose(lines[:, 0, 2], lines[:, 1, 2])   # and are level
    steps = np.diff(lines[:, 0, 1])
    assert np.all(steps < 0) and np.abs(steps).max() <= 0.25 + 1e-9
    assert lines[0, 0, 1] == pytest.approx(3.0 - 1.0)    # superior limit of the center
    assert lines[-1, 0, 1] == pytest.approx(-3.0 + 1.0)  # inferior limit


def test_finishing_pass_takes_the_ridges_down():
    """Simulated: away from the downhill wall strip, which a flat end cannot
    reach, what is left is under `finish stepover x tan(angle)`."""
    from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor

    pocket = box(0.0, 0.0, 8.0, 12.0)
    (_, floor), = castle_pocket_floors([pocket], _castle(5.0, depth=2.0))
    params = CastleCamParams()
    r = 1.0
    op = hinge_pocket_op([pocket], floor.z_fixed, 7.0, r, params, floors=[floor])
    res = 0.02
    shape = (int(14 / res), int(10 / res))
    got = achieved_floor(op.paths, ToolProfile(kind="flat", radius_mm=r),
                         (-1.0, -1.0), shape, res, init_z=99.0)
    gx, gy = np.meshgrid(-1.0 + np.arange(shape[1]) * res,
                         -1.0 + np.arange(shape[0]) * res)
    # clear of the downhill strip and of the square corners no round end reaches
    field = (gx > r) & (gx < 8.0 - r) & (gy > 2 * r + 0.05) & (gy < 11.95)
    left = got[field] - floor.z(gx[field], gy[field])
    assert left.min() > -0.005                                    # no gouge
    ridge = params.pocket_finish_stepover_mm * math.tan(math.radians(5.0))
    assert left.max() < ridge + 0.01


def test_temple_program_tilts_about_the_hinge_end():
    import yaml
    from guildmodel.core.cam.temple_ops import temple_hinge_pocket_op

    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text())

    t = TempleParams(hinge_pocket_depth_mm=1.5, hinge_pocket_angle_deg=6.0)
    outline = box(-80.0, -6.0, 60.0, 6.0)
    pocket = box(40.0, -3.0, 55.0, 3.0)
    op = temple_hinge_pocket_op([pocket], t, tools, CastleCamParams(),
                                outline=outline)
    pts = np.array([p for path in op.paths for p in path])
    deepest = pts[np.argmin(pts[:, 2])]
    assert deepest[0] < 47.5          # the posterior (−x) end is the deep one


# ------------------------------------------------------------------ limits

def test_angle_range_keeps_both_edges_inside_the_endpiece():
    castle = _castle(0.0, depth=1.0)
    lim = castle_limits(castle, hinge_polys=[POCKET])["hinge_pocket_angle_deg"]
    ceiling = castle.zones.endpiece_mm - MIN_POCKET_FLOOR_MM
    assert math.tan(math.radians(lim.low)) * 6.0 == pytest.approx(-1.0)
    assert math.tan(math.radians(lim.high)) * 6.0 == pytest.approx(ceiling - 1.0)


def test_tilt_narrows_the_depth_range():
    castle = _castle(5.0, depth=1.0)
    rise = 6.0 * math.tan(math.radians(5.0))
    lim = castle_limits(castle, hinge_polys=[POCKET])["hinge_pocket_depth_mm"]
    ceiling = castle.zones.endpiece_mm - MIN_POCKET_FLOOR_MM
    assert lim.high == pytest.approx(ceiling - rise)

    lim = castle_limits(_castle(-5.0), hinge_polys=[POCKET])["hinge_pocket_depth_mm"]
    assert lim.low == pytest.approx(rise)


def test_no_hinges_leaves_the_angle_unbounded_and_the_depth_as_it_was():
    lims = castle_limits(_castle(5.0))
    assert "hinge_pocket_angle_deg" not in lims
    assert lims["hinge_pocket_depth_mm"].low == 0.0


def test_temple_limits_measure_along_the_temple():
    t = TempleParams(hinge_pocket_depth_mm=1.0)
    pocket = box(40.0, -3.0, 55.0, 3.0)
    lim = temple_limits(t, [pocket], box(-80.0, -6.0, 60.0, 6.0))
    assert math.tan(math.radians(lim["hinge_pocket_angle_deg"].low)) * 15.0 \
        == pytest.approx(-1.0)
    assert pocket_span([pocket], (1.0, 0.0)) == pytest.approx(15.0)


# ------------------------------------------------------------------ schema / GUI

def test_old_projects_load_flat():
    c = CastleParams.model_validate(
        CastleParams().model_dump(exclude={"hinge_pocket_angle_deg"}))
    t = TempleParams.model_validate(
        TempleParams().model_dump(exclude={"hinge_pocket_angle_deg"}))
    assert c.hinge_pocket_angle_deg == 0.0 and t.hinge_pocket_angle_deg == 0.0


def test_panel_round_trips_the_angle_on_both_tabs():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    QApplication.instance() or QApplication([])
    panel = ParamsPanel()
    panel.set_castle_params(_castle(3.5))
    assert panel.castle_params().hinge_pocket_angle_deg == pytest.approx(3.5)

    # The temple's depth used to be dropped on every read of the tab.
    panel.set_temple_params(TempleParams(hinge_pocket_depth_mm=1.4,
                                         hinge_pocket_angle_deg=-2.0))
    t = panel.temple_params()
    assert t.hinge_pocket_depth_mm == pytest.approx(1.4)
    assert t.hinge_pocket_angle_deg == pytest.approx(-2.0)


def test_panel_bounds_the_angle_from_the_drawing():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    QApplication.instance() or QApplication([])
    panel = ParamsPanel()
    panel.set_castle_params(_castle(0.0))
    panel.set_hinges([POCKET])
    low, high = panel.hinge_pocket_angle.safe_range()
    assert low == pytest.approx(math.degrees(math.atan(-1.0 / 6.0)), abs=0.05)
    assert high > 0.0
