"""The castle as a mesh (BUILDPLAN-NEW M-N1).

The mesh-domain counterpart of `core/solid/build.py`, built to the same public
shape — *(partition, castle params, hinges) -> a closed solid* — so the two can
be run side by side and diffed while the port proceeds.

**Deliberately the same construction, not a better one.** Every stage here
mirrors what the B-Rep path does, including the composite rule and the order,
because the point of this milestone is parity: the two kernels must produce the
same part before either can be trusted to replace the other. Improvements that
the mesh domain makes possible (live slider rebuilds, no cached base) come after
parity, not instead of it.

Reuses `core.solid.build.zone_heights` and the geometry helpers in
`core.solid.features` outright. Those are kernel-neutral — they compute *where*
things go from the partition and the parameters — and duplicating them is how a
port grows a second set of subtly different answers.
"""
from __future__ import annotations

from typing import Callable, Optional

from manifold3d import Manifold

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from .kernel import (ManifoldError, extrude, subtract_all, to_trimesh,
                     union_all)

ProgressFn = Optional[Callable[[str, float], None]]

#: How far a cutter reaches beyond the material it removes. Same value and same
#: reason as the B-Rep path's `CUT_MARGIN_MM`: a tool must *cross* every surface
#: it exits, never stop on it. M-N0 is what a grazing cutter costs — one
#: tangency left a non-manifold edge that read as valid all the way to the user.
CUT_MARGIN_MM = 1.0


def _report(progress: ProgressFn, label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)


def build_terraces(partition: CastlePartition,
                   heights: dict[str, float]) -> Manifold:
    """Every zone extruded to its height and unioned — the stepped castle."""
    parts = [extrude(zone.polygon, heights[zone.name])
             for zone in partition.zones
             if not zone.polygon.is_empty and zone.polygon.area > 0]
    if not parts:
        raise ManifoldError("partition has no zones with area")
    return union_all(parts)


def hinge_pockets(hinges, castle: CastleParams, top: float) -> list[Manifold]:
    """The pocket prisms. Pure extrusions off the hinge polygons — no anchor
    ray, so these never care what has already been cut."""
    polys = [p for p in hinges or []
             if p is not None and not p.is_empty and p.area > 0]
    if not polys:
        return []
    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    height = max(top - floor, CUT_MARGIN_MM)
    return [extrude(p, height, base=floor) for p in polys]


def build_castle_model(partition: CastlePartition, castle: CastleParams,
                       hinges: list | None = None,
                       heights: dict[str, float] | None = None,
                       progress: ProgressFn = None) -> Manifold:
    """Terraces and hinge pockets.

    The features — footing blends, groove, bezel, edge features, splay, scoop —
    land here as the port proceeds. Until then this is the "bare" castle, which
    is exactly the stage the parity gate can already check against OCCT.
    """
    from ..geometry.rings import lip_partition
    from ..solid.build import SWEEP_MARGIN_MM, zone_heights
    from .features import (bezel_cutters, groove_cutters,
                           resolved_edge_cutters)

    # With the groove on, the visible aperture is the rim *lip* — cut
    # `depth_mm` smaller — and the terraces have to reach it, so the zones grow
    # into the annulus the shrink exposes. Same rule and the same function as
    # the B-Rep path; every feature downstream is built against this partition,
    # not the original.
    groove = getattr(castle, "lens_groove", None)
    if groove is not None and groove.enabled and groove.depth_mm > 0:
        partition = lip_partition(partition, groove.depth_mm)

    h = zone_heights(partition, castle, heights)
    top = max(h.values()) + SWEEP_MARGIN_MM

    _report(progress, "Building terraces", 0.20)
    solid = build_terraces(partition, h)

    _report(progress, "Lens groove", 0.55)
    tools = groove_cutters(partition, castle)

    # The bezel anchors on the surface under it, so it needs the part as it
    # stands — but only the *terraces* under it, which is what the B-Rep path
    # feeds it too: the groove and the pockets do not touch the rim band, so
    # every cutter here still sees the same target and one pass suffices.
    # Tessellated lazily: the anchor rays need a mesh, and with no
    # surface-reading feature enabled that conversion is the whole build. It
    # cost 9 ms -> 828 ms on the demo frame before this was made conditional.
    surface = None
    bezel = getattr(castle, "eyewire_bezel", None)
    wants_rays = ((bezel is not None and bezel.enabled)
                  or castle.resolved_edge_features())
    if wants_rays:
        surface = to_trimesh(solid)

        _report(progress, "Eyewire bezel", 0.70)
        tools.extend(bezel_cutters(surface, partition, castle, top))

        _report(progress, "Edge features", 0.78)
        tools.extend(resolved_edge_cutters(surface, partition, castle, top))

    _report(progress, "Hinge pockets", 0.85)
    tools.extend(hinge_pockets(hinges, castle, top))
    solid = subtract_all(solid, tools)

    _report(progress, "Model ready", 1.0)
    return solid
