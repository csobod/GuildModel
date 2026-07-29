"""The worktable posting must be the single-component posting, placed.

Regression suite for INCIDENT-2026-07-29 (worktable G-code thrashes the machine).
The bed program was generated from a relief rasterized at the **3D-preview** grid
(0.4 mm) while the single-component program used 0.15 mm. Coarse grid → the
terrace footing blends alias into a staircase → `_bilinear_sample` rides the
staircase → the Z axis reverses direction on roughly every other cutting move.
On real hardware that program had to be E-stopped.

Three properties keep it fixed, matching the incident's definition of done:

1. **One grid, one clamp.** `CUT_RES_MM` is what posting paths rasterize on, and
   `clamp_cam_to_machine` is the single seam that applies machine + material
   limits (§7.1).
2. **Placement, not regeneration.** A part's ops on the bed are its standalone ops
   plus a rigid transform — same point count, same Z at the same local XY (§7.2).
3. **Z-thrash gate.** Relief ops built on the posting grid stay under a reversal
   density the machine can actually follow (§7.3).

Headless (numpy + shapely + the demo DXF); no Qt.
"""
from pathlib import Path

import math
import pytest
import yaml

from guildmodel.core.cam.castle_ops import generate_castle_program
from guildmodel.core.cam.layout import (
    BedPart, build_nest_program, nest_components_on_worktable, transform_ops,
)
from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
from guildmodel.core.post.machine import clamp_cam_to_machine
from guildmodel.core.project.schema import (
    BedRole, CastleCamParams, CastleParams, MachineProfile, Worktable, WorktableZone,
)
from guildmodel.core.relief.castle import CUT_RES_MM, PREVIEW_RES_MM, build_castle_relief

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())

RELIEF_OPS = ("Rough Relief", "Fine Relief")

# The Guild CNC's Z axis: $112 = 400 mm/min, and the incident's single-component
# program — which cut cleanly — ran 16.5 reversals per 100 mm on the rough pass
# and 8.3 on the fine. The bed program ran 55.8 / 48.3 and had to be E-stopped.
# Gate midway, well clear of good and nowhere near bad.
MAX_Z_REVERSALS_PER_100MM = 25.0


# ------------------------------------------------------------------ helpers

def _demo_front():
    """The demo frame front: (partition, hinge polys)."""
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _castle_ops(partition, hinges, castle, cam, resolution):
    """One frame front's ops, exactly as every posting path builds them."""
    relief = build_castle_relief(partition, castle, hinges, resolution=resolution)
    return generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"],
                                   params=cam, tools_cfg=TOOLS)


def _z_reversals_per_100mm(op) -> float:
    """Z direction reversals per 100 mm of XY travel — the incident's metric."""
    xy = 0.0
    revs = 0
    prev = 0
    for path in op.paths:
        for a, b in zip(path, path[1:]):
            xy += math.hypot(b[0] - a[0], b[1] - a[1])
            dz = b[2] - a[2]
            s = 0 if abs(dz) < 1e-9 else (1 if dz > 0 else -1)
            if s and prev and s != prev:
                revs += 1
            if s:
                prev = s
    return revs / max(xy, 1e-9) * 100.0


@pytest.fixture(scope="module")
def demo_front():
    return _demo_front()


@pytest.fixture(scope="module")
def cut_ops(demo_front):
    partition, hinges = demo_front
    return _castle_ops(partition, hinges, CastleParams(), CastleCamParams(), CUT_RES_MM)


# ------------------------------------------------------------------ §7.1 one grid

def test_cut_grid_is_finer_than_the_preview_grid():
    """The posting grid is a separate, finer constant — not the preview one.

    The whole incident is that a `.nc` inherited a grid chosen for pixels."""
    assert CUT_RES_MM < PREVIEW_RES_MM
    assert CUT_RES_MM <= 0.2      # at/below VALIDATE_RES_MM: blends are resolved


def test_nest_worker_cannot_be_given_a_resolution():
    """`NestWorker` / `BedSimWorker` post-facing ops: no caller-chosen grid.

    The bug was a call site passing `max(0.4, prefs["preview_resolution_mm"])`.
    Removing the parameter is what makes that unrepeatable, so guard the signature.
    """
    pytest.importorskip("PySide6")
    import inspect

    from guildmodel.gui.app import BedSimWorker, NestWorker

    for cls in (NestWorker, BedSimWorker):
        assert "resolution" not in inspect.signature(cls.__init__).parameters, (
            f"{cls.__name__} takes a resolution again — a preview grid can reach "
            "posted G-code (INCIDENT-2026-07-29)")


# ------------------------------------------------------------------ §7.1 one clamp

def test_clamp_cam_to_machine_caps_stepdown_to_machine_and_material():
    machine = MachineProfile(max_doc_mm=2.0)
    cam = CastleCamParams(contour_stepdown_mm=5.0)

    clamped, out = clamp_cam_to_machine(cam, machine, {"max_doc_mm": 1.2})
    assert clamped.contour_stepdown_mm == pytest.approx(1.2)   # material is tighter
    assert out.contour_stepdown_mm == pytest.approx(1.2)
    assert any("stepdown" in w for w in out.warnings)


def test_clamp_cam_to_machine_falls_back_to_material_feeds():
    """An unset cam feed resolves from the material, like the castle path always did."""
    cam = CastleCamParams(feed_rate_mmpm=0.0, plunge_rate_mmpm=0.0, spindle_rpm=0)
    _clamped, out = clamp_cam_to_machine(cam, MachineProfile(), MATS["acetate"])
    assert out.feed_rate_mmpm == pytest.approx(
        min(MATS["acetate"]["feed_rate_mmpm"], MachineProfile().max_feed_mmpm))
    assert out.spindle_rpm > 0


def test_clamp_cam_to_machine_linearizes_without_arc_support():
    _clamped, out = clamp_cam_to_machine(
        CastleCamParams(arc_tolerance_mm=0.05),
        MachineProfile(supports_arcs=False), MATS["acetate"])
    assert out.arc_tol_mm == 0.0


# ------------------------------------------------------------------ §7.2 placement

def _one_part_bed(ops):
    bed = Worktable(zones=[WorktableZone(
        id="front", role=BedRole.FRAME_FRONT,
        polygon=[(120.0, 60.0), (220.0, 60.0), (220.0, 150.0), (120.0, 150.0)])])
    part = BedPart("frame_front", "Frame", "", ops, set(CASTLE_CONTOUR_OPS), set())
    return nest_components_on_worktable([part], bed)


def test_bed_ops_are_the_standalone_ops_plus_a_rigid_transform(cut_ops):
    """§7.2: same point count, and Z identical at the same *local* XY.

    The bad worktable program had 848 rough-relief points against the standalone
    program's 798, a 0.8 mm narrower footprint and Z differing by up to 0.845 mm at
    coinciding XY — it had regenerated the surface, not placed it.
    """
    nest = _one_part_bed(cut_ops)
    (placement,) = nest.placements
    dx, dy = placement.dx, placement.dy

    placed = {op.name: op for op in placement.ops}
    for name in RELIEF_OPS:
        src, dst = next(o for o in cut_ops if o.name == name), placed[name]
        assert len(src.paths) == len(dst.paths), f"{name}: path count changed"
        for a, b in zip(src.paths, dst.paths):
            assert len(a) == len(b), f"{name}: point count changed"
            for (x0, y0, z0), (x1, y1, z1) in zip(a, b):
                # XY to the placement's own precision: the ops carry the exact
                # translation, `dx`/`dy` are the reported copy rounded to 1 µm.
                assert x1 - dx == pytest.approx(x0, abs=1e-3)
                assert y1 - dy == pytest.approx(y0, abs=1e-3)
                # Z is untouched by placement — this is the one the incident broke.
                assert z1 == z0, f"{name}: Z changed on the bed"


def test_bed_program_preserves_relief_z_travel(cut_ops):
    """The combined post must not inflate Z travel — the incident's headline symptom
    was total |dZ| roughly doubling for the same surface."""
    nest = _one_part_bed(cut_ops)
    prog = build_nest_program(nest)

    def total_dz(op):
        return sum(abs(b[2] - a[2]) for p in op.paths for a, b in zip(p, p[1:]))

    for name in RELIEF_OPS:
        src = next(o for o in cut_ops if o.name == name)
        dst = next(o for o in prog.ops if o.name == f"Frame · {name}")
        assert total_dz(dst) == pytest.approx(total_dz(src), rel=1e-9)


def test_placement_transform_survives_an_interactive_rotation(cut_ops):
    """A placement is `p → R(rotation_deg)·p + (dx, dy)`, and stays that way after
    the maker spins it on the bed — the setup sheet reports those numbers to the
    operator and a re-post has to be able to reproduce the placed ops from them."""
    nest = _one_part_bed(cut_ops)
    (placement,) = nest.placements
    placement.rotate(37.0)

    rebuilt = transform_ops(cut_ops, placement.dx, placement.dy, placement.rotation_deg)
    for src, dst in zip(rebuilt, placement.ops):
        for a, b in zip(src.paths, dst.paths):
            for (x0, y0, _z0), (x1, y1, _z1) in zip(a, b):
                # 1 µm: `dx`/`dy` are stored rounded (see the parity test above).
                assert x1 == pytest.approx(x0, abs=2e-3)
                assert y1 == pytest.approx(y0, abs=2e-3)


# ------------------------------------------------------------------ §7.3 Z-thrash

def test_relief_ops_on_the_cut_grid_do_not_thrash_z(cut_ops):
    """The gate the incident asks for: bounded Z-reversal density on the relief ops."""
    for name in RELIEF_OPS:
        op = next(o for o in cut_ops if o.name == name)
        density = _z_reversals_per_100mm(op)
        assert density <= MAX_Z_REVERSALS_PER_100MM, (
            f"{name}: {density:.1f} Z reversals per 100 mm of XY travel exceeds "
            f"{MAX_Z_REVERSALS_PER_100MM} — the relief grid coarsened "
            "(INCIDENT-2026-07-29)")


def test_the_z_thrash_gate_has_teeth(demo_front):
    """The preview grid must actually fail the gate above.

    Without this the gate could pass for reasons unrelated to resolution and would
    not catch a regression to preview-grade posting.
    """
    partition, hinges = demo_front
    coarse = _castle_ops(partition, hinges, CastleParams(), CastleCamParams(),
                         max(PREVIEW_RES_MM, 0.4))
    worst = max(_z_reversals_per_100mm(next(o for o in coarse if o.name == n))
                for n in RELIEF_OPS)
    assert worst > MAX_Z_REVERSALS_PER_100MM, (
        "a preview-grade relief no longer trips the Z-thrash gate — the gate has "
        "stopped measuring what caused the incident")
