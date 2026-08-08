"""Display diagnostics — ``guildmodel --diag-display`` (BUILDPLAN-NEW UI-0).

The UI scale has now been wrong in both directions on the same machine (68%
too small before the 2026-08-07 hidpi work, far too big after), and both times
the root cause was invisible: nothing recorded who was scaling what. This
module is the fix's first half — **evidence**. It prints everything the scale
decision depends on, per screen, plus the decision itself and the reason, so a
wrong-size report is diagnosable from one paste.

The second half is the invariant (see ``hidpi.py``): exactly one party applies
scale, and the startup log names it. This report and that log line come from
the same code, so they cannot drift apart.

Run it exactly as the app runs — ``guildmodel --diag-display`` — to see what
the app will do, or with ``QT_QPA_PLATFORM`` overridden to interrogate the
other platform plugins. Keep it light: no VTK, no MainWindow, safe to run
headless over SSH.
"""
from __future__ import annotations

import os

#: Environment that influences Qt's own scaling or ours. Reported even when
#: unset, because "unset" is half of most diagnoses.
_ENV_KEYS = (
    "QT_QPA_PLATFORM", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY",
    "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI",
    "QT_ENABLE_HIGHDPI_SCALING", "QT_AUTO_SCREEN_SCALE_FACTOR",
    "GDK_BACKEND", "XDG_CURRENT_DESKTOP",
)


def display_report(app, prefs: dict | None = None) -> str:
    """The evidence table, for an already-constructed Q(Gui)Application."""
    from guildmodel.gui import hidpi

    lines: list[str] = []
    add = lines.append

    add("GuildModel display diagnostic")
    add("=" * 60)
    add(f"platform plugin : {app.platformName()}")
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        add(f"  {key:<28} = {val if val is not None else '(unset)'}")

    prefs = prefs or {}
    add(f"prefs ui_scale  : {prefs.get('ui_scale', 'auto')!r}")
    add("")

    primary = app.primaryScreen()
    for screen in app.screens():
        geo = screen.geometry()
        phys = screen.physicalSize()
        mark = "  <-- primary (scale is derived from this one)" \
            if screen is primary else ""
        add(f"screen {screen.name()!r}{mark}")
        add(f"  geometry        : {geo.width()}x{geo.height()} at "
            f"({geo.x()},{geo.y()})")
        add(f"  physical size   : {phys.width():.0f}x{phys.height():.0f} mm")
        add(f"  physical DPI    : {screen.physicalDotsPerInch():.1f}")
        add(f"  logical DPI     : {screen.logicalDotsPerInch():.1f}")
        add(f"  devicePixelRatio: {screen.devicePixelRatio():.3f}")
        add(f"  ui_scale() here : {hidpi.ui_scale(screen, prefs):.3f}")
        add("")

    add(hidpi.scale_decision(primary, prefs, app))
    font = app.font()
    reported = (f"{font.pointSizeF():.1f} pt" if font.pointSizeF() > 0
                else f"{font.pixelSize()} px")
    add(f"  Qt reports    : {font.family()!r} {reported}"
        + ("  <-- Qt's generic fallback: no platform theme answered "
           "(PySide6 bundles its own Qt and cannot see a system-installed one)"
           if hidpi.desktop_font_scale(app) * hidpi.DESIGN_BASE_PX
           != (font.pointSizeF() * 96.0 / 72.0) else ""))
    add(f"  design baseline: {hidpi.DESIGN_BASE_PX:.0f} px "
        f"(stylesheet font-size values are ratios against this)")
    return "\n".join(lines)


def run_diag() -> int:
    """Construct the minimal Qt app the same way boot does, print, exit."""
    from guildmodel.gui.hidpi import force_x11_on_wayland
    force_x11_on_wayland()

    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])

    from guildmodel.gui import prefs as prefs_mod
    print(display_report(app, prefs_mod.load()))
    return 0
