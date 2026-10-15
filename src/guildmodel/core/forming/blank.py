"""The pre-formed blank (BUILDPLAN M25 §10.2): the blank slab pressed to the
project's forming before it is cut, as a mesh the stock engine reads and
the CAM roughs from.

The same map that made the pre-cut dies makes the blank: the slab the Stock
tab lists, extruded and warped through `ThermoformMap`. Its two envelopes on
the relief's grid are the stock top the roughing starts from and the stock
bottom the through-cuts stop at, and the mesh itself is the simulation's
starting stock. A hybrid blank (apertures cut flat before pressing) has its
lens apertures taken out before the warp.

Qt-free and kernel-free in the CAM's sense: `core.zmap` calls this; the CAM
reads the heightfields it leaves on the relief and never imports this module.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import box

from ..model.kernel import extrude, subtract_all, to_trimesh
from .thermoform import EXPORT_REFINE_MM, ThermoformMap, formed_model

__all__ = ["formed_blank_mesh", "formed_blank_envelopes", "BLANK_REFINE_MM"]

#: Edge length the slab is refined to before the warp, mm: the chord sag on
#: a 144 mm sphere at this length is 3.5 microns.
BLANK_REFINE_MM = 2.0


def formed_blank_mesh(stock, fmap: ThermoformMap, *, apertures=(),
                      refine_mm: float = BLANK_REFINE_MM):
    """The blank slab (``blank_length x blank_width x blank_thickness``,
    centered on the design origin, anterior face at z = 0) pressed to
    `fmap`, as a trimesh. `apertures` are polygons cut through before the
    warp (the hybrid's lens openings). The pad block is not here: a pressed
    sheet carries none."""
    L, W, T = (float(stock.blank_length_mm), float(stock.blank_width_mm),
               float(stock.blank_thickness_mm))
    slab = extrude(box(-L / 2.0, -W / 2.0, L / 2.0, W / 2.0), T)
    tools = [extrude(p, T + 2.0, base=-1.0) for p in (apertures or ()) if p is not None and not p.is_empty]
    if tools:
        slab = subtract_all(slab, tools)
    if fmap.is_flat:
        return to_trimesh(slab)
    return to_trimesh(formed_model(slab, fmap, max(float(refine_mm), 0.25)))


def formed_blank_envelopes(stock, fmap: ThermoformMap, origin, rows: int, cols: int,
                           resolution: float, *, apertures=(), background: float = np.nan):
    """``(top, bottom)`` of the pressed blank on a grid, as two ``(rows,
    cols)`` arrays; cells the blank does not cover keep `background`."""
    from ..zmap import triangle_envelopes
    mesh = formed_blank_mesh(stock, fmap, apertures=apertures)
    return triangle_envelopes(np.asarray(mesh.vertices), np.asarray(mesh.faces), origin,
                              rows, cols, resolution, background=background)
