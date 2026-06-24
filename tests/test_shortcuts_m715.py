"""M7.15 — hotkey + toolbar customization model."""
from guildcam.gui.shortcuts import (
    ActionSpec, effective_shortcuts, effective_toolbar, find_conflicts,
)


def _specs():
    return [
        ActionSpec("open_model", "Open Drawing", "Ctrl+Shift+O", "input", True),
        ActionSpec("build", "Build 3D", "F5", "build", True),
        ActionSpec("gcode", "Generate G-code", "Ctrl+G", "build", True),
        ActionSpec("simulate", "Simulation", "Ctrl+Shift+S", "view", True),
        ActionSpec("show_worktable", "Worktable", "Ctrl+B", "view", False),
    ]


def test_effective_shortcuts_default_and_override():
    eff = effective_shortcuts(_specs(), {"build": "Ctrl+B"})
    assert eff["build"] == "Ctrl+B"            # override wins
    assert eff["gcode"] == "Ctrl+G"            # default kept
    assert eff["open_model"] == "Ctrl+Shift+O"


def test_no_conflicts_by_default():
    eff = effective_shortcuts(_specs(), {})
    assert find_conflicts(eff) == {}


def test_conflict_detected_when_two_actions_share_a_key():
    # rebind build to Worktable's Ctrl+B
    eff = effective_shortcuts(_specs(), {"build": "Ctrl+B"})
    conflicts = find_conflicts(eff)
    assert "Ctrl+B" in conflicts
    assert set(conflicts["Ctrl+B"]) == {"build", "show_worktable"}


def test_empty_shortcuts_never_conflict():
    eff = effective_shortcuts(_specs(), {"build": "", "gcode": ""})
    assert find_conflicts(eff) == {}


def test_effective_toolbar_default_order():
    order = effective_toolbar(_specs(), None)
    # default = the toolbar_default specs in registry order (worktable excluded)
    assert order == ["open_model", "build", "gcode", "simulate"]


def test_effective_toolbar_custom_order_and_selection():
    saved = ["simulate", "build", "show_worktable"]   # reordered + adds a non-default
    assert effective_toolbar(_specs(), saved) == ["simulate", "build", "show_worktable"]


def test_effective_toolbar_drops_unknown_keys():
    saved = ["build", "ghost_action", "gcode"]
    assert effective_toolbar(_specs(), saved) == ["build", "gcode"]


def test_roundtrip_override_then_clear_returns_default():
    specs = _specs()
    overrides = {"build": "Ctrl+Alt+B"}
    assert effective_shortcuts(specs, overrides)["build"] == "Ctrl+Alt+B"
    assert effective_shortcuts(specs, {})["build"] == "F5"   # reset to shipped default
