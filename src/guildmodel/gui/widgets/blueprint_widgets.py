"""The blueprint's settings as widgets (2.3): one editor for a
`BlueprintSettings`, used by the export dialog over a project's copy and by
Preferences ▸ Blueprint over the shop's defaults, and the draft's own
defaults page beside it."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QCompleter,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from guildmodel.core.project.schema import (BARREL_COUNTS, BLUEPRINT_COLOR_PRESETS,
                                            HINGE_KIND_LABELS, PAPER_SIZES,
                                            SCREW_THREADS, STANDARD_SCALES,
                                            BlueprintSettings, DraftHinge, HingeKind,
                                            ToleranceRow, hex_color)

_SCALE_LABELS = {2.0: "2:1", 1.0: "1:1", 2.0 / 3.0: "1:1.5", 0.5: "1:2", 0.4: "1:2.5", 0.2: "1:5"}
_DEFAULT_FONT_LABEL = "Default (Helvetica)"


class ColorSwatch(QPushButton):
    """A button painted in its color; a click opens the color dialog.
    ``swatch.color`` is #rrggbb; `changed` fires on a pick."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._color = "#000000"
        self._listeners: list = []
        # a QPushButton in a dialog is autoDefault: Enter in any text field
        # would open the color dialog
        self.setAutoDefault(False)
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance("#000000") + 18)
        self.setToolTip(f"{title}: click to choose")
        self.clicked.connect(self._pick)

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, value: str) -> None:
        self._color = hex_color(value, self._color)
        c = QColor(self._color)
        text = "#000000" if c.lightnessF() > 0.5 else "#ffffff"
        self.setStyleSheet(f"QPushButton {{ background: {self._color}; color: {text}; "
                           f"border: 1px solid #808080; padding: 2px; }}")
        self.setText(self._color)

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, self._title)
        if c.isValid():
            self.set_color(c.name())
            for fn in self._listeners:
                fn()


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
        self.paper.setToolTip("A3 and tabloid hold the three views at 1:1; letter and A4 "
                              "at 1:2 (A4 sometimes 1:1.5).")
        pf.addRow("Paper:", self.paper)
        self.orientation = QComboBox()
        for key, label in (("auto", "Auto (the larger scale)"), ("landscape", "Landscape"),
                           ("portrait", "Portrait")):
            self.orientation.addItem(label, key)
        self.orientation.setToolTip("Portrait stacks the views down the page, as eyewear "
                                    "sheets do; Auto takes whichever gives the larger scale.")
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
        self.scale.setToolTip("Auto picks the largest standard scale the views fit at; a "
                              "fixed scale is kept even when the views run off the page.")
        pf.addRow("Scale:", self.scale)
        self.line_weight = QDoubleSpinBox()
        self.line_weight.setRange(0.1, 1.0)
        self.line_weight.setSingleStep(0.05)
        self.line_weight.setDecimals(2)
        self.line_weight.setSuffix(" mm")
        self.line_weight.setToolTip("The outlines' line weight on paper; the rest is thinner.")
        pf.addRow("Line weight:", self.line_weight)
        self.border = QCheckBox("Draw the border")
        self.border.setToolTip("The frame around the sheet, 10 mm in from the paper's edge.")
        pf.addRow("", self.border)
        lay.addWidget(page)

        lettering = QGroupBox("Lettering and colors")
        lf = QFormLayout(lettering)
        self.font = QComboBox()
        self.font.addItem(_DEFAULT_FONT_LABEL, "")
        try:
            families = list(QFontDatabase.families())
        except Exception:                                   # noqa: BLE001
            families = []
        for fam in families:
            if fam and not fam.startswith("."):
                self.font.addItem(fam, fam)
        self.font.setToolTip("The sheet's font: the default is Helvetica, or the nearest sans "
                             "this machine has; a PDF embeds the font it uses. Type to search.")
        self.font.setMaxVisibleItems(18)
        self.font.setEditable(True)
        self.font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(self.font.model(), self.font)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.font.setCompleter(completer)
        self.font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font.setMinimumContentsLength(24)
        lf.addRow("Font:", self.font)
        self.dim_text = QComboBox()
        self.dim_text.addItem("In a break in the dimension line (ASME)", "inline")
        self.dim_text.addItem("Above the dimension line (ISO)", "above")
        self.dim_text.setToolTip("Where a dimension's value sits. A value wider than its "
                                 "dimension goes outside the extension lines either way.")
        lf.addRow("Dimension text:", self.dim_text)
        self.color_preset = QComboBox()
        for key, (label, _line, _paper) in BLUEPRINT_COLOR_PRESETS.items():
            self.color_preset.addItem(label, key)
        self.color_preset.addItem("Custom", "custom")
        self.color_preset.setToolTip("The ink and the paper. The blueprint preset is white "
                                     "lines on Prussian blue, the cyanotype's look; the PDF, "
                                     "the SVG and the printer take the colors (a printer "
                                     "leaves its own margin white), the DXF does not.")
        self.color_preset.currentIndexChanged.connect(self._on_preset)
        lf.addRow("Colors:", self.color_preset)
        swatches = QHBoxLayout()
        self.line_color = ColorSwatch("Line color")
        self.paper_color = ColorSwatch("Paper color")
        for sw, label in ((self.line_color, "lines"), (self.paper_color, "paper")):
            swatches.addWidget(sw)
            swatches.addWidget(QLabel(label))
            sw.on_change(self._on_swatch)
        swatches.addStretch(1)
        lf.addRow("", swatches)
        lay.addWidget(lettering)

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
        self.sheet_template.setToolTip("The plan of the open frame at 1:1 with the tips and "
                                       "ear points in ±2 mm targets, the side view and a ruler.")
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
        self.notes.setTabChangesFocus(True)
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
        self.tolerances.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tolerances.itemChanged.connect(self._on_tolerance_edited)
        self._filling = False
        tl.addWidget(self.tolerances)
        lay.addWidget(tol)

    def _on_preset(self, _i: int = 0) -> None:
        key = self.color_preset.currentData()
        if key in BLUEPRINT_COLOR_PRESETS:
            _label, line, paper = BLUEPRINT_COLOR_PRESETS[key]
            self.line_color.set_color(line)
            self.paper_color.set_color(paper)

    def _on_swatch(self) -> None:
        """A picked color: the preset combo says which preset it matches,
        or Custom."""
        line, paper = self.line_color.color, self.paper_color.color
        match = "custom"
        for key, (_label, pl, pp) in BLUEPRINT_COLOR_PRESETS.items():
            if pl == line and pp == paper:
                match = key
        self.color_preset.blockSignals(True)
        self.color_preset.setCurrentIndex(max(self.color_preset.findData(match), 0))
        self.color_preset.blockSignals(False)

    def set_settings(self, s: BlueprintSettings) -> None:
        for combo, value in ((self.paper, s.paper), (self.orientation, s.orientation),
                             (self.projection, s.projection), (self.dim_text, s.dim_text)):
            i = combo.findData(value)
            combo.setCurrentIndex(max(i, 0))
        i = self.font.findData(s.font_family)
        if i < 0 and s.font_family:
            # a family this machine has not got: offered as is, so the
            # setting survives a round trip here and takes effect elsewhere
            self.font.addItem(f"{s.font_family} (not on this machine)", s.font_family)
            i = self.font.count() - 1
        self.font.setCurrentIndex(max(i, 0))
        self.line_color.set_color(s.line_color)
        self.paper_color.set_color(s.paper_color)
        self._on_swatch()
        i = next((j for j in range(self.scale.count())
                  if abs(float(self.scale.itemData(j)) - float(s.scale)) < 1e-6), -1)
        if i < 0 and s.scale > 0:
            label = f"1:{1.0 / s.scale:g}" if s.scale < 1 else f"{s.scale:g}:1"
            self.scale.addItem(f"{label} (this project's)", float(s.scale))
            i = self.scale.count() - 1
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
        was = self._filling
        self._filling = True
        try:
            r = self.tolerances.rowCount()
            self.tolerances.insertRow(r)
            for c, text in enumerate(("", "", "ISO") if row is None
                                     else (row.name, row.value, row.source)):
                self.tolerances.setItem(r, c, QTableWidgetItem(text))
        finally:
            self._filling = was
        self._size_tolerances()

    def _size_tolerances(self) -> None:
        """The table shows every row: inside a scrolling page it would be
        held at its minimum otherwise, 1.6 rows of 9."""
        t = self.tolerances
        h = t.verticalHeader().length() + t.horizontalHeader().height() + 2 * t.frameWidth() + 2
        t.setMinimumHeight(h)
        t.setMaximumHeight(h)

    def _on_tolerance_edited(self, item: QTableWidgetItem) -> None:
        """A name typed into the spare row: another spare appears under it."""
        if self._filling or item.column() != 0:
            return
        last = self.tolerances.rowCount() - 1
        last_item = self.tolerances.item(last, 0)
        if last_item is not None and last_item.text().strip():
            self._add_tolerance(None)

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
            source = {"iso": "ISO", "customer": "customer", "internal": "internal"}.get(
                source.lower(), "internal")
            rows.append(ToleranceRow(name=name, value=value, source=source))
        return BlueprintSettings(
            paper=self.paper.currentData(), orientation=self.orientation.currentData(),
            projection=self.projection.currentData(), scale=float(self.scale.currentData()),
            line_weight_mm=float(self.line_weight.value()), border=self.border.isChecked(),
            font_family=str(self.font.currentData() or ""), text_width_em=base.text_width_em,
            dim_text=self.dim_text.currentData(),
            line_color=self.line_color.color, paper_color=self.paper_color.color,
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
        from guildmodel.gui.widgets.draft_panel import SIDE_RANGE, SPLAY_RANGE
        self.side = QDoubleSpinBox()
        self.side.setRange(*SIDE_RANGE)
        self.side.setSingleStep(0.5)
        self.side.setDecimals(1)
        self.side.setSuffix("°")
        self.side.setToolTip("The angle of side a new project's temples hang at.")
        form.addRow("Angle of side:", self.side)
        self.splay = QDoubleSpinBox()
        self.splay.setRange(*SPLAY_RANGE)
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
        self.kind.setToolTip("How the hinge is mounted: riveted, a heat-set cleat, or a "
                             "spring hinge; the detail view draws the installation.")
        row.addWidget(self.kind)
        self.barrels = QComboBox()
        for b in BARREL_COUNTS:
            self.barrels.addItem(f"{b} barrels", b)
        self.barrels.setToolTip("The knuckles along the barrel; the front takes the odd one.")
        row.addWidget(self.barrels)
        self.screw = QComboBox()
        self.screw.addItems(list(SCREW_THREADS))
        self.screw.setToolTip("The hinge screw's thread; its length is the hinge's width "
                              "plus 0.5 mm, snapped to the catalog's step.")
        row.addWidget(self.screw)
        form.addRow("Hinge:", row)
        self.slant = QDoubleSpinBox()
        self.slant.setRange(-15.0, 15.0)
        self.slant.setDecimals(0)
        self.slant.setSuffix("°")
        self.slant.setToolTip("The barrel axis tilted from the pocket's floor, top toward the "
                              "front; it adds to the angle of side the hinge alone gives.")
        form.addRow("Hinge slant:", self.slant)
        self.stop = QDoubleSpinBox()
        self.stop.setRange(80.0, 180.0)
        self.stop.setDecimals(0)
        self.stop.setSuffix("°")
        self.stop.setToolTip("How far the hinge opens from the closed position; 180 is a "
                             "flush hinge for a wrap.")
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
