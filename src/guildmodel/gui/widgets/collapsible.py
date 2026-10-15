"""A collapsible group: a header the maker clicks to fold its contents away
(BUILDPLAN M20 §5.2.6, the Worktable panel first; the archived M21 wanted it
for the Model tab).

A `QToolButton` with an arrow and the title, flat, over a body widget whose
layout the caller fills. Folded, only the header shows; the state is the
button's checked state, so it can be saved and restored like any other.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleGroup(QWidget):
    """``group = CollapsibleGroup("Bed"); group.body_layout.addWidget(...)``."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None,
                 *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.header = QToolButton(self)
        self.header.setObjectName("collapsibleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(self.header.sizePolicy().horizontalPolicy().Expanding,
                                  self.header.sizePolicy().verticalPolicy())
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
