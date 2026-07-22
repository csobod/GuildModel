"""Per-component CAM dispatch (BUILDPLAN M7.1).

The seam that turns a project `Component` (kind + params) plus its prepared
geometry into a posted-ready op list, routing to the right M3/M6 generator by
kind. Per-component **Generate** (M7.3) and the worktable bed program (M7.6) both
build on this, so the five component kinds share one entry point — and the
returned `ComponentProgram` carries exactly the op-name sets + stock the post and
the M6.5 bed nesting (`cam/layout.py` `BedPart`) need.

Geometry is *not* stored on the schema (it is derived from the embedded source);
the caller prepares the kind-appropriate inputs on a `ComponentGeometry` and the
heavy frame-front relief build stays in the worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon

from ..project.schema import (
    CastleCamParams,
    Component,
    ComponentKind,
    StockDefinition,
)
from .block_ops import BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program
from .castle_ops import CamOp, generate_castle_program
from .temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program

# The castle's through-cut ops (the partial-lap ramped contours) — matches the
# default in write_castle_program. "Holes" (decorative OUTLINE openings) is an
# inside through-cut like the eyewires, so it rides the same ramped entry.
CASTLE_CONTOUR_OPS = {"Eyewires", "Holes", "Perimeter"}


@dataclass
class ComponentGeometry:
    """Kind-appropriate geometry for one component (the caller prepares it).

    - frame_front: `relief` (a built CastleRelief) + `hinge_polys`
    - temple_*:    `outline` (the OUTLINE) + `engraving_curves`
    - base_curve_*: `lens_outline` (a LENS interior from the frame)
    """
    relief: object | None = None                 # CastleRelief (kept loose to avoid the import)
    hinge_polys: list[Polygon] = field(default_factory=list)
    outline: Polygon | None = None
    engraving_curves: list[list[tuple[float, float]]] = field(default_factory=list)
    lens_outline: Polygon | None = None


@dataclass
class ComponentProgram:
    """A built component's ops plus the metadata the post / bed nesting need.

    Maps straight onto `cam/layout.BedPart` for the worktable program (M7.6):
    `ops` + `contour_op_names` + `drill_op_names` per part, placed on `fixture_zone`.
    """
    kind: ComponentKind
    label: str
    fixture_zone: str
    ops: list[CamOp]
    contour_op_names: set
    drill_op_names: set
    stock: StockDefinition


def build_component_ops(
    component: Component,
    geometry: ComponentGeometry,
    tools_cfg: dict,
    *,
    cam_params: CastleCamParams | None = None,
    tool: dict | None = None,
) -> ComponentProgram:
    """Route `component` to its generator and return its ops + post metadata.

    `tools_cfg` is the full tools.yaml dict (each generator resolves its own
    per-op / per-feature tools from it). `tool` is the global/default tool dict —
    required only for the frame-front castle program. A missing kind-required
    geometry input raises ValueError.
    """
    kind = component.kind

    if kind == ComponentKind.FRAME_FRONT:
        if geometry.relief is None:
            raise ValueError("frame_front needs geometry.relief (build_castle_relief)")
        if tool is None:
            raise ValueError("frame_front needs the global `tool` dict")
        ops = generate_castle_program(
            geometry.relief, component.castle, geometry.hinge_polys,
            tool, params=cam_params, tools_cfg=tools_cfg,
        )
        return ComponentProgram(
            kind, component.label, component.fixture_zone(),
            ops, set(CASTLE_CONTOUR_OPS), set(), component.castle.stock,
        )

    if kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        if geometry.outline is None:
            raise ValueError("temple needs geometry.outline")
        ops = generate_temple_program(
            geometry.outline, geometry.engraving_curves, component.temple,
            tools_cfg, params=cam_params, hinge_polys=geometry.hinge_polys,
        )
        return ComponentProgram(
            kind, component.label, component.fixture_zone(),
            ops, set(TEMPLE_CONTOUR_OPS), set(), component.temple.stock(),
        )

    if kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
        if geometry.lens_outline is None:
            raise ValueError("base_curve needs geometry.lens_outline")
        ops = generate_block_program(
            geometry.lens_outline, component.base_curve_block, tools_cfg,
            params=cam_params,
        )
        return ComponentProgram(
            kind, component.label, component.fixture_zone(),
            ops, set(BLOCK_CONTOUR_OPS), set(BLOCK_DRILL_OPS),
            component.base_curve_block.stock(),
        )

    raise ValueError(f"unknown component kind: {kind!r}")
