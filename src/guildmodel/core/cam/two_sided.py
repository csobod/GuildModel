"""Two-sided machining of a flat blank (BUILDPLAN M24 §9; the anterior first, 2.0).

The maker's order (2026-10-17): the anterior first, the blank front face up
while it is still a flat slab, cutting only what the anterior's features need:
the seats, and barely enough of each chamfer or round-over. Then the blank is
flipped onto its front face, re-registered on its dowel pins, and the
posterior is cut exactly as a one-sided job cuts it, the through-cuts and the
onion skin with it. All the major removal happens with the piece flat on the
bed, where it is most secure, and the posterior program is the one-sided
program.

The anterior is **its Z-map as a relief of its own**: mirrored in X about the
flip line (or turned about the rotary's centerline, M26) and re-zeroed on the
fixture plane with the front face as the top, so the generators that cut a
posterior cut it unchanged. The anterior seats are its pockets, and the
material a feature takes off the front is its feature band. Past the part's
edge the stock stands uncut, so the relief reaches a tool's width beyond the
part, and each feature finishes at the edge
(`CastleRelief.uncut_beyond_edge`). A front that takes nothing off the front
has one setup, the posterior, byte for byte the one-sided program.

Kernel-free, like everything in `core.cam`: it reads a `CastleRelief` and
writes ops and setups.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely import contains_xy, prepare
from shapely import get_coordinates, line_interpolate_point
from shapely.affinity import scale as _scale
from shapely.geometry import LineString, Polygon

from ..geometry.regions import CastlePartition, Zone
from ..project.schema import CastleCamParams, CastleParams, Setup
from ..relief.castle import CastleRelief
from ..relief.heightfield import Heightfield
from .castle_ops import CamOp, generate_castle_program

__all__ = ["TwoSidedJob", "RingHold", "anterior_castle", "anterior_setup_relief",
           "mirror_points", "mirror_polygon", "mirrored_partition", "needs_second_side",
           "plan_two_sided",
           "skin_holds", "skin_hold_notes", "FLIP_PAUSE", "ANTERIOR_BAND_MM",
           "THROUGH_CUT_OPS"]

#: The ops that open the part and release it: the posterior's, always, with
#: the onion skin or the tabs the maker chose; the anterior never cuts them.
THROUGH_CUT_OPS = frozenset({"Eyewires", "Holes", "Lens Groove", "Perimeter"})
#: Material taken off the front deeper than this is a feature the anterior cuts.
ANTERIOR_BAND_MM = 0.05
#: The pause GuildSend classifies as the flip; the details follow it.
FLIP_PAUSE = "Flip stock and re-register on dowel pins"


@dataclass
class TwoSidedJob:
    """What each setup cuts, and how the machine gets from one to the next."""
    posterior: list                        # CamOp: the posterior, the one-sided program (G54)
    anterior: list                         # CamOp: the anterior, cut first (G55); empty = one setup
    relief_anterior: CastleRelief | None   # the anterior as a relief, for the simulation
    castle_anterior: CastleParams | None   # the castle as the anterior setup sees it
    setups: list = field(default_factory=list)      # Setup records, in the order they run
    notes: list = field(default_factory=list)

    @property
    def two_sided(self) -> bool:
        return bool(self.anterior)


# ------------------------------------------------------------------ geometry

def mirror_polygon(poly, mirror_x: float = 0.0, axis: str = "x"):
    """`poly` mirrored about ``x = mirror_x`` (the manual flip about the
    fixture's vertical line) or, with ``axis="y"``, about ``y = mirror_x``
    (the rotary's flip about the frame's horizontal, M26)."""
    if axis == "y":
        return _scale(poly, xfact=1.0, yfact=-1.0, origin=(0.0, float(mirror_x)))
    return _scale(poly, xfact=-1.0, yfact=1.0, origin=(float(mirror_x), 0.0))


def mirror_points(points, mirror_x: float = 0.0, axis: str = "x") -> list[tuple[float, float]]:
    """XY points mirrored as `mirror_polygon` mirrors a polygon. The mirror is
    its own inverse, so this also takes the anterior setup's paths back into
    the design frame, where the posterior's are drawn."""
    m = float(mirror_x)
    if axis == "y":
        return [(float(p[0]), 2.0 * m - float(p[1])) for p in points]
    return [(2.0 * m - float(p[0]), float(p[1])) for p in points]


def mirrored_partition(partition: CastlePartition, mirror_x: float = 0.0,
                       axis: str = "x") -> CastlePartition:
    """The partition as the anterior setup sees it: every polygon mirrored,
    the zones keeping their names (the heights are the same for both eyes),
    the seams dropped (no footing is cut on the anterior), the holes mirrored
    so `is_hole`
    still tells an opening from an aperture."""
    zones = [Zone(z.name, z.kind, z.side, mirror_polygon(z.polygon, mirror_x, axis))
             for z in partition.zones]
    return CastlePartition(
        body=mirror_polygon(partition.body, mirror_x, axis), zones=zones, edges=[],
        matched=partition.matched,
        holes=[mirror_polygon(h, mirror_x, axis) for h in partition.holes])


def _mask(polys, origin, rows, cols, res) -> np.ndarray:
    if not polys:
        return np.zeros((rows, cols), dtype=bool)
    xs = origin[0] + np.arange(cols) * res
    ys = origin[1] + np.arange(rows) * res
    X, Y = np.meshgrid(xs, ys)
    out = np.zeros(rows * cols, dtype=bool)
    for p in polys:
        prepare(p)
        out |= contains_xy(p, X.ravel(), Y.ravel())
    return out.reshape(rows, cols)


def _front_mask(relief: CastleRelief) -> np.ndarray:
    """The front's own footprint on the relief grid: the body as it is on a
    flat blank; on a pressed blank (M25) the body the relief's partition
    carries, which is the front's, wider than the back's by the walls' lean."""
    if relief.stock_bottom is None:
        return relief.inside
    f = relief.field
    rows, cols = f.z.shape
    return _mask([relief.partition.body], f.origin, rows, cols, float(f.resolution))


def needs_second_side(relief: CastleRelief) -> bool:
    """True when the front takes material off the anterior, or carries a
    seat there: something for the anterior setup to cut first."""
    if relief.anterior is not None:
        depth = np.where(_front_mask(relief), relief.anterior_depth, 0.0)
        if bool((depth > ANTERIOR_BAND_MM).any()):
            return True
    return bool(relief.anterior_pocket_polys)


def anterior_setup_relief(relief: CastleRelief, castle: CastleParams, *,
                          mirror_x: float = 0.0, flip: str = "manual",
                          center_y: float = 0.0,
                          center_z: float | None = None,
                          force: bool = False) -> CastleRelief | None:
    """The anterior as a relief for the anterior setup, cut first with the
    front face up, or None when there is nothing to cut there.

    A manual flip mirrors in X about `mirror_x` (the flip line in the design
    frame: the blank's center line, 0, on the Guild bed) and re-zeroes on the
    fixture plane: the top is the anterior face at ``T``, the blank's
    thickness, and the target height is ``T - anterior``. A blank with the pad
    block lies on a spacer as thick as the pad, its cut-out holding the pad
    (`flip_height`): the whole stack is what turns, the pad's back on the bed
    and the sheet on the spacer, and the relief carries that stock
    explicitly, its top the front face and its bottom the spacer's top or,
    over the pad, the bed. A rotary flip (M26) turns the blank about the
    rotary's centerline instead: mirrored in Y about `center_y` and in Z about
    `center_z` (half the blank by default). The anterior seats become the
    pockets; the cells a feature takes material from become the band the
    Features pass finishes, at the anterior features' steepest slope. The
    stock past the part stands uncut (`uncut_beyond_edge`).
    """
    if not force and not needs_second_side(relief):
        return None
    f = relief.field
    rows, cols = f.z.shape
    res = float(f.resolution)
    ox, oy = f.origin
    T = float(castle.stock.blank_thickness_mm)
    rotary = flip == "rotary"
    axis = "y" if rotary else "x"
    m = float(center_y) if rotary else float(mirror_x)
    padded = relief.stock_bottom is None and pad_on(castle.stock)
    zf = ((2.0 * float(center_z if center_z is not None else T / 2.0)) if rotary
          else flip_height(castle.stock))
    flipg = np.flipud if rotary else np.fliplr
    # with nothing cut on the front, the anterior is the stock's own face:
    # the pressed slab's bottom on a pressed blank, 0 on a flat one
    a = (relief.stock_bottom.z if relief.anterior is None and relief.stock_bottom is not None
         else relief.anterior_z)
    front = _front_mask(relief)                        # the face the anterior cuts
    depth = np.where(front, relief.anterior_depth, 0.0)
    z2 = flipg(zf - a)
    if rotary:
        origin2 = (float(ox), float(2.0 * m - (oy + (rows - 1) * res)))
    else:
        origin2 = (float(2.0 * m - (ox + (cols - 1) * res)), float(oy))
    seats2 = [mirror_polygon(p, m, axis) for p in relief.anterior_pocket_polys]
    seat_mask = _mask(seats2, origin2, rows, cols, res)
    # the top: the front face, flat at the flip height, or the pressed slab's
    # own bottom turned over (M25)
    if relief.stock_bottom is not None:
        new_top = flipg(zf - relief.stock_bottom.z)
        new_bottom = flipg(zf - relief.stock_top.z)
    elif padded:
        # the blank, the sheet and the pad block over its footprint, turned
        # over onto the spacer
        from ..relief.castle import stock_top_heightfield
        top_one = stock_top_heightfield(castle.stock, resolution=res, origin=f.origin,
                                        shape=f.z.shape).z
        new_top = np.full((rows, cols), zf)
        new_bottom = flipg(zf - top_one)
    else:
        new_top = np.full((rows, cols), zf)
        new_bottom = None
    surface2 = np.where(seat_mask, new_top, z2)   # the passes sail over the seats
    band = flipg(depth > ANTERIOR_BAND_MM) & ~seat_mask
    slope = float(castle.anterior_feature_slope()) if band.any() else 0.0
    return CastleRelief(
        field=Heightfield(z=z2, origin=origin2, resolution=res),
        inside=flipg(front).copy(),
        zone_index=flipg(relief.zone_index).copy(),
        partition=mirrored_partition(relief.partition, m, axis),
        pocket_polys=seats2,
        surface_field=Heightfield(z=surface2, origin=origin2, resolution=res),
        feature_band=band if band.any() else None,
        feature_max_slope_deg=slope,
        stock_top=(Heightfield(z=new_top, origin=origin2, resolution=res)
                   if new_bottom is not None else None),
        stock_bottom=(Heightfield(z=new_bottom, origin=origin2, resolution=res)
                      if new_bottom is not None else None),
        uncut_beyond_edge=True,
    )


def pad_on(stock) -> bool:
    """A flat blank that carries the pad block."""
    from .castle_ops import pad_footprint
    return (not getattr(stock, "preformed", False) and pad_footprint(stock) is not None
            and stock.total_pad_height_mm > stock.blank_thickness_mm)


def flip_height(stock) -> float:
    """The height a flat blank turns about by hand: the sheet's, or with the
    pad block the whole stack's. For the anterior the pad goes into the
    spacer's cut-out and stands on the bed, and the sheet stands on the
    spacer, the pad's thickness (the maker, 2026-10-17). Both setups' Z0 is
    the stock's bottom on the bed: the pad's back, then the front's face."""
    return float(stock.total_pad_height_mm if pad_on(stock) else stock.blank_thickness_mm)


def anterior_castle(castle: CastleParams) -> CastleParams:
    """The castle as the anterior setup sees it, front face up: no pad block
    on top (it is under the blank, in the spacer's cut-out, and the stock is
    the stack standing on the bed), and every seat's face swapped, so the
    anterior seats read as pockets from the top. It makes no through-cut, so
    its holding is never asked."""
    inlays = [i.model_copy(update={"face": "posterior" if i.face == "anterior" else "anterior"})
              for i in castle.inlays]
    return castle.model_copy(update={
        "stock": castle.stock.model_copy(update={
            "use_pad_block": False, "blank_thickness_mm": flip_height(castle.stock)}),
        "inlays": inlays,
    })


def spacer_note(stock) -> str:
    """What the operator lays a blank with the pad block on for the anterior
    setup, front face up, or ""."""
    if not pad_on(stock):
        return ""
    pad = stock.total_pad_height_mm - stock.blank_thickness_mm
    return (f"lay the blank front face up on the spacer: {pad:.1f} mm thick, its "
            f"cut-out holding the {stock.pad_block_length_mm:g} x "
            f"{stock.pad_block_width_mm:g} mm pad block")


# ------------------------------------------------------------------ the plan

def _anterior_seats(castle_a: CastleParams, inlay_polys, mirror_x: float,
                    params: CastleCamParams, tools_cfg, default_tool, T: float,
                    axis: str = "x") -> list:
    """The Inlays op for the anterior: its seats, mirrored, cut from the front
    face down by their depth."""
    if not castle_a.inlays or not inlay_polys:
        return []
    from ..geometry.inlays import inlay_cuts
    from .inlay_ops import inlay_ops
    polys2 = [mirror_polygon(p, mirror_x, axis) for p in inlay_polys]
    seats = inlay_cuts(castle_a.inlays, polys2, [], posterior_reference=T)
    seats = [s for s in seats if s.posterior and s.depth_mm > 0.0]
    return inlay_ops(seats, params, tools_cfg, default_tool) if seats else []


class FlipRefused(ValueError):
    """A two-sided job whose flip cannot be posted safely; the message is a
    sentence for the maker, not a fault."""


def blank_swing_radius_mm(stock, rotary) -> float:
    """How far the blank reaches from the rotary's axis as it turns: the
    farthest corner of its section (and the pad block's) from the axis."""
    import math

    about_x = getattr(rotary, "about", "X") == "X"
    half = (stock.blank_width_mm if about_x else stock.blank_length_mm) / 2.0
    cy = float(getattr(rotary, "center_y_mm", 0.0)) if about_x else 0.0
    cz = float(getattr(rotary, "center_z_mm", stock.blank_thickness_mm / 2.0))
    corners = [(s * half, z) for s in (-1.0, 1.0) for z in (0.0, stock.blank_thickness_mm)]
    if stock.use_pad_block and stock.pad_block_length_mm > 0 and stock.pad_block_width_mm > 0:
        pad_half = (stock.pad_block_width_mm if about_x else stock.pad_block_length_mm) / 2.0
        off = stock.pad_block_dy_mm if about_x else stock.pad_block_dx_mm
        corners += [(off + s * pad_half, stock.total_pad_height_mm) for s in (-1.0, 1.0)]
    return max(math.hypot(y - cy, z - cz) for y, z in corners)


def rotary_swing_problem(machine, stock, rotary_bar: dict | None) -> str | None:
    """Why the indexed flip cannot be posted, or None when the blank's swing
    clears the tool at the top of Z travel. The swing is the larger of the
    blank's own (`blank_swing_radius_mm`) and the fixture's; the room is the
    profile's spindle-nose-to-table height less the rotary's center height
    and the tool's stick-out (`MachineProfile.max_swing_radius_mm`)."""
    bar = rotary_bar or {}
    swing = blank_swing_radius_mm(stock, machine.rotary)
    try:
        swing = max(swing, float(bar.get("swing_radius_mm") or 0.0))
        center = float(bar.get("center_z_mm") or 0.0)
    except (TypeError, ValueError):
        return "The fixture file's rotary bar has a value that is not a number."
    room = machine.max_swing_radius_mm(center)
    if room is None:
        return ("The indexed flip turns the blank through a radius of "
                f"{swing:.1f} mm, and the machine profile does not say how much room "
                "the spindle leaves: measure the spindle nose to the table at Z max "
                "(spindle_nose_to_table_mm) first, or flip the blank by hand.")
    if swing > room:
        return (f"The blank swings a radius of {swing:.1f} mm about the rotary's axis, "
                f"and the tool's tip at the top of Z travel clears only {room:.1f} mm "
                "of it: the turn would strike the tool. Flip the blank by hand.")
    return None


def _anterior_params(relief: CastleRelief, params: CastleCamParams) -> CastleCamParams:
    """The ops the anterior setup may cut: never a hinge pocket or a
    through-cut, which are the posterior's, and the Rough Relief only where
    the front is cut deeper than a pass. The anterior cuts barely what its
    features need (the maker, 2026-10-17), and a chamfer or a round-over a
    pass deep or less is the Fine Relief's and the Features pass's alone."""
    off = dict(params.op_enabled)
    for name in THROUGH_CUT_OPS | {"Component Pockets"}:
        off[name] = False
    deepest = 0.0
    if relief.anterior is not None:
        deepest = float(np.max(np.where(_front_mask(relief), relief.anterior_depth, 0.0)))
    if deepest <= float(params.contour_stepdown_mm) + 1e-9:
        off["Rough Relief"] = False
    return params.model_copy(update={"op_enabled": off})


def plan_two_sided(relief: CastleRelief, castle: CastleParams, hinge_polys, tool: dict,
                   params: CastleCamParams, tools_cfg: dict | None = None,
                   inlay_polys=(), *, mirror_x: float = 0.0,
                   flip_axis_x_mm: float | None = None, progress=None,
                   flip: str = "manual", rotary=None) -> TwoSidedJob:
    """The setups and their ops, in the order they run.

    The posterior is always the one-sided program: every op the maker left
    on, the through-cuts and the onion skin or the tabs included.
    `params.two_sided` decides whether the anterior is cut first: ``off``
    never; ``on`` always, and a front with nothing on its anterior then posts
    the posterior alone with a note; ``auto`` when the front takes material
    off the anterior or seats something there. The anterior cuts its relief,
    its features and its seats, and nothing that is the posterior's
    (`_anterior_params`).

    `flip` is ``manual`` (the blank turned by hand about the fixture's flip
    line) or ``rotary`` (M26: the anterior program turns the rotary to A180
    before it cuts and back at its end, so the posterior runs at A0 as it
    would alone).
    """
    mode = getattr(params, "two_sided", "auto")
    rotary_flip = flip == "rotary" and rotary is not None
    cy = float(getattr(rotary, "center_y_mm", 0.0)) if rotary_flip else 0.0
    cz = float(getattr(rotary, "center_z_mm", castle.stock.blank_thickness_mm / 2.0)) if rotary_flip else None
    axis = "y" if rotary_flip else "x"
    m = cy if rotary_flip else mirror_x
    notes: list = []
    posterior = generate_castle_program(relief, castle, hinge_polys, tool, params=params,
                                        progress=progress, tools_cfg=tools_cfg,
                                        inlay_polys=inlay_polys)
    alone = [Setup(side="posterior", wcs="G54", program="posterior_cut.nc",
                   stock_top_mm=castle.stock.total_pad_height_mm)]
    relief_a = None if mode == "off" else anterior_setup_relief(
        relief, castle, mirror_x=mirror_x, flip="rotary" if rotary_flip else "manual",
        center_y=cy, center_z=cz, force=mode == "on")
    if relief_a is None:
        return TwoSidedJob(posterior, [], None, None, alone, notes)

    castle_a = anterior_castle(castle)
    T = float(castle.stock.blank_thickness_mm)
    # the anterior's top: the front face, at the flip height or turned about
    # the rotary's centerline, or the pressed slab's bottom turned over
    top_a = (float(np.nanmax(relief_a.stock_top.z)) if relief_a.stock_top is not None else T)
    params_a = _anterior_params(relief, params)
    anterior = [op for op in generate_castle_program(
        relief_a, castle_a, [], tool, params=params_a, progress=progress,
        tools_cfg=tools_cfg, inlay_polys=()) if op.paths]
    if params.is_op_enabled("Inlays"):
        from .castle_ops import resolve_tool
        inlay_tool = (resolve_tool(params.tool_for_op("Inlays"), tools_cfg or {}, default=tool)
                      if tools_cfg else tool)
        # the seats are measured from the front face: the stack's top on a
        # padded blank lying on its spacer, the sheet's otherwise
        seat_ops = _anterior_seats(castle_a, inlay_polys, m, params_a, tools_cfg,
                                   inlay_tool, top_a if pad_on(castle.stock) else T, axis)
        if seat_ops:
            # beside the ops on the seats' own tool, so the setup changes
            # tools as few times as it can
            seat_tool = seat_ops[0].tool_name
            k = next((i + 1 for i in range(len(anterior) - 1, -1, -1)
                      if anterior[i].tool_name == seat_tool), len(anterior))
            anterior[k:k] = seat_ops
    if not anterior:
        notes.append("The anterior had nothing to cut after all; the posterior is posted alone.")
        return TwoSidedJob(posterior, [], None, None, alone, notes)
    reprobe = ((["Z"] if getattr(params, "probe_block", False) else [])
               + (["XY"] if getattr(params, "reprobe_xy", False) and not rotary_flip else []))
    a_deg = (180.0 * float(getattr(rotary, "direction_sign", 1))) if rotary_flip else None
    setups = [
        Setup(side="anterior", wcs="G55", program="anterior_cut.nc",
              flip="rotary" if rotary_flip else "none", a_deg=a_deg,
              stock_top_mm=top_a, mirror_x_mm=float(mirror_x), flip_axis_x_mm=flip_axis_x_mm,
              notes=[n for n in (
                  "front face up, cut first: the seats and the features alone",
                  "" if rotary_flip else spacer_note(castle.stock),
                  (f"indexed: the rotary turns the blank {a_deg:+.0f} degrees about its "
                   "centerline first, and back at the end" if rotary_flip else "")) if n]),
        Setup(side="posterior", wcs="G54", program="posterior_cut.nc",
              flip="rotary" if rotary_flip else "manual", a_deg=0.0 if rotary_flip else None,
              stock_top_mm=castle.stock.total_pad_height_mm, mirror_x_mm=float(mirror_x),
              flip_axis_x_mm=flip_axis_x_mm, reprobe=reprobe,
              notes=["front face down on the bed: the one-sided program, through-cuts "
                     "and onion skin"]),
    ]
    return TwoSidedJob(posterior, anterior, relief_a, castle_a, setups, notes)


def flip_pause_text(setup: Setup) -> str:
    """The pause GuildSend parses before `setup`, with the flip line, the work
    offset and the probe to run after it; for a rotary flip, the indexed turn
    instead."""
    if setup.flip == "rotary":
        a = setup.a_deg if setup.a_deg is not None else 180.0
        parts = [f"Indexed flip: the rotary turns the blank to A{a:.3f}",
                 f"then {setup.wcs}"]
        if setup.reprobe:
            parts.append("re-probe " + " and ".join(setup.reprobe))
        return "; ".join(parts)
    parts = [FLIP_PAUSE]
    if setup.side == "posterior":
        parts.append("front face down on the bed")
    if setup.flip_axis_x_mm is not None:
        parts.append(f"flip about machine X {setup.flip_axis_x_mm:.3f} mm")
    parts.append(f"then {setup.wcs}")
    if setup.reprobe:
        parts.append("re-probe " + " and ".join(setup.reprobe))
    return "; ".join(parts)


# ------------------------------------------------------------------ the hold

@dataclass
class RingHold:
    """How much of a through-cut ring keeps its hold once the anterior is cut."""
    ring: str                 # "perimeter", "opening" (a lens's) or "hole" (decorative)
    op: str                   # the posterior op that cuts it through
    at: tuple                 # the ring's center, design frame, mm
    held: float               # the fraction of the ring the hold survives on
    deepest_mm: float         # the anterior's deepest cut along the ring
    hold_mm: float            # the onion skin, or the perimeter's tab height
    tabs: bool = False        # the hold is the perimeter's tabs
    rims: int = 1             # the front's rims: 2 for separated rims


def skin_holds(relief: CastleRelief, castle: CastleParams, params: CastleCamParams,
               step_mm: float = 0.5) -> list[RingHold]:
    """Each through-cut ring the anterior cuts into, and how much of it the
    hold survives on (2.0).

    The posterior's through-cuts stop an onion skin above the front face, and
    the perimeter's tabs stand up from it; the anterior, cut first, takes
    material off that same face. Where it cuts deeper than the skin at a
    ring's edge, the skin there joins nothing. A chamfer along part of the
    perimeter leaves the part held by the rest; a bezel round a whole lens
    opening frees the opening's core when the posterior's eyewires cut
    through. The depth is read along each ring, the deepest within a cell of
    it on the part's side; a ring the anterior does not reach is left out.
    """
    if relief.anterior is None:
        return []
    from scipy.ndimage import maximum_filter

    f = relief.field
    res = float(f.resolution)
    ox, oy = f.origin
    rows, cols = f.z.shape
    depth = np.where(_front_mask(relief), relief.anterior_depth, -np.inf)
    near = maximum_filter(depth, size=3, mode="constant", cval=-np.inf)
    skin = float(castle.onion_skin_mm)
    tabs = castle.holding.tabs_on()
    holes = [h.representative_point() for h in relief.partition.holes]
    parts = relief.partition.parts
    out: list[RingHold] = []
    for part in parts:
        rings = [("perimeter", "Perimeter", part.exterior)]
        for r in part.interiors:
            hole = any(Polygon(r).contains(pt) for pt in holes)
            rings.append(("hole", "Holes", r) if hole else ("opening", "Eyewires", r))
        for kind, op, ring in rings:
            if not params.is_op_enabled(op):
                continue
            on_tabs = tabs and kind == "perimeter"
            hold = float(castle.holding.tab_height_mm) if on_tabs else skin
            if hold <= ANTERIOR_BAND_MM:
                continue                  # the maker keeps nothing to hold it
            line = LineString(ring.coords)
            n = max(8, int(np.ceil(line.length / step_mm)))
            xy = get_coordinates(line_interpolate_point(
                line, np.linspace(0.0, line.length, n, endpoint=False)))
            i = np.clip(np.rint((xy[:, 1] - oy) / res).astype(int), 0, rows - 1)
            j = np.clip(np.rint((xy[:, 0] - ox) / res).astype(int), 0, cols - 1)
            d = near[i, j]
            d = d[np.isfinite(d)]
            if not len(d) or not (d > ANTERIOR_BAND_MM).any():
                continue
            c = Polygon(ring).centroid
            out.append(RingHold(kind, op, (float(c.x), float(c.y)),
                                float(np.mean(d < hold - ANTERIOR_BAND_MM)), float(d.max()),
                                hold, on_tabs, len(parts)))
    return out


def skin_hold_notes(holds: list[RingHold]) -> list[tuple[bool, str]]:
    """The log's lines for `skin_holds`, each with whether it is a warning: a
    ring held nowhere is one; a ring held on part of its length is said."""
    out = []
    for h in holds:
        x, y = h.at
        where = {"perimeter": ("the perimeter" if h.rims < 2
                               else f"the perimeter of the rim at ({x:.1f}, {y:.1f}) mm"),
                 "opening": f"the lens opening at ({x:.1f}, {y:.1f}) mm",
                 "hole": f"the hole at ({x:.1f}, {y:.1f}) mm"}[h.ring]
        hold = (f"the {h.hold_mm:.2f} mm tabs" if h.tabs
                else f"the {h.hold_mm:.2f} mm onion skin")
        if h.held <= 0.0:
            freed = "the part is free" if h.ring == "perimeter" else "its core comes loose"
            verb = "cuts" if h.op == "Perimeter" else "cut"
            out.append((True, f"Two-sided: the anterior cuts deeper than {hold} all round "
                              f"{where}, to {h.deepest_mm:.2f} mm, so {freed} when the "
                              f"posterior's {h.op} {verb} through."))
        elif h.held < 0.995:
            out.append((False, f"Two-sided: the anterior cuts deeper than {hold} along "
                               f"{100.0 * (1.0 - h.held):.0f}% of {where}; "
                               f"{'they hold' if h.tabs else 'it holds'} on the rest."))
    return out
