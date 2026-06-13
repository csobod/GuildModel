"""
Persistent user preferences — stored in ~/.guildcam/prefs.json.

Modeled line-for-line on GuildDraw's framedraft/prefs.py (the reference
behaviour): all keys are listed in DEFAULTS, load() merges saved data over
defaults so future versions that add new keys always have a valid value,
and save() is silent on write errors.
"""

import json
import pathlib

_DIR = pathlib.Path.home() / ".guildcam"
_FILE = _DIR / "prefs.json"

DEFAULTS: dict = {
    # Appearance
    "dark_mode":             False,
    # Show the bottom log dock on startup (toggle the button to change it for
    # the session; this pref sets the default) — M4.6
    "show_log_on_start":     False,
    # Recently opened files (most recent first)
    "recent_files":          [],
    # 3D preview / STL export grid resolution (mm)
    "preview_resolution_mm": 0.3,
    "export_resolution_mm":  0.15,
    # Last folder used for G-code / STL output ("" = system default)
    "last_output_dir":       "",
    # Main-window geometry + dock/toolbar state (base64 QByteArray strings;
    # "" = first run, fall back to the coded default layout) — M4.6 Part A.5
    "main_window_geometry":  "",
    "main_window_state":     "",
}


def load() -> dict:
    """Return prefs dict, merged with DEFAULTS so all keys are present."""
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
    except Exception:
        pass
    return dict(DEFAULTS)


def save(prefs: dict) -> None:
    """Write prefs dict to disk.  Silently ignores write errors."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass
