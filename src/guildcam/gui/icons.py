"""Toolbar icon runtime (BUILDPLAN M4.6 Part C).

Ports GuildDraw's ``_make_icon`` (SVG → two-state QIcon, recolored per
theme/state by string-replacing ``currentColor``) and adds
:func:`apply_toolbar_icons`, the hook the main window calls from
``_apply_dark_mode``.

Icons live in ``gui/resources/icons/`` and follow ``docs/ICON-STYLE-GUIDE.md``
(20×20 viewBox, ``stroke="currentColor"``, monochrome). An action whose SVG is
missing is left text-only — icons are drop-in, no code change on delivery
(GuildDraw parity).
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QAction

_ICONS_DIR = Path(__file__).parent / "resources" / "icons"

# Recolor pairs (normal / checked) per theme — mirrors GuildDraw's
# _apply_toolbar_icons: off-state uses the body text color, on-state uses the
# inverted (checked button) color so a toggled action's glyph stays legible on
# the inverted button fill.
_NORMAL = {False: "#1f1f1f", True: "#d4cfc0"}
_CHECKED = {False: "#ffd580", True: "#1a1a1a"}


def make_icon(name: str, normal_color: str, checked_color: str) -> QIcon | None:
    """Render ``<name>.svg`` at two colors for off/on toolbar states.

    Returns None if the SVG does not exist (caller leaves the action text-only).
    """
    svg = _ICONS_DIR / f"{name}.svg"
    if not svg.exists():
        return None
    from PySide6.QtSvg import QSvgRenderer

    src = svg.read_text(encoding="utf-8")
    icon = QIcon()
    for color, state in (
        (normal_color, QIcon.State.Off),
        (checked_color, QIcon.State.On),
    ):
        renderer = QSvgRenderer(src.replace("currentColor", color).encode())
        px = QPixmap(20, 20)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        icon.addPixmap(px, QIcon.Mode.Normal, state)
    return icon


def themed_icon(name: str, dark: bool) -> QIcon | None:
    """Two-state QIcon recolored for the given theme, or None if the SVG is
    absent.  Use for any widget with a ``setIcon`` (QAction, QPushButton…)."""
    return make_icon(name, _NORMAL[dark], _CHECKED[dark])


def apply_toolbar_icons(pairs: list[tuple[QAction, str]], dark: bool) -> None:
    """Set (or refresh) every action's icon for the current theme.

    pairs: (action, icon-name) — the icon-name has no ``.svg`` suffix.
    Actions whose SVG is absent keep their text only.
    """
    for act, name in pairs:
        icon = themed_icon(name, dark)
        if icon is not None:
            act.setIcon(icon)
