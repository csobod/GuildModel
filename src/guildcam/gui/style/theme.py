"""GuildCAM theme — single source of truth for all GUI styling (M4.5 Part A).

The two stylesheets are ported verbatim from GuildDraw (``framedraft/app.py``
``QSS`` / ``QSS_DARK`` — same palette, same Inter font stack, same control
styling; GuildDraw is the design reference and must not change), then extended
for widgets GuildCAM has and GuildDraw lacks (QListWidget, QTableWidget /
QHeaderView, QTextEdit, QScrollArea, QDialogButtonBox) plus object-name
selectors for GuildCAM's labelled chrome (#toolbarStrip, #appTitle,
#hintLabel, …).

Painter-drawn surfaces (the 2D canvas, the 3D viewport) cannot be styled by
QSS; they read their colors from :class:`CanvasPalette` via :func:`palette`.
No widget module may contain a hex literal that is not sourced from here
(layer colors come from ``core.layers.LAYER_STYLES`` and are dark-adjusted by
:func:`layer_color`).
"""
from __future__ import annotations
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Light theme — GuildDraw QSS port (framedraft/app.py:118) + GuildCAM extras
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
QToolBar::separator { background: #d4a840; height: 2px; margin: 7px 5px; }
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

/* ---- GuildCAM extensions (widgets GuildDraw lacks) ---- */
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

/* ---- GuildCAM named chrome ---- */
QWidget#toolbarStrip { background-color: #ffd580; border-bottom: 1px solid #d4a840; }
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
QToolBar::separator { background: #554433; height: 2px; margin: 7px 5px; }
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

/* ---- GuildCAM extensions (widgets GuildDraw lacks) ---- */
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

/* ---- GuildCAM named chrome ---- */
QWidget#toolbarStrip { background-color: #1a1a1a; border-bottom: 1px solid #554433; }
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
    return DARK if dark else LIGHT


# Layer colors come from core.layers.LAYER_STYLES (the light-canvas set).
# Dark canvases need brighter variants or the OUTLINE layer disappears.
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
    """Theme-corrected layer color (input: the LAYER_STYLES light hex)."""
    if not dark:
        return light_hex
    return _DARK_LAYER_COLORS.get(light_hex.lower(), light_hex)
