"""Tooltips wrap and can be switched off; a typed number settles when the
typing is done (2026-09-27)."""
import json

import pytest


def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


LONG = ("Copy this tab's settings to the other temple: blank, snap and stock side, "
        "hinge pocket depth and angle, engraving, tools, onion skin, hand allowance "
        "and holding. Each temple keeps its own program zero.")


def _tip_labels(app):
    return [w for w in app.topLevelWidgets()
            if w.metaObject().className() == "QTipLabel" and w.isVisible()]


# ------------------------------------------------------------------ wrapping

def test_a_plain_tooltip_becomes_wrapped_rich_text(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from PySide6.QtGui import QFont, QFontMetrics
    from guildmodel.gui.tooltips import format_tooltip, LINE_CHARS
    fm = QFontMetrics(QFont())
    out = format_tooltip(LONG, fm)
    assert "<" not in out                                    # plain text, Qt's own breaks off
    lines = out.split("\n")
    assert len(lines) >= 3
    limit = fm.averageCharWidth() * LINE_CHARS
    assert all(fm.horizontalAdvance(line) <= limit for line in lines)
    widths = [fm.horizontalAdvance(line) for line in lines[:-1]]
    assert max(widths) - min(widths) < limit * 0.35          # balanced, not ragged
    assert "".join(out.split()) == "".join(LONG.split())     # every character kept
    # a hand-wrapped line reflows; a blank line, a colon or a bullet keeps its break
    assert format_tooltip("a\nb", fm) == "a b"
    assert format_tooltip("a\n\nb", fm) == "a\n\nb"
    assert format_tooltip("Uses:\n\u2022 one\n\u2022 two", fm) == "Uses:\n\u2022 one\n\u2022 two"
    assert format_tooltip("<b>rich</b>", fm) == "<b>rich</b>"
    assert format_tooltip("", fm) == ""


def test_the_filter_shows_a_narrow_tip_and_swallows_when_off(tmp_path, monkeypatch):
    app = _qt(monkeypatch, tmp_path)
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton, QToolTip
    from guildmodel.gui.tooltips import TooltipFilter, LINE_CHARS
    btn = QPushButton("b")
    btn.setToolTip(LONG)
    btn.show()
    app.processEvents()
    filt = TooltipFilter(enabled=True)
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), btn.mapToGlobal(QPoint(5, 5)))
    assert filt.eventFilter(btn, ev) is True
    app.processEvents()
    tips = _tip_labels(app)
    assert tips, "the wrapped tip was not shown"
    fm = btn.fontMetrics()
    assert tips[0].width() <= fm.averageCharWidth() * LINE_CHARS * 1.3
    assert tips[0].height() > fm.height() * 2                # it wrapped
    QToolTip.hideText()
    QTest.qWait(600)                                        # the tip fades on a timer
    assert not _tip_labels(app)

    filt.enabled = False
    assert filt.eventFilter(btn, ev) is True                # swallowed
    QTest.qWait(100)
    assert not _tip_labels(app)
    filt.set_exempt([btn])
    assert filt.eventFilter(btn, ev) is True                # exempt: shown even when off
    QTest.qWait(100)
    assert _tip_labels(app)
    QToolTip.hideText()
    QTest.qWait(600)
    # anything but a tooltip event passes straight through
    assert filt.eventFilter(btn, QEvent(QEvent.Type.Resize)) is False


# ------------------------------------------------------------------ typing

def test_a_typed_feed_settles_on_enter_not_per_keystroke(tmp_path, monkeypatch):
    app = _qt(monkeypatch, tmp_path)
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.show()
    app.processEvents()
    fired = []
    p.cam_changed.connect(lambda: fired.append(1))
    for box in (p.tool_feed_rows()["flat_3175"].feed, p.spindle_override,
                p.ov_spindle, p.block_hole_count, p.hold_tab_count):
        assert box.keyboardTracking() is False, box
    row = p.tool_feed_rows()["flat_3175"]
    row.feed.setFocus()
    row.feed.selectAll()
    QTest.keyClicks(row.feed, "1500")
    assert fired == []                                       # nothing while typing
    QTest.keyClick(row.feed, Qt.Key.Key_Return)
    assert len(fired) == 1
    assert p.cam_params().tool_feeds["flat_3175"].feed_rate_mmpm == 1500.0


def test_the_preferences_editors_settle_on_commit_too(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QAbstractSpinBox
    from guildmodel.gui import prefs as prefs_mod
    from guildmodel.gui.app import PrefsDialog
    dlg = PrefsDialog(dict(prefs_mod.DEFAULTS))
    boxes = dlg.findChildren(QAbstractSpinBox)
    assert boxes
    assert all(not b.keyboardTracking() for b in boxes)


# ------------------------------------------------------------------ the window

@pytest.mark.gui
def test_the_question_mark_ends_the_toolbar_and_switches_tooltips(tmp_path, monkeypatch):
    app = _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox, QToolButton
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    try:
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    acts = win._toolbar.actions()
    assert acts[-1] is win._act_tooltips                     # last, past the spacer
    assert not win._act_tooltips.icon().isNull()
    btn = win._toolbar.widgetForAction(win._act_tooltips)
    assert isinstance(btn, QToolButton) and btn in win._tooltip_filter._exempt
    assert win._tooltip_filter.enabled is True and win._act_tooltips.isChecked()

    win._act_tooltips.trigger()                             # off
    assert win._tooltip_filter.enabled is False
    assert win._prefs["tooltips"] is False
    assert json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))["tooltips"] is False
    assert "off" in win._act_tooltips.toolTip()
    # a rebuilt toolbar keeps the switch at its end and the exemption current
    win._rebuild_toolbar()
    assert win._toolbar.actions()[-1] is win._act_tooltips
    assert win._toolbar.widgetForAction(win._act_tooltips) in win._tooltip_filter._exempt
    win._act_tooltips.trigger()                             # on again
    assert win._tooltip_filter.enabled is True and win._prefs["tooltips"] is True
