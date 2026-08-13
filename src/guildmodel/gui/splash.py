"""Loading splash screen (ported from GuildDraw's framedraft/splash.py).

Shown the instant GuildModel starts — before the (comparatively slow) VTK
import and MainWindow build — so the maker gets immediate visual feedback that
the program is launching. That feedback is the point: without it, a slow cold
start looks like nothing happened and the user double-clicks again, ending up
with two copies of the app fighting over the same autosave/recovery slot.

The card is deliberately formal: the Guild seal, a serif face, and the license
line, evoking a guild certificate rather than a typical software toast — the
same card GuildDraw shows, so the family reads as one ecosystem.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QEventLoop, QRectF
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPixmap, QPen, QFontMetrics,
)
from PySide6.QtWidgets import QWidget

from guildmodel import __version__

_SEAL_PATH = Path(__file__).resolve().parents[1] / "assets" / "gasm_seal.svg"

# Logical (device-independent) card size in px.
_W, _H = 540, 600

# Brand palette — warm "parchment" card on the amber Guild accent, charcoal
# ink, matching the QSS in gui/style/theme.py (#ffd580 accent, #1f1f1f ink).
_PARCHMENT = QColor("#f7edd6")
_AMBER     = QColor("#d9a441")
_INK       = QColor("#1f1f1f")
_INK_SOFT  = QColor("#5a513c")

_GUILD_NAME = "Guild of American Spectacle Makers"
_LICENSE    = "Released under the GNU General Public License v3.0"


def _serif(size: int, *, bold: bool = False, italic: bool = False) -> QFont:
    """A serif face with graceful fallback across platforms.

    Names a few common serifs, then asks Qt for its generic serif if none are
    installed, so the splash always reads as a serif even on a bare system.
    """
    font = QFont("Georgia")
    font.setStyleHint(QFont.StyleHint.Serif, QFont.StyleStrategy.PreferQuality)
    font.setFamilies(["Georgia", "Times New Roman", "Cambria", "serif"])
    font.setPointSize(size)
    font.setBold(bold)
    font.setItalic(italic)
    return font


def _draw_centered(p: QPainter, font: QFont, color: QColor,
                   text: str, y: int) -> int:
    """Draw *text* horizontally centerd at vertical position *y* (top of line).
    Returns the y just below the line for easy stacking."""
    p.setFont(font)
    p.setPen(QPen(color))
    fm = QFontMetrics(font)
    p.drawText(QRectF(0, y, _W, fm.height()),
               int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
               text)
    return y + fm.height()


def _render_card(dpr: float, scale: float = 1.0) -> QPixmap:
    """Compose the whole splash into one high-DPI pixmap.

    `scale` is the UI scale (see `gui/hidpi.py`) — the card is drawn in logical
    units and grows with the rest of the chrome, so it does not sit on a HiDPI
    panel as a postage stamp while the app behind it is correctly sized.

    Rendered through a `QImage` in an explicitly alpha-capable format rather
    than a bare `QPixmap`: `QPixmap(w, h)` starts uninitialized and its format
    is the platform's choice, so `fill(transparent)` is only reliably
    transparent once the format is pinned.
    """
    total = dpr * scale
    img = QImage(int(_W * total), int(_H * total),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)

    p = QPainter(pm)
    if abs(scale - 1.0) >= 0.01:
        p.scale(scale, scale)   # draw in logical units, land on the bigger card
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)

    # Parchment card with a double amber/charcoal rule — a "certificate" frame.
    p.setBrush(_PARCHMENT)
    p.setPen(QPen(_AMBER, 3))
    p.drawRoundedRect(QRectF(6, 6, _W - 12, _H - 12), 14, 14)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_INK, 1))
    p.drawRoundedRect(QRectF(14, 14, _W - 28, _H - 28), 9, 9)

    # Guild seal, centerd near the top.
    seal_box = 232
    seal_x = (_W - seal_box) / 2
    seal_y = 40
    if _SEAL_PATH.exists():
        try:
            from PySide6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(str(_SEAL_PATH))
            renderer.render(p, QRectF(seal_x, seal_y, seal_box, seal_box))
        except Exception:
            pass   # a missing/broken seal must never block the launch

    y = seal_y + seal_box + 14
    y = _draw_centered(p, _serif(40, bold=True), _INK, "GuildModel", y)
    y = _draw_centered(p, _serif(13, italic=True), _INK_SOFT,
                       f"version {__version__}", y + 2)

    # Divider rule.
    y += 18
    p.setPen(QPen(_AMBER, 1))
    p.drawLine(int(_W * 0.30), y, int(_W * 0.70), y)
    y += 14

    y = _draw_centered(p, _serif(12), _INK_SOFT, "A production of the", y)
    y = _draw_centered(p, _serif(17, bold=True), _INK, _GUILD_NAME, y + 2)

    # License + loading line pinned toward the bottom of the card.
    _draw_centered(p, _serif(11), _INK_SOFT, _LICENSE, _H - 86)
    _draw_centered(p, _serif(12, italic=True), _INK, "Loading…", _H - 58)

    p.end()
    return pm


class GuildSplash(QWidget):
    """Frameless, always-on-top guild certificate shown during startup.

    **Deliberately not a `QSplashScreen`.** That class costs **1010 ms** in
    `show()` on XWayland/KWin — a flat, reproducible second, the same whether
    the window is translucent or opaque, first call or fifth. A plain frameless
    widget carrying the identical pixmap and the identical window flags shows in
    **1.0 ms**. Whatever handshake `QSplashScreen` waits on is timing out, and
    a splash that takes a second to appear is worse than no splash: it is dead
    time in exactly the window it exists to explain, and it is most of why the
    card read as a black rectangle at launch.

    So this is a `QWidget` that paints one pixmap, plus the two things
    `QSplashScreen` was actually providing — centring on the primary screen and
    a `finish()` that closes it once the real window is up.
    """

    def __init__(self, dpr: float = 1.0, scale: float = 1.0):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.SplashScreen
                         | Qt.WindowType.WindowStaysOnTopHint)
        # The card is a rounded rectangle on a transparent fill, so the corners
        # need real translucency; without it they composite against undefined
        # surface content rather than the desktop.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._pixmap = _render_card(dpr, scale)
        self.setFixedSize(self._pixmap.size() / self._pixmap.devicePixelRatio())

    def paintEvent(self, event) -> None:      # noqa: N802  (Qt naming)
        QPainter(self).drawPixmap(0, 0, self._pixmap)

    def center_on(self, screen) -> None:
        """Put the card in the middle of `screen` — QSplashScreen did this."""
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)

    def finish(self, _window) -> None:
        """Close the splash now that the main window is up. The argument is
        ignored — it exists so callers read the same as QSplashScreen's."""
        self.close()


#: How long `make_splash` will wait for the compositor to expose the surface.
#: Generous because the cost of overshooting is a few idle milliseconds, and the
#: cost of undershooting is the whole black-splash bug back again.
_EXPOSE_TIMEOUT_S = 1.0


def make_splash(app, scale: float = 1.0) -> GuildSplash:
    """Build, show, and *actually paint* the splash.

    Caller closes it with ``splash.finish(window)`` once the main window is up.

    **The single `processEvents()` this used to do was not enough, and that is
    the whole black-splash bug.** `show()` maps the surface, but a Wayland
    client cannot paint until the compositor has sent a configure event and Qt
    has turned that into an expose. One `processEvents()` pumps whatever
    happens to be queued and returns long before that round trip completes —
    measured on KDE Plasma, the window was still `isExposed() == False` two
    full seconds later. Control then returns to `boot.main`, which immediately
    blocks for seconds importing VTK, so the compositor holds a mapped,
    never-painted surface on top of everything: a black rectangle, for exactly
    as long as the slow start it was added to explain.

    So pump until the window reports itself exposed, then once more to let the
    paint event through. The deadline is a safety net — a platform that never
    exposes (offscreen, a headless test) must not hang the launch.
    """
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    splash = GuildSplash(dpr, scale)
    splash.center_on(screen)
    splash.show()

    # WaitForMoreEvents blocks until the compositor actually says something
    # instead of spinning on an empty queue — the naive loop burned ~3,500
    # iterations across the 21 ms this takes.
    deadline = time.monotonic() + _EXPOSE_TIMEOUT_S
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.WaitForMoreEvents, 20)
        handle = splash.windowHandle()
        if handle is not None and handle.isExposed():
            app.processEvents()      # and now the paint itself
            break
    return splash
