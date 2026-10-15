"""Two-sided machining of a flat blank (BUILDPLAN M24 §9).

A flat-blank flip is a fixture and bookkeeping problem. Side one is the
posterior program as it has always been, less the through-cuts when they
move to side two; the blank is then flipped about the fixture's flip axis
and re-registered on its dowel pins, and side two machines the anterior:
the brow chamfers, the anterior bezel, the anterior seats and sculpts, and
the eyewires, the holes and the perimeter last, so the blank stays rigid
for both faces.

Side two is **the anterior Z-map as a relief of its own**: mirrored in X
about the flip line, re-zeroed on the blank's new bottom (the fixture
plane, where the former stock top lay) with the former anterior face as the
new top, so the generators that cut a posterior cut it unchanged. The
anterior seats are its pockets; the material a feature took off the front
is its feature band. A front that takes nothing off the front has no side
two, and posts byte-identical with one setup.

Kernel-free, like everything in `core.cam`: it reads a `CastleRelief` and
writes ops and setups.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely import contains_xy, prepare
from shapely.affinity import scale as _scale
from shapely.geometry import Polygon

from ..geometry.regions import CastlePartition, Zone
from ..project.schema import CastleCamParams, CastleParams, Setup
from ..relief.castle import CastleRelief
from ..relief.heightfield import Heightfield
from .castle_ops import CamOp, generate_castle_program

__all__ = ["TwoSidedJob", "anterior_setup_relief", "flipped_castle", "mirror_polygon",
           "mirrored_partition", "needs_second_side", "plan_two_sided", "FLIP_PAUSE",
           "ANTERIOR_BAND_MM", "THROUGH_CUT_OPS"]

#: The ops that open the part and release it: on side two by default, so the
#: blank is rigid while both faces are cut.
THROUGH_CUT_OPS = frozenset({"Eyewires", "Holes", "Lens Groove", "Perimeter"})
#: Material taken off the front deeper than this is a feature side two finishes.
ANTERIOR_BAND_MM = 0.05
#: The pause GuildSend classifies as the flip; the details follow it.
FLIP_PAUSE = "Flip stock and re-register on dowel pins"


@dataclass
class TwoSidedJob:
    """What the two sides cut, and how the machine gets from one to the other."""
    side_one: list                     # CamOp, side one (posterior, G54)
    side_two: list                     # CamOp, side two (anterior, G55); empty = one setup
    relief_two: CastleRelief | None    # the anterior as a relief, for the simulation
    castle_two: CastleParams | None    # the castle as side two sees it (no pad, tabs)
    setups: list = field(default_factory=list)      # Setup records, in order
    notes: list = field(default_factory=list)

    @property
    def two_sided(self) -> bool:
        return bool(self.side_two)


# ------------------------------------------------------------------ geometry

def mirror_polygon(poly, mirror_x: float = 0.0):
    """`poly` mirrored in X about ``x = mirror_x``."""
    return _scale(poly, xfact=-1.0, yfact=1.0, origin=(float(mirror_x), 0.0))


def mirrored_partition(partition: CastlePartition, mirror_x: float = 0.0) -> CastlePartition:
    """The partition as side two sees it: every polygon mirrored, the zones
    keeping their names (the heights are the same for both eyes), the seams
    dropped (no footing is cut on side two), the holes mirrored so `is_hole`
    still tells an opening from an aperture."""
    zones = [Zone(z.name, z.kind, z.side, mirror_polygon(z.polygon, mirror_x))
             for z in partition.zones]
    return CastlePartition(
        body=mirror_polygon(partition.body, mirror_x), zones=zones, edges=[],
        matched=partition.matched,
        holes=[mirror_polygon(h, mirror_x) for h in partition.holes])


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
    seat there: something for side two to cut."""
    if relief.anterior is not None:
        depth = np.where(_front_mask(relief), relief.anterior_depth, 0.0)
        if bool((depth > ANTERIOR_BAND_MM).any()):
            return True
    return bool(relief.anterior_pocket_polys)


def anterior_setup_relief(relief: CastleRelief, castle: CastleParams, *,
                          mirror_x: float = 0.0) -> CastleRelief | None:
    """The anterior as a relief for side two, or None when there is nothing
    to cut there.

    Mirrored in X about `mirror_x` (the flip line in the design frame: the
    blank's center line, 0, on the Guild bed), and re-zeroed: the new top is
    the former anterior face at ``T``, the blank's thickness, and the target
    height is ``T - anterior``. The anterior seats become the pockets; the
    cells a feature took material from become the band the Features pass
    finishes, at the anterior features' steepest slope.
    """
    if not needs_second_side(relief):
        return None
    f = relief.field
    rows, cols = f.z.shape
    res = float(f.resolution)
    ox, oy = f.origin
    T = float(castle.stock.blank_thickness_mm)
    a = relief.anterior_z
    front = _front_mask(relief)                        # the face side two cuts
    depth = np.where(front, relief.anterior_depth, 0.0)
    z2 = np.fliplr(T - a)
    ox2 = 2.0 * float(mirror_x) - (ox + (cols - 1) * res)
    origin2 = (float(ox2), float(oy))
    seats2 = [mirror_polygon(p, mirror_x) for p in relief.anterior_pocket_polys]
    seat_mask = _mask(seats2, origin2, rows, cols, res)
    # the new top: the former front, flat at T, or the pressed slab's own
    # bottom turned over (M25)
    if relief.stock_bottom is not None:
        new_top = np.fliplr(T - relief.stock_bottom.z)
        new_bottom = np.fliplr(T - relief.stock_top.z)
    else:
        new_top = np.full((rows, cols), T)
        new_bottom = None
    surface2 = np.where(seat_mask, new_top, z2)   # the passes sail over the seats
    band = np.fliplr(depth > ANTERIOR_BAND_MM) & ~seat_mask
    slope = float(castle.anterior_feature_slope()) if band.any() else 0.0
    return CastleRelief(
        field=Heightfield(z=z2, origin=origin2, resolution=res),
        inside=np.fliplr(front).copy(),
        zone_index=np.fliplr(relief.zone_index).copy(),
        partition=mirrored_partition(relief.partition, mirror_x),
        pocket_polys=seats2,
        surface_field=Heightfield(z=surface2, origin=origin2, resolution=res),
        feature_band=band if band.any() else None,
        feature_max_slope_deg=slope,
        stock_top=(Heightfield(z=new_top, origin=origin2, resolution=res)
                   if relief.stock_bottom is not None else None),
        stock_bottom=(Heightfield(z=new_bottom, origin=origin2, resolution=res)
                      if new_bottom is not None else None),
    )


def flipped_castle(castle: CastleParams) -> CastleParams:
    """The castle as side two sees it: no pad block (it is on the back), the
    part released on tabs (the onion skin would hold nothing: side one has
    already cut the stock around the part down to the terraces), and every
    seat's face swapped, so the anterior seats read as pockets from the top."""
    inlays = [i.model_copy(update={"face": "posterior" if i.face == "anterior" else "anterior"})
              for i in castle.inlays]
    return castle.model_copy(update={
        "stock": castle.stock.model_copy(update={"use_pad_block": False}),
        "holding": castle.holding.model_copy(update={"strategy": "tabs"}),
        "inlays": inlays,
    })


# ------------------------------------------------------------------ the plan

def _side_two_inlays(castle_two: CastleParams, inlay_polys, mirror_x: float,
                     params: CastleCamParams, tools_cfg, default_tool, T: float) -> list:
    """The Inlays op for side two: the former anterior seats, mirrored, cut
    from the new top down by their depth."""
    if not castle_two.inlays or not inlay_polys:
        return []
    from ..geometry.inlays import inlay_cuts
    from .inlay_ops import inlay_ops
    polys2 = [mirror_polygon(p, mirror_x) for p in inlay_polys]
    seats = inlay_cuts(castle_two.inlays, polys2, [], posterior_reference=T)
    seats = [s for s in seats if s.posterior and s.depth_mm > 0.0]
    return inlay_ops(seats, params, tools_cfg, default_tool) if seats else []


def plan_two_sided(relief: CastleRelief, castle: CastleParams, hinge_polys, tool: dict,
                   params: CastleCamParams, tools_cfg: dict | None = None,
                   inlay_polys=(), *, mirror_x: float = 0.0,
                   flip_axis_x_mm: float | None = None, progress=None) -> TwoSidedJob:
    """Both sides' ops and the setups between them.

    `params.two_sided` decides: ``off`` posts the posterior alone as before;
    ``on`` posts two sides whatever the front carries; ``auto`` posts two
    when the front takes material off the anterior or seats something there.
    With two sides, `params.through_cuts_side` ``two`` moves the eyewires,
    the holes and the perimeter to side two (and the groove with them, when
    it is on, since it is cut through the open apertures); ``one`` keeps
    them on side one with the skin or the tabs as today.
    """
    mode = getattr(params, "two_sided", "auto")
    relief_two = None if mode == "off" else anterior_setup_relief(relief, castle, mirror_x=mirror_x)
    if mode == "on" and relief_two is None:
        relief_two = _flat_second_side(relief, castle, mirror_x)
    notes: list = []
    if relief_two is None:
        ops = generate_castle_program(relief, castle, hinge_polys, tool, params=params,
                                      progress=progress, tools_cfg=tools_cfg,
                                      inlay_polys=inlay_polys)
        stock_top = castle.stock.total_pad_height_mm
        return TwoSidedJob(ops, [], None, None,
                           [Setup(side="posterior", wcs="G54", program="posterior_cut.nc",
                                  stock_top_mm=stock_top)], notes)

    through_two = getattr(params, "through_cuts_side", "two") == "two"
    groove_on = relief.groove is not None
    if through_two and groove_on:
        through_two = False
        notes.append("The lens groove is cut from the back through the open apertures, "
                     "so a grooved front keeps its through-cuts on side one.")
    off_one = dict(params.op_enabled)
    off_two = dict(params.op_enabled)
    for name in THROUGH_CUT_OPS:
        if through_two:
            off_one[name] = False
        else:
            off_two[name] = False
    off_two["Hinge Pockets"] = False
    params_one = params.model_copy(update={"op_enabled": off_one})
    params_two = params.model_copy(update={"op_enabled": off_two})

    ops_one = generate_castle_program(relief, castle, hinge_polys, tool, params=params_one,
                                      progress=progress, tools_cfg=tools_cfg,
                                      inlay_polys=inlay_polys)
    castle_two = flipped_castle(castle)
    T = float(castle.stock.blank_thickness_mm)
    ops_two = generate_castle_program(relief_two, castle_two, [], tool, params=params_two,
                                      progress=progress, tools_cfg=tools_cfg, inlay_polys=())
    ops_two = [op for op in ops_two if op.paths]
    if params.is_op_enabled("Inlays"):
        from .castle_ops import resolve_tool
        inlay_tool = (resolve_tool(params.tool_for_op("Inlays"), tools_cfg or {}, default=tool)
                      if tools_cfg else tool)
        seat_ops = _side_two_inlays(castle_two, inlay_polys, mirror_x, params_two, tools_cfg,
                                    inlay_tool, T)
        if seat_ops:
            # after the relief finishes the face the seats are measured from,
            # before the through-cuts open the part: the same place as side one
            k = next((i for i, op in enumerate(ops_two) if op.name in THROUGH_CUT_OPS),
                     len(ops_two))
            ops_two[k:k] = seat_ops
    if not ops_two:
        notes.append("Side two had nothing to cut after all; one setup posted.")
        ops = generate_castle_program(relief, castle, hinge_polys, tool, params=params,
                                      progress=progress, tools_cfg=tools_cfg,
                                      inlay_polys=inlay_polys)
        return TwoSidedJob(ops, [], None, None,
                           [Setup(side="posterior", wcs="G54", program="posterior_cut.nc",
                                  stock_top_mm=castle.stock.total_pad_height_mm)], notes)
    reprobe = ["Z"] + (["XY"] if getattr(params, "reprobe_xy", False) else [])
    setups = [
        Setup(side="posterior", wcs="G54", program="posterior_cut.nc",
              stock_top_mm=castle.stock.total_pad_height_mm, mirror_x_mm=float(mirror_x),
              flip_axis_x_mm=flip_axis_x_mm),
        Setup(side="anterior", wcs="G55", program="back_cut.nc", flip="manual",
              stock_top_mm=T, mirror_x_mm=float(mirror_x), flip_axis_x_mm=flip_axis_x_mm,
              reprobe=reprobe,
              notes=[("through-cuts on side two" if through_two else "through-cuts on side one"),
                     "released on tabs" if through_two else ""]),
    ]
    setups[1].notes = [n for n in setups[1].notes if n]
    return TwoSidedJob(ops_one, ops_two, relief_two, castle_two, setups, notes)


def _flat_second_side(relief: CastleRelief, castle: CastleParams, mirror_x: float) -> CastleRelief:
    """A side two with nothing to finish on the face, for a maker who wants
    the through-cuts there anyway (`two_sided == "on"`)."""
    f = relief.field
    rows, cols = f.z.shape
    res = float(f.resolution)
    ox, oy = f.origin
    T = float(castle.stock.blank_thickness_mm)
    origin2 = (2.0 * float(mirror_x) - (ox + (cols - 1) * res), float(oy))
    flat = Heightfield(z=np.full((rows, cols), T), origin=origin2, resolution=res)
    return CastleRelief(field=flat, inside=np.fliplr(relief.inside).copy(),
                        zone_index=np.fliplr(relief.zone_index).copy(),
                        partition=mirrored_partition(relief.partition, mirror_x),
                        surface_field=flat)


def flip_pause_text(setup: Setup) -> str:
    """The pause GuildSend parses, with the flip line, the work offset and
    the probe to run after it."""
    parts = [FLIP_PAUSE]
    if setup.flip_axis_x_mm is not None:
        parts.append(f"flip about machine X {setup.flip_axis_x_mm:.3f} mm")
    parts.append(f"then {setup.wcs}")
    if setup.reprobe:
        parts.append("re-probe " + " and ".join(setup.reprobe))
    return "; ".join(parts)
