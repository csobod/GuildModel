"""Job & validation inspector panel (BUILDPLAN M7.14).

One dockable list of everything the engine flags — tool reach, bed / worktable
clearance, machine lint, cut completeness / gouge — each a severity-tagged row that,
when activated, asks the main window to jump to the relevant view (via the
``issue_activated`` signal carrying the issue's ``target``). The readiness dot says
ready / not-ready; this panel says *why*.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont

from guildmodel.gui.style import theme

_SEV_LABEL = {"error": "■", "warning": "▲", "info": "●"}


class InspectorPanel(QWidget):
    """List the aggregated `core.diagnostics.Issue`s; emit the target on activation."""

    issue_activated = Signal(object)   # the issue's `target` tuple (or None)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._dark = False
        self._palette = theme.palette(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._summary = QLabel("")
        self._summary.setObjectName("hintLabel")
        self._summary.setWordWrap(True)
        lay.addWidget(self._summary)

        self._list = QListWidget()
        self._list.setObjectName("inspectorList")
        self._list.setAlternatingRowColors(True)
        # Wrap long issue messages to the panel width instead of clipping / scrolling
        # sideways (the panel is often narrow when docked beside the toolpaths).
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._emit_target)
        self._list.itemClicked.connect(self._emit_target)
        lay.addWidget(self._list, 1)

        self.set_issues([])

    # ------------------------------------------------------------------ public
    def set_dark_mode(self, dark: bool) -> None:
        self._dark = dark
        self._palette = theme.palette(dark)
        # re-tint the current rows
        self.set_issues(self._issues)

    def set_issues(self, issues) -> None:
        """Replace the listed issues (a sequence of `core.diagnostics.Issue`)."""
        self._issues = list(issues)
        self._list.clear()
        errs = sum(1 for i in self._issues if i.severity == "error")
        warns = sum(1 for i in self._issues if i.severity == "warning")

        if not self._issues:
            self._summary.setText("No issues — generate or simulate to validate the job.")
            placeholder = QListWidgetItem("✓  Nothing flagged.")
            placeholder.setForeground(QBrush(QColor(self._palette.ready_green)))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
            return

        bits = []
        if errs:
            bits.append(f"{errs} error{'s' if errs != 1 else ''}")
        if warns:
            bits.append(f"{warns} warning{'s' if warns != 1 else ''}")
        self._summary.setText("  ·  ".join(bits) + "   (click a row to locate it)")

        colors = {
            "error": QColor(self._palette.ready_red),
            "warning": QColor(self._palette.ready_yellow),
            "info": QColor(self._palette.annotation),
        }
        for issue in self._issues:
            mark = _SEV_LABEL.get(issue.severity, "•")
            item = QListWidgetItem(f"{mark}  [{issue.category}]  {issue.message}")
            item.setForeground(QBrush(colors.get(issue.severity, colors["info"])))
            if issue.severity == "error":
                f = QFont(self.font())
                f.setBold(True)
                item.setFont(f)
            item.setData(Qt.ItemDataRole.UserRole, issue.target)
            item.setToolTip(issue.message)
            if issue.target is None:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._list.addItem(item)

    # ------------------------------------------------------------------ internal
    def _emit_target(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if target is not None:
            self.issue_activated.emit(target)
