"""The blueprint dialog (2.3): the project's blueprint settings, the way
they are written (PDF, SVG, DXF or a printer), and the offer to keep them
as the shop's defaults."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout)

from guildmodel.core.project.schema import BlueprintSettings
from guildmodel.gui.widgets.blueprint_widgets import BlueprintSettingsWidget

__all__ = ["BlueprintDialog"]


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
        self.defaults_check.setToolTip("The page, the projection, the views, the owner, the "
                                       "author and the tolerances; not this design's name, "
                                       "number or date.")
        self.defaults_check.setVisible(offer_defaults)
        lay.addWidget(self.defaults_check)
        row = QHBoxLayout()
        row.addStretch(1)
        for key, label in (("pdf", "Export PDF…"), ("svg", "Export SVG…"),
                           ("dxf", "Export DXF…"), ("print", "Print…")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _c=False, k=key: self._choose(k))
            row.addWidget(btn)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _choose(self, key: str) -> None:
        self.action = key
        self.accept()

    def settings(self) -> BlueprintSettings:
        return self.editor.settings(self._base)

    @property
    def save_defaults(self) -> bool:
        return self.defaults_check.isChecked()
