"""The *Inlays* section: one row per seat the drawing carries, and an editor
for the selected one (BUILDPLAN §8a, 2026-10-15; tidied the same day).

The list is the drawing's, not the maker's: a seat is drawn in GuildDraw on
the INLAY layer and arrives at intake, so there is no Add and no Remove here,
only what each seat is cut to. The derived facts — what a seat is relative to,
and the face a nested seat or one in a hinge inherits — are shown and not
typed, the way the edge features' zone names are offered rather than invented.

What a maker sets every time stays in view: the row, enabled and its name,
the face and the depth, step or island. The rest — the flush, the tool, the
depth per pass, the minimum thickness — folds under *Cut details*, closed by
default. The explanation lives on the section header's tooltip
(`InlaysGroup.TIP`), not in the dock.

The same widget serves the frame front and the temples; `kind` only changes
the words for the two faces, since a temple's anterior face is its outer side.
Qt-free reconciliation lives in `core.geometry.inlays`; this widget calls it
when the geometry arrives, so the rows always match the drawing.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QVBoxLayout, QWidget,
)

from guildmodel.core.project.schema import InlayFeature
from guildmodel.gui.widgets.collapsible import CollapsibleBox
from guildmodel.gui.widgets.param_slider import ParamSlider

__all__ = ["InlaysGroup"]

_FACES = ("anterior", "posterior")
_MODES = ("step", "island")
_FACE_LABELS = {
    "front": ("Anterior (front) — modeled, not posted", "Posterior (back)"),
    "temple": ("Outer face — modeled, not posted", "Inner face (hinge side)"),
}
_NO_TOOL = "(the part's pocket tool)"


class InlaysGroup(QWidget):
    """Rows and an editor for the part's `InlayFeature`s."""

    #: What the section is, for its header's tooltip.
    TIP = ("Seats for plaques, laminates and plates: one row per INLAY curve in "
           "the drawing. A seat is cut into the visible face by default; a seat "
           "drawn inside another is a step down from it, and one drawn inside a "
           "HINGE curve steps the hinge pocket's floor. Draw seats in GuildDraw.")

    changed = Signal()

    def __init__(self, kind: str = "front", tool_names: list[str] = (),
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind if kind in _FACE_LABELS else "front"
        self._features: list[InlayFeature] = []
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self.rows = QListWidget()
        self.rows.setFixedHeight(3 * (self.rows.fontMetrics().height() + 6) + 6)
        self.rows.setToolTip(self.TIP)
        self.rows.currentRowChanged.connect(self._on_selected)
        v.addWidget(self.rows)

        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(0, 2, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        d = InlayFeature()

        head = QHBoxLayout()
        head.setSpacing(6)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)
        self.enabled.setToolTip("Off leaves the seat uncut, and anything drawn inside it.")
        self.label = QLineEdit()
        self.label.setPlaceholderText("Plaque seat")
        head.addWidget(self.enabled)
        head.addWidget(self.label, 1)
        form.addRow("", head)

        self.relative = QLabel("the face")
        self.relative.setObjectName("mutedSmallLabel")
        form.addRow("Relative to:", self.relative)

        self.face = QComboBox()
        self.face.addItems(list(_FACE_LABELS[self._kind]))
        self.face.setToolTip(
            "Which face the seat is cut into. The anterior face is the visible "
            "one — the front of a frame, the outer side of a temple — and a seat "
            "there is modeled and shown in 3D now; machining it needs the flip "
            "setup (M24). A nested seat takes its parent's face, and a seat in a "
            "hinge pocket is on the hinge's.")
        form.addRow("Face:", self.face)

        self.depth = ParamSlider(d.depth_mm, 0.0, 6.0, step=0.05, decimals=2)
        self.depth.setToolTip(
            "The insert's thickness: how deep the seat is cut below what it is "
            "relative to. An island's depth sinks its top; 0 leaves it standing "
            "at the surface.")
        form.addRow("Depth:", self.depth)

        self.mode = QComboBox()
        self.mode.addItems(["Step (a pocket)", "Island (left standing)"])
        self.mode.setToolTip(
            "A step is pocketed down from its reference. An island is drawn "
            "inside another seat and left standing while its parent is pocketed "
            "around it — a raised monogram on a plaque.")
        form.addRow("Mode:", self.mode)
        v.addWidget(self.editor)

        # The rarer numbers, folded away until wanted.
        self.details = CollapsibleBox("Cut details", expanded=False)
        more = QFormLayout(self.details.body)
        more.setContentsMargins(0, 0, 0, 0)
        more.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.flush = QDoubleSpinBox()
        self.flush.setRange(-3.0, 3.0)
        self.flush.setSingleStep(0.05)
        self.flush.setDecimals(2)
        self.flush.setSuffix(" mm")
        self.flush.setKeyboardTracking(False)
        self.flush.setToolTip(
            "Cut the seat shallower than the insert (+, the insert sits proud) "
            "or deeper (−, sunk). 0 seats it flush.")
        more.addRow("Flush:", self.flush)
        self.tool = QComboBox()
        self.tool.addItem(_NO_TOOL)
        self.tool.addItems(list(tool_names))
        self.tool.setToolTip(
            "The end mill that pockets this seat. The part's pocket tool by "
            "default (the Hinge Pockets tool); a seat on another tool posts as "
            "its own Inlays operation.")
        more.addRow("Tool:", self.tool)
        self.stepdown = QDoubleSpinBox()
        self.stepdown.setRange(0.0, 4.0)
        self.stepdown.setSingleStep(0.1)
        self.stepdown.setDecimals(2)
        self.stepdown.setSuffix(" mm")
        self.stepdown.setSpecialValueText("(cut setting)")
        self.stepdown.setKeyboardTracking(False)
        self.stepdown.setToolTip(
            "Depth per pass for this seat. '(cut setting)' takes the pocket "
            "depth per pass from the Cut tab.")
        more.addRow("Depth per pass:", self.stepdown)
        self.min_thickness = ParamSlider(d.min_thickness_mm, 0.0, 8.0, step=0.1,
                                         decimals=2)
        self.min_thickness.setToolTip(
            "The seat's floor must leave at least this much material against "
            "the other face. GuildModel checks it when it generates and says "
            "which seat fails.")
        more.addRow("Min thickness:", self.min_thickness)
        v.addWidget(self.details)

        for w in (self.depth, self.min_thickness):
            w.valueChanged.connect(self._on_edited)
        for w in (self.flush, self.stepdown):
            w.valueChanged.connect(self._on_edited)
        for cb in (self.face, self.mode, self.tool):
            cb.currentIndexChanged.connect(self._on_edited)
        self.enabled.toggled.connect(self._on_edited)
        self.label.textEdited.connect(self._on_edited)
        self._refresh_rows()

    # ------------------------------------------------------------------ rows

    def _summary(self, f: InlayFeature) -> str:
        where = _FACE_LABELS[self._kind][_FACES.index(f.face)].split(" —")[0]
        rel = {"face": "from the face", "seat": "a step in its parent",
               "hinge": "a step in the hinge pocket"}[f.relative_to]
        name = f.label or f.id or "seat"
        posted = "" if f.face == "posterior" else "  · not posted"
        flag = "" if f.enabled else "  (off)"
        mode = "" if f.mode == "step" else "  · island"
        return f"{name} — {where} · {f.depth_mm:g} mm · {rel}{mode}{posted}{flag}"

    def _refresh_rows(self) -> None:
        row = self.rows.currentRow()
        self.rows.blockSignals(True)
        self.rows.clear()
        for f in self._features:
            self.rows.addItem(self._summary(f))
        self.rows.blockSignals(False)
        if self._features:
            self.rows.setCurrentRow(min(max(row, 0), len(self._features) - 1))
        has = bool(self._features)
        self.editor.setEnabled(has)
        self.details.body.setEnabled(has)      # the header always answers a click

    def _on_selected(self, row: int) -> None:
        if not (0 <= row < len(self._features)):
            return
        f = self._features[row]
        self._loading = True
        self.enabled.setChecked(f.enabled)
        self.label.setText(f.label)
        self.face.setCurrentIndex(_FACES.index(f.face))
        self.depth.setValue(f.depth_mm)
        self.flush.setValue(f.flush_mm)
        self.mode.setCurrentIndex(_MODES.index(f.mode))
        i = self.tool.findText(f.tool) if f.tool else 0
        self.tool.setCurrentIndex(i if i >= 0 else 0)
        self.stepdown.setValue(f.stepdown_mm or 0.0)
        self.min_thickness.setValue(f.min_thickness_mm)
        self.relative.setText({
            "face": "the face",
            "seat": "its parent seat's floor (the face follows the parent)",
            "hinge": "the hinge pocket's floor, tilt included (always the hinge's face)",
        }[f.relative_to])
        # The face is derived for a nested seat and for one in a hinge.
        self.face.setEnabled(f.relative_to == "face")
        self._loading = False

    def _on_edited(self, *_a) -> None:
        if self._loading:
            return
        row = self.rows.currentRow()
        if not (0 <= row < len(self._features)):
            return
        tool = self.tool.currentText()
        step = self.stepdown.value()
        self._features[row] = self._features[row].model_copy(update=dict(
            enabled=self.enabled.isChecked(),
            label=self.label.text(),
            face=_FACES[self.face.currentIndex()],
            depth_mm=self.depth.value(),
            flush_mm=self.flush.value(),
            mode=_MODES[self.mode.currentIndex()],
            tool="" if tool == _NO_TOOL else tool,
            stepdown_mm=step if step > 0 else None,
            min_thickness_mm=self.min_thickness.value(),
        ))
        self._refresh_rows()
        self.changed.emit()

    # ---------------------------------------------------------------- public

    def features(self) -> list[InlayFeature]:
        return [f.model_copy() for f in self._features]

    def set_features(self, features) -> None:
        self._features = [f.model_copy() for f in (features or [])]
        self._refresh_rows()
        if self._features:
            self._on_selected(self.rows.currentRow())

    def set_geometry(self, polys, hinges, *, default_depth_mm: float,
                     default_face: str = "anterior") -> None:
        """The drawing's seats arrived (or changed): one row per seat, each
        existing feature following its seat, a new seat on the defaults."""
        from guildmodel.core.geometry.inlays import reconcile
        self._features = reconcile(self._features, list(polys or []),
                                   list(hinges or []),
                                   default_depth_mm=default_depth_mm,
                                   default_face=default_face)
        self._refresh_rows()
        if self._features:
            self._on_selected(self.rows.currentRow())

    def set_tool_names(self, names: list[str]) -> None:
        """Repopulate the tool combo from an edited library, keeping the choice."""
        current = self.tool.currentText()
        self.tool.blockSignals(True)
        self.tool.clear()
        self.tool.addItem(_NO_TOOL)
        self.tool.addItems(list(names))
        i = self.tool.findText(current)
        self.tool.setCurrentIndex(i if i >= 0 else 0)
        self.tool.blockSignals(False)
