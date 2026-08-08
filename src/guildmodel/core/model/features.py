"""Castle features as mesh bodies (BUILDPLAN-NEW M-N1).

The mesh-domain counterpart of `core/solid/features.py`. Same features, same
placement — the *where* comes from `core/geometry/rings.py`, shared by both
kernels — built as swept hull chains instead of lofted B-Rep sections.

**Why every sweep here is a chain of convex hulls.** The B-Rep path builds these
with `BRepOffsetAPI_ThruSections` and, where it tried them, `MakePipeShell`.
Both are where the season's worst failures came from: a bezel sweep that
produced a valid 4-face cutter whose *cut* took 260 s and returned negative
volume, a spine that took 401 s to fail, and the M-N0 tangency that left a
non-manifold edge. Hulling each consecutive pair of profiles cannot
self-intersect however tight the corner, and the union of the cells is a
manifold by construction. The spike measured the groove this way at 39 ms with
the undercut present at 40 of 40 stations.
"""
from __future__ import annotations

import numpy as np
from manifold3d import Manifold
from shapely.geometry import LineString, Polygon

from ..geometry.rings import inward_normals, ring_stations
from ..project.schema import CastleParams
from .kernel import hull_chain

__all__ = ["groove_cutters", "v_groove_cutter"]

#: Stations around an aperture for the groove V. Matches the B-Rep path's
#: `GROOVE_STATIONS` so the two kernels inscribe the same polygon in the same
#: ring and their volumes are comparable at the chord level.
GROOVE_STATIONS = 180

#: How far the V's mouth reaches back out of the wall, mm. The cutter has to
#: *cross* the rim face rather than stop on it — the M-N0 lesson, and cheap
#: insurance here since the overshoot is in open air.
GROOVE_LEAD_MM = 0.3


def v_groove_cutter(body: Polygon, ring, groove,
                    stations: int = GROOVE_STATIONS) -> Manifold:
    """The drageoir V for one aperture, as a swept triangular tube.

    `body` must already be the **lip** body and `ring` one of its lip rings —
    the aperture after the groove depth has been taken off it. The V is then cut
    back outward so its apex lands exactly on the original LENS contour, which
    is what keeps the boxed dimension honest. Shrinking again here would put the
    V a further `depth_mm` inboard, into open aperture, where it removes
    nothing.

    The section is a triangle: apex `depth` into the wall at `anterior_offset`,
    opening to `width` at the rim face and overshooting it by `GROOVE_LEAD_MM`
    so the mouth breaks cleanly through.
    """
    depth = float(groove.depth_mm)
    half_w = float(groove.width_mm) / 2.0
    apex_z = float(groove.anterior_offset_mm)
    if depth <= 0.0 or half_w <= 0.0:
        raise ValueError("degenerate lens groove")

    pts, tans = ring_stations(LineString(ring), stations)
    # `inward_normals` means "into the material", and for an aperture ring that
    # is already into the wall — which is where the groove cuts. Negating it
    # here (the obvious reading of the name) buries the mouth in the wall and
    # puts the apex out in the hole: still a V, still removes material, no
    # undercut at all. Caught only by the ray test; the volume gate passed it.
    into_wall = inward_normals(body, pts, tans)

    # The mouth is opened in proportion, so the V's flanks stay straight lines
    # through the rim face instead of kinking at it.
    lead_half_w = half_w * (1.0 + GROOVE_LEAD_MM / depth)

    def profile(i):
        p, o = pts[i % stations], into_wall[i % stations]
        mouth, apex = p - o * GROOVE_LEAD_MM, p + o * depth
        return np.array([
            [mouth[0], mouth[1], apex_z + lead_half_w],
            [apex[0], apex[1], apex_z],
            [mouth[0], mouth[1], apex_z - lead_half_w],
        ])

    return hull_chain([profile(i) for i in range(stations)], closed=True)


def groove_cutters(partition, castle: CastleParams) -> list[Manifold]:
    """One V per lens aperture. Decorative OUTLINE holes are through-cuts and
    take no groove, so they keep their size.

    Takes no solid and fires no anchor ray — the V is positioned entirely from
    the partition, so unlike the surface features it never cares what has
    already been cut.
    """
    groove = getattr(castle, "lens_groove", None)
    if groove is None or not groove.enabled or groove.depth_mm <= 0:
        return []
    lip = partition.body
    return [v_groove_cutter(lip, ring, groove)
            for ring in lip.interiors if not partition.is_hole(ring)]
