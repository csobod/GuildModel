"""Hotkey + toolbar customization model (BUILDPLAN M7.15).

A small, mostly-pure layer over the main window's actions so the maker can rebind
shortcuts and choose / order the toolbar buttons (Preferences ▸ Hotkeys / Toolbar),
persisted in ``~/.guildcam/prefs.json``. The data logic here — effective bindings,
conflict detection, the effective toolbar order — is unit-testable apart from Qt;
the main window owns the actual `QAction`s and applies the result.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    """One customizable action: a stable key, a human label, its shipped default
    shortcut, a toolbar group, and whether it sits on the default toolbar."""
    key: str
    label: str
    default_shortcut: str
    group: str               # "input" | "build" | "view" | "util" — toolbar grouping
    toolbar_default: bool


def effective_shortcuts(specs, overrides: dict) -> dict[str, str]:
    """key → the shortcut to use: the user override if present, else the default."""
    out: dict[str, str] = {}
    for s in specs:
        out[s.key] = overrides.get(s.key, s.default_shortcut)
    return out


def find_conflicts(bindings: dict[str, str]) -> dict[str, list[str]]:
    """Map a shortcut → the action keys that share it, for any non-empty shortcut
    bound to more than one action. Empty result means no conflicts."""
    by_sc: dict[str, list[str]] = defaultdict(list)
    for key, sc in bindings.items():
        if sc:
            by_sc[sc].append(key)
    return {sc: keys for sc, keys in by_sc.items() if len(keys) > 1}


def effective_toolbar(specs, saved) -> list[str]:
    """The ordered action keys to place on the toolbar.

    ``saved`` is a list of keys from prefs (a custom order/selection) or None/empty
    for the shipped default. Saved keys are filtered to those that still exist, so a
    stale prefs file can't break the toolbar; the default preserves registry order.
    """
    valid = {s.key for s in specs}
    if saved:
        return [k for k in saved if k in valid]
    return [s.key for s in specs if s.toolbar_default]


def normalize_shortcut(text: str) -> str:
    """Canonicalise a shortcut string via QKeySequence (e.g. 'ctrl+s' → 'Ctrl+S'),
    so equal bindings compare equal. Empty/invalid → ''. Needs a QGuiApplication."""
    if not text:
        return ""
    from PySide6.QtGui import QKeySequence
    seq = QKeySequence(text)
    return seq.toString(QKeySequence.SequenceFormat.PortableText)
