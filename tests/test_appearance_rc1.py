"""Appearance customization (RC1 polish): viewport presets carried over from
GuildDraw, the 3D light rig, the model-surface override, and the toolpath
palettes — all Qt-free theme-module logic."""
import math

import pytest

from guildmodel.gui import prefs as prefs_mod
from guildmodel.gui.style import theme


@pytest.fixture(autouse=True)
def _reset_theme_state():
    yield
    theme.apply_viewport(None)
    theme.set_mesh_color(None)
    theme.set_lighting(None)
    theme.set_toolpath_palette(None)


# ---------------------------------------------------------------- viewport

def test_viewport_presets_match_guilddraw_set():
    # the shipped canvas themes are GuildDraw's, name-for-name
    assert set(theme.VIEWPORT_PRESETS) == {
        "parchment", "dimmed", "blueprint", "matte", "white"}
    for vals in theme.VIEWPORT_PRESETS.values():
        assert set(vals) == {"bg", "ink", "grid"}


def test_auto_is_the_shipped_look():
    theme.apply_viewport("auto")
    assert not theme.viewport_preset_active()
    assert theme.palette(False) == theme.LIGHT
    assert theme.palette(True) == theme.DARK


def test_preset_pins_both_ui_modes():
    theme.apply_viewport("dimmed")
    assert theme.viewport_preset_active()
    for dark in (False, True):
        pal = theme.palette(dark)
        assert pal.canvas_bg == "#d8d1c3"
        assert pal.annotation == "#1f1f1f"


def test_dark_preset_flips_supporting_colors_and_layers():
    # Blueprint is a dark backdrop: even in light UI mode the palette must
    # come from the dark support set and layers use their dark variants.
    theme.apply_viewport("blueprint")
    pal = theme.palette(False)
    assert pal.canvas_bg == "#16324f"
    assert pal.measure == theme.DARK.measure
    assert theme.layer_color("#1a6cbf", False) == "#5aa0e0"      # LENS
    # OUTLINE follows the preset ink in both modes
    assert theme.layer_color("#1a1a1a", False) == "#dce8f2"
    assert theme.layer_color("#1a1a1a", True) == "#dce8f2"


def test_layer_colors_without_preset_unchanged():
    theme.apply_viewport(None)
    assert theme.layer_color("#1a1a1a", False) == "#1a1a1a"
    assert theme.layer_color("#1a1a1a", True) == "#d4cfc0"
    assert theme.layer_color("#1a6cbf", True) == "#5aa0e0"


def test_custom_viewport_derives_ink_from_luminance():
    theme.apply_viewport("custom", "#101418")                    # near black
    assert theme.palette(False).annotation == "#d4cfc0"
    theme.apply_viewport("custom", "#f4f0e6")                    # near white
    assert theme.palette(True).annotation == "#1f1f1f"


def test_malformed_custom_bg_cannot_crash():
    theme.apply_viewport("custom", "not-a-color")
    pal = theme.palette(False)          # falls back to mid-grey internally
    assert pal.canvas_bg == "not-a-color" or pal.canvas_bg.startswith("#")


def test_unknown_preset_clears():
    theme.apply_viewport("dimmed")
    theme.apply_viewport("no-such-preset")
    assert not theme.viewport_preset_active()


# ---------------------------------------------------------------- mesh color

def test_mesh_color_override_and_reset():
    theme.set_mesh_color("#aa3355")
    assert theme.palette(False).mesh_surface == "#aa3355"
    assert theme.palette(True).mesh_surface == "#aa3355"
    theme.set_mesh_color("")            # "" behaves as None (prefs default)
    assert theme.palette(False).mesh_surface == theme.LIGHT.mesh_surface


# ---------------------------------------------------------------- lighting

def test_lighting_defaults_reproduce_shipped_key_light():
    theme.set_lighting(None)
    cfg = theme.lighting()
    assert cfg["rig"] == "studio"
    # the shipped key light sat at (100, -50, 200): same direction ±1°
    x, y, z = theme.light_position()
    az = math.degrees(math.atan2(y, x))
    el = math.degrees(math.atan2(z, math.hypot(x, y)))
    assert az == pytest.approx(math.degrees(math.atan2(-50, 100)), abs=1.0)
    assert el == pytest.approx(
        math.degrees(math.atan2(200, math.hypot(100, 50))), abs=1.0)


def test_lighting_clamps_and_ignores_junk():
    theme.set_lighting({"rig": "sparkly", "azimuth_deg": 999,
                        "elevation_deg": -40, "intensity": "bright"})
    cfg = theme.lighting()
    assert cfg["rig"] == "studio"       # unknown rig -> default
    assert cfg["azimuth_deg"] == 180.0
    assert cfg["elevation_deg"] == 5.0
    assert cfg["intensity"] == theme.LIGHTING_DEFAULTS["intensity"]


def test_light_position_tracks_azimuth_elevation():
    theme.set_lighting({"azimuth_deg": 90.0, "elevation_deg": 90.0})
    x, y, z = theme.light_position(radius=100.0)
    assert x == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-6)
    assert z == pytest.approx(100.0)
    theme.set_lighting({"azimuth_deg": 90.0, "elevation_deg": 5.0})
    x, y, z = theme.light_position(radius=100.0)
    assert y > 0 and z == pytest.approx(100.0 * math.sin(math.radians(5.0)))


# ---------------------------------------------------------------- toolpaths

def test_toolpath_palettes_shape():
    assert set(theme.TOOLPATH_PALETTES) == {"vivid", "soft", "bold", "mono"}
    for colors in theme.TOOLPATH_PALETTES.values():
        assert len(colors) == 8
        assert all(c.startswith("#") and len(c) == 7 for c in colors)


def test_toolpath_palette_selection_and_fallback():
    theme.set_toolpath_palette("mono")
    assert theme.toolpath_colors() == theme.TOOLPATH_PALETTES["mono"]
    theme.set_toolpath_palette("nope")
    assert theme.toolpath_colors() == theme.TOOLPATH_PALETTES["vivid"]


# ---------------------------------------------------------------- prefs

def test_prefs_defaults_carry_appearance_keys():
    d = prefs_mod.DEFAULTS
    assert d["viewport"]["preset"] == "auto"
    assert d["render3d"]["rig"] == "studio"
    assert d["render3d"]["model_color"] == ""
    assert d["toolpath_palette"] == "vivid"
    # defaults must round-trip through the theme setters unchanged
    theme.set_lighting(d["render3d"])
    assert theme.lighting()["intensity"] == d["render3d"]["intensity"]
