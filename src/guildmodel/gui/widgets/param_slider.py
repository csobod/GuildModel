"""A slider you can also type into, with two ranges instead of one.

Every number on the Model and Stock tabs used to be a bare ``QDoubleSpinBox``:
exact, but you cannot *feel* a frame that way. A footing radius or an eyewire
height wants to be dragged — the shape is the point, and the number is how you
record the shape you found.

**Why two ranges.** A parameter has a range because of what it *means* — an
eyewire wall is between half a millimeter and twelve — and a narrower range
because of the job in front of you: a nosepad tower cannot be 12 mm tall when
the stock is a 6 mm blank under a 4 mm pad block, and a hinge pocket cannot be
deeper than the endpiece it is sunk into or it punches through the front of the
frame. The first is the **hard** range and it belongs to the schema. The second
is the **safe** range, `core.project.limits` derives it from the rest of the
project, and it moves whenever the stock or a neighboring parameter moves.

The slider travels the safe range; the spin box keeps the hard one. So dragging
can never build something impossible, and typing is never silently refused or
silently rewritten — a value outside the safe range is *kept*, flagged with a
marker whose tooltip says which rule it broke, and the handle pins to that end
of its travel. That split matters most on load: opening a project whose nosepad
no longer fits its stock must tell the maker, not quietly shorten the tower.

**Cross-platform behavior is specified here rather than inherited**, because
Qt's defaults for a slider differ by style and this application ships on three
desktops:

  * *Click on the groove jumps to that spot.* macOS does this natively, the
    Fusion style used on Linux and Windows pages by one step instead. Paging is
    the wrong idiom for a continuous measurement, so all three jump.
  * *The wheel only turns a control that has focus.* Both children sit inside a
    scrolling tab. Qt's default focus policy for a slider and a spin box is
    ``WheelFocus``, which means an unlucky scroll down the panel silently
    rewrites whatever number happened to be under the pointer. They take focus
    on click or tab, and an unfocused wheel event goes to the scroll area.
  * *Widths come from the font, not from pixels.* macOS renders the same panel
    in a wider face than KDE does; a hard-coded spin-box width clips there.
  * *Typing does not fire until it is finished.* ``keyboardTracking`` is off, so
    entering "12.5" is one edit rather than the three the digits would make —
    each of which would otherwise start a model rebuild.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QDoubleSpinBox, QHBoxLayout,
                               QLabel, QSizePolicy, QSlider, QStyle,
                               QStyleOptionSlider, QWidget)

#: Shown next to a value that sits outside its safe range. A character rather
#: than a color, so it survives both themes and a monochrome display.
OUT_OF_RANGE_MARK = "⚠"

#: The slider never gets narrower than this many average character widths, so
#: the dock can be dragged small without the handle losing its travel.
_MIN_SLIDER_CHARS = 8

#: Extra character widths beyond the longest number the spin box can show.
#: Covers the suffix's leading space, the up/down buttons, and the frame.
_SPIN_PADDING_CHARS = 5


class _JumpSlider(QSlider):
    """A horizontal slider that jumps to a click and ignores an unfocused wheel.

    Both are corrections to a *platform* default rather than to Qt: see this
    module's docstring. The jump is implemented against the style's own
    sub-control rectangles so it lands where the handle would be drawn, which
    is the only way to get it right under an arbitrary stylesheet.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _handle_holds(self, pos) -> bool:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        return rect.contains(pos)

    def _value_at(self, x: int) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        span = groove.width() - handle.width()
        if span <= 0:
            return self.value()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(),
            x - groove.x() - handle.width() // 2, span, opt.upsideDown)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and not self._handle_holds(event.position().toPoint())):
            self.setSliderDown(True)          # emits sliderPressed
            self.setSliderPosition(self._value_at(int(event.position().x())))
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self.hasFocus():
            event.ignore()                    # let the scroll area have it
            return
        super().wheelEvent(event)


class _QuietSpinBox(QDoubleSpinBox):
    """A spin box that does not steal the wheel while the panel is scrolling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class ParamSlider(QWidget):
    """One measured parameter: a slider over its safe range, a spin box over its
    hard one, and a marker when the two disagree.

    Drop-in for the ``QDoubleSpinBox`` this panel used before it — ``value``,
    ``setValue``, ``setToolTip``, ``setSpecialValueText`` and ``blockSignals``
    all mean what they meant, and ``valueChanged`` still carries a float.
    """

    #: A settled value: released the handle, finished typing, arrow, or wheel.
    valueChanged = Signal(float)
    #: Every intermediate value while the handle is held. Nothing connects this
    #: yet; it is the seam a live-continuous preview attaches to, kept separate
    #: so a drag cannot start one model rebuild per pixel by accident.
    sliding = Signal(float)

    def __init__(
        self,
        value: float,
        min_: float,
        max_: float,
        step: float = 0.1,
        decimals: int = 2,
        suffix: str = " mm",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("paramSlider")
        self._scale = 10 ** int(decimals)
        self._hard = (float(min_), float(max_))
        self._safe = (float(min_), float(max_))
        self._reason = ""
        self._syncing = False
        self._dragging = False
        self._pressed_at = float(value)

        self.spin = _QuietSpinBox()
        self.spin.setRange(float(min_), float(max_))
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)   # one edit per number, not per digit
        self.spin.setAccelerated(True)
        self.spin.setGroupSeparatorShown(False)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.spin.setValue(float(value))

        self.slider = _JumpSlider()
        self.slider.setSingleStep(max(1, round(step * self._scale)))
        self.slider.setPageStep(max(1, round(step * self._scale) * 10))
        self._apply_slider_range()

        self.mark = QLabel(OUT_OF_RANGE_MARK)
        self.mark.setObjectName("outOfRangeMark")
        self.mark.hide()

        self._size_children()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.slider, 1)
        row.addWidget(self.mark, 0)
        row.addWidget(self.spin, 0)

        self.spin.valueChanged.connect(self._on_spin)
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderPressed.connect(self._on_press)
        self.slider.sliderReleased.connect(self._on_release)
        self._sync_slider()

    # ------------------------------------------------------------- geometry

    def _size_children(self) -> None:
        """Width from font metrics, so the same panel fits on every desktop.

        The special-value text counts: "(constant)" on the edge feature's taper
        is longer than any number that control can show, and sizing to the
        numbers alone clips the word that explains what the control is doing.
        """
        fm = self.spin.fontMetrics()
        em = max(1, fm.horizontalAdvance("0"))
        widest = max(len(self.spin.textFromValue(self._hard[0])),
                     len(self.spin.textFromValue(self._hard[1])))
        chars = widest + len(self.spin.suffix()) + _SPIN_PADDING_CHARS
        special = self.spin.specialValueText()
        if special:
            chars = max(chars, len(special) + _SPIN_PADDING_CHARS)
        self.spin.setFixedWidth(em * chars)
        self.slider.setMinimumWidth(em * _MIN_SLIDER_CHARS)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        self.spin.setSizePolicy(QSizePolicy.Policy.Fixed,
                                QSizePolicy.Policy.Fixed)

    def _apply_slider_range(self) -> None:
        """Narrowing the travel must not move the value.

        Guarded, because ``QSlider.setRange`` clamps its own value into the new
        range and emits ``valueChanged`` doing it — which reached `_on_slider`
        and wrote the clamp straight back into the spin box. Tightening the
        nosepad's ceiling to 6 mm silently shortened a 10 mm tower to 6, the one
        behavior `set_safe_range` exists to prevent, and it took a stock change
        on a loaded frame to show it.
        """
        lo, hi = self._safe
        self._syncing = True
        try:
            self.slider.setRange(round(lo * self._scale), round(hi * self._scale))
        finally:
            self._syncing = False

    # ------------------------------------------------------------ the ranges

    def hard_range(self) -> tuple[float, float]:
        return self._hard

    def safe_range(self) -> tuple[float, float]:
        return self._safe

    def out_of_range(self) -> bool:
        """True when the current value is outside what the project allows."""
        lo, hi = self._safe
        v = self.spin.value()
        eps = 0.5 / self._scale
        return v < lo - eps or v > hi + eps

    def set_safe_range(self, low: float, high: float, reason: str = "") -> None:
        """Restrict the slider's travel to ``[low, high]``, explained by ``reason``.

        Never touches the value. A value already outside is kept and marked —
        the maker is told their nosepad no longer fits the stock; the tower is
        not shortened behind their back.
        """
        lo = max(float(low), self._hard[0])
        hi = min(float(high), self._hard[1])
        if hi < lo:                    # nothing survives the rule; say so with
            hi = lo                    # a single point rather than an inverted range
        if (lo, hi, reason) == (*self._safe, self._reason):
            return
        self._safe = (lo, hi)
        self._reason = reason
        self._apply_slider_range()
        self._sync_slider()
        self._refresh_mark()

    def clear_safe_range(self) -> None:
        self.set_safe_range(*self._hard, "")

    def _refresh_mark(self) -> None:
        bad = self.out_of_range()
        self.mark.setVisible(bad)
        if bad:
            lo, hi = self._safe
            why = self._reason or "outside the range this project allows"
            self.mark.setToolTip(
                f"{self.spin.value():g} is outside {lo:g}–{hi:g} — {why}")

    # ------------------------------------------------------------- the value

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float) -> None:  # noqa: N802
        self.spin.setValue(float(v))

    def setRange(self, low: float, high: float) -> None:  # noqa: N802
        """Move the *hard* range. The safe range is reset to match it."""
        self._hard = (float(low), float(high))
        self.spin.setRange(float(low), float(high))
        self._safe, self._reason = self._hard, ""
        self._size_children()
        self._apply_slider_range()
        self._sync_slider()
        self._refresh_mark()

    def setSpecialValueText(self, text: str) -> None:  # noqa: N802
        self.spin.setSpecialValueText(text)
        self._size_children()

    def setSuffix(self, text: str) -> None:  # noqa: N802
        self.spin.setSuffix(text)
        self._size_children()

    def setToolTip(self, text: str) -> None:  # noqa: N802
        super().setToolTip(text)
        self.slider.setToolTip(text)
        self.spin.setToolTip(text)

    def setFocus(self) -> None:  # noqa: N802
        self.spin.setFocus()

    # ------------------------------------------------------------ the wiring

    def _sync_slider(self) -> None:
        """Put the handle where the value is, pinned to the end of its travel
        when the value has left the safe range."""
        self._syncing = True
        try:
            self.slider.setValue(
                max(self.slider.minimum(),
                    min(self.slider.maximum(),
                        round(self.spin.value() * self._scale))))
        finally:
            self._syncing = False

    def _on_spin(self, v: float) -> None:
        # `_syncing` means the slider is already mid-handling this same value.
        # Without the guard a drag emitted `valueChanged` once per pixel through
        # here — one full model rebuild per tick — which is precisely what
        # keeping `sliding` separate was for.
        if self._syncing:
            return
        self._sync_slider()
        self._refresh_mark()
        self.valueChanged.emit(v)

    def _on_slider(self, ticks: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.spin.setValue(ticks / self._scale)
        finally:
            self._syncing = False
        self._refresh_mark()
        if self._dragging:
            self.sliding.emit(self.spin.value())
        else:
            self.valueChanged.emit(self.spin.value())

    def _on_press(self) -> None:
        self._dragging = True
        self._pressed_at = self.spin.value()

    def _on_release(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        # A click that lands where the handle already was is not an edit, and a
        # rebuild is too expensive to spend on one.
        if self.spin.value() != self._pressed_at:
            self.valueChanged.emit(self.spin.value())
