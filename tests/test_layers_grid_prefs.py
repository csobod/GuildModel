"""Appearance parity round (V1-prep cluster b, GuildDraw patterns): per-layer
color overrides (Preferences ▸ Layers), the configurable 2D-canvas grid
(Preferences ▸ Appearance ▸ Grid), and the prefs deep-merge that stops an old
prefs.json from silently clobbering new nested defaults.
"""
import json
import os

import pytest

from guildmodel.gui.style import theme


@pytest.fixture(autouse=True)
def _reset_theme():
    """Theme state is module-level — always restore the shipped config."""
    yield
    theme.set_layer_overrides(None)
    theme.set_grid(None)
    theme.apply_viewport("auto")


# ------------------------------------------------------------------ prefs merge


def test_prefs_deep_merge_completes_nested_dicts(tmp_path, monkeypatch):
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    # An "old" prefs file: nested dicts missing keys added in later versions.
    (tmp_path / "prefs.json").write_text(json.dumps({
        "dark_mode": True,
        "viewport": {"preset": "blueprint"},          # no custom_bg
        "grid": {"spacing_mm": 5.0},                  # no major_every etc.
    }), encoding="utf-8")
    p = prefs_mod.load()
    assert p["dark_mode"] is True
    assert p["viewport"]["preset"] == "blueprint"
    assert p["viewport"]["custom_bg"]                 # default survived
    assert p["grid"]["spacing_mm"] == 5.0
    assert p["grid"]["major_every"] == 5              # default survived
    assert p["layer_colors"] == {}                    # new key present


def test_prefs_merge_survives_corrupt_nested_value(tmp_path, monkeypatch):
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({"grid": 7}),
                                         encoding="utf-8")
    p = prefs_mod.load()
    assert p["grid"] == prefs_mod.DEFAULTS["grid"]    # non-dict → defaults


# ------------------------------------------------------------------ layer overrides


def test_layer_override_wins_per_mode():
    theme.set_layer_overrides({"LENS": {"light": "#112233", "dark": ""}})
    assert theme.layer_color_for("LENS", dark=False) == "#112233"
    # No dark override — falls through to the shipped dark variant.
    assert theme.layer_color_for("LENS", dark=True) == "#5aa0e0"
    # Un-overridden layers keep the shipped colors.
    assert theme.layer_color_for("OUTLINE", dark=False) == "#1a1a1a"


def test_layer_override_follows_pinned_backdrop():
    theme.set_layer_overrides({"LENS": {"light": "#112233", "dark": "#445566"}})
    theme.apply_viewport("matte")                     # dark backdrop pinned
    # Even in light UI mode the dark-slot override applies on a dark backdrop.
    assert theme.layer_color_for("LENS", dark=False) == "#445566"
    theme.apply_viewport("parchment")                 # light backdrop pinned
    assert theme.layer_color_for("LENS", dark=True) == "#112233"


def test_layer_overrides_reset():
    theme.set_layer_overrides({"HINGE": {"light": "#0000ff", "dark": ""}})
    theme.set_layer_overrides(None)
    assert theme.layer_color_for("HINGE", dark=False) == "#d94f1a"
    assert theme.layer_overrides() == {}


# ------------------------------------------------------------------ grid config


def test_grid_config_merges_and_clamps():
    theme.set_grid({"spacing_mm": 0.1, "major_every": 0, "visible": False})
    cfg = theme.grid_config()
    assert cfg["visible"] is False
    assert cfg["spacing_mm"] == 0.5                   # clamped
    assert cfg["major_every"] == 1                    # clamped
    assert cfg["minor_color"] == ""                   # default survived
    theme.set_grid(None)
    assert theme.grid_config() == theme.GRID_DEFAULTS


# ------------------------------------------------------------------ GUI wiring


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_prefs_dialog_layers_and_grid_roundtrip(qapp):
    from guildmodel.gui import prefs as prefs_mod
    from guildmodel.gui.app import PrefsDialog
    dlg = PrefsDialog(dict(prefs_mod.DEFAULTS), parent=None)

    # The Layers tab exists and every design layer has its swatch buttons.
    from guildmodel.core.layers import LAYER_STYLES
    assert all((layer, mode) in dlg._layer_btns
               for layer in LAYER_STYLES for mode in ("light", "dark"))

    dlg._layer_colors["LENS"] = {"light": "#112233", "dark": ""}
    dlg._layer_colors["REF"] = {"light": "", "dark": ""}   # a reset — dropped
    dlg._grid_major.setValue(4)
    dlg._grid_visible.setChecked(False)
    out = dlg.to_prefs()
    assert out["layer_colors"] == {"LENS": {"light": "#112233", "dark": ""}}
    assert out["grid"]["major_every"] == 4
    assert out["grid"]["visible"] is False
    assert out["grid"]["spacing_mm"] == 10.0


def test_canvas_grid_honors_visibility_and_layer_override(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap
    from guildmodel.gui.widgets.dxf_canvas import DxfCanvas

    canvas = DxfCanvas()
    canvas.resize(200, 150)

    def _grid_pixels() -> int:
        pm = QPixmap(200, 150)
        pm.fill(Qt.GlobalColor.white)
        p = QPainter(pm)
        canvas._draw_grid(p)
        p.end()
        img = pm.toImage()
        white = 0xFFFFFFFF
        return sum(1 for y in range(0, 150, 3) for x in range(0, 200, 3)
                   if img.pixel(x, y) != white)

    theme.set_grid({"visible": True})
    assert _grid_pixels() > 0
    theme.set_grid({"visible": False})
    assert _grid_pixels() == 0

    # The layer painter asks the theme by NAME, so overrides recolor curves.
    theme.set_layer_overrides({"OUTLINE": {"light": "#ff0000", "dark": ""}})
    assert canvas._dark is False                       # fresh canvas = light mode
    assert theme.layer_color_for("OUTLINE", canvas._dark) == "#ff0000"
