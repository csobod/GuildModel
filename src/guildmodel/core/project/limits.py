"""What each parameter is *allowed* to be, given the rest of the project.

A schema field has a range because of what it means — an eyewire wall is
somewhere between half a millimeter and twelve. That range is fixed, and it is
not the interesting one. The interesting range is the one that moves: a nosepad
tower cannot be 12 mm tall out of a 6 mm blank under a 4 mm pad block, and a
hinge pocket cannot be sunk deeper than the endpiece it is cut into without
coming out of the front of the frame.

This module derives that second range. `ParamSlider` (the GUI) travels it, so
dragging can never ask for something impossible; the spin box keeps the first
one, so typing is never refused. Nothing here imports a kernel, Qt, or the CAM,
and every bound is a pure function of `CastleParams` plus — where the answer
depends on the drawing — a `CastlePartition`.

**Every rule below was measured, not reasoned.** The three that break a build
were found by sweeping the panel's own spin-box ranges on all three fixtures
(2026-08-10):

  * *Zone height against stock.* The model kernels do not know stock exists —
    a 15 mm nosepad builds a clean, watertight, unmachinable solid. Nothing
    caught this before, at either end of the toolchain.
  * *Hinge pocket depth.* On the demo at a 5.5 mm endpiece the removed volume
    stops changing at 5.5 mm of depth (7362.9 mm3 at 5.5, 6.0 and 8.0) because
    by then the pocket is a hole clean through the front face. Same shape on
    the gabriel and the aviator.
  * *Groove depth.* The rim-lip re-partition stops yielding the castle at
    2.30 mm on the demo, **1.55 mm on the gabriel** and 1.90 mm on the aviator
    — two of those inside the 0.2–2.0 mm the panel offered, and the guard that
    fires there was itself raising `NameError` (fixed with this work; see
    `geometry.rings.BooleanError`). The ceiling is drawing-dependent, so it is
    measured per partition rather than assumed: `max_groove_depth`.

The rest are geometric identities — a chamfer of width *w* at angle *a* drops
*w·tan a*, so on a wall *h* tall it comes out the other side beyond *h / tan a*
— or the two conditions `cam.castle_ops.groove_warnings` already stated in
prose and warned about after the fact.

**Most of the interesting bounds are ceilings, and that is a finding rather than
an oversight.** Every zone height was swept to the bottom of its range on the
demo: 0.0 mm of endpiece, bridge, nosepad or either eyewire builds a solid that
verifies clean. Nothing down there breaks, so nothing down there is bounded, and
the panel's own 0.5 mm floor stands as the sensible minimum it always was. The
real floors are the two that come from a shape having to fit *between* things —
the groove V clearing the anterior face, and a pad block staying on its blank.

Bounds are computed against the *current* value of every other parameter and
re-derived after each change, the way a constraint-driven CAD panel behaves.
So raising a chamfer's angle can push its width out of range; the width is then
marked rather than rewritten, and lowering either one opens the other again.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .schema import CastleParams, EdgeFeature, StockDefinition

#: The thinnest floor this project is willing to call a pocket rather than a
#: hole. A choice, not a measurement — the measurement only says that at zero
#: the hinge pocket has broken through the anterior face.
MIN_POCKET_FLOOR_MM = 0.5

#: Back-off from the last groove depth that re-partitioned successfully. One
#: bisection step of `max_groove_depth`, so the ceiling offered is a depth that
#: was tried and worked rather than the first one that was not tried.
GROOVE_DEPTH_MARGIN_MM = 0.05

#: Coarsest step `max_groove_depth` bisects to. Each probe re-partitions the
#: whole castle (~70 ms on the demo), so this trades resolution for the ~0.5 s
#: the search costs once per drawing.
GROOVE_BISECT_TOL_MM = 0.05


@dataclass(frozen=True)
class Limit:
    """A safe range and the rule that produced it.

    `reason` is shown to the maker verbatim when a value falls outside, so it is
    written as a sentence about their frame, not about this module.
    """

    low: float
    high: float
    reason: str = ""

    def clamp(self, value: float) -> float:
        return max(self.low, min(self.high, float(value)))

    def holds(self, value: float, eps: float = 1e-9) -> bool:
        return self.low - eps <= float(value) <= self.high + eps


# --------------------------------------------------------------------- stock

def stock_ceiling(stock: StockDefinition, polygon=None) -> float:
    """How tall material stands over `polygon` — the whole of it, not its best part.

    A zone that laps over the edge of the pad block can only be as tall as the
    blank, because the part hanging off has nothing but blank under it. So the
    answer is the *minimum* stock height across the footprint, which makes
    `within` the right test and "overlaps a bit" worth nothing.

    With no polygon, or no pad block, the blank alone. Measured on the three
    fixtures with the default 45x45 pad: bridge and both nosepads sit wholly on
    it, the eyewires lap over (18–44% on the pad), and the endpieces are
    entirely off it.
    """
    blank = float(stock.blank_thickness_mm)
    if not stock.use_pad_block:
        return blank
    if stock.pad_block_length_mm <= 0 or stock.pad_block_width_mm <= 0:
        return blank
    if polygon is None or polygon.is_empty:
        return blank
    from shapely.geometry import box

    pad = box(stock.pad_block_dx_mm - stock.pad_block_length_mm / 2.0,
              stock.pad_block_dy_mm - stock.pad_block_width_mm / 2.0,
              stock.pad_block_dx_mm + stock.pad_block_length_mm / 2.0,
              stock.pad_block_dy_mm + stock.pad_block_width_mm / 2.0)
    return float(stock.total_pad_height_mm) if polygon.within(pad) else blank


#: Which zones the pad block exists for, when there is no drawing to measure.
#: `StockDefinition` says it in words — "the raised nosepad pad-block" — and the
#: three fixtures agree, but a drawing whose nosepads run off the block is
#: exactly the case worth measuring rather than assuming.
_PAD_KINDS = ("nosepad",)


def zone_ceilings(stock: StockDefinition, partition=None) -> dict[str, float]:
    """Stock ceiling per zone *kind*, and per zone *name* for the overrides.

    Without a partition, falls back to what the pad block is documented to be
    for. With one, every zone is measured against the actual block, so moving
    the pad off the nose or shrinking it takes the nosepad ceiling down with it.
    """
    blank = float(stock.blank_thickness_mm)
    out: dict[str, float] = {}
    if partition is None:
        padded = float(stock.total_pad_height_mm)     # already blank-only when off
        for kind in ("endpiece", "bridge", "nosepad",
                     "eyewire_superior", "eyewire_inferior"):
            out[kind] = padded if kind in _PAD_KINDS else blank
        return out

    for zone in partition.zones:
        ceiling = stock_ceiling(stock, zone.polygon)
        out[zone.name] = ceiling
        # A kind is only as tall as its shortest zone: one nosepad hanging off
        # the block governs the control that drives both.
        out[zone.kind] = min(out.get(zone.kind, ceiling), ceiling)
    return out


def stock_limits(stock: StockDefinition) -> dict[str, Limit]:
    """The stock's own internal consistency: the pad block sits on the blank."""
    half_l = max(0.0, (stock.blank_length_mm - stock.pad_block_length_mm) / 2.0)
    half_w = max(0.0, (stock.blank_width_mm - stock.pad_block_width_mm) / 2.0)
    on_blank = "the pad block has to sit on the blank"
    return {
        "stock.pad_block_length_mm": Limit(
            0.0, float(stock.blank_length_mm),
            f"the blank is {stock.blank_length_mm:g} mm long"),
        "stock.pad_block_width_mm": Limit(
            0.0, float(stock.blank_width_mm),
            f"the blank is {stock.blank_width_mm:g} mm wide"),
        "stock.pad_block_dx_mm": Limit(-half_l, half_l, on_blank),
        "stock.pad_block_dy_mm": Limit(-half_w, half_w, on_blank),
    }


# --------------------------------------------------------------- the castle

def _stack(stock: StockDefinition) -> str:
    if not stock.use_pad_block:
        return f"a {stock.blank_thickness_mm:g} mm blank"
    return (f"a {stock.blank_thickness_mm:g} + {stock.pad_block_thickness_mm:g} mm "
            "stack")


def _wall_top(castle: CastleParams) -> float:
    """The shorter of the two eyewire walls — the one the groove has to fit in."""
    return min(castle.zones.eyewire_superior_mm, castle.zones.eyewire_inferior_mm)


def _spanned_height(castle: CastleParams, feature: EdgeFeature) -> float:
    """The thinnest wall an edge feature runs along.

    Zone names first (that is what `EdgeFeature.zones` holds, and what a
    per-zone override is keyed by), falling back to the kind embedded in the
    name, so a per-drawing zone like `eyewire_superior_ou` resolves without the
    partition being handed in.
    """
    kinds = {"endpiece": castle.zones.endpiece_mm,
             "bridge": castle.zones.bridge_mm,
             "nosepad": castle.zones.nosepad_mm,
             "eyewire_superior": castle.zones.eyewire_superior_mm,
             "eyewire_inferior": castle.zones.eyewire_inferior_mm}
    lookup = dict(kinds)
    lookup.update(castle.zone_height_overrides)

    def height_of(name: str) -> float:
        if name in lookup:
            return float(lookup[name])
        for kind, value in sorted(kinds.items(), key=lambda kv: -len(kv[0])):
            if name.startswith(kind):
                return float(value)
        return min(kinds.values())

    names = list(feature.zones or ())
    if not names:
        return min(kinds.values())
    return min(height_of(n) for n in names)


def _drop_for(profile: str, width: float, angle_deg: float, radius: float) -> float:
    """How far below the surface a profile of this shape reaches."""
    if profile == "fillet":
        return float(radius)
    return float(width) * math.tan(math.radians(max(angle_deg, 1e-6)))


def edge_feature_limits(castle: CastleParams,
                        feature: EdgeFeature) -> dict[str, Limit]:
    """Bounds for one edge feature, against the wall it actually runs along.

    A chamfer of width *w* at angle *a* drops *w·tan a* below the face; a
    round-over of radius *r* drops *r*. Either has to stop short of the far face
    by `min_thickness_mm`, so the budget is `height - min_thickness`, and each
    of width / angle / radius is bounded by that budget given the other two.

    Measured on the demo (2026-08-10): a 12 mm posterior chamfer at 45 degrees
    on the 4.8 mm brow wall builds a solid that overlaps itself along 3 edges
    and will not export as valid STL. The same feature with `min_thickness_mm`
    at 2.5 mm verifies clean, which is the clamp doing its job — and
    `height / tan(45 deg)` puts the ceiling at 4.8 mm, short of the failure.
    """
    height = _spanned_height(castle, feature)
    budget = max(0.0, height - float(feature.min_thickness_mm))
    wall = f"the {height:g} mm wall it runs along"

    out: dict[str, Limit] = {
        "min_thickness_mm": Limit(
            0.0, height,
            f"{wall} is all there is to keep"),
    }
    if budget <= 0.0:
        return out

    angle = max(float(feature.angle_deg), 1e-6)
    tan_a = math.tan(math.radians(angle))
    out["width_mm"] = Limit(
        0.0, budget / tan_a if tan_a > 0 else budget,
        f"a {angle:g}° chamfer any wider cuts through {wall}")
    out["radius_mm"] = Limit(
        0.0, budget, f"a round-over any deeper cuts through {wall}")
    width = max(float(feature.width_mm), 1e-6)
    out["angle_deg"] = Limit(
        0.0, math.degrees(math.atan(budget / width)),
        f"a {width:g} mm chamfer any steeper cuts through {wall}")
    return out


def max_groove_depth(partition, low: float = 0.05, high: float = 4.0,
                     tol: float = GROOVE_BISECT_TOL_MM) -> float:
    """The deepest lens groove whose rim lip still re-partitions into the castle.

    Drawing-dependent and not derivable: shrinking every aperture by `depth`
    moves the SCULPT cut lines' intersections, and past some depth the result is
    no longer the same set of zones. Measured on the fixtures at 2.25 mm (demo),
    1.50 mm (gabriel) and 1.85 mm (aviator).

    Costs one castle re-partition per probe — about 70 ms on the demo, so under
    a second for the whole search. Call it once per drawing and cache; it does
    not depend on any other parameter.
    """
    from ..geometry.rings import lip_partition

    def survives(depth: float) -> bool:
        try:
            lip_partition(partition, depth)
        except Exception:
            return False
        return True

    if not survives(low):
        return 0.0
    if survives(high):
        return float(high)
    lo, hi = float(low), float(high)
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if survives(mid):
            lo = mid
        else:
            hi = mid
    return max(0.0, lo - GROOVE_DEPTH_MARGIN_MM)


def castle_limits(castle: CastleParams, partition=None,
                  groove_ceiling: float | None = None) -> dict[str, Limit]:
    """Every bound the Model and Stock tabs need, keyed by schema path.

    `partition` sharpens the stock ceilings from "what the pad block is for" to
    "what this drawing's zones actually stand on". `groove_ceiling` is
    `max_groove_depth`'s answer, passed in rather than computed because it costs
    a re-partition per probe and only changes when the drawing does.
    """
    stock = castle.stock
    out: dict[str, Limit] = dict(stock_limits(stock))
    ceilings = zone_ceilings(stock, partition)
    stack = _stack(stock)

    for kind, field in (("endpiece", "zones.endpiece_mm"),
                        ("bridge", "zones.bridge_mm"),
                        ("nosepad", "zones.nosepad_mm"),
                        ("eyewire_superior", "zones.eyewire_superior_mm"),
                        ("eyewire_inferior", "zones.eyewire_inferior_mm")):
        ceiling = ceilings.get(kind, float(stock.blank_thickness_mm))
        out[field] = Limit(
            0.0, ceiling,
            f"{stack} gives {ceiling:g} mm of material over the {kind.replace('_', ' ')}")

    # Per-zone overrides answer to their own footprint, which is the whole point
    # of having them: one nosepad off the block is not the other one's problem.
    for name, ceiling in ceilings.items():
        if partition is not None and any(z.name == name for z in partition.zones):
            out[f"zone_height_overrides.{name}"] = Limit(
                0.0, ceiling, f"{stack} gives {ceiling:g} mm of material over {name}")

    endpiece = float(castle.zones.endpiece_mm)
    out["hinge_pocket_depth_mm"] = Limit(
        0.0, max(0.0, endpiece - MIN_POCKET_FLOOR_MM),
        f"a pocket deeper than this comes out of the front of a {endpiece:g} mm "
        f"endpiece")

    out.update(_groove_limits(castle, groove_ceiling))
    out.update(_finishing_limits(castle))
    return out


def _groove_limits(castle: CastleParams,
                   groove_ceiling: float | None) -> dict[str, Limit]:
    """The V has to fit between the anterior face and the top of the wall.

    Both conditions are `cam.castle_ops.groove_warnings`', which has stated them
    in prose since V1 and warned about them after the toolpath was posted.
    """
    groove = castle.lens_groove
    wall = _wall_top(castle)
    half = float(groove.width_mm) / 2.0
    offset = float(groove.anterior_offset_mm)
    out = {
        "lens_groove.anterior_offset_mm": Limit(
            half, max(half, wall - half),
            f"the V's flanks have to clear the anterior face and the {wall:g} mm "
            f"wall top"),
        "lens_groove.width_mm": Limit(
            0.0, max(0.0, 2.0 * min(offset, wall - offset)),
            f"a wider V reaches past the anterior face or the {wall:g} mm wall top"),
    }
    if groove_ceiling is not None and groove_ceiling > 0.0:
        out["lens_groove.depth_mm"] = Limit(
            0.0, float(groove_ceiling),
            "a deeper groove shrinks the apertures until the castle no longer "
            "partitions into the same zones")
    return out


def _finishing_limits(castle: CastleParams) -> dict[str, Limit]:
    """Posterior-finishing clamps: a floor above the surface carves nothing.

    Not a broken build — a no-op one, which is the quieter failure. Each clamp
    is "never leave the frame thinner than this", so at the height of the zone
    the feature cuts into there is nothing left for it to do.
    """
    z = castle.zones
    splay = min(z.bridge_mm, z.nosepad_mm)
    rim = min(z.eyewire_superior_mm, z.eyewire_inferior_mm)
    nothing = "the feature carves nothing at or above the height it cuts into"
    scoop = castle.bridge_relief
    # Past this on the SUM of the two radii the U has no straight ramp left and
    # `geometry.blends._fit_radii` shrinks both to fit — the shape stops
    # responding to the slider. Reported per-radius against the other one, so the
    # number a maker sees is the headroom the one they are turning actually has.
    half_w = max(scoop.width_mm / 2.0, 1e-9)
    depth = max(scoop.depth_mm, 1e-9)
    r_sum = (half_w * half_w + depth * depth) / (2.0 * depth)
    r_full = (f"a wider or shallower scoop is needed for more than this: at "
              f"{scoop.width_mm:g} x {scoop.depth_mm:g} mm the two radii can "
              f"total {r_sum:.1f} mm before the U loses its straight wall")
    gap = "the gap would swallow the whole run, leaving nothing to cut"
    return {
        "pad_splay.anterior_clamp_mm": Limit(0.0, splay, nothing),
        "pad_splay.gap_mm": Limit(0.0, 2.0 * castle.pad_splay.run_mm, gap),
        "eyewire_bezel.anterior_clamp_mm": Limit(0.0, rim, nothing),
        "bridge_relief.anterior_clamp_mm": Limit(0.0, float(z.bridge_mm), nothing),
        "bridge_relief.depth_mm": Limit(
            0.0, float(z.bridge_mm),
            f"the scoop cannot be deeper than the {z.bridge_mm:g} mm bridge"),
        "bridge_relief.exterior_radius_mm": Limit(
            0.0, max(r_sum - scoop.interior_radius_mm, 0.0), r_full),
        "bridge_relief.interior_radius_mm": Limit(
            0.0, max(r_sum - scoop.exterior_radius_mm, 0.0), r_full),
    }
