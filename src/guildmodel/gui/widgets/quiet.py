"""Fields that do not take the wheel unless they have focus (session two of
M20, 2026-10-14).

A spin box or a combo inside a scrolling sidebar takes the wheel by default,
so a scroll down the Worktable panel silently rewrote whatever field sat under
the pointer — the bed zero, a rotation, an offset. `ParamSlider`'s spin boxes
solved it for the Model tab with a subclass; this is the same rule as an event
filter, so any existing widget can be made quiet after the fact: it takes focus
on a click or Tab, and an unfocused wheel event goes on to the scroll area.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt


class _WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt)
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


def make_quiet(*widgets) -> None:
    """Give each widget a strong focus policy and the wheel guard."""
    for w in widgets:
        w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        guard = _WheelGuard(w)
        w.installEventFilter(guard)
        w._wheel_guard = guard           # keep it alive beside the widget
