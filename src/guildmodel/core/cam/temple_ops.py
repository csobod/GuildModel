"""Temple component CAM: hinge pockets + engraving + outline profile (M6.3 / M7).

A temple is a flat acetate blank — no castle relief. It gets, in cut order:

  1. **Hinge Pockets** — the HINGE polys milled to a blind floor (the same ramped
     lap-entry pocketing the frame's hinges use) while the blank is still rigid.
     Only emitted when the component carries HINGE geometry; the 3D model, the cut
     sim, and the posted G-code all agree on the same recess (BUILDPLAN M7).
  2. **Engraving** — shallow grooves traced along the ENGRAVING curves at a set
     depth below the top face, cut with a small tool (engraving bit) while the
     part is still held in the full blank.
  3. **Temple Profile** — the OUTLINE through-cut with an onion skin (exactly the
     perimeter strategy), cut last to release the part, with the bulk tool. On a
     blank-end-snapped temple the profile is CLIPPED at the blank end
     (`clip_op_at_blank_end`): the butt sits flush on the blank's short edge with
     the injected metal core running to it, so the pass never crosses that end.

The ops carry different tools, so the program posts a tool change between each
(the multi-tool machinery from BUILDPLAN M6.1). All ride the same GRBL post and
program-zero offset as the frame front.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from ..project.schema import CastleCamParams, HoldingParams, TempleParams
from .castle_ops import (
    CamOp, _rdp, contour_op, hinge_pocket_op, order_paths_for_travel,
    pocket_levels, resolve_tool)

Point3 = tuple[float, float, float]

# The temple's through-cut ops — get the ramped lead-in in write_castle_program.
# "Holes" (decorative OUTLINE openings) is an inside through-cut, ramped like the
# profile so it never plunges the tool straight to full depth.
TEMPLE_CONTOUR_OPS = {"Temple Profile", "Holes"}


def engrave_op(
    engraving_curves: list[list[tuple[float, float]]],
    depth_z: float,
    tool: dict,
    simplify_tol_mm: float = 0.01,
    top_z: float | None = None,
    stepdown_mm: float = 0.0,
) -> CamOp:
    """Trace each ENGRAVING polyline down to ``z = depth_z`` — a groove on the
    temple's top face. Open polylines (text strokes) are fine: the post plunges to
    depth at the start of each and feeds along it.

    With `top_z` (the blank's top face) and a positive `stepdown_mm`, a groove
    deeper than one stepdown is traced once per depth level instead of plunging
    straight to full depth — the engraving tool is the most slender in the program
    and is the one that snaps. Levels are stroke-major: each stroke is finished
    through its depth stack before the next, matching the ring-major order the
    through-cuts use, so a deep engraving costs no extra travel."""
    op = CamOp("Engraving", tool=tool)
    if top_z is None or stepdown_mm <= 1e-9 or top_z - depth_z <= stepdown_mm + 1e-9:
        zs = [float(depth_z)]
    else:
        zs = pocket_levels(float(top_z), float(depth_z), float(stepdown_mm))
    for curve in engraving_curves:
        pts: list[Point3] = [(float(x), float(y), float(depth_z)) for x, y in curve]
        if len(pts) >= 2:
            op.paths.append(_rdp(pts, simplify_tol_mm))
    # Strokes arrive in draw/file order; cut them nearest-neighbor instead —
    # multi-stroke text otherwise hops the length of the part between strokes
    # (measured 6× the necessary air on a 40-stroke engraving). A pure
    # permutation: every stroke's geometry and direction are unchanged (the
    # M12.1 guarantee).
    op.paths = order_paths_for_travel(op.paths)
    # Expand each stroke into its depth stack only AFTER ordering, so the travel
    # order is still computed over strokes rather than over level copies that all
    # share one footprint (nearest-neighbor on duplicates is meaningless).
    if len(zs) > 1:
        op.paths = [[(x, y, z) for x, y, _ in path] for path in op.paths for z in zs]
    return op


def temple_hinge_pocket_op(
    hinge_polys: list[Polygon],
    temple: TempleParams,
    tools_cfg: dict,
    params: CastleCamParams,
) -> CamOp:
    """Pocket each HINGE poly to ``thickness − hinge_pocket_depth`` with the same
    ramped lap-entry pocketing the frame uses, cut with the temple's hinge tool.
    The op may have no paths if every pocket is too small for the tool — the caller
    drops it in that case."""
    tool = resolve_tool(temple.hinge_tool, tools_cfg)
    floor_z = temple.blank_thickness_mm - temple.hinge_pocket_depth_mm
    op = hinge_pocket_op(
        hinge_polys, floor_z,
        start_z=temple.blank_thickness_mm + 0.5,
        tool_radius_mm=tool["radius_mm"], params=params,
    )
    op.tool = tool
    return op


def temple_profile_op(
    outline: Polygon,
    profile_tool: dict,
    allowance_mm: float,
    top_z: float,
    skin_z: float,
    params: CastleCamParams,
    holding: "HoldingParams | None" = None,
) -> CamOp:
    """The OUTLINE through-cut for the temple — the op that releases the part, so
    it carries the hold-down strategy (onion skin by default, tabs on request)."""
    op = contour_op(
        "Temple Profile", [outline], "outside",
        profile_tool["radius_mm"], allowance_mm, top_z, skin_z, params,
        holding=holding,
    )
    op.tool = profile_tool
    return op


def clip_op_at_blank_end(op: CamOp, blank_length_mm: float,
                         stock_side: str = "right") -> CamOp:
    """Open the profile at the snapped blank end so the tool never crosses the
    injected metal core (BUILDPLAN 2026-07-09 core-safe profile).

    A snapped temple's butt end sits flush on the blank's short edge, and the metal
    core runs to that edge — a closed profile lap would drag the cutter straight
    across it and dull the tool. Clip every pass at the blank-end plane
    (x = +L/2 for ``stock_side`` "right", −L/2 for "left"): each closed ring becomes
    an open polyline that stops at the blank edge on either side of the butt and
    skips the crossing entirely (the part stays attached to the off-blank end; there
    is no stock past the edge to release). Crossing points are interpolated onto the
    plane, and the ring seam is re-joined so each pass stays one continuous cut.
    The post feeds open paths with a plain plunge (no ramp), which is one stepdown
    deep at most — the same entry every drill / engrave pass uses."""
    half = blank_length_mm / 2.0
    sign = -1.0 if stock_side == "left" else 1.0
    eps = 1e-9

    def inside(p) -> bool:                       # tool CENTER never past the blank end
        return sign * p[0] <= half + eps

    def cross(a, b):
        """The point where segment a→b meets the blank-end plane."""
        t = (half - sign * a[0]) / (sign * (b[0] - a[0]))
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t)

    clipped = CamOp(op.name, tool=op.tool)
    for path in op.paths:
        pts = list(path)
        if len(pts) < 2:
            continue
        if all(inside(p) for p in pts):          # nothing to clip on this pass
            clipped.paths.append(pts)
            continue
        closed = (len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) < eps
                  and abs(pts[0][1] - pts[-1][1]) < eps)
        if closed:
            pts = pts[:-1]                       # walk the cycle; edges wrap below
        n = len(pts)
        edges = n if closed else n - 1
        segs: list[list] = []
        cur: list = [pts[0]] if inside(pts[0]) else []
        for k in range(edges):
            a, b = pts[k], pts[(k + 1) % n]
            ain, bin_ = inside(a), inside(b)
            if ain and bin_:
                cur.append(b)
            elif ain and not bin_:               # leaving: end the segment on the plane
                cur.append(cross(a, b))
                segs.append(cur)
                cur = []
            elif not ain and bin_:               # re-entering: start on the plane
                cur = [cross(a, b), b]
        if cur:
            segs.append(cur)
        # A cycle walk that started inside split one physical segment across the
        # seam — the last runs into the first; rejoin them into one continuous cut.
        if closed and len(segs) >= 2 and inside(pts[0]):
            segs = [segs[-1] + segs[0][1:]] + segs[1:-1]
        for seg in segs:
            if len(seg) >= 2:
                clipped.paths.append(seg)
    return clipped


def generate_temple_program(
    outline: Polygon,
    engraving_curves: list[list[tuple[float, float]]],
    temple: TempleParams,
    tools_cfg: dict,
    params: CastleCamParams | None = None,
    hinge_polys: list[Polygon] = (),
) -> list[CamOp]:
    """Pocket the HINGE recess (if any), engrave (if any ENGRAVING curves), then
    profile-cut the temple outline.

    The hinge pockets and engraving are cut first while the blank is rigid; the
    profile releases the part last. Each op's tool comes from `temple` (resolved
    from `tools_cfg`) — when they differ the post emits a tool change between ops.
    `hinge_polys` defaults to empty, so a temple with no HINGE geometry posts the
    historical engrave→profile program unchanged.
    """
    params = params or CastleCamParams()
    profile_tool = resolve_tool(temple.profile_tool, tools_cfg)
    engrave_tool = resolve_tool(temple.engrave_tool, tools_cfg)

    top_z = temple.blank_thickness_mm
    skin_z = temple.onion_skin_mm
    engrave_z = temple.blank_thickness_mm - temple.engrave_depth_mm

    hinges = [p for p in hinge_polys if p is not None and not p.is_empty]

    if engraving_curves and temple.engrave_centerline:
        from .engrave_centerline import engraving_centerlines
        engraving_curves = engraving_centerlines(engraving_curves)

    ops: list[CamOp] = []
    if hinges:
        hinge_op = temple_hinge_pocket_op(hinges, temple, tools_cfg, params)
        if hinge_op.paths:                 # skip when the pockets can't admit the tool
            ops.append(hinge_op)
    if engraving_curves:
        ops.append(engrave_op(engraving_curves, engrave_z, engrave_tool,
                              params.simplify_tol_mm, top_z=top_z,
                              stepdown_mm=temple.engrave_stepdown_mm))
    # Decorative OUTLINE openings (normalize.assemble_outline) are inside
    # through-cuts, taken before the profile releases the part. Same tool as the
    # profile unless pinned, so they add no tool change.
    holes = [Polygon(r) for r in outline.interiors]
    if holes:
        pinned = params.op_tools.get("Holes")
        holes_tool = (resolve_tool(pinned, tools_cfg, default=profile_tool)
                      if pinned else profile_tool)
        holes_op = contour_op(
            "Holes", holes, "inside", holes_tool["radius_mm"],
            temple.hand_finishing_allowance_mm, top_z, skin_z, params)
        holes_op.tool = holes_tool
        if holes_op.paths:
            ops.append(holes_op)

    profile = temple_profile_op(
        outline, profile_tool, temple.hand_finishing_allowance_mm,
        top_z, skin_z, params, holding=temple.holding)
    if temple.snap_to_blank_end:
        # The butt end sits flush on the blank's short edge with the metal core
        # running to it — never drag the profile across it (core-safe profile).
        profile = clip_op_at_blank_end(
            profile, temple.blank_length_mm, temple.stock_side)
    if profile.paths:
        ops.append(profile)
    return params.enabled_ops(ops)
