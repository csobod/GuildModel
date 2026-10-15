"""A collapsible group: a header the maker clicks to fold its contents away
(BUILDPLAN M20 §5.2.6, the Worktable panel first; the archived M21 wanted it
for the Model tab, and the whole dock took it on 2026-10-15).

A `QToolButton` with an arrow and the title, flat, over a body widget. Folded,
only the header shows; the state is the button's checked state, so it can be
saved and restored like any other. Two shapes of the same thing:

* `CollapsibleGroup` fills its own body layout — the Worktable panel's.
* `CollapsibleBox` leaves the body bare, so a builder lays it out exactly as
  it laid out the `QGroupBox` it replaces — the parameter dock's.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


def _header(parent: QWidget, title: str, expanded: bool) -> QToolButton:
    header = QToolButton(parent)
    header.setObjectName("collapsibleHeader")
    header.setText(title)
    header.setCheckable(True)
    header.setChecked(expanded)
    header.setAutoRaise(True)
    header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    header.setSizePolicy(header.sizePolicy().horizontalPolicy().Expanding,
                         header.sizePolicy().verticalPolicy())
    return header


class CollapsibleGroup(QWidget):
    """``group = CollapsibleGroup("Bed"); group.body_layout.addWidget(...)``."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None,
                 *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.header = _header(self, title, expanded)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 0, 4)
        self.body_layout.setSpacing(6)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)

        self.header.toggled.connect(self._on_toggled)
        self._on_toggled(expanded)

    def _on_toggled(self, on: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
        self.toggled.emit(on)

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_title(self, title: str) -> None:
        self.header.setText(title)


class CollapsibleBox(QWidget):
    """``box = CollapsibleBox("Model Properties"); form = QFormLayout(box.body)``.

    The body carries no layout of its own, so a builder treats it as it treated
    a titled group box and adds the *box* to its column. Folded by title, the
    way the dock remembers it (`ParamsPanel.fold_state`).
    """

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None,
                 *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.header = _header(self, title, expanded)
        self.body = QWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.header.toggled.connect(self._on_toggled)
        self._on_toggled(expanded)

    def _on_toggled(self, on: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
        self.toggled.emit(on)

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_title(self, title: str) -> None:
        self.header.setText(title)
