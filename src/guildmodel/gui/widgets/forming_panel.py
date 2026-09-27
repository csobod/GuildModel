"""The Forming panel (BUILDPLAN M18): press, base curve, face form, bridge,
die, crease blend.

A plain child frame of the main window, in the idiom of GuildDraw's snap
palette — non-modal, no window flags, open across operations until the
Forming view is toggled off. It sits under the 3D viewport rather than over
it: the viewport is a native GL window, and a Qt widget floated over one is
the kind of xcb-embedding delicacy `hidpi.py` exists to avoid.

The panel is *thin*, per the house rule: it turns controls into a
`FormingMetadata` and back and says when something moved. What a value means
for the part lives in `core.forming`; what to rebuild lives in the window.

Two signals for two speeds, exactly as the Model tab does it: `sliding` fires
with every intermediate value while a handle is held and `changed` once it
settles. The window binds the first straight to the warp — no debounce, no
worker — because the whole transform is well under the time VTK takes to
draw it. The spin boxes never refuse a typed value, per the M-N4 rule; the
ranges are the slider's, not the schema's.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QWidget)

from guildmodel.core.forming.presses import on_row
from guildmodel.core.forming import (CUSTOM_LABEL, FLAT_LABEL, ThermoformMap,
                                     find_press, matching_press, press_rows,
                                     radius_for)
from guildmodel.gui.widgets.param_slider import ParamSlider

#: Lens base curve on the slider, diopters, in the quarter steps a frame is
#: ordered in. 0 at the left end is flat; nobody orders a reverse curve, so
#: the range starts there. The SBT dies are tagged base 2, 3 and 4.
BASE_CURVE_RANGE = (0.0, 16.0)
BASE_CURVE_STEP = 0.25
#: Face form, degrees: 180 is flat; 150 is a hard wrap.
FACE_FORM_RANGE = (150.0, 180.0)
#: Bridge projection, mm, forward (away from the face). The die only ever
#: presses forward, so there is no negative projection.
PROJECTION_RANGE = (0.0, 8.0)
#: Distance between the two creases at the bridge's top edge, mm.
CREASE_GAP_RANGE = (4.0, 40.0)
#: The V plate's included angle, degrees: 0 is parallel creases.
CREASE_ANGLE_RANGE = (0.0, 120.0)
#: The V's centre line off the frame's axis, mm, for a bridge not drawn centred.
OFFSET_RANGE = (-10.0, 10.0)
#: The die's convex face, mm; 0 is Auto — the largest die that still reaches
#: the projection through the gap, which is the arc through both creases.
DIE_RADIUS_RANGE = (0.0, 40.0)
#: The fillet at each crease, mm; 0 is a sharp fold.
CREASE_BLEND_RANGE = (0.0, 5.0)


class FormingPanel(QFrame):

    #: A settled value: a preset picked, a handle released, a number typed,
    #: a checkbox flipped. The window writes it to the component and rebuilds.
    changed = Signal()
    #: A handle moving. The window re-warps and nothing else.
    sliding = Signal()
    #: A handle that moves the crease *layout* (gap, angle, offset, blend)
    #: moving: the window re-warps the uncut base rather than re-cutting the
    #: mesh on every tick; the release (`changed`) does it properly.
    layout_sliding = Signal()
    #: A layout handle was let go, moved or not (the window puts the cut
    #: front back after a drag that ended where it began).
    layout_released = Signal()
    #: The eyewire-groove override flipped: the flat base is rebuilt once.
    groove_toggled = Signal(bool)
    #: The flat ghost under the formed part.
    ghost_toggled = Signal(bool)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("formingPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._applying = 0            # >0 while a preset or a restore sets the sliders
        self._carried = (0.0, 0.0)    # (base curve, radius) the project came in with

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)

        # ---- row 0: press · base curve · face form -------------------------
        self.press = QComboBox()
        self.press.setToolTip(
            "The press the front will be formed on. Picking a row sets the base\n"
            "curve and the face form together, because on the press they come\n"
            "as a pair; touching either slider makes the choice Custom.\n"
            "Your own presses go in ~/.guildmodel/presses.yaml.")
        self.press.currentIndexChanged.connect(self._on_press_picked)
        grid.addWidget(QLabel("Press"), 0, 0)
        grid.addWidget(self.press, 0, 1)

        self.base_curve = ParamSlider(0.0, *BASE_CURVE_RANGE, step=BASE_CURVE_STEP,
                                      decimals=2, suffix=" D")
        self.base_curve.setSpecialValueText("Flat")
        self.base_curve.setToolTip(
            "Lens base curve, in diopters, in the quarter steps a frame is\n"
            "ordered in. 0 is flat. On a press row the die's own radius is\n"
            "used; elsewhere the optical convention, 530 / D. The radius in\n"
            "use is shown beside it.")
        self.radius_readout = QLabel("")
        self.radius_readout.setObjectName("mutedSmallLabel")
        self.radius_readout.setMinimumWidth(64)
        grid.addWidget(QLabel("Base curve"), 0, 2)
        grid.addWidget(self.base_curve, 0, 3)
        grid.addWidget(self.radius_readout, 0, 4)

        self.face_form = ParamSlider(180.0, *FACE_FORM_RANGE, step=0.5,
                                     decimals=2, suffix="°")
        self.face_form.setToolTip(
            "Face form: the included angle between the two eyewire planes,\n"
            "formed at the bridge center line. 180° is flat; the press forms\n"
            "164-175°. The wrap beside it is 180° minus this.")
        self.face_form_readout = QLabel("")
        self.face_form_readout.setObjectName("mutedSmallLabel")
        self.face_form_readout.setMinimumWidth(64)
        grid.addWidget(QLabel("Face form"), 0, 5)
        grid.addWidget(self.face_form, 0, 6)
        grid.addWidget(self.face_form_readout, 0, 7)

        # ---- row 1: the bridge — projection · crease gap · crease angle ---
        self.projection = ParamSlider(0.0, *PROJECTION_RANGE, step=0.5,
                                      decimals=1, suffix=" mm")
        self.projection.setToolTip(
            "Bridge projection: how far the convex die sets the bridge forward,\n"
            "away from the face, between the two creases. The die only presses\n"
            "forward; 0 leaves the bridge in the curve.")
        grid.addWidget(QLabel("Bridge projection"), 1, 0)
        grid.addWidget(self.projection, 1, 1)

        self.crease_gap = ParamSlider(20.0, *CREASE_GAP_RANGE, step=0.5,
                                      decimals=1, suffix=" mm")
        self.crease_gap.setToolTip(
            "Distance between the two creases at the bridge's top edge: the\n"
            "width of the V plate that braces the anterior while the die\n"
            "presses the posterior. Seeded from the drawing's bridge width.")
        grid.addWidget(QLabel("Crease gap"), 1, 2)
        grid.addWidget(self.crease_gap, 1, 3, 1, 2)

        self.crease_angle = ParamSlider(45.0, *CREASE_ANGLE_RANGE, step=1.0,
                                        decimals=0, suffix="°")
        self.crease_angle.setToolTip(
            "The V's included angle: how fast the two creases converge toward\n"
            "the nose, seen from the front. 0° keeps them parallel.")
        grid.addWidget(QLabel("Crease angle"), 1, 5)
        grid.addWidget(self.crease_angle, 1, 6, 1, 2)

        # ---- row 2: offset · die radius · crease blend ---------------------
        self.offset = ParamSlider(0.0, *OFFSET_RANGE, step=0.5, decimals=1,
                                  suffix=" mm")
        self.offset.setToolTip(
            "Bridge offset: the V's center line left or right of the frame's\n"
            "axis, for a bridge that is not drawn centered.")
        grid.addWidget(QLabel("Bridge offset"), 2, 0)
        grid.addWidget(self.offset, 2, 1)

        self.die_radius = ParamSlider(0.0, *DIE_RADIUS_RANGE, step=0.5,
                                      decimals=1, suffix=" mm")
        self.die_radius.setSpecialValueText("Auto")
        self.die_radius.setToolTip(
            "The radius of the anvil's convex face, pressed into the posterior\n"
            "bridge. Between the die and each crease the sheet runs straight,\n"
            "tangent to the die. Auto is the largest die that still reaches the\n"
            "projection through the gap: the arc through both creases. A die\n"
            "wider than that rests on the V plate before it reaches the\n"
            "projection, and the readout says so.")
        self.die_readout = QLabel("")
        self.die_readout.setObjectName("mutedSmallLabel")
        self.die_readout.setMinimumWidth(64)
        grid.addWidget(QLabel("Die radius"), 2, 2)
        grid.addWidget(self.die_radius, 2, 3)
        grid.addWidget(self.die_readout, 2, 4)

        self.crease_blend = ParamSlider(0.0, *CREASE_BLEND_RANGE, step=0.25,
                                        decimals=2, suffix=" mm")
        self.crease_blend.setSpecialValueText("Sharp")
        self.crease_blend.setToolTip(
            "Crease blend: the fillet where the bump meets the flat at each\n"
            "crease. Sharp is the fold the plate's edge leaves; a radius rounds\n"
            "it into the flat, as a softened plate edge or a relaxed sheet would.")
        grid.addWidget(QLabel("Crease blend"), 2, 5)
        grid.addWidget(self.crease_blend, 2, 6, 1, 2)

        # ---- row 3: groove · ghost · readout · export ----------------------
        tail = QWidget()
        row = QHBoxLayout(tail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.groove = QCheckBox("Eyewire groove")
        self.groove.setChecked(True)
        self.groove.setToolTip(
            "Build the formed front with the lens bevel groove, whether or not\n"
            "the cutting model has it on: the printed part is the finished\n"
            "piece. Uses the Model tab's groove dimensions.")
        self.groove.toggled.connect(self._on_groove)
        row.addWidget(self.groove)
        self.ghost = QCheckBox("Show flat ghost")
        self.ghost.setToolTip("Draw the flat part, translucent, under the formed one.")
        self.ghost.toggled.connect(self.ghost_toggled)
        row.addWidget(self.ghost)
        self.readout = QLabel("")
        self.readout.setObjectName("formingBadge")
        row.addWidget(self.readout, 1)
        self.export_btn = QPushButton("Export Formed STL…")
        self.export_btn.setToolTip(
            "Write the formed front — with the groove — as a watertight STL a\n"
            "slicer opens as one closed solid.")
        self.export_btn.clicked.connect(self.export_requested)
        row.addWidget(self.export_btn)
        grid.addWidget(tail, 3, 0, 1, 8)
        grid.setColumnStretch(3, 2)
        grid.setColumnStretch(6, 2)

        #: The handles whose motion changes where the creases are cut into
        #: the mesh; the others only move vertices.
        self._layout_handles = (self.crease_gap, self.crease_angle, self.offset,
                                self.crease_blend)
        self._handles = (self.base_curve, self.face_form, self.projection,
                         self.crease_gap, self.crease_angle, self.offset,
                         self.die_radius, self.crease_blend)
        for handle in self._handles:
            handle.valueChanged.connect(self._on_settled)
            if handle in self._layout_handles:
                handle.released.connect(self.layout_released)
            handle.sliding.connect(
                self._on_layout_sliding if handle in self._layout_handles
                else self._on_sliding)

        self.set_presses()
        self._refresh_readouts()

    # ------------------------------------------------------------ presses

    def set_presses(self, rows=None) -> None:
        """(Re)fill the press combo: Flat, the rows, Custom. Keeps the current
        choice by label where it still exists."""
        rows = list(press_rows()) if rows is None else list(rows)
        current = self.press.currentText()
        self._applying += 1
        try:
            self.press.blockSignals(True)
            self.press.clear()
            self.press.addItem(FLAT_LABEL)
            for p in rows:
                self.press.addItem(p.label)
            self.press.addItem(CUSTOM_LABEL)
            i = self.press.findText(current)
            self.press.setCurrentIndex(i if i >= 0 else 0)
        finally:
            self.press.blockSignals(False)
            self._applying -= 1

    def _on_press_picked(self, _index: int) -> None:
        if self._applying:
            return
        label = self.press.currentText()
        if label == CUSTOM_LABEL:
            return                      # the sliders already say what they say
        self._applying += 1
        try:
            if label == FLAT_LABEL:
                self.base_curve.setValue(0.0)
                self.face_form.setValue(180.0)
            else:
                p = find_press(label)
                if p is None:
                    return
                self.base_curve.setValue(p.base_curve)
                self.face_form.setValue(p.face_form_deg)
        finally:
            self._applying -= 1
        self._refresh_readouts()
        self.changed.emit()

    def _name_the_press(self) -> None:
        """Point the combo at whatever row the sliders now describe, or Custom.
        Never emits: this runs *because* a slider moved."""
        d, f = self.base_curve.value(), self.face_form.value()
        if d <= 0.0 and f >= 180.0:
            label = FLAT_LABEL
        else:
            p = matching_press(d, f)
            label = p.label if p is not None else CUSTOM_LABEL
        i = self.press.findText(label)
        if i >= 0 and i != self.press.currentIndex():
            self.press.blockSignals(True)
            self.press.setCurrentIndex(i)
            self.press.blockSignals(False)

    # ------------------------------------------------------------ sliders

    def _on_sliding(self, _v: float) -> None:
        self._refresh_readouts()
        self.sliding.emit()

    def _on_layout_sliding(self, _v: float) -> None:
        self._refresh_readouts()
        self.layout_sliding.emit()

    def _on_settled(self, _v: float) -> None:
        if self._applying:
            return
        self._name_the_press()
        self._refresh_readouts()
        self.changed.emit()

    def _on_groove(self, on: bool) -> None:
        if self._applying:
            return
        self.groove_toggled.emit(bool(on))
        self.changed.emit()

    def _radius_in_use(self) -> float:
        """The radius the map bends to: the named row's die, else the project's
        own while its curve is unmoved, else 530 / D."""
        d = self.base_curve.value()
        if d <= 0.0:
            return 0.0
        row = self._row_in_use()
        return row.radius_mm if row is not None else self._custom_radius(d)

    def _row_in_use(self):
        """The press row the sliders are on: the combo's row, while the
        sliders still read its values. A base-curve drag off a row leaves the
        row's die behind at once — the part moved only on release before,
        when the combo was renamed Custom — and the combo follows at release."""
        label = self.press_label()
        row = find_press(label) if label else None
        if row is None or not on_row(row, self.base_curve.value(), self.face_form.value()):
            return None
        return row

    def _custom_radius(self, d: float) -> float:
        """The radius for a base curve on no press row.

        The one the project carried, while the curve slider still reads the
        curve it was saved at: a press row that has since been deleted,
        renamed or edited in ``~/.guildmodel/presses.yaml``, or that was never
        installed on this machine, keeps bending to its own die rather than
        snapping to 530 / D on open — which put the preview and the export on
        different radii and rewrote the project on the first slider touch.
        Once the maker moves the curve the convention is the only radius there
        is."""
        carried_d, carried_r = self._carried
        if carried_r > 0.0 and abs(d - carried_d) < 1e-9:
            return carried_r
        return radius_for(d)

    def _die_in_use(self) -> float:
        """The die radius the map uses: the named one, else Auto's for this
        gap and projection (`ThermoformMap.auto_die_radius`)."""
        d = self.die_radius.value()
        if d > 0.0:
            return float(d)
        return ThermoformMap.auto_die_radius(self.crease_gap.value(),
                                             self.projection.value())

    def _refresh_readouts(self) -> None:
        r = self._radius_in_use()
        self.radius_readout.setText(f"R {r:.0f} mm" if r > 0 else "flat")
        wrap = 180.0 - self.face_form.value()
        self.face_form_readout.setText(f"{wrap:.0f}° wrap" if wrap > 0 else "flat")
        die = self._die_in_use()
        if self.projection.value() == 0.0 or not die < float("inf"):
            self.die_readout.setText("")
        elif self.die_radius.value() > 0.0:
            self.die_readout.setText("")
        else:
            self.die_readout.setText(f"R {die:.1f} mm")

    # ---------------------------------------------------------- the model

    def press_label(self) -> str:
        """The preset the controls are on, "" for Flat or Custom."""
        label = self.press.currentText()
        return "" if label in (FLAT_LABEL, CUSTOM_LABEL) else label

    def forming(self, base):
        """`base` (a component's `FormingMetadata`) with the panel's values.
        A copy: the drawing's own fields ride along untouched."""
        label = self.press_label()
        row = self._row_in_use()
        d = float(self.base_curve.value())
        return base.with_base_curve(
            d, self.face_form.value(),
            radius_mm=row.radius_mm if row is not None else self._custom_radius(d),
            bridge_projection_mm=float(self.projection.value()),
            crease_gap_mm=float(self.crease_gap.value()),
            crease_angle_deg=float(self.crease_angle.value()),
            bridge_offset_mm=float(self.offset.value()),
            die_radius_mm=float(self.die_radius.value()),
            crease_blend_mm=float(self.crease_blend.value()),
            formed_groove=self.groove.isChecked(),
            press_preset=label)

    def set_forming(self, forming) -> None:
        """Push a component's forming into the controls without emitting."""
        self._carried = (float(forming.base_curve), float(forming.base_radius_mm))
        self._applying += 1
        try:
            for w in (*self._handles, self.groove):
                w.blockSignals(True)
            self.base_curve.setValue(float(forming.base_curve))
            self.face_form.setValue(180.0 - float(forming.face_form_wrap_deg))
            self.projection.setValue(float(forming.bridge_projection_mm))
            if forming.crease_gap_mm > 0.0:
                self.crease_gap.setValue(float(forming.crease_gap_mm))
            self.crease_angle.setValue(float(forming.crease_angle_deg))
            self.offset.setValue(float(forming.bridge_offset_mm))
            self.die_radius.setValue(float(getattr(forming, "die_radius_mm", 0.0)))
            self.crease_blend.setValue(float(getattr(forming, "crease_blend_mm", 0.0)))
            self.groove.setChecked(bool(forming.formed_groove))
            label = forming.press_preset or ""
            if label and self.press.findText(label) >= 0:
                self.press.blockSignals(True)
                self.press.setCurrentIndex(self.press.findText(label))
                self.press.blockSignals(False)
            else:
                self._name_the_press()
        finally:
            for w in (*self._handles, self.groove):
                w.blockSignals(False)
            self._applying -= 1
        self._refresh_readouts()

    def set_readout(self, text: str) -> None:
        self.readout.setText(text)

    def set_export_enabled(self, on: bool) -> None:
        self.export_btn.setEnabled(bool(on))
