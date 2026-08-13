"""The slider you can also type into (BUILDPLAN-NEW M-N4).

Two ranges, and the whole design turns on what happens between them. The slider
travels the *safe* range `core.project.limits` derives, so dragging cannot ask
for a frame that will not build. The spin box keeps the *hard* range the schema
means, so an exact number is never refused — and, the part that is easy to get
wrong, never silently rewritten either.

That last one is not hypothetical. The first version of `set_safe_range` did
rewrite: `QSlider.setRange` clamps its own value into the new range and emits
`valueChanged` doing it, which came back through the sync and wrote the clamp
into the spin box. Tightening the nosepad ceiling to 6 mm quietly shortened a
10 mm tower. `test_narrowing_the_range_never_moves_the_value` is that bug.

The rest are the cross-platform promises the module docstring makes, which are
worth pinning precisely because they are corrections to a platform default and
nothing on this machine would notice them regressing.
"""
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPoint, QPointF, Qt      # noqa: E402
from PySide6.QtGui import QWheelEvent               # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def slider(qt_app):
    from guildmodel.gui.widgets.param_slider import ParamSlider

    return ParamSlider(5.0, 0.0, 10.0, step=0.1, decimals=1)


# ------------------------------------------------------------ the two ranges

def test_the_handle_travels_the_safe_range_and_the_box_keeps_the_hard_one(slider):
    slider.set_safe_range(2.0, 6.0, "the stock says so")
    assert slider.hard_range() == (0.0, 10.0)
    assert slider.safe_range() == (2.0, 6.0)
    assert slider.spin.minimum() == pytest.approx(0.0)
    assert slider.spin.maximum() == pytest.approx(10.0)

    slider.slider.setValue(slider.slider.maximum())
    assert slider.value() == pytest.approx(6.0)
    slider.slider.setValue(slider.slider.minimum())
    assert slider.value() == pytest.approx(2.0)


def test_narrowing_the_range_never_moves_the_value(slider):
    """The bug this widget was rewritten for. A safe range is a statement about
    what fits, not permission to edit the maker's number."""
    slider.setValue(9.0)
    seen = []
    slider.valueChanged.connect(seen.append)

    slider.set_safe_range(0.0, 6.0, "smaller stock")

    assert slider.value() == pytest.approx(9.0)
    assert seen == []


def test_a_value_outside_the_safe_range_is_marked_not_corrected(slider):
    slider.setValue(9.0)
    slider.set_safe_range(0.0, 6.0, "a 6 mm blank")

    assert slider.out_of_range()
    assert not slider.mark.isHidden()
    assert "6 mm blank" in slider.mark.toolTip()
    assert slider.slider.value() == slider.slider.maximum()   # pinned, not moved


def test_typing_a_value_the_slider_cannot_reach_is_allowed(slider):
    """Exact entry is the reason the spin box keeps the hard range: a maker who
    is about to change the stock should be able to type the tower first."""
    slider.set_safe_range(0.0, 6.0, "for now")
    slider.setValue(8.5)
    assert slider.value() == pytest.approx(8.5)
    assert slider.out_of_range()


def test_moving_the_handle_brings_an_out_of_range_value_back(slider):
    slider.setValue(9.0)
    slider.set_safe_range(0.0, 6.0, "a 6 mm blank")
    slider.slider.setValue(40)
    assert slider.value() == pytest.approx(4.0)
    assert not slider.out_of_range()
    assert slider.mark.isHidden()


def test_a_rule_nothing_survives_collapses_to_a_point_not_an_inverted_range(slider):
    slider.set_safe_range(8.0, 2.0, "impossible")
    low, high = slider.safe_range()
    assert low <= high


def test_the_safe_range_cannot_exceed_the_hard_one(slider):
    slider.set_safe_range(-5.0, 99.0, "wishful")
    assert slider.safe_range() == (0.0, 10.0)


# -------------------------------------------------------------- the signals

def test_a_drag_reports_live_and_commits_once(slider):
    """`sliding` is every intermediate value; `valueChanged` is the settled one.

    Kept apart so a drag cannot start one model rebuild per pixel — the panel
    connects the second and, for now, nothing connects the first.
    """
    live, committed = [], []
    slider.sliding.connect(live.append)
    slider.valueChanged.connect(committed.append)

    slider.slider.sliderPressed.emit()
    for tick in (55, 60, 65, 70):
        slider.slider.setValue(tick)
    slider.slider.sliderReleased.emit()

    assert live == [5.5, 6.0, 6.5, 7.0]
    assert committed == [7.0]


def test_a_keystroke_or_a_wheel_settles_immediately(slider):
    live, committed = [], []
    slider.sliding.connect(live.append)
    slider.valueChanged.connect(committed.append)

    slider.slider.setValue(80)          # no press: an arrow key or a wheel notch
    assert live == []
    assert committed == [8.0]


def test_a_click_that_moves_nothing_is_not_an_edit(slider):
    committed = []
    slider.valueChanged.connect(committed.append)
    slider.slider.sliderPressed.emit()
    slider.slider.sliderReleased.emit()
    assert committed == []


def test_blocking_signals_still_keeps_the_handle_in_step(slider):
    """`set_castle_params` restores three dozen values this way. The handle has
    to follow even though nothing is told about it."""
    committed = []
    slider.valueChanged.connect(committed.append)

    slider.blockSignals(True)
    slider.setValue(7.5)
    slider.blockSignals(False)

    assert committed == []
    assert slider.value() == pytest.approx(7.5)
    assert slider.slider.value() == 75


# ------------------------------------------------------- cross-platform work

def test_a_click_on_the_groove_jumps_there_on_every_platform(slider):
    """macOS jumps natively, Fusion pages by one step. Paging is the wrong idiom
    for a continuous measurement, so `_JumpSlider` makes all three jump.

    Checked by clicking near the right-hand end: a jump lands close to the
    maximum, a page-step moves one tenth of a millimeter and would fail.
    """
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent

    slider.resize(240, 28)
    slider.slider.resize(200, 28)
    slider.setValue(1.0)

    x = slider.slider.width() - 6
    slider.slider.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, 14), QPointF(x, 14),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))

    assert slider.value() > 8.0, "the click paged instead of jumping"
    assert slider.slider.isSliderDown(), "a jump starts a drag, so it can be dragged on"


def test_an_unfocused_wheel_goes_to_the_scrolling_panel(slider):
    """Both children live in a scroll area, and Qt's default focus policy for a
    slider and a spin box is WheelFocus — one unlucky scroll down the Model tab
    would otherwise rewrite whatever number was under the pointer."""
    assert slider.slider.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert slider.spin.focusPolicy() == Qt.FocusPolicy.StrongFocus

    for child in (slider.slider, slider.spin):
        child.clearFocus()
        event = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        child.wheelEvent(event)
        assert not event.isAccepted(), child


def test_typing_fires_once_per_number_not_once_per_digit(slider):
    """`keyboardTracking` off. Entering "12.5" is one edit; with it on, each
    digit is a value and each value would start a rebuild."""
    assert slider.spin.keyboardTracking() is False


def test_the_box_is_wide_enough_for_its_own_widest_number(qt_app):
    """Sized from font metrics rather than pixels: macOS renders this panel in a
    wider face than KDE does, and a hard-coded width clips there."""
    from guildmodel.gui.widgets.param_slider import ParamSlider

    wide = ParamSlider(170.0, 50.0, 300.0, step=1.0, decimals=1)
    narrow = ParamSlider(1.0, 0.0, 9.0, step=0.1, decimals=1)
    assert wide.spin.width() > narrow.spin.width()
    assert wide.spin.width() >= wide.spin.fontMetrics().horizontalAdvance("300.0 mm")


@pytest.mark.parametrize("decimals,step,typed", [(1, 0.1, 4.3), (2, 0.05, 1.25),
                                                 (4, 0.0125, 6.5125)])
def test_the_handle_resolves_every_value_the_box_can_hold(qt_app, decimals, step, typed):
    """The slider is an integer control underneath. Its tick has to be the spin
    box's last decimal place or dragging would quantise away digits the maker
    typed — the base-curve blank runs to four."""
    from guildmodel.gui.widgets.param_slider import ParamSlider

    s = ParamSlider(1.0, 0.0, 20.0, step=step, decimals=decimals)
    s.setValue(typed)
    assert s.value() == pytest.approx(typed)
    assert s.slider.value() == round(typed * 10 ** decimals)
