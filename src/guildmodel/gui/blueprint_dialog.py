"""The blueprint dialog (2.3): the project's blueprint settings, the way
they are written (PDF, SVG, DXF or a printer), and the offer to keep them
as the shop's defaults."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout)

from guildmodel.core.project.schema import BlueprintSettings
from guildmodel.gui.widgets.blueprint_widgets import BlueprintSettingsWidget

__all__ = ["BlueprintDialog"]


def _available_screen(widget):
    """The screen the dialog will show on, else a plain rectangle."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication
    try:
        parent = widget.parentWidget()
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
    except Exception:                                           # noqa: BLE001
        screen = None
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)


class BlueprintDialog(QDialog):
    """``dlg.exec(); dlg.action in ("pdf", "svg", "dxf", "print", None);
    dlg.settings(); dlg.save_defaults``."""

    def __init__(self, settings: BlueprintSettings, parent=None, *,
                 offer_defaults: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Blueprint")
        self.setMinimumWidth(520)
        self.action: str | None = None
        self._base = settings
        lay = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        self.editor = BlueprintSettingsWidget()
        self.editor.set_settings(settings)
        scroll.setWidget(self.editor)
        lay.addWidget(scroll, 1)
        self.defaults_check = QCheckBox("Save these as my defaults (Preferences ▸ Blueprint)")
        self.defaults_check.setToolTip("Everything here but this design's name, number, "
                                       "revision, approver and date: the page, the lettering, "
                                       "the colors, the views, the shop's cells, the material, "
                                       "the notes and the tolerances.")
        self.defaults_check.setVisible(offer_defaults)
        lay.addWidget(self.defaults_check)
        row = QHBoxLayout()
        row.addStretch(1)
        for key, label in (("pdf", "Export PDF…"), ("svg", "Export SVG…"),
                           ("dxf", "Export DXF…"), ("print", "Print…")):
            btn = QPushButton(label)
            btn.setAutoDefault(False)           # Enter in a field writes nothing
            btn.clicked.connect(lambda _c=False, k=key: self._choose(k))
            row.addWidget(btn)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        # open tall enough for the editor, within the screen
        hint = self.editor.sizeHint()
        avail = _available_screen(self)
        self.resize(max(min(hint.width() + 48, int(avail.width() * 0.8)), self.minimumWidth()),
                    min(hint.height() + 96, int(avail.height() * 0.85)))

    def _choose(self, key: str) -> None:
        self.action = key
        self.accept()

    def settings(self) -> BlueprintSettings:
        return self.editor.settings(self._base)

    @property
    def save_defaults(self) -> bool:
        return self.defaults_check.isChecked()
