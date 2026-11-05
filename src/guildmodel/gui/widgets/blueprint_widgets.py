"""The blueprint's settings as widgets (2.3): one editor for a
`BlueprintSettings`, used by the export dialog over a project's copy and by
Preferences ▸ Blueprint over the shop's defaults, and the draft's own
defaults page beside it."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from guildmodel.core.project.schema import (BARREL_COUNTS, HINGE_KIND_LABELS,
                                            PAPER_SIZES, SCREW_THREADS,
                                            STANDARD_SCALES, BlueprintSettings,
                                            DraftHinge, HingeKind, ToleranceRow)

_SCALE_LABELS = {2.0: "2:1", 1.0: "1:1", 2.0 / 3.0: "1:1.5", 0.5: "1:2", 0.4: "1:2.5", 0.2: "1:5"}


class BlueprintSettingsWidget(QWidget):
    """``w.set_settings(s); s = w.settings()``."""

    def __init__(self, parent: QWidget | None = None, *, show_cells: bool = True) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        page = QGroupBox("Page")
        pf = QFormLayout(page)
        self.paper = QComboBox()
        for key, (label, _w, _h) in PAPER_SIZES.items():
            self.paper.addItem(label, key)
        pf.addRow("Paper:", self.paper)
        self.orientation = QComboBox()
        for key, label in (("auto", "Auto (the larger scale)"), ("landscape", "Landscape"),
                           ("portrait", "Portrait")):
            self.orientation.addItem(label, key)
        pf.addRow("Orientation:", self.orientation)
        self.projection = QComboBox()
        self.projection.addItem("First angle (Europe, China)", "first")
        self.projection.addItem("Third angle (US)", "third")
        self.projection.setToolTip("Where the top and side views sit around the front view; "
                                   "the symbol in the title block says which.")
        pf.addRow("Projection:", self.projection)
        self.scale = QComboBox()
        self.scale.addItem("Auto (the largest that fits)", 0.0)
        for k in STANDARD_SCALES:
            self.scale.addItem(_SCALE_LABELS.get(k, f"{k:g}"), k)
        pf.addRow("Scale:", self.scale)
        self.line_weight = QDoubleSpinBox()
        self.line_weight.setRange(0.1, 1.0)
        self.line_weight.setSingleStep(0.05)
        self.line_weight.setDecimals(2)
        self.line_weight.setSuffix(" mm")
        self.line_weight.setToolTip("The outlines' line weight on paper; the rest is thinner.")
        pf.addRow("Line weight:", self.line_weight)
        self.border = QCheckBox("Draw the border")
        pf.addRow("", self.border)
        lay.addWidget(page)

        views = QGroupBox("Sheets and views")
        vf = QFormLayout(views)
        self.view_front = QCheckBox("Front view")
        self.view_top = QCheckBox("Top view")
        self.view_side = QCheckBox("Side view")
        self.view_hinge = QCheckBox("Hinge detail (reference only)")
        self.view_notes = QCheckBox("Notes, tolerances and the checks")
        self.view_folded = QCheckBox("Folded temples, dashed, in the front view")
        self.view_folded.setToolTip("The closed-temple check drawn: the temples folded across "
                                    "the back, which should cross the center and clear the lenses.")
        self.sheet_template = QCheckBox("Sheet 2: the 1:1 alignment template")
        for cb in (self.view_front, self.view_top, self.view_side, self.view_hinge,
                   self.view_notes, self.view_folded, self.sheet_template):
            vf.addRow(cb)
        lay.addWidget(views)

        cells = QGroupBox("Title block")
        cf = QFormLayout(cells)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("the legal owner: your shop")
        self.author = QLineEdit()
        self.author.setPlaceholderText("created by")
        self.design_name = QLineEdit()
        self.design_name.setPlaceholderText("the project's name")
        self.id_number = QLineEdit()
        self.revision = QLineEdit()
        self.document_type = QLineEdit()
        self.approver = QLineEdit()
        self.issue_date = QLineEdit()
        self.issue_date.setPlaceholderText("the day it is written")
        self.material = QLineEdit()
        self.material.setPlaceholderText("the project's material and sheet")
        self.finish = QLineEdit()
        cf.addRow("Owner:", self.owner)
        cf.addRow("Author:", self.author)
        if show_cells:
            cf.addRow("Design name:", self.design_name)
            cf.addRow("ID number:", self.id_number)
            cf.addRow("Revision:", self.revision)
            cf.addRow("Approved by:", self.approver)
            cf.addRow("Date of issue:", self.issue_date)
        cf.addRow("Document type:", self.document_type)
        cf.addRow("Material:", self.material)
        cf.addRow("Finish:", self.finish)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("notes for the factory, one per line")
        self.notes.setFixedHeight(64)
        cf.addRow("Notes:", self.notes)
        lay.addWidget(cells)
        self._show_cells = show_cells

        tol = QGroupBox("Tolerances")
        tl = QVBoxLayout(tol)
        self.tolerances = QTableWidget(0, 3)
        self.tolerances.setHorizontalHeaderLabels(["Dimension", "Tolerance", "Source"])
        self.tolerances.horizontalHeader().setStretchLastSection(True)
        self.tolerances.verticalHeader().setVisible(False)
        self.tolerances.setToolTip("Every row is editable; a blank name drops the row. The "
                                   "source is ISO, customer or internal.")
        tl.addWidget(self.tolerances)
        lay.addWidget(tol)

    def set_settings(self, s: BlueprintSettings) -> None:
        for combo, value in ((self.paper, s.paper), (self.orientation, s.orientation),
                             (self.projection, s.projection)):
            i = combo.findData(value)
            combo.setCurrentIndex(max(i, 0))
        i = self.scale.findData(float(s.scale))
        self.scale.setCurrentIndex(max(i, 0))
        self.line_weight.setValue(float(s.line_weight_mm))
        self.border.setChecked(bool(s.border))
        for cb, v in ((self.view_front, s.view_front), (self.view_top, s.view_top),
                      (self.view_side, s.view_side), (self.view_hinge, s.view_hinge),
                      (self.view_notes, s.view_notes), (self.view_folded, s.view_folded),
                      (self.sheet_template, s.sheet_template)):
            cb.setChecked(bool(v))
        for edit, v in ((self.owner, s.owner), (self.author, s.author),
                        (self.design_name, s.design_name), (self.id_number, s.id_number),
                        (self.revision, s.revision), (self.document_type, s.document_type),
                        (self.approver, s.approver), (self.issue_date, s.issue_date),
                        (self.material, s.material), (self.finish, s.finish)):
            edit.setText(v)
        self.notes.setPlainText(s.notes)
        self.tolerances.setRowCount(0)
        for row in s.tolerances:
            self._add_tolerance(row)
        self._add_tolerance(None)       # a blank row to type a new one into
        self.tolerances.resizeColumnsToContents()

    def _add_tolerance(self, row: ToleranceRow | None) -> None:
        r = self.tolerances.rowCount()
        self.tolerances.insertRow(r)
        for c, text in enumerate(("", "", "ISO") if row is None
                                 else (row.name, row.value, row.source)):
            self.tolerances.setItem(r, c, QTableWidgetItem(text))

    def settings(self, base: BlueprintSettings | None = None) -> BlueprintSettings:
        base = base if base is not None else BlueprintSettings()
        rows = []
        for r in range(self.tolerances.rowCount()):
            cells = [self.tolerances.item(r, c) for c in range(3)]
            name = cells[0].text().strip() if cells[0] else ""
            if not name:
                continue
            value = cells[1].text().strip() if cells[1] else ""
            source = (cells[2].text().strip() if cells[2] else "ISO") or "ISO"
            if source not in ("ISO", "customer", "internal"):
                source = "internal"
            rows.append(ToleranceRow(name=name, value=value, source=source))
        return BlueprintSettings(
            paper=self.paper.currentData(), orientation=self.orientation.currentData(),
            projection=self.projection.currentData(), scale=float(self.scale.currentData()),
            line_weight_mm=float(self.line_weight.value()), border=self.border.isChecked(),
            view_front=self.view_front.isChecked(), view_top=self.view_top.isChecked(),
            view_side=self.view_side.isChecked(), view_hinge=self.view_hinge.isChecked(),
            view_notes=self.view_notes.isChecked(), view_folded=self.view_folded.isChecked(),
            sheet_template=self.sheet_template.isChecked(),
            owner=self.owner.text().strip(), author=self.author.text().strip(),
            design_name=self.design_name.text().strip() if self._show_cells else base.design_name,
            id_number=self.id_number.text().strip() if self._show_cells else base.id_number,
            revision=self.revision.text().strip() if self._show_cells else base.revision,
            document_type=self.document_type.text().strip(),
            approver=self.approver.text().strip() if self._show_cells else base.approver,
            issue_date=self.issue_date.text().strip() if self._show_cells else base.issue_date,
            material=self.material.text().strip(), finish=self.finish.text().strip(),
            notes=self.notes.toPlainText().strip(), tolerances=rows)


class DraftDefaultsWidget(QWidget):
    """The draft's own defaults for Preferences ▸ Blueprint: the targets a
    new project's temples hang at and the hinge it starts with."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Draft view")
        form = QFormLayout(box)
        self.side = QDoubleSpinBox()
        self.side.setRange(0.0, 20.0)
        self.side.setSingleStep(0.5)
        self.side.setDecimals(1)
        self.side.setSuffix("°")
        self.side.setToolTip("The angle of side a new project's temples hang at.")
        form.addRow("Angle of side:", self.side)
        self.splay = QDoubleSpinBox()
        self.splay.setRange(-10.0, 20.0)
        self.splay.setSingleStep(0.5)
        self.splay.setDecimals(1)
        self.splay.setSuffix("°")
        self.splay.setToolTip("The splay per side a new project's temples open to; 0 is "
                                 "parallel.")
        form.addRow("Splay:", self.splay)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for k in HingeKind:
            self.kind.addItem(HINGE_KIND_LABELS[k], k.value)
        row.addWidget(self.kind)
        self.barrels = QComboBox()
        for b in BARREL_COUNTS:
            self.barrels.addItem(f"{b} barrels", b)
        row.addWidget(self.barrels)
        self.screw = QComboBox()
        self.screw.addItems(list(SCREW_THREADS))
        row.addWidget(self.screw)
        form.addRow("Hinge:", row)
        self.slant = QDoubleSpinBox()
        self.slant.setRange(-15.0, 15.0)
        self.slant.setDecimals(0)
        self.slant.setSuffix("°")
        form.addRow("Hinge slant:", self.slant)
        self.stop = QDoubleSpinBox()
        self.stop.setRange(80.0, 180.0)
        self.stop.setDecimals(0)
        self.stop.setSuffix("°")
        form.addRow("Hinge stop:", self.stop)
        lay.addWidget(box)

    def set_values(self, side: float, splay: float, hinge: DraftHinge) -> None:
        self.side.setValue(float(side))
        self.splay.setValue(float(splay))
        i = self.kind.findData(HingeKind(hinge.kind).value)
        self.kind.setCurrentIndex(max(i, 0))
        i = self.barrels.findData(int(hinge.barrels))
        self.barrels.setCurrentIndex(max(i, 0))
        if self.screw.findText(hinge.screw_thread) >= 0:
            self.screw.setCurrentText(hinge.screw_thread)
        self.slant.setValue(float(hinge.slant_deg))
        self.stop.setValue(float(hinge.open_deg))

    def values(self) -> tuple[float, float, DraftHinge]:
        hinge = DraftHinge(kind=HingeKind(self.kind.currentData()),
                           barrels=int(self.barrels.currentData()),
                           screw_thread=self.screw.currentText(),
                           slant_deg=float(self.slant.value()),
                           open_deg=float(self.stop.value()))
        return float(self.side.value()), float(self.splay.value()), hinge


def draft_defaults(prefs: dict) -> tuple[float, float, DraftHinge, BlueprintSettings]:
    """What Preferences ▸ Blueprint holds: (angle of side, splay, the
    hinge, the blueprint settings), each sparse over the schema."""
    d = prefs.get("draft") if isinstance(prefs.get("draft"), dict) else {}
    try:
        side = float(d.get("angle_of_side_deg", 8.0))
    except (TypeError, ValueError):
        side = 8.0
    try:
        splay = float(d.get("splay_deg", 0.0))
    except (TypeError, ValueError):
        splay = 0.0
    try:
        hinge = DraftHinge.model_validate(d.get("hinge") or {})
    except Exception:                                   # noqa: BLE001
        hinge = DraftHinge()
    try:
        bp = BlueprintSettings.model_validate(d.get("blueprint") or {})
    except Exception:                                   # noqa: BLE001
        bp = BlueprintSettings()
    return side, splay, hinge, bp


def sparse_dump(model, default) -> dict:
    """The fields of `model` that differ from `default`'s, as a dict."""
    a, b = model.model_dump(), default.model_dump()
    return {k: v for k, v in a.items() if v != b.get(k)}
