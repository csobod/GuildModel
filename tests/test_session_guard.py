"""Session safety net (V1 prep): dirty tracking, close/open guards, autosave.

MainWindow gains GuildDraw's safety machinery: a dirty flag driven by real user
edits (title star), Save/Discard/Cancel confirmation on close and on the open
actions, a 3-minute autosave snapshot to ~/.guildmodel/autosave, and a startup
recovery offer. Programmatic restores (project open, component-tab activation)
must NOT mark the session dirty. Also covered: the boot module stays light
(importable without Qt side effects) and the splash card renders.
"""
import json
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

_SVG_NS = "http://www.w3.org/2000/svg"


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path):
    front = {
        "curves": [
            _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
            _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
            _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
            _line("SCULPT", [(0, -20), (0, 20)]),
            _line("SCULPT", [(30, -20), (30, 20)]),
        ],
    }
    temple_r = {"curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
    ]}
    states = {"front": front, "temple_r": temple_r, "temple_l": {"curves": []},
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def _window(tmp_path, monkeypatch):
    """A MainWindow with home redirected to tmp_path and dialogs silenced.
    Skips where no Qt/VTK platform is usable (mirrors test_components_m73)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    from guildmodel.gui.app import MainWindow
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


# ------------------------------------------------------------------ dirty flag


def test_fresh_load_is_clean_and_edit_marks_dirty(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    assert win._dirty is False                    # a just-loaded design is clean
    assert win.windowTitle() == "GuildModel  —  model.gdraw"

    win.params.castle_changed.emit()              # a real user edit
    assert win._dirty is True
    assert win.windowTitle().endswith("*")


def test_tab_switch_is_not_an_edit(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win._activate_workspace(1)                    # temple
    win._activate_workspace(0)                    # back to the front
    assert win._dirty is False


def test_save_clears_dirty_and_reopen_is_clean(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win.params.cam_changed.emit()
    assert win._dirty is True

    proj = tmp_path / "job.gmodel"
    assert win._save_gmodel_to(proj) is True
    assert win._dirty is False
    assert win.windowTitle() == "GuildModel  —  job.gmodel"

    # Reopening the project is a programmatic restore — clean, no star.
    win._open_project(proj)
    assert win._dirty is False
    assert win.windowTitle() == "GuildModel  —  job.gmodel"


def test_open_project_does_not_pollute_recents(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    proj = tmp_path / "job.gmodel"
    assert win._save_gmodel_to(proj) is True
    win._open_project(proj)
    # The re-import of the embedded drawing goes through a temp file which must
    # NOT land in the recent-files menu — only the real design + project paths.
    assert all("gmodel_" not in p for p in win._recent_files)
    assert str(proj) in win._recent_files


# ------------------------------------------------------------------ confirm/close


def _btn(name):
    from PySide6.QtWidgets import QMessageBox
    return getattr(QMessageBox.StandardButton, name)


def test_confirm_discard_clean_never_asks(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    from PySide6.QtWidgets import QMessageBox

    def _boom(*a, **k):                                        # pragma: no cover
        raise AssertionError("dialog shown for a clean session")
    monkeypatch.setattr(QMessageBox, "warning", _boom)
    assert win._confirm_discard() is True


def test_confirm_discard_cancel_and_discard(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win.params.castle_changed.emit()
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: _btn("Cancel"))
    assert win._confirm_discard() is False
    assert win._dirty is True                     # cancel keeps the session

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: _btn("Discard"))
    assert win._confirm_discard() is True


def test_confirm_discard_save_path(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    proj = tmp_path / "job.gmodel"
    assert win._save_gmodel_to(proj) is True      # project now has a path
    win.params.castle_changed.emit()
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: _btn("Save"))
    assert win._confirm_discard() is True         # saved straight back
    assert win._dirty is False


def test_close_event_cancel_keeps_window(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win.params.castle_changed.emit()
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: _btn("Cancel"))
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted() is False

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: _btn("Discard"))
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted() is True


# ------------------------------------------------------------------ autosave + recovery


def test_autosave_snapshot_and_clear(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))

    win._do_autosave()                            # clean — must not snapshot
    rec, meta = win._autosave_paths()
    assert not rec.exists()

    win.params.castle_changed.emit()
    win._do_autosave()
    assert rec.exists() and meta.exists()
    info = json.loads(meta.read_text(encoding="utf-8"))
    assert info["source_path"] is None            # never saved to a project yet

    win._clear_autosave()
    assert not rec.exists() and not meta.exists()


def test_recovery_offer_restores_dirty_unsaved(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win.params.castle_changed.emit()
    win._do_autosave()
    rec, _meta = win._autosave_paths()
    assert rec.exists()

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: _btn("Yes"))
    recents_before = list(win._recent_files)
    win._offer_recovery()
    # Recovered content is unsaved work belonging to no project file.
    assert win._dirty is True
    assert win._project_path is None
    assert win.windowTitle().endswith("*")
    assert win._recent_files == recents_before    # recovery slot never in recents


def test_recovery_declined_clears_slot(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    win.params.castle_changed.emit()
    win._do_autosave()
    rec, _meta = win._autosave_paths()
    assert rec.exists()

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: _btn("No"))
    win._offer_recovery()
    assert not rec.exists()                       # declined — slot cleared


# ------------------------------------------------------------------ splash + boot


def test_splash_card_renders(qapp):
    from guildmodel.gui.splash import _render_card, GuildSplash
    pm = _render_card(1.0)
    assert not pm.isNull()
    assert pm.width() > 0 and pm.height() > 0
    s = GuildSplash(1.0)                          # constructs without showing
    assert s.pixmap() is not None


def test_boot_module_is_light():
    """boot.py must import without Qt side effects (no QApplication, no VTK) —
    it is the pre-splash entry, so its import must stay instant."""
    import importlib
    import guildmodel.gui.boot as boot
    importlib.reload(boot)
    assert callable(boot.main)
    # The heavy module must not be a module-level import of boot.
    import inspect
    src = inspect.getsource(boot)
    head = src.split("def main", 1)[0]
    assert "from guildmodel.gui.app" not in head
    assert "import guildmodel.gui.app" not in head
