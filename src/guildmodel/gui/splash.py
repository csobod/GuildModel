"""Loading splash screen (ported from GuildDraw's framedraft/splash.py).

Shown the instant GuildModel starts — before the (comparatively slow) VTK
import and MainWindow build — so the maker gets immediate visual feedback that
the program is launching. That feedback is the point: without it, a slow cold
start looks like nothing happened and the user double-clicks again, ending up
with two copies of the app fighting over the same autosave/recovery slot.

The card is deliberately formal: the Guild seal, a serif face, and the licence
line, evoking a guild certificate rather than a typical software toast — the
same card GuildDraw shows, so the family reads as one ecosystem.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPixmap, QPen, QFontMetrics,
)
from PySide6.QtWidgets import QSplashScreen

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
_LICENCE    = "Released under the GNU General Public License v3.0"


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
    """Draw *text* horizontally centred at vertical position *y* (top of line).
    Returns the y just below the line for easy stacking."""
    p.setFont(font)
    p.setPen(QPen(color))
    fm = QFontMetrics(font)
    p.drawText(QRectF(0, y, _W, fm.height()),
               int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
               text)
    return y + fm.height()


def _render_card(dpr: float) -> QPixmap:
    """Compose the whole splash into one high-DPI pixmap."""
    pm = QPixmap(int(_W * dpr), int(_H * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
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

    # Guild seal, centred near the top.
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

    # Licence + loading line pinned toward the bottom of the card.
    _draw_centered(p, _serif(11), _INK_SOFT, _LICENCE, _H - 86)
    _draw_centered(p, _serif(12, italic=True), _INK, "Loading…", _H - 58)

    p.end()
    return pm


class GuildSplash(QSplashScreen):
    """Frameless, always-on-top guild certificate shown during startup."""

    def __init__(self, dpr: float = 1.0):
        super().__init__(_render_card(dpr))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)


def make_splash(app) -> GuildSplash:
    """Build, show, and paint the splash. Caller closes it with
    ``splash.finish(window)`` once the main window is ready."""
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    splash = GuildSplash(dpr)
    splash.show()
    app.processEvents()   # force an immediate paint before the slow init begins
    return splash
