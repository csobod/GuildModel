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

**The mesh path is OCCT-free as of M-N4** *(2026-08-09)*. Measured per feature
in a fresh interpreter — a bare frame, the eyewire bezel, the pad splay, the
bridge relief and now the **lens groove** each load **zero** OCP modules.

The groove used to load 349, through `geometry.rings.offset_aperture`, which
samples the rim lip as an exact parallel of the authored curve and had no
sampler but OCCT's. Both ways out were tried and only one survived:

* **Take the Shapely buffer it already falls back to.** It measures 8 - 10 um
  away, which against a model flattened at 10 um and cut on a 150 um grid
  looked free. It is not: `solid.features._swept_groove_cutter` rides that
  exact curve, and without it the B-Rep's grooved build stops being watertight
  on all three drawings. Reverted — it would have removed the third opinion for
  the one feature whose surface is hardest to check.
* **Evaluate the curve ourselves.** `curves.sample_curve` — de Boor with a
  hodograph tangent, and adaptive bisection to a chord tolerance. The exact lip
  survives, the sweep survives, and the dependency goes.

`test_curve_eval_mn4` holds the evaluator to `Geom_BSplineCurve` and
`Geom_OffsetCurve` at 1e-9, which is not ceremony: the first version had the
offset sign backwards and sat `2 * distance` from OCCT's answer on every curve.
A circle cannot catch that — its offset is a circle either way.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from ..relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from ..zmap import (cam_relief, grid_for, groove_body, relief_from_zmap,
                    triangles_to_zmap)

ProgressFn = Callable[[str, float], None]

__all__ = ["mesh_cam_relief", "mesh_to_relief", "mesh_to_zmap"]


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


def _triangles(partition: CastlePartition, castle: CastleParams, hinges):
    from .build import build_castle_model
    from .kernel import to_trimesh

    mesh = to_trimesh(build_castle_model(partition, castle, list(hinges)))
    return mesh.vertices, mesh.faces


def mesh_cam_relief(partition: CastlePartition, castle: CastleParams,
                    hinges=(), resolution: float = CUT_RES_MM,
                    margin: float = GRID_MARGIN_MM,
                    progress: Optional[ProgressFn] = None) -> CastleRelief:
    """The complete relief the CAM posts from, built by Manifold.

    Takes the *parameters* rather than a model, because filling
    `surface_field` and `feature_band` means building the part more than once —
    see `core.zmap.cam_relief`, which owns that and knows nothing about which
    kernel is answering.
    """
    return cam_relief(_triangles, partition, castle, hinges, resolution,
                      margin, progress)
