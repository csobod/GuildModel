"""Readiness traffic-light dot (BUILDPLAN M5.2).

A small painted circle docked in the status-bar corner that tells the maker at
a glance how far the open job is from being transmittable to the machine. Dot
only — the stage name lives in the tooltip:

    grey/off  nothing loaded (no DXF)
    red       DXF imported, nothing built  — "DXF Loaded, Missing 3D Model + G-Code"
    yellow    3D model built               — "Model Built, Missing G-Code"
    green     G-code stored to the .gcam   — "Ready for Transmission"

Colors are sourced from ``theme`` (no hex literals here) and recolored per
light/dark theme; the state machine that drives it lives in ``MainWindow``.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QSize

from guildcam.gui.style import theme

# State keys + their exact tooltips (BUILDPLAN M5.2 wording — do not reword).
OFF = "off"
RED = "red"
YELLOW = "yellow"
GREEN = "green"

TOOLTIPS = {
    OFF: "No DXF loaded",
    RED: "DXF Loaded, Missing 3D Model + G-Code",
    YELLOW: "Model Built, Missing G-Code",
    GREEN: "Ready for Transmission",
}

_DIAMETER = 10  # px — subtle


def state_for(dxf_loaded: bool, mesh_built: bool, program_stored: bool) -> str:
    """The readiness state machine as a pure function of three job facts.

    green outranks yellow outranks red: a stored program implies the job is
    transmittable regardless of whether the (lazily rebuilt) preview mesh is
    currently in hand. No DXF at all is grey/off.
    """
    if not dxf_loaded:
        return OFF
    if program_stored:
        return GREEN
    if mesh_built:
        return YELLOW
    return RED


class ReadinessDot(QWidget):
    """A ~10 px filled circle whose color + tooltip reflect the job readiness."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = OFF
        self._dark = False
        # Leave a little breathing room around the dot in the status-bar corner.
        self.setFixedSize(_DIAMETER + 8, _DIAMETER + 6)
        self._apply_tooltip()

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in TOOLTIPS:
            raise ValueError(f"unknown readiness state: {state!r}")
        if state == self._state:
            return
        self._state = state
        self._apply_tooltip()
        self.update()

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def _apply_tooltip(self) -> None:
        self.setToolTip(TOOLTIPS[self._state])

    def _color(self) -> QColor:
        pal = theme.palette(self._dark)
        return QColor({
            OFF: pal.ready_off,
            RED: pal.ready_red,
            YELLOW: pal.ready_yellow,
            GREEN: pal.ready_green,
        }[self._state])

    def sizeHint(self) -> QSize:
        return QSize(_DIAMETER + 8, _DIAMETER + 6)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._color()
        p.setBrush(QBrush(color))
        # A faint darker rim keeps the dot legible on either canvas tone.
        p.setPen(QPen(color.darker(135), 1))
        x = (self.width() - _DIAMETER) / 2
        y = (self.height() - _DIAMETER) / 2
        p.drawEllipse(int(round(x)), int(round(y)), _DIAMETER, _DIAMETER)
        p.end()
