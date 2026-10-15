"""The bed simulation composites a rotated placement (BUILDPLAN M19 §4.1.4).

A placement is the affine ``p ↦ R(θ)·p + (dx, dy)`` from the part's design
frame; the nest's ops carry it, and so must the heightfields the whole-bed
report and the bed removal are composited from. Until M19 `composite_bed_report`
and `_bed_stock` applied the translation only — a left temple nested at its 180°
default was verified against a floor that faced the other way — on the strength
of a comment that rotation defaulted to 0 in the nest, which had been false since
the 180° seed for an unsnapped left temple.

Three checks, each independent of the others' arithmetic: the exact quarter-turn
path against the affine applied to one marked cell; the resampler against the
exact path at 90°; and both against a direct machine-frame stamp of the rotated
toolpaths, the oracle. Headless (numpy + scipy); the worker check is offscreen Qt
without a window.
"""
import math

import numpy as np
import pytest
from scipy.ndimage import binary_dilation, binary_erosion

from guildmodel.core.sim.bed import (
    BedRemovalPart, ComponentSim, _bed_stock, _resample_fields, _rot90_fields,
    composite_bed_report, placed_fields,
)
from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor

RES = 0.4


def _place(x, y, deg, dx, dy):
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    return (c * x - s * y + dx, s * x + c * y + dy)


def _place_path(path, deg, dx, dy):
    return [(*_place(x, y, deg, dx, dy), z) for x, y, z in path]


# ------------------------------------------------------------------ placed_fields

def test_no_rotation_is_the_translation_it_was():
    f = np.arange(12.0).reshape(3, 4)
    out, origin = placed_fields([f], (1.0, 2.0), 0.5, 10.0, 20.0, 0.0, kinds=("height",))
    assert out[0] is f and origin == (11.0, 22.0)      # the grid itself, not a copy
    out, origin = placed_fields([f], (1.0, 2.0), 0.5, 10.0, 20.0, 360.0, kinds=("height",))
    assert out[0] is f and origin == (11.0, 22.0)      # a full turn is none


@pytest.mark.parametrize("deg", [90, 180, 270, -90])
def test_a_quarter_turn_puts_a_cell_where_the_placement_does(deg):
    """One marked cell, off-center both ways, lands at R(θ)·p + d exactly."""
    f = np.zeros((5, 9))
    f[1, 7] = 1.0
    origin = (-1.6, -0.8)
    dx, dy = 7.0, 3.0
    (g,), (mx, my) = placed_fields([f], origin, RES, dx, dy, deg, kinds=("height",))
    assert g.shape == ((9, 5) if deg % 180 else (5, 9))
    r, c = np.argwhere(g == 1.0)[0]
    got = (mx + c * RES, my + r * RES)
    want = _place(origin[0] + 7 * RES, origin[1] + 1 * RES, deg, dx, dy)
    assert got == pytest.approx(want, abs=1e-9)
    assert g.sum() == 1.0                              # exact: nothing interpolated


def _by_position(field, origin):
    r, c = np.indices(field.shape)
    xs = np.round((origin[0] + c * RES) / RES).astype(int)
    ys = np.round((origin[1] + r * RES) / RES).astype(int)
    return {(int(x), int(y)): v for x, y, v in zip(xs.ravel(), ys.ravel(), field.ravel())}


def test_the_resampler_agrees_with_the_exact_quarter_turn():
    """At 90° both paths exist; laid out so the exact path's lattice lands on the
    machine grid, every cell of it is found in the resampled grid, mask and
    height alike, and the resampler's extra margin carries no body."""
    rng = np.random.default_rng(7)
    rows, cols = 7, 11
    height = rng.uniform(1.0, 5.0, (rows, cols))
    mask = np.zeros((rows, cols), dtype=bool)
    mask[1:-1, 2:-2] = True
    mask[2, 3] = False                                  # a hole, to catch a flip
    origin, dx, dy = (0.0, 0.0), 10.0, 4.8               # placed center on the grid
    (ah, am), ao = _rot90_fields([height, mask], origin, RES, dx, dy, 1)
    (bh, bm), bo = _resample_fields([height, mask], origin, RES, dx, dy, 90.0,
                                    kinds=("height", "mask"))
    a_h, a_m = _by_position(ah, ao), _by_position(am, ao)
    b_h, b_m = _by_position(bh, bo), _by_position(bm, bo)
    assert set(a_h) <= set(b_h)
    for key, v in a_h.items():
        assert b_h[key] == pytest.approx(v, abs=1e-9)
        assert b_m[key] == a_m[key]
    assert not any(b_m[k] for k in set(b_m) - set(a_m))


def test_a_target_keeps_its_body_and_its_nan_off_it():
    """A target is NaN off the body; rotating it must not bleed NaN into the
    body or values out of it."""
    rows, cols = 9, 15
    inside = np.zeros((rows, cols), dtype=bool)
    inside[2:-2, 3:-3] = True
    target = np.where(inside, 3.0, np.nan)
    (t, m), _ = placed_fields([target, inside], (0.0, 0.0), RES, 5.0, 5.0, 37.0,
                              kinds=("target", "mask"))
    assert np.isfinite(t[m]).all() and np.allclose(t[m], 3.0)
    assert np.isnan(t[~m]).all()


# ------------------------------------------------------------------ the oracle

def _asymmetric_paths():
    """A pocket near the +x end (five raster lines at z = 2) and a slot above the
    axis near the −x end (z = 3): no symmetry a wrong turn could hide behind.
    Every coordinate is on the cell pitch, so no tool position sits on a half
    cell of either lattice, where round-half-to-even would decide the cell by
    floating-point noise and spoil the exact comparison."""
    pocket = [[(8.0, y, 2.0), (12.0, y, 2.0)] for y in (-1.6, -0.8, 0.0, 0.8, 1.6)]
    slot = [[(-12.0, 3.2, 3.0), (-4.0, 3.2, 3.0)]]
    return pocket + slot


TOOL = ToolProfile("flat", 1.0)
INIT_Z = 4.0
# An odd count of cells each way with the origin on the grid, so the lattice
# center is a cell center at (0, 0): a quarter turn about it then lands on the
# bed grid and the exact path can be held to exact equality.
D_ORIGIN = (-16.0, -7.2)
D_SHAPE = (37, 81)
BED = (60.0, 40.0)
BED_SHAPE = (int(round(BED[1] / RES)), int(round(BED[0] / RES)))


def _design_sim(deg, dx, dy):
    paths = _asymmetric_paths()
    floor = achieved_floor(paths, TOOL, D_ORIGIN, D_SHAPE, RES, INIT_Z)
    inside = np.ones(D_SHAPE, dtype=bool)
    return ComponentSim(floor, floor.copy(), inside, D_ORIGIN, RES, dx=dx, dy=dy,
                        label="part", kind="temple_left", rotation_deg=deg)


def _direct_stamp(deg, dx, dy):
    paths = [_place_path(p, deg, dx, dy) for p in _asymmetric_paths()]
    return achieved_floor(paths, TOOL, (0.0, 0.0), BED_SHAPE, RES, INIT_Z)


@pytest.mark.parametrize("deg", [0, 90, 180, 270, 37, 123])
def test_the_composite_matches_a_direct_stamp_of_the_rotated_ops(deg):
    """Within one cell: every cut cell of the composite is within a cell (eight
    neighbors) of one in the direct stamp and the other way round, and away
    from the edges the depths are the same number.

    A cell counts as cut below half the shallowest cut's depth, so the bilinear
    ramp a resampled edge carries over its neighbor is not a cut cell; the
    quarter turns are exact and need no such allowance (measured 2026-10-14:
    at the raw threshold a resampled edge reaches two cells out, at half depth
    one, at 15°, 37°, 60° and 123° alike)."""
    dx, dy = 30.0, 20.0
    report = composite_bed_report([_design_sim(deg, dx, dy)], BED, resolution=RES)
    direct = _direct_stamp(deg, dx, dy)
    body = np.isfinite(report.target)
    cut_c = body & (report.floor < INIT_Z - 0.5)
    cut_m = direct < INIT_Z - 0.5
    assert cut_c.any() and cut_m.any()
    near = np.ones((3, 3), dtype=bool)
    assert not (cut_c & ~binary_dilation(cut_m, structure=near)).any()
    assert not (cut_m & ~binary_dilation(cut_c, structure=near)).any()
    core = binary_erosion(cut_c & cut_m, iterations=2)
    assert core.sum() > 20
    assert np.abs(report.floor[core] - direct[core]).max() < 1e-6
    if deg % 90 == 0:                                    # exact, no interpolation
        assert np.array_equal(cut_c, cut_m)


def test_a_left_temple_at_180_faces_its_pocket_the_other_way():
    """The case that was wrong: at the 180° nest default the pocket, drawn near
    +x, is cut near −x of the placement, and the composite says so."""
    dx, dy = 30.0, 20.0
    report = composite_bed_report([_design_sim(180.0, dx, dy)], BED, resolution=RES)
    body = np.isfinite(report.target)
    deep = body & (report.floor < 2.0 + 1e-6)          # the pocket floor, z = 2
    rows, cols = np.nonzero(deep)
    cx, cy = cols.mean() * RES, rows.mean() * RES
    assert (cx, cy) == pytest.approx((dx - 10.0, dy), abs=RES)
    # ...and the translation-only composite of old would have put it at +10
    assert abs(cx - (dx + 10.0)) > 10.0


# ------------------------------------------------------------------ the bed stock

def test_the_bed_stock_turns_with_the_part():
    """A front's stock has its pad block at one end; nested at 180° the raised
    region is at the other end of the cropped bed."""
    rows, cols = 10, 30
    stock = np.full((rows, cols), 6.0)
    stock[:, 20:] = 10.0                                 # the pad block, +x end
    part = BedRemovalPart([], stock, (0.0, 0.0), dx=40.0, dy=10.0, rotation_deg=180.0)
    bed, (ox, oy) = _bed_stock([part], RES, 2.0)
    raised = bed > 9.0
    assert raised.any()
    cols_r = np.nonzero(raised)[1]
    x_raised = ox + cols_r.mean() * RES
    x_blank = ox + np.nonzero((bed > 5.0) & ~raised)[1].mean() * RES
    assert x_raised < x_blank                            # +x end became the −x end
    assert x_raised == pytest.approx(40.0 - 25.0 * RES, abs=RES)


def test_a_flat_blank_keeps_its_height_when_turned():
    """A temple's stock is one height; turned 37° it is still that height on
    the footprint and nothing beyond its corners."""
    stock = np.full((12, 40), 4.0)
    part = BedRemovalPart([], stock, (0.0, 0.0), dx=30.0, dy=20.0, rotation_deg=37.0)
    bed, _ = _bed_stock([part], RES, 2.0)
    on = bed > 2.0                                       # the edge cells ramp to zero
    assert on.sum() == pytest.approx(stock.size, rel=0.05)
    assert bed.max() == pytest.approx(4.0)
    assert (bed[on] > 3.99).mean() > 0.85                # the ramp is one cell wide


# ------------------------------------------------------------------ the worker

def test_the_bed_sim_worker_hands_the_rotation_on(tmp_path, monkeypatch):
    """`BedSimWorker` builds each `ComponentSim` and `BedRemovalPart` with the
    placement's rotation, not only its offset."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from shapely.geometry import Polygon

    QApplication.instance() or QApplication([])
    import guildmodel.core.sim as sim_pkg
    from guildmodel.core.cam.castle_ops import CamOp
    from guildmodel.core.cam.layout import BedPlacement
    from guildmodel.core.project.schema import BaseCurveBlockParams, CastleCamParams
    from guildmodel.gui.app import BedSimWorker

    lens = Polygon([(0, 0), (40, 0), (40, 26), (0, 26)])
    spec = {"mode": "block", "kind": "base_curve_right", "label": "BC R",
            "lens": lens, "block": BaseCurveBlockParams()}
    pl = BedPlacement(kind="base_curve_right", label="BC R", zone_id="z",
                      role="base_curve_right", dx=100.0, dy=50.0, rotation_deg=180.0,
                      ops=[CamOp("Block Profile", paths=[[(0.0, 0.0, 0.0)]])])

    seen: dict = {}
    real_report, real_plan = sim_pkg.composite_bed_report, sim_pkg.build_bed_removal_plan

    def fake_report(comps, work_area, *, resolution, **kw):
        seen["comps"] = comps
        return real_report(comps, work_area, resolution=resolution, **kw)

    def fake_plan(parts, *, resolution, **kw):
        seen["parts"] = parts
        return real_plan(parts, resolution=resolution, **kw)

    monkeypatch.setattr(sim_pkg, "composite_bed_report", fake_report)
    monkeypatch.setattr(sim_pkg, "build_bed_removal_plan", fake_plan)

    errs = []
    worker = BedSimWorker([spec], [pl], (300.0, 200.0), cam_params=CastleCamParams())
    worker.error.connect(lambda tb: errs.append(tb))
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert [c.rotation_deg for c in seen["comps"]] == [180.0]
    assert [p.rotation_deg for p in seen["parts"]] == [180.0]
    assert (seen["comps"][0].dx, seen["comps"][0].dy) == (100.0, 50.0)
