"""Pop-up sizing (2026-09-27): the Preferences window opens within the screen
it will show on, at its content's size, with every tab scrolling so none can
dictate a minimum, and it remembers the size the maker leaves it at; the
operation summary's table is bounded to half the screen."""
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


def test_the_operation_summary_never_outgrows_the_screen(tmp_path, monkeypatch):
    app = _qt(monkeypatch, tmp_path)
    from guildmodel.gui.app import OpSummaryDialog
    rows = [{"name": f"Op {i}", "strategy": "outside", "floor_z_mm": 0.4,
             "cut_length_mm": 100.0, "est_minutes": 0.1} for i in range(60)]
    dlg = OpSummaryDialog(rows, "sixty operations")
    dlg.show()
    app.processEvents()
    avail = app.primaryScreen().availableGeometry()
    assert dlg.height() <= avail.height()
    from PySide6.QtWidgets import QTableWidget
    table = dlg.findChild(QTableWidget)
    assert table.height() <= avail.height() // 2
    assert table.verticalScrollBar().maximum() > 0          # the rows scroll


@pytest.mark.gui
def test_preferences_opens_within_the_screen_and_remembers_its_size(tmp_path, monkeypatch):
    app = _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QDialog, QMessageBox, QScrollArea, QTabWidget
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    try:
        from guildmodel.gui.app import MainWindow, PrefsDialog
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    avail = app.primaryScreen().availableGeometry()

    dlg = PrefsDialog({**win._prefs, "dark_mode": False}, win)
    dlg.show()
    app.processEvents()
    tabs = dlg.findChild(QTabWidget)
    assert tabs.count() >= 8                                   # Hotkeys + Toolbar present
    for i in range(tabs.count()):
        assert isinstance(tabs.widget(i), QScrollArea), tabs.tabText(i)
    assert dlg.minimumSizeHint().height() < avail.height() // 2
    assert dlg.minimumSizeHint().width() < 700                # the hints wrap now
    assert dlg.width() <= int(avail.width() * 0.8) and dlg.width() >= dlg.minimumWidth()
    assert dlg.height() <= int(avail.height() * 0.8) and dlg.height() >= dlg.minimumHeight()
    # a remembered size is honored, and clamped to 80 % of the screen
    dlg2 = PrefsDialog({**win._prefs, "dark_mode": False, "prefs_dialog_size": [600, 9000]}, win)
    dlg2.show()
    app.processEvents()
    assert dlg2.width() == 600 and dlg2.height() == int(avail.height() * 0.8)
    # the size the maker leaves it at is kept, Cancel or OK
    def cancel_after_resize(self):
        self.resize(640, 560)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PrefsDialog, "exec", cancel_after_resize)
    win._open_preferences()
    assert win._prefs["prefs_dialog_size"] == [640, 560]
    assert json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))["prefs_dialog_size"] == [640, 560]
