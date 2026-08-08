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

**Why the app must NOT normally decide the scale.** The 2026-08-07 first cut of
this module measured the panel's physical DPI and scaled the UI to match
(1.475x on this machine's 141.6 DPI panel). That was wrong in the way that
matters most: the desktop already *had* a convention — the maker runs that
panel at compositor scale 1, deliberately — and Qt 6 follows the desktop's
convention by itself through `devicePixelRatio`. Measuring the panel made
GuildModel the one over-sized window on the desktop. The policy now
(`_decide`, and BUILDPLAN-NEW UI-0) is: the maker's pin wins, a managed
desktop is followed exactly, and the physical-DPI heuristic fires only on an
unmanaged bare-WM setup where nobody else has an opinion. Every decision is
reportable via `scale_decision` / `--diag-display`.
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

    **The one-scaler invariant** (BUILDPLAN-NEW UI-0): exactly one party may
    scale this UI — the maker (preference or env), Qt (devicePixelRatio), or
    this measurement — and the choice must be reportable. `scale_decision`
    renders this function's reasoning as one log line; the two share
    `_decide`, so the log cannot drift from the behavior.
    """
    return _decide(screen, prefs)[0]


def stylesheet_scale(app, prefs: dict | None = None) -> float:
    """The single number `theme.stylesheet` should be scaled by.

    Two independent factors, multiplied here so no caller can forget one:
    the platform's typography (`desktop_font_scale`) and the maker's/desktop's
    UI scale (`ui_scale`). The application *font* gets only the second, because
    it already carries the first.
    """
    return desktop_font_scale(app) * ui_scale(app.primaryScreen(), prefs)


def scale_decision(screen, prefs: dict | None = None, app=None) -> str:
    """One line naming the applied scale and *why* — for the startup log and
    `--diag-display`, so a wrong-size report is diagnosable from a paste."""
    scale, why = _decide(screen, prefs)
    line = f"scale decision  : x{scale:.3f} — {why}"
    if app is not None:
        font = app.font()
        base = _base_font_size(app)
        shown = (f"{base:.1f} pt" if base > 0 else f"{-base:.0f} px")
        line += (f"\n  typography    : platform base {font.family()!r} {shown}"
                 f" -> stylesheet x{stylesheet_scale(app, prefs):.3f}")
    return line


def _decide(screen, prefs: dict | None = None) -> tuple[float, str]:
    """The one-scaler policy, in priority order.

    1. The maker's pin (preference, then env) always wins.
    2. **A managed desktop is followed, never second-guessed.** Qt 6 already
       delivers the desktop's scaling convention through `devicePixelRatio`
       (compositor scale on Wayland, Xft.dpi on X11, the user's display scale
       on Windows/macOS) — fonts *and* stylesheet px follow it. When a DE is
       present, the convention it reports IS the user's choice, including the
       choice not to scale: this machine's maker runs a 141.6 DPI panel at
       scale 1 deliberately, and the 2026-08-07 "measure the panel" version of
       this function overrode that, making GuildModel the one window on the
       desktop 1.475x bigger than its neighbours. That is the bug this
       docstring exists to prevent re-introducing. (The app looking cramped
       *at* the desktop size was real, but it was the stylesheet's 11px
       baseline — fixed in `theme.py` — not a DPI problem.)
    3. The physical-DPI heuristic survives only where nothing manages the
       desktop at all (a bare window manager on a HiDPI panel — no
       XDG_CURRENT_DESKTOP, no dpr, logical DPI left at Qt's 96 default).
    """
    pref = (prefs or {}).get("ui_scale", "auto")
    if pref != "auto":
        try:
            return _clamp(float(pref)), (
                f"pinned by the ui_scale preference ({pref!r}); "
                f"measurement skipped")
        except (TypeError, ValueError):
            pass                      # unparseable pref: fall back to auto

    for var in _SCALE_OVERRIDES:
        if os.environ.get(var):
            return 1.0, (f"left alone — the maker set {var}="
                         f"{os.environ[var]!r} and two scalers would compound")
    if screen is None:
        return 1.0, "left alone — no screen to measure"

    physical = float(screen.physicalDotsPerInch() or 0.0)
    logical = float(screen.logicalDotsPerInch() or 0.0)
    dpr = max(float(screen.devicePixelRatio()), 1.0)

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    managed = (not sys.platform.startswith("linux")   # Windows/macOS: always
               or bool(desktop)                        # a DE is running
               or dpr > 1.01                           # something already scales
               or (logical > 0 and abs(logical - 96.0) > 0.5))  # Xft.dpi set
    if managed:
        who = desktop or sys.platform
        return 1.0, (f"following the desktop convention — {who} reports "
                     f"dpr {dpr:.2f}, logical {logical:.1f} DPI on "
                     f"{screen.name()!r}; Qt applies that itself and adding "
                     f"more would make this the one over-scaled app")

    if physical <= 0 or logical <= 0:
        return 1.0, (f"left alone — screen {screen.name()!r} reports no "
                     f"usable DPI (physical {physical}, logical {logical})")

    ratio = (physical / logical) / dpr
    detail = (f"unmanaged desktop, screen {screen.name()!r}: physical "
              f"{physical:.1f} DPI, logical {logical:.1f}, dpr {dpr:.2f}")
    if ratio < _SCALE_THRESHOLD:
        return 1.0, f"left alone — {detail}; ratio {ratio:.3f} is near 1"
    return _clamp(ratio), f"measured — {detail}; ratio {ratio:.3f}"


def _clamp(scale: float) -> float:
    return max(1.0, min(float(scale), _SCALE_CEILING))


#: The font size the stylesheet was authored against, in px at 96 DPI. Every
#: `font-size` in `style/theme.py` is a ratio against this, so scaling the sheet
#: by `desktop_font_scale()` makes the whole UI track the platform's own
#: typography instead of pinning one designer's screen.
DESIGN_BASE_PX = 13.0

#: What Qt hands back when *no* platform theme answered — not a desktop choice.
#: PySide6 bundles its own Qt and looks for platform themes only inside that
#: bundle, so a system-installed KDEPlasmaPlatformTheme6.so is never seen and
#: this fallback is what every Plasma session gets. Loading the system plugin
#: into PySide6's Qt would mean mixing Qt builds; substituting a sane modern
#: default is the safe half of that trade.
_QT_FALLBACK_FAMILIES = {"sans serif", "sans-serif", "helvetica"}
_QT_FALLBACK_PT = 9.0

#: Point size the mainstream Linux desktops actually ship (Plasma: Noto Sans 10,
#: GNOME: Cantarell 11). Used only to replace the fallback above.
_LINUX_DEFAULT_PT = 10.0


def _base_font_size(app) -> float:
    """The platform's intended UI font size: points if > 0, else -pixels.

    Captured once and cached on the application object, so that every later
    caller — `desktop_font_scale`, a re-`apply_ui_scale` from Preferences —
    reasons about the *platform* font rather than whatever we last set. Without
    this the two would feed each other and each Preferences visit would compound.

    Qt's generic fallback is substituted here, at the single point where the
    platform's answer is read, so nothing downstream has to know about it.
    """
    cached = app.property("_guildmodel_base_font_size")
    if cached is not None:
        return float(cached)

    font = app.font()
    points = font.pointSizeF()
    if points <= 0:
        base = -float(font.pixelSize())            # a pixel-sized default
    else:
        if (sys.platform.startswith("linux")
                and font.family().strip().lower() in _QT_FALLBACK_FAMILIES
                and abs(points - _QT_FALLBACK_PT) < 0.01):
            points = _LINUX_DEFAULT_PT
        base = points
    app.setProperty("_guildmodel_base_font_size", base)
    return base


def desktop_font_scale(app) -> float:
    """How much bigger the platform's UI font is than the design baseline.

    The stylesheet pins 139 `font-size` values in px, which is why the app used
    to look identical whatever the desktop asked for — on Windows (Segoe UI 9),
    GNOME (Cantarell 11) and Plasma (Noto Sans 10) alike. Multiplying the sheet
    by this ratio makes those authored sizes behave as *proportions*, so the app
    inherits the platform's typography. That is most of what "renders well
    across platforms" means in practice, and it needs no DPI guessing at all.
    """
    base = _base_font_size(app)
    if base > 0:
        return (base * 96.0 / 72.0) / DESIGN_BASE_PX
    return (-base) / DESIGN_BASE_PX if base < 0 else 1.0


def apply_ui_scale(app, scale: float) -> None:
    """Set the application's default font to `scale` x the platform default.

    Only the font: widget metrics come from the stylesheet, which is scaled
    separately by `theme.stylesheet(dark, scale)`. Splitting them means a
    stylesheet reload (the dark-mode toggle) does not have to re-derive the
    scale, and the font survives it.

    **Idempotent, deliberately** — see `_base_font_size`. Every call sets an
    absolute size from the captured platform base, so re-applying (a
    Preferences change, a future theme reload) cannot compound. The first
    version multiplied whatever font was current, which made any second caller
    a silent x-squared bug waiting to happen.
    """
    base = _base_font_size(app)
    font = app.font()
    if base > 0:
        font.setPointSizeF(base * scale)
    else:
        font.setPixelSize(max(1, round(-base * scale)))
    app.setFont(font)
