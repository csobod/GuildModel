"""How tall each zone stands, and how far a cutter reaches past it.

Two names both solid kernels need and neither owns. They were in
`solid/build.py`, which imports OCP at module scope, so `model/build.py`
reaching in for them pulled **349 OCP modules into every mesh build** — enough
to make the Manifold path depend on the kernel it replaces for a constant and a
dictionary comprehension. Found 2026-08-08 while checking that a mesh-derived
Z-map could post without OCCT; it could not.

`solid.build` re-exports both, so every existing import still resolves.
"""
from __future__ import annotations

from ..project.schema import CastleParams
from .regions import CastlePartition

__all__ = ["SWEEP_MARGIN_MM", "zone_heights"]

#: How far a swept cutter reaches above the tallest terrace and, for fills,
#: below the anterior face. Only needs to guarantee overlap for the boolean.
SWEEP_MARGIN_MM = 1.0


def zone_heights(partition: CastlePartition, castle: CastleParams,
                 heights: dict[str, float] | None = None) -> dict[str, float]:
    """Zone name -> posterior height, same resolution order as the raster path."""
    if heights is not None:
        return dict(heights)
    if not partition.classified:
        raise ValueError(
            "the section cuts did not yield recognizable castle zones; "
            "pass explicit zone heights"
        )
    out = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}
    out.update({n: mm for n, mm in castle.zone_height_overrides.items()
                if n in out})
    return out
