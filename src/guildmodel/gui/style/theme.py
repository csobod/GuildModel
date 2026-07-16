"""GuildModel theme — single source of truth for all GUI styling (M4.5 Part A).

The two stylesheets are ported verbatim from GuildDraw (``framedraft/app.py``
``QSS`` / ``QSS_DARK`` — same palette, same Inter font stack, same control
styling; GuildDraw is the design reference and must not change), then extended
for widgets GuildModel has and GuildDraw lacks (QListWidget, QTableWidget /
QHeaderView, QTextEdit, QScrollArea, QDialogButtonBox) plus object-name
selectors for GuildModel's labelled chrome (#toolbarStrip, #appTitle,
#hintLabel, …).

Painter-drawn surfaces (the 2D canvas, the 3D viewport) cannot be styled by
QSS; they read their colors from :class:`CanvasPalette` via :func:`palette`.
No widget module may contain a hex literal that is not sourced from here
(layer colors come from ``core.layers.LAYER_STYLES`` and are dark-adjusted by
:func:`layer_color`).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, replace

# ---------------------------------------------------------------------------
# Light theme — GuildDraw QSS port (framedraft/app.py:118) + GuildModel extras
# ---------------------------------------------------------------------------

QSS = """
QMainWindow, QWidget {
    background-color: #ffd580;
    color: #1f1f1f;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: #ffd580;
    border: none;
    spacing: 2px;
    padding: 4px;
}
QToolButton, QPushButton {
    background-color: #fce9c2;
    border: 1px solid #1f1f1f;
    border-radius: 4px;
}
QToolButton { padding: 5px; min-width: 30px; }
QPushButton { padding: 4px 10px; min-width: 54px; }
QToolButton:hover, QPushButton:hover { background-color: #ffe9b8; }
QToolButton:checked, QPushButton:checked { background-color: #1f1f1f; color: #ffd580; }
QToolButton:disabled, QPushButton:disabled {
    background-color: #f4dfae; border-color: #b89c5e; color: #a08c58;
}
QToolBar::separator { background: #d4a840; height: 3px; margin: 12px 3px; border-radius: 1px; }
QStatusBar {
    background-color: #ffd580;
    border-top: 1px solid #d4a840;
}
QMenuBar { background-color: #ffd580; color: #1f1f1f; }
QMenuBar::item:selected { background-color: #fce9c2; }
QMenu { background-color: #fce9c2; color: #1f1f1f; border: 1px solid #1f1f1f; }
QMenu::item:selected { background-color: #1f1f1f; color: #ffd580; }
QMenu::separator { height: 1px; background: #d4a840; margin: 2px 6px; }
QDockWidget { background-color: #ffd580; }
QDockWidget::title {
    background-color: #d4a840;
    padding: 4px 6px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid #d4a840;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    background-color: #ffd580;
}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #fce9c2;
    border: 1px solid #d4a840;
    border-radius: 3px;
    padding: 2px 4px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #1f1f1f; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #fce9c2;
    border: 1px solid #1f1f1f;
    selection-background-color: #1f1f1f;
    selection-color: #ffd580;
}
QSlider::groove:horizontal {
    border: 1px solid #d4a840;
    height: 4px;
    background: #fce9c2;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #1f1f1f;
    border: 1px solid #1f1f1f;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #555; }
QTabWidget::pane { border-top: 1px solid #d4a840; }
QTabBar::tab {
    background: #fce9c2;
    color: #1f1f1f;
    border: 1px solid #d4a840;
    border-bottom: none;
    padding: 5px 8px;
    min-width: 40px;
}
QTabBar::tab:selected { background: #ffd580; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #ffe9b8; }

/* ---- GuildModel extensions (widgets GuildDraw lacks) ---- */
QListWidget {
    background-color: #fce9c2;
    border: 1px solid #d4a840;
    border-radius: 3px;
    font-size: 11px;
}
QListWidget::item:selected { background-color: #1f1f1f; color: #ffd580; }
QListWidget::item:hover { background-color: #ffe9b8; }
QTableWidget {
    background-color: #fce9c2;
    border: 1px solid #d4a840;
    gridline-color: #d4a840;
}
QHeaderView::section {
    background-color: #d4a840;
    color: #1f1f1f;
    border: none;
    padding: 3px 6px;
    font-weight: bold;
}
QTableWidget QTableCornerButton::section { background-color: #d4a840; border: none; }
QTextEdit {
    background-color: #fce9c2;
    border: 1px solid #d4a840;
    border-radius: 3px;
}
QScrollArea { border: none; }
QToolTip { background-color: #fce9c2; color: #1f1f1f; border: 1px solid #1f1f1f; }
QCheckBox { spacing: 5px; }

/* ---- GuildModel named chrome ---- */
QWidget#toolbarStrip { background-color: #ffd580; border-bottom: 1px solid #d4a840; }
/* The 3D viewer's strip buttons are icon-only squares: without this override
   the app-wide QPushButton min-width/padding stretches them wide (their
   setFixedWidth loses to the stylesheet box model). */
QWidget#toolbarStrip QPushButton { padding: 1px; min-width: 0px; }
/* The sim-playback button is the exception: a comfortable target with a
   readable ▶ glyph (the square-button shrink left it tiny). */
QWidget#toolbarStrip QPushButton#playButton {
    font-size: 14px; padding: 0px; min-width: 34px; min-height: 20px;
}
QLabel#appTitle { font-size: 16px; font-weight: bold; background: transparent; }
QLabel#hintLabel { font-size: 10px; color: #8a6d2f; background: transparent; }
QLabel#smallLabel { font-size: 11px; background: transparent; }
QLabel#mutedSmallLabel { font-size: 11px; color: #8a6d2f; background: transparent; }
QLabel#sectionLabel { font-size: 11px; font-weight: bold; margin-top: 4px; background: transparent; }
QLabel#placeholderLabel { font-size: 13px; color: #d4a840; }
QTextEdit#logView {
    background-color: #1a1a1a;
    color: #ffd580;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
    border: 1px solid #d4a840;
}
"""

# ---------------------------------------------------------------------------
# Dark theme — GuildDraw QSS_DARK port (framedraft/app.py:210) + extras
# ---------------------------------------------------------------------------

QSS_DARK = """
QMainWindow, QWidget {
    background-color: #1a1a1a;
    color: #d4cfc0;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QToolBar {
    background-color: #1a1a1a;
    border: none;
    spacing: 2px;
    padding: 4px;
}
QToolButton, QPushButton {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 4px;
    color: #d4cfc0;
}
QToolButton { padding: 5px; min-width: 30px; }
QPushButton { padding: 4px 10px; min-width: 54px; }
QToolButton:hover, QPushButton:hover { background-color: #3a3a3a; }
QToolButton:checked, QPushButton:checked { background-color: #d4cfc0; color: #1a1a1a; }
QToolButton:disabled, QPushButton:disabled {
    background-color: #222222; border-color: #3a3328; color: #6a6558;
}
QToolBar::separator { background: #b8923c; height: 3px; margin: 12px 3px; border-radius: 1px; }
QStatusBar {
    background-color: #1a1a1a;
    border-top: 1px solid #554433;
}
QMenuBar { background-color: #1a1a1a; color: #d4cfc0; }
QMenuBar::item:selected { background-color: #2a2a2a; }
QMenu { background-color: #2a2a2a; color: #d4cfc0; border: 1px solid #554433; }
QMenu::item:selected { background-color: #d4cfc0; color: #1a1a1a; }
QMenu::separator { height: 1px; background: #554433; margin: 2px 6px; }
QDockWidget { background-color: #1a1a1a; }
QDockWidget::title {
    background-color: #2a2a2a;
    padding: 4px 6px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid #554433;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    background-color: #1a1a1a;
}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 3px;
    padding: 2px 4px;
    color: #d4cfc0;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #d4cfc0; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    selection-background-color: #d4cfc0;
    selection-color: #1a1a1a;
}
QSlider::groove:horizontal {
    border: 1px solid #554433;
    height: 4px;
    background: #2a2a2a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #d4cfc0;
    border: 1px solid #d4cfc0;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #e8e0d0; }
QTabWidget::pane { border-top: 1px solid #554433; }
QTabBar::tab {
    background: #2a2a2a;
    color: #d4cfc0;
    border: 1px solid #554433;
    border-bottom: none;
    padding: 5px 8px;
    min-width: 40px;
}
QTabBar::tab:selected { background: #1a1a1a; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #3a3a3a; }

/* ---- GuildModel extensions (widgets GuildDraw lacks) ---- */
QListWidget {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 3px;
    font-size: 11px;
}
QListWidget::item:selected { background-color: #d4cfc0; color: #1a1a1a; }
QListWidget::item:hover { background-color: #3a3a3a; }
QTableWidget {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    gridline-color: #554433;
}
QHeaderView::section {
    background-color: #2a2a2a;
    color: #d4cfc0;
    border: none;
    border-bottom: 1px solid #554433;
    padding: 3px 6px;
    font-weight: bold;
}
QTableWidget QTableCornerButton::section { background-color: #2a2a2a; border: none; }
QTextEdit {
    background-color: #2a2a2a;
    border: 1px solid #554433;
    border-radius: 3px;
}
QScrollArea { border: none; }
QToolTip { background-color: #2a2a2a; color: #d4cfc0; border: 1px solid #554433; }
QCheckBox { spacing: 5px; }

/* ---- GuildModel named chrome ---- */
QWidget#toolbarStrip { background-color: #1a1a1a; border-bottom: 1px solid #554433; }
/* Icon-only square strip buttons — see the light-theme note. */
QWidget#toolbarStrip QPushButton { padding: 1px; min-width: 0px; }
/* Sim-playback button: comfortable target + readable glyph (see light theme). */
QWidget#toolbarStrip QPushButton#playButton {
    font-size: 14px; padding: 0px; min-width: 34px; min-height: 20px;
}
QLabel#appTitle { font-size: 16px; font-weight: bold; background: transparent; }
QLabel#hintLabel { font-size: 10px; color: #9a9382; background: transparent; }
QLabel#smallLabel { font-size: 11px; background: transparent; }
QLabel#mutedSmallLabel { font-size: 11px; color: #9a9382; background: transparent; }
QLabel#sectionLabel { font-size: 11px; font-weight: bold; margin-top: 4px; background: transparent; }
QLabel#placeholderLabel { font-size: 13px; color: #8a7a5a; }
QTextEdit#logView {
    background-color: #1a1a1a;
    color: #ffd580;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
    border: 1px solid #554433;
}
"""


def stylesheet(dark: bool) -> str:
    """The full application stylesheet for the requested theme."""
    return QSS_DARK if dark else QSS


# ---------------------------------------------------------------------------
# Painter palette — for QPainter / VTK surfaces QSS cannot reach
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanvasPalette:
    canvas_bg: str          # 2D canvas + 3D viewport background
    grid: str               # 10-mm grid lines
    annotation: str         # scale bar, measurement text
    measure: str            # measure-tool dimension lines + vertex markers (M7.13)
    placeholder: str        # "open a DXF" canvas text
    stock_dash: str         # dashed stock blank / pad block outlines (2D)
    stock_ghost: str        # wireframe stock ghost (3D)
    zone_outline: str       # zone-inspector hover outline
    zone_fill_rgba: tuple[int, int, int, int]   # zone hover fill
    mesh_surface: str       # 3D part surface
    ready_off: str          # readiness dot — nothing loaded
    ready_red: str          # readiness dot — DXF only
    ready_yellow: str       # readiness dot — model built
    ready_green: str        # readiness dot — ready for transmission


# Canvas backgrounds match GuildDraw (_CANVAS_BG_LIGHT / _CANVAS_BG_DARK).
LIGHT = CanvasPalette(
    canvas_bg="#faf6ee",
    grid="#e8e0c0",
    annotation="#444444",
    measure="#0c7fb8",
    placeholder="#d4a840",
    stock_dash="#909090",
    stock_ghost="#9a9a9a",
    zone_outline="#e07800",
    zone_fill_rgba=(255, 150, 30, 70),
    mesh_surface="#d4a84b",
    ready_off="#c2b89e",
    ready_red="#c0392b",
    ready_yellow="#d4a017",
    ready_green="#3a8c3a",
)

DARK = CanvasPalette(
    canvas_bg="#1e1e1e",
    grid="#333333",
    annotation="#d4cfc0",
    measure="#43c5e8",
    placeholder="#8a7a5a",
    stock_dash="#6a6a6a",
    stock_ghost="#777777",
    zone_outline="#e8924a",
    zone_fill_rgba=(255, 160, 60, 60),
    mesh_surface="#d4a84b",
    ready_off="#5a5446",
    ready_red="#d05a4a",
    ready_yellow="#d4a840",
    ready_green="#5aa95a",
)


def palette(dark: bool) -> CanvasPalette:
    """Painter palette for the requested UI mode, with the user's Appearance
    overrides applied (viewport preset backdrop + model surface color).

    A viewport preset pins the canvas/3D backdrop in BOTH UI modes (GuildDraw
    parity): the base palette is then chosen by the preset background's
    luminance — not the UI mode — so every supporting color (measure, zone,
    stock ghost…) stays legible on the chosen backdrop.
    """
    base = DARK if dark else LIGHT
    vp = _viewport
    if vp is not None:
        base = DARK if _luminance(vp["bg"]) < 0.5 else LIGHT
        base = replace(
            base,
            canvas_bg=vp["bg"],
            grid=vp["grid"],
            annotation=vp["ink"],
            placeholder=_mix(vp["bg"], vp["ink"], 0.4),
        )
    if _mesh_color:
        base = replace(base, mesh_surface=_mesh_color)
    return base


# Layer colors come from core.layers.LAYER_STYLES (the light-canvas set).
# Dark canvases need brighter variants or the OUTLINE layer disappears.
_OUTLINE_LIGHT_HEX = "#1a1a1a"
_DARK_LAYER_COLORS: dict[str, str] = {
    "#1a1a1a": "#d4cfc0",   # OUTLINE  — GuildDraw's dark geometry color
    "#1a6cbf": "#5aa0e0",   # LENS
    "#d94f1a": "#e8784a",   # HINGE
    "#2e8040": "#58b070",   # BRIDGE
    "#8040bf": "#a878d8",   # SCULPT
    "#1a9a9a": "#40c0c0",   # ENGRAVING
    "#888888": "#777777",   # REF
}


def layer_color(light_hex: str, dark: bool) -> str:
    """Theme-corrected layer color (input: the LAYER_STYLES light hex).

    With a viewport preset active the OUTLINE layer follows the preset's
    drawing ink, and every other layer picks its light/dark variant from the
    preset background's luminance instead of the UI mode."""
    if _viewport is not None:
        if light_hex.lower() == _OUTLINE_LIGHT_HEX:
            return _viewport["ink"]
        dark = _luminance(_viewport["bg"]) < 0.5
    if not dark:
        return light_hex
    return _DARK_LAYER_COLORS.get(light_hex.lower(), light_hex)


# Per-layer color overrides (Preferences ▸ Layers — GuildDraw parity). The
# maker can pin each design layer's drawing color per UI mode; "" / absent
# falls through to the shipped LAYER_STYLES color via layer_color().
_layer_overrides: dict[str, dict] = {}


def set_layer_overrides(cfg: dict | None) -> None:
    """Install {layer: {"light": "#rrggbb"|"", "dark": ...}} from prefs."""
    global _layer_overrides
    _layer_overrides = {k: dict(v) for k, v in (cfg or {}).items()
                        if isinstance(v, dict)}


def layer_overrides() -> dict:
    """The active per-layer override map (a copy)."""
    return {k: dict(v) for k, v in _layer_overrides.items()}


def layer_color_for(layer: str, dark: bool) -> str:
    """The 2D-canvas color for a design layer by NAME: the user's override for
    the effective mode when set, else the shipped color via layer_color().

    The effective mode follows a pinned viewport preset's backdrop luminance —
    the same rule layer_color applies — so the override that wins is the one
    the maker tuned for that backdrop."""
    eff_dark = dark
    if _viewport is not None:
        eff_dark = _luminance(_viewport["bg"]) < 0.5
    ov = _layer_overrides.get(layer) or {}
    user = ov.get("dark" if eff_dark else "light") or ""
    if user:
        return user
    from guildmodel.core.layers import LAYER_STYLES
    light_hex = LAYER_STYLES.get(layer, ("#888888", 1.0))[0]
    return layer_color(light_hex, dark)


# ---------------------------------------------------------------------------
# Appearance customization (Preferences ▸ Appearance) — RC1 polish.
#
# Module-level like GuildDraw's framedraft/theme.py: the main window pushes
# the persisted prefs in at startup and on Preferences-OK; every painter/VTK
# surface re-pulls palette()/lighting() on its next refresh.
# ---------------------------------------------------------------------------

# Viewport presets carried over from GuildDraw (framedraft/theme.py
# VIEWPORT_PRESETS — same backgrounds + inks, so the two apps feel like one
# product). `grid` is tuned for GuildModel's full 10-mm grid, which wants a
# fainter line than GuildDraw's single center cross.
VIEWPORT_PRESETS: dict[str, dict[str, str]] = {
    "parchment": {"bg": "#faf6ee", "ink": "#1f1f1f", "grid": "#e8e0c0"},
    # Dimmed: between Parchment and dark — easy on the eyes but still light
    # enough that the light-mode layer palette keeps its contrast.
    "dimmed":    {"bg": "#d8d1c3", "ink": "#1f1f1f", "grid": "#c4bcab"},
    "blueprint": {"bg": "#16324f", "ink": "#dce8f2", "grid": "#2b4664"},
    "matte":     {"bg": "#1e1e1e", "ink": "#d4cfc0", "grid": "#333333"},
    "white":     {"bg": "#ffffff", "ink": "#1f1f1f", "grid": "#e6e6e6"},
}

_viewport: dict[str, str] | None = None   # active preset values (bg/ink/grid)
_mesh_color: str | None = None            # 3D part-surface override ("" = default)

# 3D light rig — defaults reproduce the shipped look exactly: one key light
# from (100, -50, 200) at 0.8 over VTK's default kit (azimuth/elevation of
# that vector, see Viewer3D).
LIGHTING_DEFAULTS: dict = {
    "rig": "studio",           # studio | directional | flat
    "azimuth_deg": -27.0,      # around +Z, 0° = +X, CCW positive
    "elevation_deg": 61.0,     # up from the XY plane
    "intensity": 0.8,          # key-light strength
}
_lighting: dict = dict(LIGHTING_DEFAULTS)

# Toolpath-overlay color sets (M7.11 overlay; Preferences ▸ Appearance).
TOOLPATH_PALETTES: dict[str, list[str]] = {
    # the original M7.11 set
    "vivid": ["#e0563b", "#3b86e0", "#3aa33a", "#c79a2b",
              "#9b59b6", "#16a085", "#e08c3b", "#d6477f"],
    "soft":  ["#c9826d", "#7a9cc9", "#7fb08a", "#c2ae7d",
              "#a98bc0", "#7ab3ab", "#c9a07a", "#bd8aa2"],
    "bold":  ["#e02b2b", "#1f5fe0", "#1fa01f", "#d99000",
              "#8e2be0", "#009a9a", "#e0641f", "#e01f8e"],
    # one hue, stepped — for makers who find the multicolor overlay noisy
    "mono":  ["#2f6f9f", "#4a89b8", "#6ba3cc", "#8fbcdb",
              "#3a5a78", "#5577a0", "#7c9dc0", "#274d6d"],
}
_toolpath_palette: str = "vivid"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """(r, g, b) from #rrggbb / #AARRGGBB; mid-grey on a malformed value so a
    hand-corrupted prefs color can't crash startup (GuildDraw parity)."""
    try:
        h = hex_color.lstrip("#")
        if len(h) == 8:          # #AARRGGBB
            h = h[2:]
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, AttributeError, IndexError):
        return (128, 128, 128)


def _luminance(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _mix(a: str, b: str, t: float) -> str:
    """Blend color *a* toward *b* by t in [0, 1]."""
    ar, ag, ab_ = _rgb(a)
    br, bg, bb = _rgb(b)
    return "#{:02x}{:02x}{:02x}".format(
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab_ + (bb - ab_) * t))


def apply_viewport(preset: str | None, custom_bg: str | None = None) -> None:
    """Activate (or clear, for "auto"/None) a viewport preset.

    "custom" derives a legible ink + grid from the chosen background's
    luminance, exactly like GuildDraw's custom canvas color."""
    global _viewport
    if preset in (None, "", "auto"):
        _viewport = None
        return
    if preset == "custom":
        bg = custom_bg or LIGHT.canvas_bg
        ink = "#d4cfc0" if _luminance(bg) < 0.5 else "#1f1f1f"
        _viewport = {"bg": bg, "ink": ink, "grid": _mix(bg, ink, 0.18)}
        return
    vals = VIEWPORT_PRESETS.get(preset)
    _viewport = dict(vals) if vals else None


def viewport_preset_active() -> bool:
    return _viewport is not None


def set_mesh_color(hex_color: str | None) -> None:
    """Override the 3D part-surface color in both modes (None/"" = default)."""
    global _mesh_color
    _mesh_color = hex_color or None


def set_lighting(cfg: dict | None) -> None:
    """Install the 3D light-rig config (unknown keys ignored, missing keys keep
    their defaults — a stale prefs.json can never break the render)."""
    global _lighting
    cfg = cfg or {}
    out = dict(LIGHTING_DEFAULTS)
    if cfg.get("rig") in ("studio", "directional", "flat"):
        out["rig"] = cfg["rig"]
    for key, lo, hi in (("azimuth_deg", -180.0, 180.0),
                        ("elevation_deg", 5.0, 90.0),
                        ("intensity", 0.0, 2.0)):
        try:
            out[key] = min(hi, max(lo, float(cfg[key])))
        except (KeyError, TypeError, ValueError):
            pass
    _lighting = out


def lighting() -> dict:
    """The active 3D light-rig config (a copy)."""
    return dict(_lighting)


def light_position(radius: float = 230.0) -> tuple[float, float, float]:
    """Key-light position on a sphere around the scene origin, from the
    configured azimuth (around +Z from +X) and elevation (up from XY)."""
    az = math.radians(_lighting["azimuth_deg"])
    el = math.radians(_lighting["elevation_deg"])
    c = math.cos(el) * radius
    return (c * math.cos(az), c * math.sin(az), radius * math.sin(el))


GRID_DEFAULTS: dict = {
    # 2D design-canvas grid (Preferences ▸ Appearance ▸ Grid). Shipped values
    # reproduce the historical hardcoded grid: 10 mm dotted minor lines, a
    # slightly heavier major every 5th (new), colors from the palette.
    "visible":        True,
    "spacing_mm":     10.0,
    "major_every":    5,      # every Nth line is a major; <= 1 = all minor
    "minor_color":    "",     # "" = follow the theme (palette().grid)
    "major_color":    "",     # "" = follow the minor color
    "major_width_px": 1.0,
}
_grid_cfg: dict = dict(GRID_DEFAULTS)


def set_grid(cfg: dict | None) -> None:
    """Install the 2D-canvas grid config from prefs (missing keys keep their
    defaults — a stale prefs.json can never break the canvas)."""
    global _grid_cfg
    out = dict(GRID_DEFAULTS)
    for k in GRID_DEFAULTS:
        if cfg and k in cfg:
            out[k] = cfg[k]
    out["spacing_mm"] = min(100.0, max(0.5, float(out["spacing_mm"])))
    out["major_every"] = max(1, int(out["major_every"]))
    out["major_width_px"] = min(4.0, max(0.5, float(out["major_width_px"])))
    _grid_cfg = out


def grid_config() -> dict:
    """The active 2D-canvas grid config (a copy)."""
    return dict(_grid_cfg)


def set_toolpath_palette(name: str | None) -> None:
    global _toolpath_palette
    _toolpath_palette = name if name in TOOLPATH_PALETTES else "vivid"


def toolpath_colors() -> list[str]:
    """The active toolpath-overlay color cycle."""
    return list(TOOLPATH_PALETTES[_toolpath_palette])
