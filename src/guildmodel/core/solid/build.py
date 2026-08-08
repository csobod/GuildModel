"""The castle as a B-Rep solid (BUILDPLAN Stage 2).

The master representation. Where `core/relief/castle.py` paints heights into a
raster, this builds the same shape out of real surfaces meeting along real
curves — so a cut has an exact edge, the solid is closed by construction, and
the viewer can be handed a genuine edge set instead of a triangle soup.

**Terraces.** Each castle zone's polygon extruded to its own height and fused.

**Footings — swept cross-sections, not edge fillets.** The Stage 1 spike found
that `BRepFilletAPI_MakeFillet` cannot build these at all: 0 of 16 edges at the
Demo Project's scheduled radii. The reason is not kernel fragility. Those radii
are 4-48 mm while the steps they blend are 0.2-5.8 mm, so they were never 3D
edge fillets in Fusion either — they are radii of a *cross-section* S-blend,
which is precisely what `relief.castle._footing_z` already computes. Sweeping
that existing profile along the SCULPT cut line succeeds 10/10 in ~0.1 s, and it
reproduces the blend the Demo Project STL was verified against rather than
hoping a kernel fillet lands in the same place.

**Composite rule**, carried over verbatim from the raster so the two paths agree
where they should: low-side fills apply first, then high-side carves win — a
later fillet cuts. Here that is `(terraces ∪ fills) − carves`.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import numpy as np
from shapely.geometry import Point

from ..geometry.regions import CastlePartition, ZoneEdge
from ..project.schema import CastleParams, FootingFillet
from ..relief.castle import _footing_spans, _footing_z
from .occ import (
    BooleanError,
    common,
    cut_many,
    extrude,
    fuse_all,
    is_valid,
    polygon_to_face,
    SourceCurves,
    volume,
    spline_wire,
)

from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_TransitionMode,
)
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Dir, gp_Pnt

ProgressFn = Callable[[str, float], None]

#: Stations sampled along a SCULPT cut when sweeping its footing profile. The
#: cut lines are gentle splines, so this is about capturing curvature, not
#: detail; 30 was ample on the demo frame and costs ~10 ms per edge.
FOOTING_STATIONS = 30

#: How far the swept cutter reaches above the tallest terrace and, for fills,
#: below the anterior face. Only needs to guarantee overlap for the boolean.
SWEEP_MARGIN_MM = 1.0


def _report(progress: Optional[ProgressFn], label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)


def zone_heights(partition: CastlePartition, castle: CastleParams,
                 heights: dict[str, float] | None = None) -> dict[str, float]:
    """Zone name -> posterior height, same resolution order as the raster path."""
    if heights is not None:
        return dict(heights)
    if not partition.classified:
        raise ValueError(
            "the section cuts did not yield recognisable castle zones; "
            "pass explicit zone heights"
        )
    out = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}
    out.update({n: mm for n, mm in castle.zone_height_overrides.items()
                if n in out})
    return out


# ------------------------------------------------------------------ terraces

#: Build zone boundaries from the drawing's authored curves instead of from the
#: flattened polygon — the model is then made of the curves GuildDraw drew,
#: rather than of a 342-segment approximation of them.
#:
#: A zone boundary is arcs of the outline and lens curves joined by the straight
#: SCULPT cuts that severed them; ~94% of every zone's vertices lie on an
#: authored curve, and `occ.curved_ring_wire` rebuilds those runs as trimmed
#: arcs. On the demo frame: 9,942 -> 8,237 edges, 4,971 -> 3,952 display edges,
#: watertight, valid, and a mesh volume within half a cubic millimetre of the
#: polygon build — the difference being the chord deficit the true curve
#: recovers.
#:
#: **The one thing that has to stay true**: whatever builds the terraces and
#: whatever clips the footing fills must use the SAME curve set. Clipping to a
#: polygonal zone prism while the terraces follow the curve leaves the fill a
#: chord-width short of the terrace it blends into, and the near-coincident
#: faces that produces tessellate with a crack — valid solid, leaking mesh.
#: That was the only defect in the curved build, and it is why `castle_base`
#: builds one `SourceCurves` and threads it through both.
CURVED_TERRACES = True


def build_terraces(partition: CastlePartition,
                   heights: dict[str, float],
                   curved: bool | None = None,
                   source: "SourceCurves | None" = None) -> TopoDS_Shape:
    """Every zone extruded to its height and fused — the stepped castle.

    With `curved` (default `CURVED_TERRACES`), zone boundaries are rebuilt from
    the drawing's authored curves. `SourceCurves` is built once here and reused
    across all nine zones — the per-vertex classification is the real cost, and
    building the OCCT handles nine times over would be waste.
    """
    use_curves = CURVED_TERRACES if curved is None else curved
    if use_curves and source is None:
        source = SourceCurves(partition)
    elif not use_curves:
        source = None
    solids = []
    for zone in partition.zones:
        poly = zone.polygon
        if poly.is_empty or poly.area <= 0:
            continue
        solids.append(extrude(polygon_to_face(poly, 0.0, curves=source),
                              heights[zone.name]))
    if not solids:
        raise BooleanError("partition has no zones with area")
    return fuse_all(solids)


def body_prism(partition: CastlePartition, height: float) -> TopoDS_Shape:
    """The whole footprint extruded — used to clip fills back inside the part."""
    return extrude(polygon_to_face(partition.body, 0.0), height)


# ------------------------------------------------------------------ footings

# Station placement and the high-side vote now live in `core/geometry/footings.py`
# so the mesh kernel can reach them without importing OCP. Re-exported under
# their old private names: same functions, and duplicating them is how two
# kernels start blending the same seam two different ways.
from ..geometry.footings import (                                # noqa: E402
    cut_stations as _stations,
    orient_high_side as _orient_high_side,
)


def _blend_section(p_xy, perp, h_high: float, h_low: float,
                   fillet: FootingFillet, side: str, top: float,
                   n: int = 40):
    """Half of the S-blend as a closed section in the (perp, Z) plane.

    The two halves are separate bodies because they act on different terraces
    and must be clipped to different zones — mirroring the raster's rule
    exactly (`castle.py`: `on_high = (zi == ia) & (d < span_high)` and
    `on_low = (zi == ib) & (d < span_low)`). Sweeping one full-width band and
    applying it to whatever it crossed was wrong: a band is up to ~8 mm wide at
    the scheduled radii and readily reaches a third zone it has no business
    touching.

    side="high" -> material to CARVE off the high terrace: above the blend
                   curve, over s in [-span_high, 0].
    side="low"  -> material to FILL onto the low terrace: below the blend
                   curve, over s in [0, span_low].
    """
    span_hi, span_lo = _footing_spans(
        h_high - h_low, fillet.exterior_mm, fillet.interior_mm, fillet.first)
    span = span_hi if side == "high" else span_lo
    if span <= 0:
        raise BooleanError(f"degenerate {side}-side footing span")

    s = (np.linspace(-span_hi, 0.0, n) if side == "high"
         else np.linspace(0.0, span_lo, n))
    z = _footing_z(s, h_high, h_low,
                   fillet.exterior_mm, fillet.interior_mm, fillet.first)

    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(perp[0]), float(perp[1])

    def at(u, v):
        return gp_Pnt(px + nx * float(u), py + ny * float(u), float(v))

    mp = BRepBuilderAPI_MakePolygon()
    for si, zi in zip(s, z):
        mp.Add(at(si, zi))
    close_z = top if side == "high" else -SWEEP_MARGIN_MM
    mp.Add(at(s[-1], close_z))
    mp.Add(at(s[0], close_z))
    mp.Close()
    return mp.Wire()


def _sweep(pts: np.ndarray, sections) -> TopoDS_Shape:
    ps = BRepOffsetAPI_MakePipeShell(spline_wire(pts, 0.0))
    # Fixed binormal, not Frenet: the blend profile must stay upright rather
    # than roll with the spine's curvature.
    ps.SetMode(gp_Dir(0.0, 0.0, 1.0))
    ps.SetTransitionMode(
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RightCorner)
    for wire in sections:
        ps.Add(wire, False, False)
    ps.Build()
    if not ps.IsDone():
        raise BooleanError("footing sweep did not complete")
    if not ps.MakeSolid():
        raise BooleanError("footing sweep did not close into a solid")
    return ps.Shape()


def footing_bodies(partition: CastlePartition, zone_edge: ZoneEdge,
                   heights: dict[str, float], fillet: FootingFillet,
                   top: float, zone_prisms: dict[str, TopoDS_Shape] | None = None,
                   stations: int = FOOTING_STATIONS,
                   source: "SourceCurves | None" = None
                   ) -> tuple[TopoDS_Shape | None, TopoDS_Shape | None]:
    """(carve, fill) swept along one SCULPT cut, each clipped to its own zone.

    Either may come back None when that side's span is degenerate — the raster
    skips those the same way.

    `source` must be the SAME curve set the terraces were built from. The
    clipping prisms are the zone polygons extruded, so building them from the
    flattened polygon while the terraces follow the authored curve leaves the
    clip a chord-width inside the real boundary. The resulting fill does not
    quite reach the terrace it is blending into, and fusing the two produces a
    pair of near-coincident faces that tessellates with a crack: the solid stays
    valid and the mesh stops being watertight. That was the *only* thing wrong
    with the curved build — the terraces themselves mesh closed.
    """
    names = zone_edge.zone_names
    if len(names) != 2 or not all(n in heights for n in names):
        raise BooleanError(f"edge {zone_edge.name!r} has no two known neighbours")
    hi_name, lo_name = ((names[0], names[1])
                        if heights[names[0]] > heights[names[1]]
                        else (names[1], names[0]))
    h_high, h_low = heights[hi_name], heights[lo_name]
    if h_high - h_low < 1e-9:
        raise BooleanError("no step across this edge")

    pts, perps = _stations(zone_edge.cut, stations)
    perps = _orient_high_side(partition, pts, perps, names, heights)

    if zone_prisms is None:
        zone_prisms = {}

    def prism_for(name: str) -> TopoDS_Shape:
        if name not in zone_prisms:
            poly = partition.zone(name).polygon
            zone_prisms[name] = extrude(
                polygon_to_face(poly, 0.0, curves=source), top)
        return zone_prisms[name]

    out: list[TopoDS_Shape | None] = []
    for side, zone_name in (("high", hi_name), ("low", lo_name)):
        try:
            body = _sweep(pts, [_blend_section(p, pn, h_high, h_low, fillet,
                                               side, top)
                                for p, pn in zip(pts, perps)])
            out.append(common(body, prism_for(zone_name)))
        except BooleanError:
            out.append(None)
    return out[0], out[1]


# ---------------------------------------------------------------- base + cache

#: Most recent `castle_base` results, newest last, as
#: `(key, source_partition, value)`. Two is deliberate: it covers A/B-ing one
#: parameter against the previous value, which is what a slider drag does,
#: without holding a pile of B-Rep solids alive.
#:
#: `source_partition` is in there only to be kept alive — the key identifies the
#: partition by `id()`, and a collected object's id can be handed to a different
#: one. Holding the reference makes that impossible.
_BASE_CACHE: list[tuple[tuple, CastlePartition, tuple]] = []
_BASE_CACHE_MAX = 2


def _base_key(partition: CastlePartition, castle: CastleParams,
              heights: dict[str, float] | None) -> tuple:
    """Everything `castle_base` reads, and nothing else.

    Zone thicknesses and overrides (terrace heights), the footing schedule
    (the blends), and the groove depth — which belongs here even though the
    groove itself is a feature, because with the groove on the terraces are
    built against the *shrunk* lip partition.

    The partition goes in by identity, and the cache holds a strong reference to
    it so a freed object's id cannot be reused underneath the key.
    """
    groove = getattr(castle, "lens_groove", None)
    return (
        id(partition),
        castle.zones.model_dump_json(),
        json.dumps(castle.zone_height_overrides, sort_keys=True),
        castle.footing.model_dump_json(),
        bool(groove is not None and groove.enabled),
        float(groove.depth_mm) if groove is not None else 0.0,
        json.dumps(heights, sort_keys=True) if heights else None,
    )


def clear_base_cache() -> None:
    """Drop the cached bases. Tests that time a cold build need this."""
    _BASE_CACHE.clear()


def castle_base(partition: CastlePartition, castle: CastleParams,
                heights: dict[str, float] | None = None,
                progress: Optional[ProgressFn] = None):
    """The castle before any finishing feature: terraces plus footing blends.

    Split out and cached because it is ~8 s of every rebuild on the demo frame
    and it depends on none of the feature parameters. Dragging a bezel width or
    a chamfer angle re-runs only what changed; the terraces and the ten footing
    blends come back from here untouched.

    Returns `(partition, heights, top, solid)` — the partition too, because with
    the lens groove enabled it is replaced by the shrunk lip partition and every
    feature downstream has to be built against that one, not the original.
    """
    key = _base_key(partition, castle, heights)
    source = partition
    for cached_key, _src, value in _BASE_CACHE:
        if cached_key == key:
            _report(progress, "Building terraces", 0.80)
            return value

    h = zone_heights(partition, castle, heights)
    top = max(h.values()) + SWEEP_MARGIN_MM

    _report(progress, "Building terraces", 0.10)
    # With the lens groove on, the visible aperture is the rim *lip* — cut
    # `depth_mm` smaller — and the terraces have to reach it, so the zones grow
    # into the annulus the shrink exposes. The raster gets this free from its
    # orphan-fill; a solid has to own the material.
    groove = getattr(castle, "lens_groove", None)
    if groove is not None and groove.enabled and groove.depth_mm > 0:
        from .features import lip_partition
        partition = lip_partition(partition, groove.depth_mm)
        h = zone_heights(partition, castle, heights)
    use_curves = CURVED_TERRACES
    source = SourceCurves(partition) if use_curves else None
    solid = build_terraces(partition, h, curved=use_curves, source=source)

    # This kernel's characteristic failure is an empty result that still reports
    # IsValid(), so a boolean that quietly ate the model looks like success all
    # the way to the Z-map. Terraces are the one stage whose volume is known to
    # be positive, which makes it the cheapest place to catch it.
    if volume(solid) <= 0.0:
        raise BooleanError(
            "terrace union collapsed to an empty solid — overlapping or "
            "coincident zone faces are the usual cause")

    carves, fills = [], []
    zone_prisms: dict[str, TopoDS_Shape] = {}
    named = [e for e in partition.edges if e.canonical]
    for i, edge in enumerate(named):
        try:
            fillet = castle.footing.for_edge(edge.canonical)
        except AttributeError:
            continue
        try:
            carve, fill = footing_bodies(partition, edge, h, fillet, top,
                                         zone_prisms, source=source)
        except BooleanError:
            # A degenerate or step-less seam contributes no blend. The raster
            # path treats these the same way — `_footing_centers` returns None
            # and the edge stays a hard step.
            continue
        if carve is not None:
            carves.append(carve)
        if fill is not None:
            fills.append(fill)
        _report(progress, "Blending footings",
                0.10 + 0.70 * (i + 1) / max(len(named), 1))

    # Composite rule, from the raster: fills first, then carves win. Each body
    # is already clipped to the zone it belongs to, so no further clipping here.
    #
    # One pass each, not fuse-the-tools-then-apply. The blends are independent
    # of one another — a union is associative and A - (B u C) == A - B - C — so
    # unlike the surface features (see `build_castle_solid`) there is no
    # ordering question here, and the multi-tool form is simply cheaper:
    # 9.8 s -> 5.9 s on the demo frame, identical volume.
    if fills:
        solid = fuse_all([solid, *fills])
    if carves:
        solid = cut_many(solid, carves)

    value = (partition, h, top, solid)
    _BASE_CACHE.append((key, source, value))
    del _BASE_CACHE[:-_BASE_CACHE_MAX]
    return value


# --------------------------------------------------------------------- build

def build_castle_solid(partition: CastlePartition, castle: CastleParams,
                       hinges: list | None = None,
                       heights: dict[str, float] | None = None,
                       progress: Optional[ProgressFn] = None,
                       return_surface: bool = False):
    """Terraces, footing blends, posterior features and hinge pockets.

    Order mirrors the raster exactly: terraces -> footings -> posterior finishing
    features -> hinge pockets. It has to, because the bezel anchors to the
    surface underneath it and the pockets cut below everything.

    `return_surface=True` also returns the solid **before** the pockets are cut.
    That is the M8 `surface_field`: the relief passes follow it so they sail over
    pockets the Hinge Pockets op has already cut, instead of diving to the floor
    a second time.

    Still to come as sweeps: pad splay, brow chamfer (`EdgeFeature`), bridge
    relief, lens groove.
    """
    partition, h, top, solid = castle_base(partition, castle, heights, progress)

    _report(progress, "Finishing features", 0.85)
    from .features import (apply_surface_features, hinge_pocket_cutters,
                           independent_cutters)
    # Two groups, and the split is the measured one — see `independent_cutters`.
    # The splay and the scoop read the surface each other leaves behind, so they
    # stay one-at-a-time; everything else sees the same target either way and so
    # goes through a single boolean pass. Cutting them separately cost 32.9 s on
    # the demo frame and cutting them together costs 7.5 s for the same solid.
    solid = apply_surface_features(solid, partition, castle)
    tools = independent_cutters(solid, partition, castle, top)
    pockets = hinge_pocket_cutters(hinges or [], castle, top)

    if return_surface:
        # The M8 surface_field is the solid *before* the pockets, so the two
        # groups have to be cut separately to have something to hand back.
        solid = cut_many(solid, tools)
        surface = solid
        _report(progress, "Hinge pockets", 0.92)
        solid = cut_many(solid, pockets)
    else:
        # Nobody wants the intermediate, so fold the pockets into the same pass.
        # `(X \ T) \ P == X \ (T u P)` holds however the kernel spells it, and
        # the pockets anchor on nothing, so this is the identical solid for one
        # boolean instead of two.
        _report(progress, "Hinge pockets", 0.92)
        solid = cut_many(solid, tools + pockets)
        surface = None

    _report(progress, "Solid ready", 1.0)
    # The terrace guard above catches an empty union at the one stage whose
    # volume is known positive; this catches the same class at the other end.
    # It is not hypothetical: spiking smooth (`ruled=False`) cutter lofts
    # produced a shape with zero faces and zero volume that `BRepCheck_Analyzer`
    # still called valid, and without this it would have reached the Z-map.
    if volume(solid) <= 0.0:
        raise BooleanError(
            "castle solid collapsed to zero volume — a boolean consumed the "
            "whole body (an empty result can still report IsValid)")
    if not is_valid(solid):
        raise BooleanError("castle solid failed BRepCheck_Analyzer")
    return (solid, surface) if return_surface else solid
