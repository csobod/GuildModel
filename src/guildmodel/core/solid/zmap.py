"""Solid -> Heightfield, for the CAM (BUILDPLAN Stage 2).

Two lines of OCCT on top of `core.zmap`, which is where the rasterizer and the
relief assembly actually live. They were written here, and only the tessellation
was ever kernel-specific; keeping the rest here meant the Manifold path could
not reach the CAM without importing the kernel it replaces. See `core.zmap`.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from ..relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from ..zmap import (cam_relief, grid_for, groove_body, relief_from_zmap,
                    triangles_to_zmap)
from .tessellate import tessellate

ProgressFn = Callable[[str, float], None]

#: Chordal tolerance for the mesh the Z-map is sampled from. Tighter than the
#: viewer's, because this one becomes G-code: 5 um is a twentieth of the M2
#: gate's 0.1 mm tolerance and well under the 0.15 mm grid it lands on.
CAM_DEFLECTION_MM = 0.005

__all__ = ["CAM_DEFLECTION_MM", "grid_for", "solid_cam_relief",
           "solid_to_relief", "solid_to_zmap"]


def solid_to_zmap(solid, origin: tuple[float, float], rows: int, cols: int,
                  resolution: float, deflection: float = CAM_DEFLECTION_MM,
                  background: float = 0.0,
                  progress: Optional[ProgressFn] = None) -> np.ndarray:
    """Upper envelope of `solid` sampled onto the grid, as a (rows, cols) array.

    Cells no triangle covers keep `background`.
    """
    if progress is not None:
        progress("Tessellating for CAM", 0.10)
    tess = tessellate(solid, deflection=deflection, with_edges=False)
    return triangles_to_zmap(tess.vertices, tess.faces, origin, rows, cols,
                             resolution, background, progress)


def solid_to_relief(solid, partition: CastlePartition, castle: CastleParams,
                    resolution: float = CUT_RES_MM,
                    margin: float = GRID_MARGIN_MM,
                    deflection: float = CAM_DEFLECTION_MM,
                    progress: Optional[ProgressFn] = None) -> CastleRelief:
    """A `CastleRelief` whose surface came from the solid."""
    body, groove = groove_body(partition, castle)
    origin, rows, cols = grid_for(body, resolution, margin)
    z = solid_to_zmap(solid, origin, rows, cols, resolution, deflection,
                      progress=progress)
    return relief_from_zmap(z, partition, castle, origin, rows, cols,
                            resolution, body, groove)


def solid_cam_relief(partition: CastlePartition, castle: CastleParams,
                     hinges=(), resolution: float = CUT_RES_MM,
                     margin: float = GRID_MARGIN_MM,
                     deflection: float = CAM_DEFLECTION_MM,
                     progress: Optional[ProgressFn] = None) -> CastleRelief:
    """The complete relief the CAM posts from, built by OpenCASCADE.

    The mesh counterpart of this rebuilds the part up to three times and costs
    about 2.2 s. Three OCCT builds is 40-115 s, so this exists to be the third
    opinion the mesh path is measured against, not to be posted from.
    """
    from .build import build_castle_solid, clear_base_cache

    def triangles(part, cst, hinge_polys):
        clear_base_cache()
        tess = tessellate(build_castle_solid(part, cst, list(hinge_polys)),
                          deflection=deflection, with_edges=False)
        return tess.vertices, tess.faces

    return cam_relief(triangles, partition, castle, hinges, resolution,
                      margin, progress)
