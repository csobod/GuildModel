"""Light launcher — QApplication + splash *before* the heavy app import.

``guildmodel.gui.app`` pulls in PyVista/VTK at import time, which dominates the
cold start. Booting from this module (the ``guildmodel`` entry point and the
repo's main.py both do) gets the guild splash card on screen the instant the
process starts; only then is the heavy module imported and the main window
built. ``python -m guildmodel.gui.app`` still works — its main() delegates
here (the splash just appears later on that path, after the module import).
"""
from __future__ import annotations

import os
import sys


def main() -> None:
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
    app.setStyleSheet(theme.stylesheet(prefs_mod.load()["dark_mode"]))

    # Show the loading splash before the slow VTK import + main-window build,
    # so the maker sees the app is starting and doesn't launch a second copy.
    from guildmodel.gui.splash import make_splash
    splash = make_splash(app)

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
