"""Ecosystem-glue round (V1-prep cluster c): the Ctrl+, Preferences shortcut,
the File ▸ Open in GuildSend handoff action, and the retirements from cluster d
(io_import.svg / mesh.twosided / mesh.stl_export are gone; mesh.section stays).
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


@pytest.mark.gui
def test_send_action_mirrors_export_enable(qapp, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    assert win._act_send.isEnabled() is False      # no program yet
    win._act_export_nc.setEnabled(True)            # a program lands
    assert win._act_send.isEnabled() is True
    win._act_export_nc.setEnabled(False)           # fresh design resets
    assert win._act_send.isEnabled() is False


def test_find_guildsend_dev_fallback_shape(monkeypatch, tmp_path):
    """Without an install or PATH entry, the sibling-checkout fallback returns
    [python, main.py] — or None on a machine with neither. Shape-check only."""
    from guildmodel.gui.app import _find_guildsend
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))   # no install here
    cmd = _find_guildsend()
    assert cmd is None or (isinstance(cmd, list) and len(cmd) in (1, 2)
                           and all(isinstance(p, str) for p in cmd))


def test_retired_modules_are_gone():
    import guildmodel.core.io_import as io_import
    import guildmodel.core.mesh as mesh
    assert not hasattr(io_import, "import_svg")
    assert not hasattr(mesh, "build_mesh") and not hasattr(mesh, "export_stl")
    from guildmodel.core.mesh import mesh_section          # the keeper
    assert callable(mesh_section)
