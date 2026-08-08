"""Light launcher — QApplication + splash *before* the heavy app import.

``guildmodel.gui.app`` pulls in PyVista/VTK at import time, which dominates the
cold start. Booting from this module (the ``guildmodel`` entry point and the
repo's main.py both do) gets the guild splash card on screen the instant the
process starts; only then is the heavy module imported and the main window
built. ``python -m guildmodel.gui.app`` still works — its main() delegates
here (the splash just appears later on that path, after the module import).

Display-platform and UI-scale decisions live in ``gui/hidpi.py``; this module
only sequences them, and the order matters — the platform must be chosen before
QApplication exists, and the scale can only be measured once it does.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    # Evidence mode (BUILDPLAN-NEW UI-0): print the display/scale diagnostic
    # and exit, without VTK or a window. Checked before anything Qt exists.
    if "--diag-display" in sys.argv:
        from guildmodel.gui.diag import run_diag
        sys.exit(run_diag())

    # Before QApplication: Qt reads QT_QPA_PLATFORM when the app is constructed,
    # so an XWayland switch is only possible here.
    from guildmodel.gui.hidpi import (apply_ui_scale, force_x11_on_wayland,
                                      scale_decision, stylesheet_scale,
                                      ui_scale)
    force_x11_on_wayland()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # Share one OpenGL context across the 3D-preview + cut-sim render windows
    # (must be set before the QApplication exists). Qt+VTK best practice for
    # apps embedding multiple QtInteractors — reduces wglMakeCurrent /
    # context-loss failures on Windows when switching views or after the
    # display sleeps.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("GuildModel")
    app.setOrganizationName("Guild")
    from guildmodel import __version__
    app.setApplicationVersion(__version__)

    from guildmodel.gui import prefs as prefs_mod
    from guildmodel.gui.style import theme
    saved = prefs_mod.load()
    # Two factors (gui/hidpi.py): the platform's typography, which only the
    # stylesheet needs since the font already carries it, and the UI scale,
    # which both need.
    scale = ui_scale(app.primaryScreen(), saved)
    apply_ui_scale(app, scale)
    app.setStyleSheet(theme.stylesheet(saved["dark_mode"],
                                       stylesheet_scale(app, saved)))
    # The one-scaler invariant's receipt (BUILDPLAN-NEW UI-0): the decision and
    # its reason, stashed for MainWindow's log pane so any wrong-size report is
    # diagnosable from the log alone (`--diag-display` prints the full table).
    app.setProperty("guildmodel_scale_decision",
                    scale_decision(app.primaryScreen(), saved, app))

    # Show the loading splash before the slow VTK import + main-window build,
    # so the maker sees the app is starting and doesn't launch a second copy.
    from guildmodel.gui.splash import make_splash
    splash = make_splash(app, scale=scale)

    from guildmodel.gui.app import MainWindow, _app_icon   # the heavy import
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    win = MainWindow()
    if icon is not None:
        win.setWindowIcon(icon)
    win.show()
    splash.finish(win)   # dismiss once the window is up

    # Open a file passed on the command line (e.g. double-clicking a .gmodel
    # via the installed file association).
    for arg in app.arguments()[1:]:
        if not arg.startswith("-") and os.path.isfile(arg):
            win.open_path(arg)
            break

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
