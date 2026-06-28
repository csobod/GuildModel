"""M5.2 tests: the readiness traffic-light (BUILDPLAN § M5.2).

The state machine is a pure function (``readiness_dot.state_for``) so the
grey → red → yellow → green walk and the stale-program revert are tested
without Qt; the dot widget itself (tooltips, theme recolor) is exercised by a
construction check that skips when no Qt platform plugin is available.
"""
import pytest

from guildmodel.gui.widgets import readiness_dot as rd


# ------------------------------------------------------------ state machine

def test_off_when_no_dxf():
    # No DXF: grey regardless of the other flags (they cannot be true anyway).
    assert rd.state_for(False, False, False) == rd.OFF
    assert rd.state_for(False, True, True) == rd.OFF


def test_red_dxf_only():
    assert rd.state_for(True, False, False) == rd.RED


def test_yellow_model_built():
    assert rd.state_for(True, True, False) == rd.YELLOW


def test_green_program_stored():
    assert rd.state_for(True, True, True) == rd.GREEN
    # A stored program outranks a not-yet-rebuilt preview mesh (reopened job).
    assert rd.state_for(True, False, True) == rd.GREEN


def test_stale_program_reverts_to_yellow():
    """The green→yellow drop is just program_stored going False with the
    model still built (the M5.2 stale-program guard)."""
    assert rd.state_for(True, True, True) == rd.GREEN
    assert rd.state_for(True, True, False) == rd.YELLOW


def test_workflow_walk():
    """grey → red → yellow → green across the real workflow order."""
    walk = [
        rd.state_for(False, False, False),  # start
        rd.state_for(True, False, False),   # DXF imported
        rd.state_for(True, True, False),    # 3D built
        rd.state_for(True, True, True),     # program saved to .gmodel
    ]
    assert walk == [rd.OFF, rd.RED, rd.YELLOW, rd.GREEN]


# ------------------------------------------------------------ exact tooltips

def test_tooltip_wording_is_exact():
    # BUILDPLAN M5.2 specifies this wording verbatim — do not reword.
    assert rd.TOOLTIPS[rd.RED] == "DXF Loaded, Missing 3D Model + G-Code"
    assert rd.TOOLTIPS[rd.YELLOW] == "Model Built, Missing G-Code"
    assert rd.TOOLTIPS[rd.GREEN] == "Ready for Transmission"


# ------------------------------------------------------------ theme colors

def test_each_state_has_a_distinct_color_in_both_themes():
    from guildmodel.gui.style import theme

    for dark in (False, True):
        pal = theme.palette(dark)
        colors = {pal.ready_off, pal.ready_red, pal.ready_yellow, pal.ready_green}
        assert len(colors) == 4, f"states share a color (dark={dark})"


# ------------------------------------------------------------ widget (Qt)

def test_dot_widget_tooltip_and_state_track():
    """The dot maps every state to its tooltip and recolors per theme.
    Skipped where no Qt platform plugin is available (headless CI)."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    try:
        app = QApplication.instance() or QApplication([])
    except Exception:  # pragma: no cover - no platform plugin
        pytest.skip("no Qt platform plugin")

    dot = rd.ReadinessDot()
    assert dot.state() == rd.OFF
    for state in (rd.RED, rd.YELLOW, rd.GREEN, rd.OFF):
        dot.set_state(state)
        assert dot.state() == state
        assert dot.toolTip() == rd.TOOLTIPS[state]

    # Theme recolor is non-throwing and the dot stays subtle (~10 px glyph).
    dot.set_dark_mode(True)
    dot.set_dark_mode(False)
    assert dot.sizeHint().width() <= 20

    with pytest.raises(ValueError):
        dot.set_state("chartreuse")
