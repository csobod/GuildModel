"""Tooltips, app-wide (2026-09-27): wrapped to a readable width, and off
altogether when the maker says so.

Qt shows a plain-text tooltip on one line, however long — a sentence of
guidance becomes a ribbon across the screen. `format_tooltip` breaks a plain
tooltip into balanced lines of about fifty-six characters, measured in the
tooltip's own font so the width holds at any UI scale, and hands Qt plain
text with those line breaks, which it lays out exactly as given. (Rich text
would not do: QLabel word-wraps a rich-text tip at a width of its own
choosing — a squarish block — and re-breaks the lines.) A tooltip an author
already wrote as rich text is left alone.

`TooltipFilter` sits on the QApplication and does that for every widget, so
the two hundred `setToolTip` calls in the app need no change. It is also the
global switch: off, every tooltip is swallowed except the ones a caller
exempts — the toolbar's own ? button, which must still say what it does.

The filter runs on every event the app delivers, so it is one `type()`
comparison and an early return, and it imports nothing (GuildDraw's macOS
gate hang, 2026-09: an import inside an app-wide filter runs the shiboken
import hook per event).
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QToolTip, QWidget

#: Characters per line, roughly — measured as average character widths.
LINE_CHARS = 56

#: A tooltip an author wrote as rich text: any HTML-looking tag in it. Qt's own
#: `mightBeRichText` lives in QtGui's C++ namespace and PySide does not expose it.
_RICH = re.compile(r"<\s*/?\s*[a-zA-Z][^<>]*>")


def _greedy(text: str, metrics: QFontMetrics, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        candidate = word if not line else line + " " + word
        if line and metrics.horizontalAdvance(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line or not lines:
        lines.append(line)
    return lines


def _wrap_paragraph(text: str, metrics: QFontMetrics, width: int) -> list[str]:
    """Wrap at `width`, then even the lines out: a greedy wrap in a
    proportional font leaves one line of forty characters over one of
    twenty-eight, so the width is narrowed as far as it goes without needing
    another line, and every line fills about the same."""
    lines = _greedy(text, metrics, width)
    n = len(lines)
    if n <= 1:
        return lines
    step = max(1, width // 40)
    for w in range(width - step, width // 2, -step):
        trial = _greedy(text, metrics, w)
        if len(trial) > n:
            break
        lines = trial
    return lines


def format_tooltip(text: str, metrics: QFontMetrics | None = None,
                   chars: int = LINE_CHARS) -> str:
    """`text` re-broken into balanced lines of about `chars` characters of
    `metrics`'s font — plain text, newline-separated, which Qt shows as is.
    Hand-wrapped lines reflow (see `_paragraphs`); rich text comes back
    unchanged; with no metrics the text is returned as written."""
    if not text or _RICH.search(text) or metrics is None:
        return text
    width = int(metrics.averageCharWidth() * chars)
    lines: list[str] = []
    for paragraph in _paragraphs(text):
        if paragraph == "":
            lines.append("")                         # a blank line between paragraphs
        else:
            lines.extend(_wrap_paragraph(paragraph, metrics, width))
    return "\n".join(lines)


_BULLET = ("\u2022", "-", "*", "\u2013", "\u2014")


def _paragraphs(text: str) -> list[str]:
    """Reflow an author's hand-wrapped lines. A single newline is a soft break
    (most tooltips here were wrapped by hand at seventy-odd characters, and
    wrapping those again leaves ragged short lines); a blank line, a line
    ending in a colon, or a line that starts a bullet keeps its break."""
    out: list[str] = []
    current = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if current:
                out.append(current)
                current = ""
            out.append("")
            continue
        if current and not (current.endswith(":") or line.startswith(_BULLET)):
            current += " " + line
        else:
            if current:
                out.append(current)
            current = line
    if current:
        out.append(current)
    return out


class TooltipFilter(QObject):
    """See the module docstring. `enabled` is the global switch; `set_exempt`
    names the widgets whose tooltips show even when it is off."""

    def __init__(self, enabled: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = bool(enabled)
        self._exempt: list = []

    def set_exempt(self, widgets) -> None:
        self._exempt = [w for w in widgets if w is not None]

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt)
        if event.type() != QEvent.Type.ToolTip:
            return False
        if not isinstance(obj, QWidget):
            return False
        if not self.enabled and not any(obj is w for w in self._exempt):
            return True                              # swallowed: nothing shows
        text = obj.toolTip()
        if not text:
            return False                             # an item view's own tips, as Qt shows them
        # Measured in the tooltip's own font, which is what the tip is set in.
        QToolTip.showText(event.globalPos(),
                          format_tooltip(text, QFontMetrics(QToolTip.font())), obj)
        return True
