"""Mesh -> Heightfield, for the CAM (BUILDPLAN-NEW M-N3).

The counterpart of `solid/zmap.py`, and the piece that was missing for the
`model_kernel` preference to mean anything outside the 3D viewer. Every G-code
path called `relief.castle.build_castle_relief` regardless of it, because a
Manifold model had no way to become the `Heightfield` the CAM consumes. Stage 2
had built that bridge for OCCT and never wired it in; `core.zmap` is now the
kernel-neutral half of it.

**No tessellation step, and no chordal tolerance to choose.** That is the whole
difference from the B-Rep side. OCCT has to mesh its trimmed surfaces before
anything can sample them, and `CAM_DEFLECTION_MM` exists to say how finely —
5 um, twenty times tighter than the viewer, because this becomes G-code. A
Manifold model *is* triangles: what the CAM samples is the model, not an
approximation of it chosen by a tolerance. There is one less thing to get wrong
and one less knob whose default nobody revisits.

**This does not yet make the mesh path OCCT-free, and M-N4 should not assume it
does.** Measured per feature in a fresh interpreter: a bare frame, the eyewire
bezel, the pad splay and the bridge relief each load **zero** OCP modules; the
**lens groove** loads 349. That one is not an accident to tidy away like
`geometry.heights` was — `geometry.rings.offset_aperture` uses
`Geom_OffsetCurve` to build the rim lip as an exact parallel of the authored
curve rather than buffering the flattened ring, which is the exact-curve work
§8.5 calls the part that survives. Dropping OCCT there means either accepting
the Shapely buffer it already falls back to, or offsetting `OffsetCurve`
ourselves. A decision, not a cleanup.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from ..relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from ..zmap import grid_for, groove_body, relief_from_zmap, triangles_to_zmap

ProgressFn = Callable[[str, float], None]

__all__ = ["mesh_to_relief", "mesh_to_zmap"]


def mesh_to_zmap(mesh, origin: tuple[float, float], rows: int, cols: int,
                 resolution: float, background: float = 0.0,
                 progress: Optional[ProgressFn] = None) -> np.ndarray:
    """Upper envelope of a `trimesh.Trimesh` on the grid.

    `mesh` is what `model.to_trimesh` returns — already welded through
    Manifold's merge map and at float64. Cells no triangle covers keep
    `background`.
    """
    return triangles_to_zmap(mesh.vertices, mesh.faces, origin, rows, cols,
                             resolution, background, progress)


def mesh_to_relief(model, partition: CastlePartition, castle: CastleParams,
                   resolution: float = CUT_RES_MM,
                   margin: float = GRID_MARGIN_MM,
                   progress: Optional[ProgressFn] = None) -> CastleRelief:
    """A `CastleRelief` whose surface came from the mesh kernel.

    `model` is a `Manifold` or anything `to_trimesh` accepts. Everything
    downstream — ops generation, posting, simulation — reads the result exactly
    as it reads the raster builder's output.
    """
    from .kernel import to_trimesh

    mesh = model if hasattr(model, "faces") else to_trimesh(model)
    body, groove = groove_body(partition, castle)
    origin, rows, cols = grid_for(body, resolution, margin)
    z = mesh_to_zmap(mesh, origin, rows, cols, resolution, progress=progress)
    return relief_from_zmap(z, partition, castle, origin, rows, cols,
                            resolution, body, groove)
