"""Base-curve holding-block CAM (BUILDPLAN M6.4).

Auto-generate the base-curve holding block straight from the frame DXF. The block
is the **lens shape** cut from a flat acetal blank — it sits on the base-curve press
and holds the eyewire so the frame doesn't distort while thermoforming. Two cuts,
nothing else (confirmed with the user 2026-06-19):

  1. **Drill Holes** — three M4 mounting holes (peck-drilled) that bolt it to the
     jig; cut first while the blank is rigid.
  2. **Block Profile** — the **lens exterior shape** through-cut with an onion skin,
     freeing the block last — exactly the way a frame outline is cut.

The drill uses its own tool, so the program carries one tool change (M6.1). The
lens shape is centred on the blank; everything rides the shared GRBL post and
program-zero offset (M6.2).
"""
from __future__ import annotations

from shapely.affinity import translate
from shapely.geometry import Polygon

from ..project.schema import BaseCurveBlockParams, CastleCamParams
from .castle_ops import CamOp, contour_op, resolve_tool

Point3 = tuple[float, float, float]

# Op-name sets for write_castle_program (drill peck-cycle, ramped through-cut).
BLOCK_DRILL_OPS = {"Drill Holes"}
BLOCK_CONTOUR_OPS = {"Block Profile"}


def center_on_origin(poly: Polygon) -> Polygon:
    """Translate a polygon so its bounding-box center sits at the origin — the
    lens footprint then sits symmetrically in the square block."""
    x0, y0, x1, y1 = poly.bounds
    return translate(poly, xoff=-(x0 + x1) / 2.0, yoff=-(y0 + y1) / 2.0)


def drill_holes_op(
    centers: list[tuple[float, float]], z_top: float, z_bottom: float, tool: dict,
) -> CamOp:
    """A peck-drill op: each hole is stored as ``[(x, y, z_top), (x, y, z_bottom)]``
    — the post reads the top/bottom and emits the G83 cycle."""
    op = CamOp("Drill Holes", tool=tool)
    for x, y in centers:
        op.paths.append([(float(x), float(y), float(z_top)),
                         (float(x), float(y), float(z_bottom))])
    return op


def block_profile_op(
    lens_shape: Polygon, profile_tool: dict, allowance_mm: float,
    top_z: float, skin_z: float, params: CastleCamParams,
) -> CamOp:
    """The lens-shape through-cut (outside contour, onion skin) — frees the block
    last, exactly the way a frame outline is cut."""
    op = contour_op("Block Profile", [lens_shape], "outside",
                    profile_tool["radius_mm"], allowance_mm, top_z, skin_z, params)
    op.tool = profile_tool
    return op


def generate_block_program(
    lens_outline: Polygon,
    block: BaseCurveBlockParams,
    tools_cfg: dict,
    params: CastleCamParams | None = None,
) -> list[CamOp]:
    """Drill the mounting holes, then cut the lens shape free — in that order
    (drill while rigid, release last). Nothing else is cut: the block *is* the lens
    shape, holding the eyewire on the base-curve press.

    `lens_outline` is a LENS interior from the frame DXF; it is centred on the
    blank. The drill / profile tools come from `block` (resolved from `tools_cfg`);
    the drill differs from the bulk tool, so the post emits one tool change.
    """
    params = params or CastleCamParams()
    drill_tool = resolve_tool(block.drill_tool, tools_cfg)
    profile_tool = resolve_tool(block.profile_tool, tools_cfg)

    top_z = block.blank_thickness_mm
    skin_z = block.onion_skin_mm
    z_bottom = -block.drill_breakthrough_mm          # drill through the bottom face

    centered_lens = center_on_origin(lens_outline)

    ops: list[CamOp] = [
        drill_holes_op(block.hole_centers(), top_z, z_bottom, drill_tool),
        block_profile_op(centered_lens, profile_tool,
                         block.hand_finishing_allowance_mm, top_z, skin_z, params),
    ]
    return ops
