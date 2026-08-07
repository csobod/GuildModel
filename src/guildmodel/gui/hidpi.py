"""Display-platform decisions: which Qt plugin to run under, and how big the UI
should be. Both are Linux/Wayland problems, and both used to be the maker's job.

**Why the app has to decide the platform.** PyVista/VTK's Linux renderer is
`vtkXOpenGLRenderWindow`, which is X11-only. Under Qt's native `wayland` plugin
it cannot embed its render window: it fails with `BadWindow` on
`X_ConfigureWindow` and takes the process with it. Re-tested 2026-08-07 on
VTK 9.6.2 / PySide6 6.11.1 / KDE Plasma — still true, so this is not a stale
workaround waiting to expire. The README told the maker to export
`QT_QPA_PLATFORM=xcb` by hand; `force_x11_on_wayland()` now does it for them,
early enough to matter, and still yields to an explicit override.

**Why the app has to decide the scale.** Running under XWayland means Qt gets no
compositor scale to follow: the panel here is 141.6 physical DPI and Qt is told
96, so the whole UI renders at about 68% of intended size. The documented
`QT_FONT_DPI` workaround only half-fixes it, because this app's stylesheet pins
139 font sizes in `px` and Qt stylesheet `px` does not follow font DPI. So the
scale is computed here and applied to *both* the application font and the
stylesheet.
"""
from __future__ import annotations

import os
import sys

#: Below this ratio the panel is close enough to Qt's assumed 96 DPI that
#: scaling would just blur things. 1.15 is about a 110 DPI panel.
_SCALE_THRESHOLD = 1.15

#: Above this we are almost certainly misreading the panel (a projector, a
#: virtual display with a bogus EDID) and a huge UI is worse than a small one.
_SCALE_CEILING = 3.0

#: Env vars that mean "the maker has already decided" — respected untouched.
_SCALE_OVERRIDES = ("QT_SCALE_FACTOR", "QT_FONT_DPI",
                    "QT_SCREEN_SCALE_FACTORS", "QT_ENABLE_HIGHDPI_SCALING")


def force_x11_on_wayland() -> bool:
    """Point Qt at XWayland when running on Wayland. Call BEFORE QApplication.

    Returns True if this call set the platform. An explicit `QT_QPA_PLATFORM`
    is always left alone — someone debugging the Wayland path (or running
    `offscreen` in tests) must be able to say so and be believed.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return False
    on_wayland = (os.environ.get("XDG_SESSION_TYPE") == "wayland"
                  or os.environ.get("WAYLAND_DISPLAY"))
    if not (sys.platform.startswith("linux") and on_wayland):
        return False
    if not os.environ.get("DISPLAY"):
        # Wayland with no XWayland to fall back to. Leave Qt alone: it will
        # pick the wayland plugin and 3D will fail, but forcing `xcb` with no
        # X server means the app does not start at all, which is worse.
        return False
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    return True


def ui_scale(screen, prefs: dict | None = None) -> float:
    """The UI scale factor for `screen`, or 1.0 to leave the UI alone.

    Derived from the panel's true DPI against the 96 Qt assumes, because under
    XWayland there is no compositor scale to ask for. `devicePixelRatio` is
    divided out: where Qt *has* already scaled (a real HiDPI X11 setup, or a
    future native-Wayland path), that part of the job is done.

    A `ui_scale` preference wins over the measurement — "auto" measures, a
    number pins it, and 1.0 turns the whole thing off.
    """
    pref = (prefs or {}).get("ui_scale", "auto")
    if pref != "auto":
        try:
            return _clamp(float(pref))
        except (TypeError, ValueError):
            pass

    if any(os.environ.get(v) for v in _SCALE_OVERRIDES):
        return 1.0            # the maker set it by hand; do not compound it
    if screen is None:
        return 1.0

    physical = float(screen.physicalDotsPerInch() or 0.0)
    logical = float(screen.logicalDotsPerInch() or 0.0)
    if physical <= 0 or logical <= 0:
        return 1.0

    ratio = (physical / logical) / max(float(screen.devicePixelRatio()), 1.0)
    return _clamp(ratio) if ratio >= _SCALE_THRESHOLD else 1.0


def _clamp(scale: float) -> float:
    return max(1.0, min(float(scale), _SCALE_CEILING))


def apply_ui_scale(app, scale: float) -> None:
    """Grow the application's default font to match `scale`.

    Only the font: widget metrics come from the stylesheet, which is scaled
    separately by `theme.stylesheet(dark, scale)`. Splitting them means a
    stylesheet reload (the dark-mode toggle) does not have to re-derive the
    scale, and the font survives it.
    """
    if abs(scale - 1.0) < 0.01:
        return
    font = app.font()
    size = font.pointSizeF()
    if size > 0:
        font.setPointSizeF(size * scale)
    else:                                  # a pixel-sized default font
        font.setPixelSize(max(1, round(font.pixelSize() * scale)))
    app.setFont(font)
