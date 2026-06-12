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
    # Recently opened files (most recent first)
    "recent_files":          [],
    # 3D preview / STL export grid resolution (mm)
    "preview_resolution_mm": 0.3,
    "export_resolution_mm":  0.15,
    # Last folder used for G-code / STL output ("" = system default)
    "last_output_dir":       "",
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
