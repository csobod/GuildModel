"""Preferences ▸ Parts — the shop defaults a fresh drawing starts from, per kind
of part (2026-09-27). The Qt face of `gui/part_defaults.py`.

One group box per kind of part — Frame Front, Temples, Base-curve blocks — each
with its program zero and the fields a shop sets once: blank sizes, the temples'
blank-end snap and stock side, the block's mounting-hole pattern, the tools. The
ranges mirror the param dock's, and *Reset to shipped* on each group puts the
schema defaults back. `to_prefs()` returns the sparse `part_defaults` dict.

`PartDefaultsOffer` is the offer on Save: one checkbox per departure.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStyle, QVBoxLayout,
    QWidget,
)

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleParams, ProgramZero, StockDefinition, TempleParams,
)
from guildmodel.gui import part_defaults
from guildmodel.gui.widgets.params_panel import _tool_names

# Schema literal ↔ display order, shared with the dock's Program Zero group.
_PZ_MODE = [("stock_box", "Stock box"), ("fixture", "Fixture (design frame)")]
_PZ_X = [("left", "Left"), ("center", "Center"), ("right", "Right")]
_PZ_Y = [("bottom", "Bottom"), ("center", "Center"), ("top", "Top")]
_PZ_Z = [("top", "Top face"), ("bottom", "Bottom face (anterior)")]


def _spin(value: float, lo: float, hi: float, step: float, decimals: int,
          suffix: str = " mm") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setSuffix(suffix)
    sb.setValue(value)
    sb.setKeyboardTracking(False)
    return sb


def _set(sb, value) -> None:
    sb.blockSignals(True)
    sb.setValue(value)
    sb.blockSignals(False)


def _set_text(cb: QComboBox, text: str) -> None:
    """Select `text`, adding it when the library no longer lists it so a stored
    tool name round-trips instead of silently becoming the first entry."""
    if cb.findText(text) < 0:
        cb.addItem(text)
    cb.setCurrentText(text)


class ZeroPicker(QWidget):
    """Mode + X / Y / Z datum on one row — the dock's Program Zero group, compact."""

    def __init__(self, pz: ProgramZero | None = None, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.mode = self._combo(_PZ_MODE, "Zero mode")
        self.x = self._combo(_PZ_X, "X datum on the blank")
        self.y = self._combo(_PZ_Y, "Y datum on the blank")
        self.z = self._combo(_PZ_Z, "Z datum on the blank")
        for cb in (self.mode, self.x, self.y, self.z):
            lay.addWidget(cb)
        self.mode.currentIndexChanged.connect(self._sync_enabled)
        self.set_value(pz or ProgramZero())

    @staticmethod
    def _combo(pairs, tip: str) -> QComboBox:
        cb = QComboBox()
        for _key, label in pairs:
            cb.addItem(label)
        cb.setToolTip(tip)
        return cb

    def _sync_enabled(self) -> None:
        stock_box = _PZ_MODE[self.mode.currentIndex()][0] == "stock_box"
        for cb in (self.x, self.y, self.z):
            cb.setEnabled(stock_box)

    def value(self) -> ProgramZero:
        return ProgramZero(
            mode=_PZ_MODE[self.mode.currentIndex()][0],
            x_ref=_PZ_X[self.x.currentIndex()][0],
            y_ref=_PZ_Y[self.y.currentIndex()][0],
            z_ref=_PZ_Z[self.z.currentIndex()][0],
        )

    def set_value(self, pz: ProgramZero) -> None:
        for cb, pairs, val in ((self.mode, _PZ_MODE, pz.mode), (self.x, _PZ_X, pz.x_ref),
                               (self.y, _PZ_Y, pz.y_ref), (self.z, _PZ_Z, pz.z_ref)):
            keys = [k for k, _ in pairs]
            if val in keys:
                cb.blockSignals(True)
                cb.setCurrentIndex(keys.index(val))
                cb.blockSignals(False)
        self._sync_enabled()


class PartDefaultsPage(QWidget):
    """The Parts tab. `prefs` is the live prefs dict; nothing is written until the
    dialog's OK reads `to_prefs()`."""

    def __init__(self, prefs: dict, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 8)

        hint = QLabel(
            "What a newly opened drawing or DXF starts from, per kind of part. A "
            "project keeps its own values; saving one whose program zero, stock or "
            "temple alignment differs offers to adopt them here.")
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        lay.addWidget(hint)

        tools = _tool_names()
        self._build_front(lay, prefs)
        self._build_temple(lay, prefs, tools)
        self._build_block(lay, prefs, tools)
        lay.addStretch()

    # ------------------------------------------------------------ groups

    @staticmethod
    def _group(title: str, tip: str) -> tuple[QGroupBox, QFormLayout]:
        grp = QGroupBox(title)
        grp.setToolTip(tip)
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        return grp, form

    @staticmethod
    def _reset_row(form: QFormLayout, on_reset) -> None:
        btn = QPushButton("Reset to shipped")
        btn.setToolTip("Put this part's shipped defaults back.")
        btn.clicked.connect(on_reset)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn)
        form.addRow("", row)

    def _build_front(self, lay: QVBoxLayout, prefs: dict) -> None:
        cp = part_defaults.default_params(prefs, "frame_front")
        grp, form = self._group(
            part_defaults.GROUP_LABELS["frame_front"],
            "The frame front: its G54 datum and the stock it is cut from.")
        self.front_zero = ZeroPicker(part_defaults.default_program_zero(prefs, "frame_front"))
        form.addRow("Program zero:", self.front_zero)
        st = cp.stock
        self.front_blank_length = _spin(st.blank_length_mm, 50.0, 300.0, 1.0, 1)
        self.front_blank_width = _spin(st.blank_width_mm, 30.0, 200.0, 1.0, 1)
        self.front_blank_thickness = _spin(st.blank_thickness_mm, 1.0, 12.0, 0.5, 1)
        form.addRow("Blank length:", self.front_blank_length)
        form.addRow("Blank width:", self.front_blank_width)
        form.addRow("Blank thickness:", self.front_blank_thickness)
        self.front_pad = QCheckBox("Add nosepad pad block")
        self.front_pad.setChecked(st.use_pad_block)
        form.addRow("", self.front_pad)
        self.front_pad_length = _spin(st.pad_block_length_mm, 10.0, 120.0, 1.0, 1)
        self.front_pad_width = _spin(st.pad_block_width_mm, 10.0, 120.0, 1.0, 1)
        self.front_pad_thickness = _spin(st.pad_block_thickness_mm, 0.5, 10.0, 0.5, 1)
        form.addRow("Pad block length:", self.front_pad_length)
        form.addRow("Pad block width:", self.front_pad_width)
        form.addRow("Pad block thickness:", self.front_pad_thickness)
        self.front_pad.toggled.connect(self._sync_pad_enabled)
        self._sync_pad_enabled(st.use_pad_block)
        self._reset_row(form, lambda: self._set_front(CastleParams(), ProgramZero()))
        lay.addWidget(grp)

    def _sync_pad_enabled(self, on: bool) -> None:
        for sb in (self.front_pad_length, self.front_pad_width, self.front_pad_thickness):
            sb.setEnabled(on)

    def _set_front(self, cp: CastleParams, pz: ProgramZero) -> None:
        self.front_zero.set_value(pz)
        st = cp.stock
        _set(self.front_blank_length, st.blank_length_mm)
        _set(self.front_blank_width, st.blank_width_mm)
        _set(self.front_blank_thickness, st.blank_thickness_mm)
        self.front_pad.setChecked(st.use_pad_block)
        _set(self.front_pad_length, st.pad_block_length_mm)
        _set(self.front_pad_width, st.pad_block_width_mm)
        _set(self.front_pad_thickness, st.pad_block_thickness_mm)

    def _build_temple(self, lay: QVBoxLayout, prefs: dict, tools: list[str]) -> None:
        t = part_defaults.default_params(prefs, "temple_right")
        grp, form = self._group(
            part_defaults.GROUP_LABELS["temple"],
            "Both temples: G54 datum, how the part sits on its blank, blank size, tools.")
        self.temple_zero = ZeroPicker(part_defaults.default_program_zero(prefs, "temple_right"))
        form.addRow("Program zero:", self.temple_zero)
        self.temple_snap = QCheckBox("Snap to blank end")
        self.temple_snap.setChecked(t.snap_to_blank_end)
        self.temple_snap.setToolTip(
            "Butt the hinge end to one end of the blank so the injected core runs "
            "the temple's length.")
        form.addRow("", self.temple_snap)
        self.temple_side = QComboBox()
        self.temple_side.addItems(["right", "left"])
        self.temple_side.setCurrentText(t.stock_side)
        self.temple_side.setToolTip("Which blank end the hinge registers to.")
        self.temple_side.setEnabled(t.snap_to_blank_end)
        self.temple_snap.toggled.connect(self.temple_side.setEnabled)
        form.addRow("Stock side:", self.temple_side)
        self.temple_blank_length = _spin(t.blank_length_mm, 50.0, 300.0, 1.0, 1)
        self.temple_blank_width = _spin(t.blank_width_mm, 8.0, 80.0, 1.0, 1)
        self.temple_blank_thickness = _spin(t.blank_thickness_mm, 1.0, 12.0, 0.5, 1)
        form.addRow("Blank length:", self.temple_blank_length)
        form.addRow("Blank width:", self.temple_blank_width)
        form.addRow("Blank thickness:", self.temple_blank_thickness)
        self.temple_engrave_tool = QComboBox()
        self.temple_hinge_tool = QComboBox()
        self.temple_profile_tool = QComboBox()
        for cb, name in ((self.temple_engrave_tool, t.engrave_tool),
                         (self.temple_hinge_tool, t.hinge_tool),
                         (self.temple_profile_tool, t.profile_tool)):
            cb.addItems(tools)
            _set_text(cb, name)
        form.addRow("Engrave tool:", self.temple_engrave_tool)
        form.addRow("Hinge tool:", self.temple_hinge_tool)
        form.addRow("Profile tool:", self.temple_profile_tool)
        self._reset_row(form, lambda: self._set_temple(
            part_defaults.schema_default("temple_right"), ProgramZero()))
        lay.addWidget(grp)

    def _set_temple(self, t: TempleParams, pz: ProgramZero) -> None:
        self.temple_zero.set_value(pz)
        self.temple_snap.setChecked(t.snap_to_blank_end)
        _set_text(self.temple_side, t.stock_side)
        _set(self.temple_blank_length, t.blank_length_mm)
        _set(self.temple_blank_width, t.blank_width_mm)
        _set(self.temple_blank_thickness, t.blank_thickness_mm)
        _set_text(self.temple_engrave_tool, t.engrave_tool)
        _set_text(self.temple_hinge_tool, t.hinge_tool)
        _set_text(self.temple_profile_tool, t.profile_tool)

    def _build_block(self, lay: QVBoxLayout, prefs: dict, tools: list[str]) -> None:
        b = part_defaults.default_params(prefs, "base_curve_right")
        grp, form = self._group(
            part_defaults.GROUP_LABELS["base_curve"],
            "Both base-curve blocks: G54 datum, blank size, the jig's mounting-hole "
            "pattern, tools.")
        self.block_zero = ZeroPicker(part_defaults.default_program_zero(prefs, "base_curve_right"))
        form.addRow("Program zero:", self.block_zero)
        self.block_blank_length = _spin(b.blank_length_mm, 30.0, 150.0, 1.0, 1)
        self.block_blank_width = _spin(b.blank_width_mm, 30.0, 150.0, 1.0, 1)
        # 4 decimals so imperial gauges round-trip exactly (3/16" = 4.7625 mm).
        self.block_blank_thickness = _spin(b.blank_thickness_mm, 3.0, 20.0, 0.0125, 4)
        form.addRow("Blank length:", self.block_blank_length)
        form.addRow("Blank width:", self.block_blank_width)
        form.addRow("Blank thickness:", self.block_blank_thickness)
        self.block_hole_count = QSpinBox()
        self.block_hole_count.setKeyboardTracking(False)
        self.block_hole_count.setRange(0, 6)
        self.block_hole_count.setValue(b.hole_count)
        form.addRow("Hole count:", self.block_hole_count)
        self.block_hole_spacing = _spin(b.hole_spacing_mm, 4.0, 40.0, 1.0, 1)
        form.addRow("Hole spacing:", self.block_hole_spacing)
        self.block_hole_diameter = _spin(b.hole_diameter_mm, 1.0, 10.0, 0.1, 2)
        form.addRow("Hole Ø:", self.block_hole_diameter)
        self.block_hole_arrangement = QComboBox()
        self.block_hole_arrangement.addItems(["inline", "triangle"])
        self.block_hole_arrangement.setCurrentText(b.hole_arrangement)
        form.addRow("Arrangement:", self.block_hole_arrangement)
        self.block_profile_tool = QComboBox()
        self.block_drill_tool = QComboBox()
        for cb, name in ((self.block_profile_tool, b.profile_tool),
                         (self.block_drill_tool, b.drill_tool)):
            cb.addItems(tools)
            _set_text(cb, name)
        form.addRow("Profile tool:", self.block_profile_tool)
        form.addRow("Drill tool:", self.block_drill_tool)
        self._reset_row(form, lambda: self._set_block(
            part_defaults.schema_default("base_curve_right"), ProgramZero()))
        lay.addWidget(grp)

    def _set_block(self, b: BaseCurveBlockParams, pz: ProgramZero) -> None:
        self.block_zero.set_value(pz)
        _set(self.block_blank_length, b.blank_length_mm)
        _set(self.block_blank_width, b.blank_width_mm)
        _set(self.block_blank_thickness, b.blank_thickness_mm)
        _set(self.block_hole_count, b.hole_count)
        _set(self.block_hole_spacing, b.hole_spacing_mm)
        _set(self.block_hole_diameter, b.hole_diameter_mm)
        _set_text(self.block_hole_arrangement, b.hole_arrangement)
        _set_text(self.block_profile_tool, b.profile_tool)
        _set_text(self.block_drill_tool, b.drill_tool)

    # ------------------------------------------------------------ out

    def front_params(self) -> CastleParams:
        base = part_defaults.schema_default("frame_front")
        return base.model_copy(update={"stock": StockDefinition(
            blank_length_mm=self.front_blank_length.value(),
            blank_width_mm=self.front_blank_width.value(),
            blank_thickness_mm=self.front_blank_thickness.value(),
            pad_block_length_mm=self.front_pad_length.value(),
            pad_block_width_mm=self.front_pad_width.value(),
            pad_block_thickness_mm=self.front_pad_thickness.value(),
            use_pad_block=self.front_pad.isChecked(),
        )})

    def temple_params(self) -> TempleParams:
        base = part_defaults.schema_default("temple_right")
        return base.model_copy(update=dict(
            snap_to_blank_end=self.temple_snap.isChecked(),
            stock_side=self.temple_side.currentText(),
            blank_length_mm=self.temple_blank_length.value(),
            blank_width_mm=self.temple_blank_width.value(),
            blank_thickness_mm=self.temple_blank_thickness.value(),
            engrave_tool=self.temple_engrave_tool.currentText(),
            hinge_tool=self.temple_hinge_tool.currentText(),
            profile_tool=self.temple_profile_tool.currentText(),
        ))

    def block_params(self) -> BaseCurveBlockParams:
        base = part_defaults.schema_default("base_curve_right")
        return base.model_copy(update=dict(
            blank_length_mm=self.block_blank_length.value(),
            blank_width_mm=self.block_blank_width.value(),
            blank_thickness_mm=self.block_blank_thickness.value(),
            hole_count=self.block_hole_count.value(),
            hole_spacing_mm=self.block_hole_spacing.value(),
            hole_diameter_mm=self.block_hole_diameter.value(),
            hole_arrangement=self.block_hole_arrangement.currentText(),
            profile_tool=self.block_profile_tool.currentText(),
            drill_tool=self.block_drill_tool.currentText(),
        ))

    def to_prefs(self) -> dict:
        """The sparse `part_defaults` dict: only what differs from the schema."""
        out: dict = {}
        for group, params, picker in (
            ("frame_front", self.front_params(), self.front_zero),
            ("temple", self.temple_params(), self.temple_zero),
            ("base_curve", self.block_params(), self.block_zero),
        ):
            entry: dict = {}
            zero = part_defaults.sparse_zero(picker.value())
            if zero is not None:
                entry["program_zero"] = zero
            params_sparse = part_defaults.sparse_params(group, params)
            if params_sparse:
                entry["params"] = params_sparse
            out[group] = entry
        return out


class PartDefaultsOffer(QDialog):
    """The offer on Save: one checkbox per departure, all checked, so a maker can
    take a new zero and leave a one-off job's blank (2026-09-28). It replaced a
    Yes/No message box that adopted the whole list or none of it.

    Yes adopts `chosen()` and is off while nothing is checked; No stays the
    default button, as it was on the message box. "Don't ask again" is the
    window's to act on, whichever button closes the dialog."""

    def __init__(self, deps: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set part defaults?")
        self._deps = list(deps)

        lay = QVBoxLayout(self)
        body = QHBoxLayout()
        style = self.style()
        size = style.pixelMetric(QStyle.PixelMetric.PM_MessageBoxIconSize, None, self)
        icon = QLabel()
        icon.setPixmap(style.standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxQuestion, None, self).pixmap(size, size))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        body.addWidget(icon)

        text = QVBoxLayout()
        head = QLabel("This project's part setup differs from your defaults.")
        head.setWordWrap(True)
        text.addWidget(head)
        text.addSpacing(4)
        self.line_checks: list[QCheckBox] = []
        for d in self._deps:
            cb = QCheckBox(d.text())
            cb.setChecked(True)
            cb.toggled.connect(self._refresh)
            text.addWidget(cb)
            self.line_checks.append(cb)
        ask = QLabel("Make the checked ones the defaults every new drawing starts "
                     "from? (Preferences \u25b8 Parts)")
        ask.setWordWrap(True)
        text.addSpacing(4)
        text.addWidget(ask)
        body.addLayout(text, 1)
        lay.addLayout(body)

        self.dont_ask = QCheckBox("Don't ask again")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
        self.yes_button = buttons.button(QDialogButtonBox.StandardButton.Yes)
        self.yes_button.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.No).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        foot = QHBoxLayout()
        foot.addWidget(self.dont_ask)
        foot.addStretch()
        foot.addWidget(buttons)
        lay.addLayout(foot)

    def _refresh(self) -> None:
        self.yes_button.setEnabled(any(cb.isChecked() for cb in self.line_checks))

    def chosen(self) -> list:
        """The departures still checked."""
        return [d for d, cb in zip(self._deps, self.line_checks) if cb.isChecked()]
