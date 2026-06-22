"""The multi-component project model (BUILDPLAN M7.1).

A project is an ordered list of role-typed `Component`s (frame front + temples +
per-lens base-curve templates). These tests cover the kind↔params/label/zone
helpers, the Component model (totality + round-trip), the ProjectSchema
`components` accessors + the legacy single-component migration, and the
per-component CAM dispatcher that routes a Component to its M3/M6 generator.
"""
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon

from guildcam.core.project.schema import (
    BaseCurveBlockParams,
    CastleParams,
    Component,
    ComponentKind,
    ProjectSchema,
    TempleParams,
    component_fixture_zone,
    component_label,
    component_param_field,
    lens_side,
)
from guildcam.core.cam.component import (
    ComponentGeometry,
    ComponentProgram,
    build_component_ops,
)
from guildcam.core.cam.block_ops import BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS
from guildcam.core.cam.temple_ops import TEMPLE_CONTOUR_OPS

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildcam" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())

ALL_KINDS = list(ComponentKind)

# synthetic geometry (mirrors test_temple_m63 / test_block_m64)
TEMPLE_OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
TEMPLE_ENGRAVING = [[(-40, 0), (-30, 3), (-20, 0)], [(10, -2), (40, -2)]]
LENS = Polygon([(40, 10), (60, 18), (66, 30), (58, 42), (42, 40), (36, 26)])


# ------------------------------------------------------------------ kind helpers

def test_kind_helpers_total_over_every_kind():
    """Every kind has a label, a fixture zone, and a param field."""
    for kind in ALL_KINDS:
        assert component_label(kind)                       # non-empty
        assert component_fixture_zone(kind)
        assert component_param_field(kind) in {"castle", "temple", "base_curve_block"}


def test_lens_side_only_for_base_curve():
    assert lens_side(ComponentKind.BASE_CURVE_RIGHT) == "right"
    assert lens_side(ComponentKind.BASE_CURVE_LEFT) == "left"
    assert lens_side(ComponentKind.FRAME_FRONT) is None
    assert lens_side(ComponentKind.TEMPLE_RIGHT) is None


def test_left_kinds_get_left_fixture_zones():
    assert component_fixture_zone(ComponentKind.TEMPLE_LEFT) == "temple_left"
    assert component_fixture_zone(ComponentKind.BASE_CURVE_LEFT) == "bc_template_left"


# ------------------------------------------------------------------ Component model

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_for_kind_populates_matching_param_only(kind):
    c = Component.for_kind(kind)
    field = component_param_field(kind)
    assert getattr(c, field) is not None                   # matching param built
    assert c.params() is getattr(c, field)
    assert c.label == component_label(kind)
    assert c.id == kind.value


def test_default_param_carries_the_kinds_fixture_zone():
    """A default-built temple/block component gets its side's fixture zone."""
    tl = Component.for_kind(ComponentKind.TEMPLE_LEFT)
    assert isinstance(tl.params(), TempleParams)
    assert tl.params().fixture_zone == "temple_left"
    assert tl.fixture_zone() == "temple_left"

    bl = Component.for_kind(ComponentKind.BASE_CURVE_LEFT)
    assert isinstance(bl.params(), BaseCurveBlockParams)
    assert bl.params().fixture_zone == "bc_template_left"


def test_component_json_round_trip_preserves_kind_and_params():
    c = Component.for_kind(ComponentKind.TEMPLE_RIGHT)
    c.params().engrave_depth_mm = 0.5                       # an edit to survive the trip
    back = Component.model_validate_json(c.model_dump_json())
    assert back.kind == ComponentKind.TEMPLE_RIGHT
    assert isinstance(back.params(), TempleParams)
    assert back.params().engrave_depth_mm == pytest.approx(0.5)
    assert back == c


# ------------------------------------------------------------------ ProjectSchema

def test_components_accessors_and_unique_ids():
    p = ProjectSchema(job_name="Model")
    p.add_component(Component.for_kind(ComponentKind.FRAME_FRONT))
    p.add_component(Component.for_kind(ComponentKind.TEMPLE_RIGHT))
    p.add_component(Component.for_kind(ComponentKind.TEMPLE_LEFT))
    # a second frame front (a run) gets a uniquified id, not a clobber
    dup = p.add_component(Component.for_kind(ComponentKind.FRAME_FRONT))
    assert dup.id == "frame_front_2"

    assert p.frame_front().kind == ComponentKind.FRAME_FRONT
    assert len(p.components_of_kind(ComponentKind.FRAME_FRONT)) == 2
    assert p.component(ComponentKind.TEMPLE_LEFT).id == "temple_left"
    assert len({c.id for c in p.components}) == len(p.components)


def test_ensure_components_migrates_legacy_single_component():
    p = ProjectSchema(job_name="Legacy", source_file="frame.dxf")
    p.castle.zones.endpiece_mm = 6.1                        # a non-default edit
    assert p.components == []                               # legacy: empty

    p.ensure_components()
    assert len(p.components) == 1
    ff = p.components[0]
    assert ff.kind == ComponentKind.FRAME_FRONT
    assert ff.castle.zones.endpiece_mm == pytest.approx(6.1)  # carries the flat castle
    assert ff.source_file == "frame.dxf"
    assert ff.forming == p.forming

    p.ensure_components()                                   # idempotent
    assert len(p.components) == 1


def test_ensure_components_noop_when_already_multi():
    p = ProjectSchema(job_name="Model")
    p.add_component(Component.for_kind(ComponentKind.FRAME_FRONT))
    p.add_component(Component.for_kind(ComponentKind.TEMPLE_RIGHT))
    p.ensure_components()
    assert len(p.components) == 2                           # untouched


def test_project_with_components_json_round_trip():
    p = ProjectSchema(job_name="Full")
    for kind in ALL_KINDS:
        p.add_component(Component.for_kind(kind))
    back = ProjectSchema.model_validate_json(p.model_dump_json())
    assert [c.kind for c in back.components] == ALL_KINDS
    assert isinstance(back.component(ComponentKind.BASE_CURVE_RIGHT).params(),
                      BaseCurveBlockParams)


# ------------------------------------------------------------------ dispatcher

def test_dispatch_temple_routes_to_temple_generator():
    c = Component.for_kind(ComponentKind.TEMPLE_RIGHT)
    geom = ComponentGeometry(outline=TEMPLE_OUTLINE, engraving_curves=TEMPLE_ENGRAVING)
    prog = build_component_ops(c, geom, TOOLS)
    assert isinstance(prog, ComponentProgram)
    assert prog.fixture_zone == "temple_right"
    assert prog.contour_op_names == set(TEMPLE_CONTOUR_OPS)
    assert prog.drill_op_names == set()
    names = {op.name for op in prog.ops}
    assert "Temple Profile" in names and "Engraving" in names
    assert prog.stock.blank_width_mm == pytest.approx(30.0)   # temple default blank


def test_dispatch_base_curve_routes_to_block_generator():
    c = Component.for_kind(ComponentKind.BASE_CURVE_LEFT)
    geom = ComponentGeometry(lens_outline=LENS)
    prog = build_component_ops(c, geom, TOOLS)
    assert prog.fixture_zone == "bc_template_left"
    assert prog.contour_op_names == set(BLOCK_CONTOUR_OPS)
    assert prog.drill_op_names == set(BLOCK_DRILL_OPS)
    names = {op.name for op in prog.ops}
    assert names & set(BLOCK_DRILL_OPS) and "Block Profile" in names


def test_dispatch_missing_geometry_raises():
    temple = Component.for_kind(ComponentKind.TEMPLE_RIGHT)
    with pytest.raises(ValueError):
        build_component_ops(temple, ComponentGeometry(), TOOLS)

    front = Component.for_kind(ComponentKind.FRAME_FRONT)
    with pytest.raises(ValueError):                          # no relief
        build_component_ops(front, ComponentGeometry(), TOOLS, tool=TOOLS["flat_3175"])


# ------------------------------------------------------------------ .gcam migration

def test_legacy_gcam_loads_as_one_component_project(tmp_path):
    """A .gcam saved without `components` (M5.1–M6.5) reopens as one frame_front."""
    from guildcam.core.project.gcam import load_gcam, save_gcam

    p = ProjectSchema(job_name="Legacy", source_file="frame.dxf")
    p.castle.zones.endpiece_mm = 5.9
    assert p.components == []                                # legacy: no components
    path = tmp_path / "legacy.gcam"
    save_gcam(path, project=p, dxf_bytes=b"dxf")

    b = load_gcam(path)
    assert len(b.project.components) == 1
    ff = b.project.components[0]
    assert ff.kind == ComponentKind.FRAME_FRONT
    assert ff.castle.zones.endpiece_mm == pytest.approx(5.9)  # carried from the flat castle
    assert isinstance(ff.params(), CastleParams)


def test_multi_component_gcam_round_trips_without_migration(tmp_path):
    """A project that already has components is loaded unchanged (no phantom add)."""
    from guildcam.core.project.gcam import load_gcam, save_gcam

    p = ProjectSchema(job_name="Model")
    p.add_component(Component.for_kind(ComponentKind.FRAME_FRONT))
    p.add_component(Component.for_kind(ComponentKind.TEMPLE_RIGHT))
    path = tmp_path / "model.gcam"
    save_gcam(path, project=p, dxf_bytes=b"dxf")

    b = load_gcam(path)
    assert [c.kind for c in b.project.components] == [
        ComponentKind.FRAME_FRONT, ComponentKind.TEMPLE_RIGHT]
