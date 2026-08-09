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

#: Bumped whenever a shipped default changes in a way an existing prefs file
#: should be carried over to rather than pinned away from. `load()` runs the
#: migrations between a file's version and this one, then stamps it.
#:
#: Needed because `save()` writes *every* key, so a maker who has ever opened
#: Preferences has every default frozen into their file — changing a default
#: then reaches new installs only, and there is no way to tell a value they
#: chose from one they inherited. A version says which defaults they could
#: possibly have had an opinion about.
#:
#: 1 — M-N3 (2026-08-08): the model kernel default moved raster -> mesh.
PREFS_VERSION = 1

DEFAULTS: dict = {
    "prefs_version":         PREFS_VERSION,
    # Appearance
    "dark_mode":             False,
    # UI scale. "auto" derives it from the panel's true DPI against the 96 Qt
    # assumes — necessary because VTK forces the app onto XWayland, where there
    # is no compositor scale to follow and everything renders ~68% too small on
    # a HiDPI panel. A number pins it; 1.0 turns it off. See gui/hidpi.py.
    "ui_scale":              "auto",
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
    # Ask, when saving / exporting a changed worktable, whether to make it the
    # default bed. The "Don't ask again" checkbox in that prompt sets this False.
    "prompt_set_default_bed": True,
    # Recently opened files (most recent first)
    "recent_files":          [],
    # Which kernel builds the frame front's 3D model — one of
    # `gui.mesh_build.KERNELS`. "raster" is the M17 heightfield, "brep" is
    # OpenCASCADE (BUILDPLAN Stage 2), "mesh" is Manifold (BUILDPLAN-NEW M-N1).
    #
    # **"mesh" as of M-N3** (2026-08-08). The condition this line used to state
    # — posted G-code shown byte-equivalent — is met, and tracing why was worth
    # more than the gate: the CAM never sees a kernel. Every G-code path builds
    # a `CastleRelief` from the partition and posts from that, so this setting
    # governs the 3D model and the edges drawn on it, and nothing a machine
    # cuts. `test_kernel_flip_mn3` pins both the parity and that insulation.
    #
    # Parity over 12 feature combinations x 3 drawings: volume within 0.0413%,
    # silhouette within 0.3609%, every build verified on both kernels. It is
    # also 20-55x faster (0.23-0.70 s against 12.75-37.91 s) and, unlike the
    # raster, carries the feature edges the viewer's edge modes draw.
    #
    # Keeping all three alive is not indecision — building the same part three
    # ways is what has caught every silent defect this season.
    "model_kernel":          "mesh",
    # Superseded by `model_kernel`; read once on load to carry a maker's
    # existing choice over, then dropped. See `_migrate`.
    "use_solid_model":       False,
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


# The depth per pass M12.4 shipped as the default. It was never validated on the
# machine and turned out to be a full-depth bite on a temple blank (M15), so a
# stored value at or above it is almost certainly the old default carried forward
# rather than a number the maker chose — a deliberate choice would have been
# *lower*, since 4.0 was already the ceiling acetate allowed.
_M124_STEPDOWN_MM = 4.0


def _retire_m124_stepdown(cam: dict) -> None:
    """Drop an M12.4-era `contour_stepdown_mm` so the upgrade actually takes.

    Prefs are restored over the schema defaults on every launch, so lowering the
    shipped default alone would have changed nothing for anyone who had already
    run GuildModel: their saved 4.0 would keep cutting temples in one pass. Values
    the maker really did tune (anything below the old default) are left alone.
    """
    try:
        if float(cam.get("contour_stepdown_mm", 0.0)) >= _M124_STEPDOWN_MM:
            cam.pop("contour_stepdown_mm", None)      # fall back to the schema default
    except (TypeError, ValueError):
        cam.pop("contour_stepdown_mm", None)


def _migrate_model_kernel(data: dict, merged: dict) -> None:
    """Carry a saved `use_solid_model` over to `model_kernel` (BUILDPLAN-NEW M-N2).

    A maker who had switched the B-Rep path on must not be silently moved back
    to the raster by an upgrade — prefs are restored over the schema defaults on
    every launch, so a new key with a new default would do exactly that.

    Only applies when the old key is present and the new one is not, so it
    cannot override a choice made since.
    """
    if "model_kernel" in data or not data.get("use_solid_model"):
        return
    merged["model_kernel"] = "brep"


def _migrate_kernel_flip(data: dict, merged: dict) -> None:
    """Carry a pre-M-N3 file onto the mesh kernel (BUILDPLAN-NEW M-N3).

    A file written before `PREFS_VERSION` existed has `"model_kernel":
    "raster"` in it whether the maker chose that or merely never opened
    Preferences, because `save()` writes every key. Left alone they would keep
    the old default forever and the flip would reach new installs only.

    So a *raster* setting from an unversioned file is treated as inherited and
    moved. `"brep"` is left exactly where it is: that one can only have got
    there by a deliberate choice or by `_migrate_model_kernel` carrying one
    over, and moving it would be the silent reassignment that migration exists
    to prevent.

    Only fires once — `load()` stamps the version, `save()` writes it back.
    """
    if data.get("prefs_version", 0) >= 1:
        return
    if merged.get("model_kernel") == "raster":
        merged["model_kernel"] = DEFAULTS["model_kernel"]


def load() -> dict:
    """Return prefs dict, merged with DEFAULTS so all keys are present."""
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULTS, **data}
            _migrate_model_kernel(data, merged)
            _migrate_kernel_flip(data, merged)
            merged["prefs_version"] = PREFS_VERSION
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
            _retire_m124_stepdown(merged["cam_params"])
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
