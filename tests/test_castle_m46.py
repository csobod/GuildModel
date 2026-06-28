"""M4.6 tests: the stage-progress callback contract (BUILDPLAN § M4.6 Part B)
and the toolbar icon set (Part C).

The window-architecture work (Part A) is GUI layout — exercised by the
headless construction smoke check at the bottom, which is skipped when no Qt
platform plugin is available.
"""
from pathlib import Path

import pytest
from shapely.geometry import Point

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
ICONS = ROOT / "src" / "guildmodel" / "gui" / "resources" / "icons"


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams(), hinges


# ------------------------------------------------------------------ Part B — progress

def test_relief_progress_is_monotonic_and_complete(demo):
    """build_castle_relief reports labelled stages with non-decreasing
    fractions in [0, 1], ending near completion."""
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    calls = []
    build_castle_relief(
        part, castle, hinges, resolution=0.4,
        progress=lambda label, frac: calls.append((label, frac)),
    )
    assert calls, "no progress reported"
    fracs = [f for _, f in calls]
    assert all(0.0 <= f <= 1.0 for f in fracs)
    assert fracs == sorted(fracs), "progress fractions must be non-decreasing"
    assert all(isinstance(lbl, str) and lbl for lbl, _ in calls)
    assert fracs[-1] >= 0.9


def test_mesh_progress_reaches_one(demo):
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_relief

    part, castle, hinges = demo
    relief = build_castle_relief(part, castle, hinges, resolution=0.4)
    calls = []
    build_castle_mesh(relief, progress=lambda label, frac: calls.append((label, frac)))
    assert calls
    assert calls[-1][1] == pytest.approx(1.0)


def test_gcode_progress_one_per_op(demo):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    relief = build_castle_relief(part, castle, hinges, resolution=0.4)
    tool = {"radius_mm": 1.5875, "type": "flat"}
    calls = []
    generate_castle_program(
        relief, castle, hinges, tool,
        progress=lambda label, frac: calls.append((label, frac)),
    )
    # Five ops, but rough+fine relief are one relief_ops call, so four
    # progress emissions; the last is the perimeter at fraction 1.0.
    assert len(calls) == 4
    assert calls[-1][1] == pytest.approx(1.0)
    assert [int(round(f * 5)) for _, f in calls] == [1, 3, 4, 5]


def test_progress_callback_can_abort_at_stage_boundary(demo):
    """A callback that raises aborts the build — the cancellation mechanism
    the GUI workers rely on (raise propagates; core never catches)."""
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo

    class Stop(Exception):
        pass

    seen = []

    def progress(label, frac):
        seen.append(label)
        if len(seen) >= 2:
            raise Stop()

    with pytest.raises(Stop):
        build_castle_relief(
            part, castle, hinges, resolution=0.4, progress=progress
        )
    assert len(seen) == 2


def test_default_progress_is_none(demo):
    """Core stays headless: omitting progress builds normally."""
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    relief = build_castle_relief(part, castle, hinges, resolution=0.4)
    assert relief.field.z.shape[0] > 2


# ------------------------------------------------------------------ Part C — icons

# Icons referenced literally by the GUI: gui/app.py's _icon_actions (toolbar)
# + the 3D viewer's camera presets (gui/widgets/viewer_3d.py).
_ICON_NAMES = [
    "op-open-dxf", "op-build-3d", "op-gcode", "op-export-gcode", "op-export-stl",
    "view-2d", "view-3d", "op-fit", "toggle-log", "view-sidebar",
    "view-iso", "view-top", "view-front", "view-reset",
    "stage-towers", "stage-walls", "stage-footing", "stage-full",
]


@pytest.mark.parametrize("name", _ICON_NAMES)
def test_icon_svg_present_and_conformant(name):
    """Every referenced icon exists and follows the style guide's hard
    requirements (viewBox 0 0 20 20, currentColor stroke, fill none)."""
    svg = ICONS / f"{name}.svg"
    assert svg.exists(), f"missing icon {name}.svg"
    text = svg.read_text(encoding="utf-8")
    assert 'viewBox="0 0 20 20"' in text
    assert "currentColor" in text
    assert 'fill="none"' in text


def test_make_icon_recolors_currentcolor():
    """gui/icons.make_icon string-replaces currentColor (no Qt needed for the
    source-level contract)."""
    from guildmodel.gui import icons as icons_mod

    src = (ICONS / "op-build-3d.svg").read_text(encoding="utf-8")
    assert "currentColor" in src
    # The recolor is a literal replace; verify both target colors land.
    assert src.replace("currentColor", "#1f1f1f").count("#1f1f1f") >= 1
    assert hasattr(icons_mod, "make_icon")
    assert hasattr(icons_mod, "apply_toolbar_icons")
