"""Tool visualizer, the V-bit ToolProfile & depth/stickout reach (BUILDPLAN M7.9).

The engrave bit becomes a real V-bit (a cone drop profile, groove width =
2·depth·tan(half-angle)); the Preferences editor gets a live 2D cross-section; and
the reach check gains a depth/flute-length sibling of the width check.
"""
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildcam.core.sim.toolsim import ToolProfile
from guildcam.core.cam.castle_ops import CamOp, depth_reach_warnings
from guildcam.core.cam.tooling import ToolSpec

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildcam" / "config"
SHIPPED_TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())


# ------------------------------------------------------------------ V-bit profile

def test_vbit_from_tool_reads_angle():
    prof = ToolProfile.from_tool(
        {"type": "vbit", "radius_mm": 0.25, "included_angle_deg": 30.0})
    assert prof.kind == "vbit" and prof.included_angle_deg == 30.0


def test_vbit_kernel_is_a_cone():
    prof = ToolProfile(kind="vbit", radius_mm=3.0, included_angle_deg=60.0)
    di, dj, dz = prof.kernel(0.25)
    dd = np.hypot(di, dj) * 0.25
    t = math.tan(math.radians(30.0))
    m = dd > 0.5                                 # away from the tip cell
    assert np.allclose(dz[m], dd[m] / t, rtol=0.02, atol=0.05)


def test_vbit_groove_widens_with_a_wider_angle():
    # at the same depth, a wider included angle removes a wider groove
    res, depth = 0.2, 0.6
    from guildcam.core.sim.toolsim import achieved_floor
    shape, origin, init = (40, 40), (-4.0, -4.0), 5.0
    path = [(-3.0, 0.0, init - depth), (3.0, 0.0, init - depth)]   # a scribe line at -depth
    narrow = achieved_floor([path], ToolProfile("vbit", 3.0, included_angle_deg=30.0),
                            origin, shape, res, init)
    wide = achieved_floor([path], ToolProfile("vbit", 3.0, included_angle_deg=90.0),
                          origin, shape, res, init)
    cut_narrow = int((narrow < init - 1e-6).sum())
    cut_wide = int((wide < init - 1e-6).sum())
    assert cut_wide > cut_narrow


def test_shipped_engrave_bit_is_now_a_vbit():
    e = SHIPPED_TOOLS["engrave_vbit"]
    assert e["type"] == "vbit"
    assert e["included_angle_deg"] == 30.0
    assert e["diameter_mm"] == 0.5              # still the 0.5 mm bit (back-compat)


# ------------------------------------------------------------------ depth reach

def _op(name, z, *, flute=None):
    tool = {"name": "t", "type": "flat", "radius_mm": 1.5, "diameter_mm": 3.0}
    if flute is not None:
        tool["flute_length_mm"] = flute
    return CamOp(name, paths=[[(0.0, 0.0, z)]], tool=tool)


def test_depth_reach_warns_when_cut_exceeds_flute():
    w = depth_reach_warnings([_op("Perimeter", 0.4, flute=4.0)], stock_top_mm=6.0)
    assert w and "Perimeter" in w[0].message()
    assert w[0].cut_depth_mm == pytest.approx(5.6)


def test_depth_reach_quiet_when_it_fits_or_unspecified():
    assert depth_reach_warnings([_op("Perimeter", 0.4, flute=8.0)], stock_top_mm=6.0) == []
    assert depth_reach_warnings([_op("Perimeter", 0.4)], stock_top_mm=6.0) == []  # no flute


# ------------------------------------------------------------------ visualizer

def test_tool_view_renders_every_type(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from guildcam.gui.widgets.tool_view import ToolView

    v = ToolView()
    v.resize(160, 180)
    for t in ("flat", "ball", "toroid", "vbit"):
        v.set_spec(ToolSpec(display_name=t, type=t, diameter_mm=3.0,
                            corner_radius_mm=0.5 if t == "toroid" else 0.0,
                            included_angle_deg=30.0 if t == "vbit" else 0.0,
                            flute_length_mm=10.0, shank_diameter_mm=3.175))
        pm = v.grab()
        assert not pm.isNull() and pm.width() > 0 and pm.height() > 0
    v.set_spec(None)                            # empty state must not crash
    assert not v.grab().isNull()
