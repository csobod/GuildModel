"""Keep the suite out of the maker's own ``~/.guildmodel``.

Found on 2026-08-12, from a test that had been passing for the wrong reason. The
maker rebound the turntable hotkey to Ctrl+Shift+T in Preferences; the next run
of ``test_alt_t_and_the_button_are_one_state`` failed, because it was reading
*their* prefs file rather than a fixture's. It asserts a shipped default, so any
personal binding breaks it — the test was only ever green because nobody had
rebound that action yet.

Reading is the harmless half. ``MainWindow._save_window_state`` calls
``prefs.save()``, which writes **every** key, so a headless test that opens a
window and closes it stamps its own window geometry, its own panel layout and
whatever value it was exercising over the real file. The turntable speed test
sets 17 and saves.

``prefs._DIR`` is bound at import time, so ``monkeypatch.setenv("HOME", ...)``
inside a test is already too late — by then some earlier test in the process has
imported the module and fixed the path to the real home. Several tests do patch
``_DIR`` / ``_FILE`` directly and are correct; this makes that the default rather
than something each new test has to remember, and covers the sibling stores that
sit in the same directory.

Autouse and session-scoped tmp dir: the isolation is per-run, not per-test, so
tests that deliberately save prefs and read them back in a second window still
work. Anything wanting a clean slate patches over this, as before.
"""
import pathlib

import pytest


#: The home-rooted stores, as `(module path, attribute, filename or None)`.
#: `None` means the attribute is the directory itself.
_HOME_STORES = [
    ("guildmodel.gui.prefs", "_DIR", None),
    ("guildmodel.gui.prefs", "_FILE", "prefs.json"),
    ("guildmodel.gui.tool_store", "_USER", "tools.yaml"),
    ("guildmodel.gui.material_store", "_USER", "materials.yaml"),
    ("guildmodel.gui.style_store", "_USER", "frame_styles.yaml"),
]


@pytest.fixture(scope="session")
def guildmodel_home(tmp_path_factory) -> pathlib.Path:
    """One throwaway ``~/.guildmodel`` for the whole run."""
    return tmp_path_factory.mktemp("guildmodel_home")


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch, guildmodel_home):
    import importlib

    for module_name, attr, filename in _HOME_STORES:
        try:
            module = importlib.import_module(module_name)
        except Exception:                                    # pragma: no cover
            continue                                         # optional GUI deps
        target = guildmodel_home if filename is None else guildmodel_home / filename
        monkeypatch.setattr(module, attr, target, raising=False)

    # `MainWindow._autosave_dir` and the worktable's default bed build their
    # paths from `Path.home()` when called, so pointing HOME at the tmp dir is
    # enough for those two — unlike the import-time constants above.
    monkeypatch.setenv("HOME", str(guildmodel_home))
    monkeypatch.setenv("USERPROFILE", str(guildmodel_home))


@pytest.fixture(autouse=True)
def _destroy_windows():
    """Free every top-level window a test built, before the next test runs.

    Nothing did, and the cost is quadratic rather than merely untidy. Each
    `MainWindow` leaves **1118 widgets** alive, and `_apply_dark_mode` calls
    `QApplication.setStyleSheet`, which re-polishes every live widget in the
    process — so building the *n*-th window walks the widgets of all *n-1*
    before it. Measured on this machine, one window at a time, none released:

        n:  1     2     3     4     5     6     7     8
        s:  0.43  1.22  1.63  2.02  2.43  2.60  3.12  3.33

    That is what killed v1.5.0's first Windows and macOS-Intel builds. Late in
    the run a construction crossed pytest's 300 s per-test timeout, and
    `--timeout-method=thread` kills the process, so the gate died and no
    artifact was produced — 80 minutes of runner each, twice. It reproduced on
    neither Linux nor macos-14, which are simply fast enough to stay under the
    limit; the stack looked like a hang because both dumps landed inside
    `_apply_dark_mode`, which is where nearly all of the time goes.

    `deleteLater`, never `close`: `closeEvent` calls `_confirm_discard`, which
    can raise a modal dialog, and a modal dialog in an offscreen test is a hang
    with no timeout at all. Destroying a widget sends no close event.
    """
    yield

    import sys

    if "PySide6.QtWidgets" not in sys.modules:      # a non-GUI test; nothing to do
        return
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    # Run the deferred deletes now rather than whenever an event loop next
    # turns — several of these tests never start one.
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
