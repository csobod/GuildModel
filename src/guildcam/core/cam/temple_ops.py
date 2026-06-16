"""Temple component CAM: engraving + outline profile (BUILDPLAN M6.3).

A temple is a flat acetate blank — no castle relief. It gets:

  1. **Engraving** — shallow grooves traced along the ENGRAVING curves at a set
     depth below the top face, cut with a small tool (engraving bit) while the
     part is still held in the full blank.
  2. **Temple Profile** — the OUTLINE through-cut with an onion skin (exactly the
     perimeter strategy), cut last to release the part, with the bulk tool.

The two ops carry different tools, so the program posts one tool change between
them (the multi-tool machinery from BUILDPLAN M6.1). Both ride the same GRBL post
and program-zero offset as the frame front.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from ..project.schema import CastleCamParams, TempleParams
from .castle_ops import CamOp, _rdp, contour_op, resolve_tool

Point3 = tuple[float, float, float]

# The temple's through-cut op — gets the ramped lead-in in write_castle_program.
TEMPLE_CONTOUR_OPS = {"Temple Profile"}


def engrave_op(
    engraving_curves: list[list[tuple[float, float]]],
    depth_z: float,
    tool: dict,
    simplify_tol_mm: float = 0.01,
) -> CamOp:
    """Trace each ENGRAVING polyline at constant ``z = depth_z`` — a shallow
    groove on the temple's top face. Open polylines (text strokes) are fine: the
    post plunges to depth at the start of each and feeds along it."""
    op = CamOp("Engraving", tool=tool)
    for curve in engraving_curves:
        pts: list[Point3] = [(float(x), float(y), float(depth_z)) for x, y in curve]
        if len(pts) >= 2:
            op.paths.append(_rdp(pts, simplify_tol_mm))
    return op


def temple_profile_op(
    outline: Polygon,
    profile_tool: dict,
    allowance_mm: float,
    top_z: float,
    skin_z: float,
    params: CastleCamParams,
) -> CamOp:
    """The OUTLINE through-cut (outside contour, onion skin) for the temple."""
    op = contour_op(
        "Temple Profile", [outline], "outside",
        profile_tool["radius_mm"], allowance_mm, top_z, skin_z, params,
    )
    op.tool = profile_tool
    return op


def generate_temple_program(
    outline: Polygon,
    engraving_curves: list[list[tuple[float, float]]],
    temple: TempleParams,
    tools_cfg: dict,
    params: CastleCamParams | None = None,
) -> list[CamOp]:
    """Engrave (if any ENGRAVING curves) then profile-cut the temple outline.

    Engraving is cut first while the blank is rigid; the profile releases the
    part last. The engrave and profile tools come from `temple` (resolved from
    `tools_cfg`) — when they differ the post emits a tool change between the ops.
    """
    params = params or CastleCamParams()
    profile_tool = resolve_tool(temple.profile_tool, tools_cfg)
    engrave_tool = resolve_tool(temple.engrave_tool, tools_cfg)

    top_z = temple.blank_thickness_mm
    skin_z = temple.onion_skin_mm
    engrave_z = temple.blank_thickness_mm - temple.engrave_depth_mm

    ops: list[CamOp] = []
    if engraving_curves:
        ops.append(engrave_op(engraving_curves, engrave_z, engrave_tool,
                              params.simplify_tol_mm))
    ops.append(temple_profile_op(
        outline, profile_tool, temple.hand_finishing_allowance_mm,
        top_z, skin_z, params))
    return ops
