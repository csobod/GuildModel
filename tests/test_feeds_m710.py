"""Feeds & speeds / chip-load calculator (BUILDPLAN M7.10).

Ties the tool (flutes / diameter) to the program's feed + spindle: chip load (feed
per tooth), surface speed, the inverse, and a per-material window that flags a cut
that's too light or too heavy. Headless math + an offscreen CAM-tab read-out smoke.
"""
import math
from pathlib import Path

import pytest
import yaml

from guildmodel.core.cam import feeds

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())


# ------------------------------------------------------------------ math

def test_chip_load_basic():
    # the demo acetate program: 750 mm/min, 10000 rpm, 1 flute → 0.075 mm/tooth
    assert feeds.chip_load_mm(750, 10000, 1) == pytest.approx(0.075)
    assert feeds.chip_load_mm(600, 12000, 2) == pytest.approx(0.025)


def test_chip_load_guards():
    assert feeds.chip_load_mm(750, 0, 1) is None
    assert feeds.chip_load_mm(750, 10000, 0) is None


def test_feed_from_chip_load_is_the_inverse():
    feed = feeds.feed_from_chip_load_mmpm(0.075, 10000, 1)
    assert feed == pytest.approx(750.0)
    assert feeds.chip_load_mm(feed, 10000, 1) == pytest.approx(0.075)


def test_surface_speed():
    # π · D · n, D in metres: 3.175 mm @ 10000 rpm ≈ 99.7 m/min
    vc = feeds.surface_speed_m_per_min(3.175, 10000)
    assert vc == pytest.approx(math.pi * 0.003175 * 10000)
    assert vc == pytest.approx(99.7, abs=0.5)


def test_chip_load_status_window():
    lo, hi = 0.02, 0.15
    assert feeds.chip_load_status(0.075, lo, hi) == "ok"
    assert feeds.chip_load_status(0.005, lo, hi) == "low"
    assert feeds.chip_load_status(0.30, lo, hi) == "high"
    assert feeds.chip_load_status(0.075, None, None) == "unknown"
    assert feeds.chip_load_status(None, lo, hi) == "unknown"


def test_materials_carry_a_chip_load_window():
    for name in ("acetate", "acetal", "horn"):
        m = MATS[name]
        assert "chip_load_min_mm" in m and "chip_load_max_mm" in m
        assert m["chip_load_min_mm"] < m["chip_load_max_mm"]
    # the demo acetate feed lands inside its own window
    cl = feeds.chip_load_mm(MATS["acetate"]["feed_rate_mmpm"],
                            MATS["acetate"]["spindle_rpm"], 1)
    assert feeds.chip_load_status(
        cl, MATS["acetate"]["chip_load_min_mm"],
        MATS["acetate"]["chip_load_max_mm"]) == "ok"


# ------------------------------------------------------------------ CAM-tab read-out

def test_params_panel_chip_readout(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    p = ParamsPanel()
    # default flat_3175 (1 flute) @ acetate (750 / 10000) → 0.0750 mm/tooth, in range
    assert "mm/tooth" in p._chip_load_lbl.text()
    assert "0.075" in p._chip_load_lbl.text()
    assert "m/min" in p._surface_speed_lbl.text()
    assert "within" in p._chip_status_lbl.text().lower()
