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
from .kernel import ManifoldError, extrude, subtract_all, union_all

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
    from ..solid.build import SWEEP_MARGIN_MM, zone_heights

    h = zone_heights(partition, castle, heights)
    top = max(h.values()) + SWEEP_MARGIN_MM

    _report(progress, "Building terraces", 0.20)
    solid = build_terraces(partition, h)

    _report(progress, "Hinge pockets", 0.80)
    solid = subtract_all(solid, hinge_pockets(hinges, castle, top))

    _report(progress, "Model ready", 1.0)
    return solid
