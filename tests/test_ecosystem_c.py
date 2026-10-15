"""Ecosystem-glue round (V1-prep cluster c): the Ctrl+, Preferences shortcut
and the retirements from cluster d (io_import.svg / mesh.twosided /
mesh.stl_export are gone; mesh.section stays). The File ▸ Open in GuildSend
handoff this round added was retired in rc2 and removed on 2026-10-15: the
apps never launch each other, and nothing of it is left to test.
"""
import os

import pytest


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from guildmodel.gui.app import MainWindow
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


@pytest.mark.gui
def test_preferences_shortcut_is_ctrl_comma(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    from PySide6.QtGui import QKeySequence
    assert win._act_prefs.text().startswith("Preferences")
    assert win._act_prefs.shortcut() == QKeySequence("Ctrl+,")


def test_no_app_launches_another():
    """The apps never find or start each other (2026-10-15): no launcher, no
    finder, no subprocess in the GUI module."""
    import inspect
    import guildmodel.gui.app as app_mod
    assert not hasattr(app_mod, "_find_guildsend")
    assert not hasattr(app_mod.MainWindow, "_on_open_in_guildsend")
    assert "subprocess" not in inspect.getsource(app_mod)


def test_retired_modules_are_gone():
    import guildmodel.core.io_import as io_import
    import guildmodel.core.mesh as mesh
    assert not hasattr(io_import, "import_svg")
    assert not hasattr(mesh, "build_mesh") and not hasattr(mesh, "export_stl")
    from guildmodel.core.mesh import mesh_section          # the keeper
    assert callable(mesh_section)
