"""
Persistent user preferences — stored in ~/.guildmodel/prefs.json.

Modeled line-for-line on GuildDraw's framedraft/prefs.py (the reference
behaviour): all keys are listed in DEFAULTS, load() merges saved data over
defaults so future versions that add new keys always have a valid value,
and save() is silent on write errors.
"""

import json
import pathlib

_DIR = pathlib.Path.home() / ".guildmodel"
_FILE = _DIR / "prefs.json"

DEFAULTS: dict = {
    # Appearance
    "dark_mode":             False,
    # Viewport backdrop preset for the 2D canvases + 3D viewport ("auto"
    # follows the UI mode; other presets pin the backdrop in both modes —
    # carried over from GuildDraw) — Preferences ▸ Appearance.
    "viewport":              {"preset": "auto", "custom_bg": "#faf6ee"},
    # 3D render: light rig (studio/directional/flat), key-light direction +
    # strength, and the model surface color ("" = theme default amber).
    "render3d":              {"rig": "studio", "azimuth_deg": -27.0,
                              "elevation_deg": 61.0, "intensity": 0.8,
                              "model_color": ""},
    # Toolpath-overlay color set: vivid | soft | bold | mono.
    "toolpath_palette":      "vivid",
    # Per-layer 2D drawing-color overrides, per UI mode — Preferences ▸ Layers
    # (GuildDraw parity). {layer: {"light": "#rrggbb"|"", "dark": ...}};
    # "" / absent = the shipped core.layers.LAYER_STYLES color.
    "layer_colors":          {},
    # 2D design-canvas grid — Preferences ▸ Appearance ▸ Grid (GuildDraw
    # parity). Shipped values reproduce the historical 10 mm dotted grid.
    "grid": {
        "visible":        True,
        "spacing_mm":     10.0,
        "major_every":    5,     # every Nth line heavier; 1 = all minor
        "minor_color":    "",    # "" = follow the theme
        "major_color":    "",    # "" = follow the minor color
        "major_width_px": 1.0,
    },
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
    # CAM tab: persisted CastleCamParams (machine/tool/strategy/feeds) — M4.8.
    # {} = first run, fall back to the schema defaults.
    "cam_params":            {},
    # Selected material (drives feeds/speeds/stepover/stepdown) — M4.x.
    "material_name":         "acetate",
    # Hotkey overrides (action-key → shortcut string) — M7.15. {} = shipped defaults.
    "hotkeys":               {},
    # Toolbar action order (list of action keys) — M7.15. [] = the default toolbar.
    "toolbar":               [],
}


def load() -> dict:
    """Return prefs dict, merged with DEFAULTS so all keys are present."""
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULTS, **data}
            # Deep-merge nested dicts so new default keys survive old prefs
            # files (GuildDraw's rule). EVERY nested dict pref must be listed
            # here — a missing entry means old files silently clobber new
            # defaults. ("toolbar" is a list, not a dict — excluded.)
            for key in ("viewport", "render3d", "grid", "layer_colors",
                        "cam_params", "hotkeys"):
                if isinstance(data.get(key), dict):
                    merged[key] = {**DEFAULTS[key], **data[key]}
                else:
                    merged[key] = dict(DEFAULTS[key])
            return merged
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
