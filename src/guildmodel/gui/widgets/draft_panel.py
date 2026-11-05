"""The Draft panel (2.3): the targets the temples hang at, the hinge the
view fills in, the temples' tip bend, and the way to the blueprint.

A plain child frame under the 3D viewport, in the Forming panel's idiom:
thin, non-modal, open while View ▸ Draft is on. It turns controls into a
`DraftParams`, the angle-of-side target (the front's
`FormingMetadata.pantoscopic_tilt_deg`) and a `TipBendParams` for both
temples, and says when something moved; what the numbers mean lives in
`core.draft`, what to redraw in the window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QSizePolicy, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QWidget)

from guildmodel.core.project.schema import (BARREL_COUNTS, HINGE_KIND_LABELS,
                                            SCREW_THREADS, DraftHinge,
                                            DraftParams, HingeKind,
                                            TipBendParams)
from guildmodel.gui.widgets.param_slider import ParamSlider

#: The angle of side the temples hang at, degrees; the trade fits 5-15.
SIDE_RANGE = (0.0, 20.0)
#: The splay per side, degrees from the front plane's normal; negative
#: converges, the hinge alone usually does on a wrapped front. The
#: schema's own bounds (`DraftParams`).
SPLAY_RANGE = (-20.0, 30.0)


def _spin(value, lo, hi, step=1.0, decimals=1, suffix="") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setSuffix(suffix)
    sb.setValue(value)
    sb.setKeyboardTracking(False)
    return sb


class DraftPanel(QFrame):

    #: A target, a hinge field or the splay settled: the window writes it
    #: to the project and redraws the assembly.
    changed = Signal()
    #: A handle moving: the window redraws and nothing else.
    sliding = Signal()
    #: The temples' tip bend edited here: both temples take it.
    tip_bend_changed = Signal()
    #: Set the front's pocket angle so the hinge agrees with the target.
    match_pocket_requested = Signal()
    #: Open the blueprint dialog.
    blueprint_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("draftPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._applying = 0

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)

        # ---- row 0: the targets
        self.side = ParamSlider(8.0, *SIDE_RANGE, step=0.5, decimals=1, suffix="°")
        self.side.setToolTip(
            "Angle of side: the open temple's downward angle from the front's\n"
            "normal, the frame's own pantoscopic angle. The temples are drawn\n"
            "at it; what the hinge alone would give, and the butt cut that\n"
            "makes up the difference, read beside it.")
        self.side_readout = QLabel("")
        self.side_readout.setObjectName("mutedSmallLabel")
        self.side_readout.setWordWrap(True)
        self.side_readout.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.side_readout.setMinimumWidth(120)
        grid.addWidget(QLabel("Angle of side"), 0, 0)
        grid.addWidget(self.side, 0, 1)
        grid.addWidget(self.side_readout, 0, 2)
        self.splay = ParamSlider(0.0, *SPLAY_RANGE, step=0.5, decimals=1, suffix="°")
        self.splay.setToolTip(
            "Splay: the open temple's outward angle from the front's normal,\n"
            "per side. 0 is parallel temples. A formed front turns its\n"
            "endpieces toward the face, so the hinge alone converges the\n"
            "temples; the butt cut takes that out.")
        self.splay_readout = QLabel("")
        self.splay_readout.setObjectName("mutedSmallLabel")
        self.splay_readout.setWordWrap(True)
        self.splay_readout.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.splay_readout.setMinimumWidth(120)
        grid.addWidget(QLabel("Splay"), 0, 3)
        grid.addWidget(self.splay, 0, 4)
        grid.addWidget(self.splay_readout, 0, 5)
        self.match_btn = QPushButton("Match pocket angle")
        self.match_btn.setToolTip(
            "Set the front's component pocket angle so the hinge alone hangs\n"
            "the temples at the angle of side: the target less the endpiece's\n"
            "own lean and the hinge's slant.")
        self.match_btn.clicked.connect(self.match_pocket_requested)
        grid.addWidget(self.match_btn, 0, 6)

        # ---- row 1: the hinge
        self.kind = QComboBox()
        for k in HingeKind:
            self.kind.addItem(HINGE_KIND_LABELS[k], k.value)
        self.kind.setToolTip("How the hinge mounts in the acetate: the detail on the blueprint "
                             "draws it so.")
        grid.addWidget(QLabel("Hinge"), 1, 0)
        grid.addWidget(self.kind, 1, 1)
        hinge_row = QWidget()
        hl = QHBoxLayout(hinge_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.barrels = QComboBox()
        for b in BARREL_COUNTS:
            self.barrels.addItem(f"{b} barrels", b)
        self.barrels.setCurrentIndex(1)
        self.barrels.setToolTip("Knuckles across both halves; the front takes the odd one.")
        hl.addWidget(self.barrels)
        self.screw = QComboBox()
        self.screw.addItems(list(SCREW_THREADS))
        self.screw.setCurrentText("M1.4")
        self.screw.setToolTip("The screw's thread (ISO 11381); its length is the width along "
                              "the axis plus 0.5, snapped to the catalog's step.")
        hl.addWidget(self.screw)
        hl.addWidget(QLabel("Slant"))
        self.slant = _spin(0.0, -15.0, 15.0, 1.0, 0, "°")
        self.slant.setToolTip("A slanted insert hinge tilts the barrel axis; 6° is the usual.")
        hl.addWidget(self.slant)
        hl.addWidget(QLabel("Stop"))
        self.stop = _spin(90.0, 80.0, 180.0, 5.0, 0, "°")
        self.stop.setToolTip("How far the hinge opens from the closed position; 180 is a "
                             "flush hinge for a wrap.")
        hl.addWidget(self.stop)
        hl.addWidget(QLabel("Inset"))
        self.inset = _spin(0.0, -5.0, 15.0, 0.5, 1, " mm")
        self.inset.setToolTip("How far the temple's outer face sits inside the frame's edge:\n"
                              "0 flush with the endpiece's end face, as an acetate temple\n"
                              "hangs; more tucks the temple toward the hinge pocket.")
        hl.addWidget(self.inset)
        hl.addWidget(QLabel("Butt gap"))
        self.butt_gap = _spin(0.0, -5.0, 10.0, 0.25, 2, " mm")
        self.butt_gap.setToolTip("The barrel axis behind the endpiece's back face, which is\n"
                                 "how far the temple's butt stands off it; 0 is the butt joint.")
        hl.addWidget(self.butt_gap)
        hl.addStretch(1)
        grid.addWidget(hinge_row, 1, 2, 1, 4)

        # ---- row 2: the temples' tip bend
        grid.addWidget(QLabel("Tip bend"), 2, 0)
        bend_row = QWidget()
        bl = QHBoxLayout(bend_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(QLabel("Length to bend"))
        self.bend_length = _spin(0.0, 0.0, 300.0, 1.0, 1, " mm")
        self.bend_length.setSpecialValueText("Auto")
        self.bend_length.setToolTip("From the hinge end to the ear point; Auto is the drawn "
                                    "length less 37 mm. Both temples take it.")
        bl.addWidget(self.bend_length)
        bl.addWidget(QLabel("Downward angle"))
        self.bend_angle = _spin(50.0, 0.0, 90.0, 1.0, 1, "°")
        self.bend_angle.setSpecialValueText("Straight")
        bl.addWidget(self.bend_angle)
        bl.addWidget(QLabel("Bend radius"))
        self.bend_radius = _spin(15.0, 0.5, 100.0, 1.0, 1, " mm")
        bl.addWidget(self.bend_radius)
        bl.addWidget(QLabel("Inward angle"))
        self.bend_inward = _spin(15.0, 0.0, 45.0, 1.0, 1, "°")
        self.bend_inward.setSpecialValueText("None")
        self.bend_inward.setToolTip("How far the temple turns toward the head, seen from above, "
                                    "between 40 % of the length to bend and the ear point; the "
                                    "drop keeps that heading. The trade bends 10 to 20°.")
        bl.addWidget(self.bend_inward)
        self.bend_readout = QLabel("")
        self.bend_readout.setObjectName("mutedSmallLabel")
        self.bend_readout.setWordWrap(True)
        self.bend_readout.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.bend_readout.setMinimumWidth(120)
        bl.addWidget(self.bend_readout, 1)
        grid.addWidget(bend_row, 2, 1, 1, 6)

        # ---- row 3: the checks and the blueprint
        tail = QWidget()
        row = QHBoxLayout(tail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.readout = QLabel("")
        self.readout.setObjectName("formingBadge")
        row.addWidget(self.readout, 1)
        self.checks = QLabel("")
        self.checks.setObjectName("mutedSmallLabel")
        self.checks.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # wrapped: a long check line must not set the window's minimum width
        self.checks.setWordWrap(True)
        self.checks.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.checks.setMinimumWidth(120)
        row.addWidget(self.checks, 2)
        self.blueprint_btn = QPushButton("Blueprint…")
        self.blueprint_btn.setToolTip(
            "Write the dimensioned drawing: the assembly after forming on sheet 1,\n"
            "the 1:1 alignment template on sheet 2, as PDF, SVG or DXF, or printed.")
        self.blueprint_btn.clicked.connect(self.blueprint_requested)
        row.addWidget(self.blueprint_btn)
        grid.addWidget(tail, 3, 0, 1, 7)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(4, 2)

        for handle in (self.side, self.splay):
            handle.valueChanged.connect(self._on_settled)
            handle.sliding.connect(self._on_sliding)
        self.kind.currentIndexChanged.connect(self._on_settled)
        self.barrels.currentIndexChanged.connect(self._on_settled)
        self.screw.currentIndexChanged.connect(self._on_settled)
        self.slant.valueChanged.connect(self._on_settled)
        self.stop.valueChanged.connect(self._on_settled)
        self.inset.valueChanged.connect(self._on_settled)
        self.butt_gap.valueChanged.connect(self._on_settled)
        for w in (self.bend_length, self.bend_angle, self.bend_radius, self.bend_inward):
            w.valueChanged.connect(self._on_bend)

    # ------------------------------------------------------------ signals

    def _on_settled(self, *_a) -> None:
        if not self._applying:
            self.changed.emit()

    def _on_sliding(self, *_a) -> None:
        if not self._applying:
            self.sliding.emit()

    def _on_bend(self, *_a) -> None:
        if not self._applying:
            self.tip_bend_changed.emit()

    # ------------------------------------------------------------ the model

    def side_target(self) -> float:
        return float(self.side.value())

    def draft(self, base: DraftParams) -> DraftParams:
        """`base` with the panel's splay and hinge; the blueprint settings
        ride along untouched."""
        hinge = base.hinge.model_copy(update={
            "kind": HingeKind(self.kind.currentData()),
            "barrels": int(self.barrels.currentData()),
            "screw_thread": self.screw.currentText(),
            "slant_deg": float(self.slant.value()),
            "open_deg": float(self.stop.value()),
            "temple_inset_mm": float(self.inset.value()),
            "axis_offset_mm": float(self.butt_gap.value()),
        })
        return base.model_copy(update={"splay_deg": float(self.splay.value()),
                                       "hinge": DraftHinge.model_validate(hinge.model_dump())})

    def tip_bend(self, base: TipBendParams | None = None) -> TipBendParams:
        """The panel's bend; `base` carries the inward start, which the
        panel does not show."""
        base = base if base is not None else TipBendParams()
        return TipBendParams(length_to_bend_mm=self.bend_length.value(),
                             drop_angle_deg=self.bend_angle.value(),
                             bend_radius_mm=self.bend_radius.value(),
                             inward_angle_deg=self.bend_inward.value(),
                             inward_start_mm=base.inward_start_mm)

    def set_draft(self, draft: DraftParams, side_target: float,
                  tip_bend: TipBendParams | None = None) -> None:
        """Push the project's draft into the controls without emitting."""
        self._applying += 1
        try:
            widgets = (self.side, self.splay, self.kind, self.barrels, self.screw,
                       self.slant, self.stop, self.inset, self.butt_gap, self.bend_length,
                       self.bend_angle, self.bend_radius, self.bend_inward)
            for w in widgets:
                w.blockSignals(True)
            self.side.setValue(float(side_target))
            self.splay.setValue(float(draft.splay_deg))
            i = self.kind.findData(HingeKind(draft.hinge.kind).value)
            self.kind.setCurrentIndex(max(i, 0))
            i = self.barrels.findData(int(draft.hinge.barrels))
            self.barrels.setCurrentIndex(max(i, 0))
            if self.screw.findText(draft.hinge.screw_thread) >= 0:
                self.screw.setCurrentText(draft.hinge.screw_thread)
            self.slant.setValue(float(draft.hinge.slant_deg))
            self.stop.setValue(float(draft.hinge.open_deg))
            self.inset.setValue(float(draft.hinge.temple_inset_mm))
            self.butt_gap.setValue(float(draft.hinge.axis_offset_mm))
            if tip_bend is not None:
                self.bend_length.setValue(float(tip_bend.length_to_bend_mm))
                self.bend_angle.setValue(float(tip_bend.drop_angle_deg))
                self.bend_radius.setValue(float(tip_bend.bend_radius_mm))
                self.bend_inward.setValue(float(tip_bend.inward_angle_deg))
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._applying -= 1

    def set_readouts(self, asm) -> None:
        """What the assembly says: the hinge-alone angles and the butt cuts
        per side, the bend, and the checks."""
        if asm is None:
            self.side_readout.setText("")
            self.splay_readout.setText("")
            self.bend_readout.setText("")
            self.checks.setText("")
            return
        sides = asm.ordered_sides()
        if not sides:
            self.side_readout.setText("")
            self.splay_readout.setText("")
        else:
            self.side_readout.setText(" · ".join(
                f"{s.label}: hinge {s.side_from_hinge_deg:.1f}°, cut {s.panto_cut_deg:.1f}°"
                for s in sides))
            self.splay_readout.setText(" · ".join(
                f"{s.label}: hinge {s.splay_from_hinge_deg:.1f}°, cut {s.splay_cut_deg:.1f}°"
                for s in sides))
        bend = next((s.temple.bend for s in sides if s.temple is not None), None)
        if bend is None:
            self.bend_readout.setText("no temple drawn")
        elif bend.out_of_range():
            self.bend_readout.setText("out of range: " + bend.out_of_range())
        elif bend.is_straight:
            self.bend_readout.setText(f"straight · overall {bend.overall_mm:.1f} mm")
        else:
            spread = ""
            if asm.right is not None and asm.left is not None and asm.right.temple and asm.left.temple:
                spread = (f" · tips {float(asm.right.temple.tip[0] - asm.left.temple.tip[0]):.0f} mm "
                          f"apart, hinges {float(asm.right.axis_point[0] - asm.left.axis_point[0]):.0f}")
            self.bend_readout.setText(
                f"to bend {bend.length_to_bend_mm:.1f} · drop {bend.drop_mm:.1f} · "
                f"overall {bend.overall_mm:.1f} mm · tip {bend.tip_drop_mm:.1f} mm down{spread}")
        bad = [c for c in asm.checks if not c.ok]
        if not asm.checks:
            self.checks.setText("")
        elif not bad:
            self.checks.setText(f"✓ {len(asm.checks)} checks pass")
        else:
            self.checks.setText("⚠ " + "; ".join(f"{c.name}: {c.text}" for c in bad))
        self.checks.setToolTip("\n".join(("☑ " if c.ok else "☐ ") + f"{c.name}: {c.text}"
                                         for c in asm.checks))

    def set_readout(self, text: str) -> None:
        self.readout.setText(text)
