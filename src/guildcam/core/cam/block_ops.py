"""Base-curve forming-block CAM (BUILDPLAN M6.4).

Auto-generate the post-cut heat-forming holding block straight from the frame
DXF. The block is a flat acetal blank that carries:

  1. **Drill Holes** — three M4 mounting holes (peck-drilled) that bolt it to a
     jig; cut first while the blank is rigid.
  2. **Forming Profile** — the eyewire-interior (LENS) footprint scribed onto the
     top face as the forming reference. The block is flat in v1 (the 3D base-curve
     surface stays metadata, §5); this contour marks where the frame drapes.
  3. **Block Profile** — the blank outline (65 × 65 default) through-cut with an
     onion skin, releasing the block last.

The drill uses its own tool, so the program carries one tool change (M6.1). The
lens interior is centred on the blank; everything rides the shared GRBL post and
program-zero offset (M6.2).
"""
from __future__ import annotations

from shapely.affinity import translate
from shapely.geometry import Polygon, box

from ..project.schema import BaseCurveBlockParams, CastleCamParams
from .castle_ops import CamOp, _rdp, contour_op, resolve_tool
from .temple_ops import engrave_op

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


def forming_profile_op(
    lens_outline: Polygon, depth_z: float, tool: dict, simplify_tol_mm: float = 0.01,
) -> CamOp:
    """Scribe the lens-interior footprint onto the top face at ``depth_z`` — the
    forming reference (a single-depth contour trace, like engraving)."""
    op = engrave_op([list(lens_outline.exterior.coords)], depth_z, tool, simplify_tol_mm)
    op.name = "Forming Profile"
    return op


def block_profile_op(
    block_outline: Polygon, profile_tool: dict, allowance_mm: float,
    top_z: float, skin_z: float, params: CastleCamParams,
) -> CamOp:
    """The blank outline through-cut (outside contour, onion skin) — releases the
    block last."""
    op = contour_op("Block Profile", [block_outline], "outside",
                    profile_tool["radius_mm"], allowance_mm, top_z, skin_z, params)
    op.tool = profile_tool
    return op


def generate_block_program(
    lens_outline: Polygon,
    block: BaseCurveBlockParams,
    tools_cfg: dict,
    params: CastleCamParams | None = None,
) -> list[CamOp]:
    """Drill the mounting holes, scribe the lens-interior footprint, then profile
    the blank — in that order (drill + scribe while rigid, release last).

    `lens_outline` is a LENS interior from the frame DXF; it is centred on the
    blank. The drill / forming / profile tools come from `block` (resolved from
    `tools_cfg`); the drill differs from the bulk tool, so the post emits one
    tool change.
    """
    params = params or CastleCamParams()
    drill_tool = resolve_tool(block.drill_tool, tools_cfg)
    forming_tool = resolve_tool(block.forming_tool, tools_cfg)
    profile_tool = resolve_tool(block.profile_tool, tools_cfg)

    top_z = block.blank_thickness_mm
    skin_z = block.onion_skin_mm
    forming_z = block.blank_thickness_mm - block.forming_depth_mm
    z_bottom = -block.drill_breakthrough_mm          # drill through the bottom face

    centered_lens = center_on_origin(lens_outline)
    half_l = block.blank_length_mm / 2.0
    half_w = block.blank_width_mm / 2.0
    block_outline = box(-half_l, -half_w, half_l, half_w)

    ops: list[CamOp] = [
        drill_holes_op(block.hole_centers(), top_z, z_bottom, drill_tool),
        forming_profile_op(centered_lens, forming_z, forming_tool, params.simplify_tol_mm),
        block_profile_op(block_outline, profile_tool,
                         block.hand_finishing_allowance_mm, top_z, skin_z, params),
    ]
    return ops
