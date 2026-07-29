"""Whole-bed cut simulation (BUILDPLAN M7.7).

The geometric verifier for the nested worktable: each placed component's single-part
cut sim is composited onto one machine-coordinate bed grid and verified for
completeness / gouge across the whole bed (`core/sim/bed.py`). Headless except the
GUI `BedSimWorker` smoke (offscreen Qt).
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleCamParams, Worktable,
)
from guildmodel.core.sim import verify
from guildmodel.core.sim.bed import ComponentSim, composite_bed_report, simulate_component

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())


# ------------------------------------------------------------------ composite (pure)

def _square_comp(*, dx, dy, label, kind, proud_right=False):
    """A 10×10 mm component (1 mm grid): target flat at z=4, floor reached (=4)
    everywhere, optionally left 'proud' (uncut) on its right half."""
    inside = np.ones((10, 10), dtype=bool)
    target = np.full((10, 10), 4.0)
    floor = np.full((10, 10), 4.0)
    if proud_right:
        floor[:, 5:] = 10.0                       # right half left well above target
    return ComponentSim(floor, np.where(inside, target, np.nan), inside,
                        origin=(0.0, 0.0), resolution=1.0, dx=dx, dy=dy,
                        label=label, kind=kind)


def test_composite_counts_every_component_body():
    a = _square_comp(dx=0, dy=0, label="A", kind="frame_front")
    b = _square_comp(dx=20, dy=0, label="B", kind="temple_right")
    report = composite_bed_report([a, b], (40.0, 20.0), resolution=1.0)
    assert report.completeness.body_cells == 200       # two disjoint 10×10 bodies


def test_composite_flags_an_uncut_component_in_its_bed_region():
    reached = _square_comp(dx=0, dy=0, label="A", kind="frame_front")
    proud = _square_comp(dx=20, dy=0, label="B", kind="temple_right", proud_right=True)
    report = composite_bed_report([reached, proud], (40.0, 20.0), resolution=1.0)
    # only B's right half (5×10 = 50 cells) is proud > tol
    assert report.completeness.uncut_cells == 50
    # ...and those cells live in B's bed region (placed at dx=20)
    _rows, cols = np.nonzero(report.completeness.uncut_mask)
    assert cols.min() >= 20


def test_composite_translates_to_the_placement_offset():
    a = _square_comp(dx=100, dy=50, label="A", kind="frame_front")
    report = composite_bed_report([a], (200.0, 120.0), resolution=1.0)
    rows, cols = np.nonzero(np.isfinite(report.target))
    assert cols.min() == 100 and rows.min() == 50      # design [0,0] → machine (100,50)


# ------------------------------------------------------------------ simulate_component

def test_simulate_component_block_reaches_its_flat_top():
    from shapely.geometry import Polygon
    lens = Polygon([(0, 0), (40, 0), (40, 26), (0, 26)])
    spec = {"mode": "block", "kind": "base_curve_right", "label": "BC",
            "lens": lens, "block": BaseCurveBlockParams()}
    floor, target, inside, origin, res = simulate_component(
        spec, cam=CastleCamParams(), tools_cfg=TOOLS, mats_cfg=MATS,
        material_name="acetate", resolution=0.6)
    assert inside.any() and floor.shape == target.shape == inside.shape
    rep = verify(floor, target, inside, origin, res, partition=None)
    # the block is a flat blank (only the profile + holes are cut) — its top is
    # reached by construction, so completeness is high.
    assert rep.completeness.uncut_fraction < 0.1


# ------------------------------------------------------------------ GUI BedSimWorker

def test_bed_sim_worker_composites_a_nest(tmp_path, monkeypatch):
    """The GUI BedSimWorker simulates a nested block and returns a whole-bed report
    (BUILDPLAN M7.7)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from shapely.geometry import Polygon

    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import BedSimWorker, NestWorker

    bed = Worktable.from_fixture_dict(FIXTURE)
    lens = Polygon([(0, 0), (40, 0), (40, 26), (0, 26)])
    spec = {"mode": "block", "kind": "base_curve_right", "label": "BC R",
            "lens": lens, "block": BaseCurveBlockParams()}

    nests = []
    nw = NestWorker([spec], bed, cam_params=CastleCamParams())
    nw.finished.connect(lambda n: nests.append(n))
    nw.run()
    nest = nests[0]
    assert nest.placements

    done, errs = [], []
    sw = BedSimWorker([spec], nest.placements,
                      (bed.work_area_width_mm, bed.work_area_height_mm),
                      cam_params=CastleCamParams(), material_name="acetate")
    sw.finished.connect(lambda r, lines: done.append((r, lines)))
    sw.error.connect(lambda tb: errs.append(tb))
    sw.run()
    assert errs == [], errs[0] if errs else ""
    assert done
    report, lines = done[0]
    assert report.completeness.body_cells > 0
    assert report.status() in {"ok", "warn", "fail"}
    assert lines
