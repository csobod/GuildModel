"""Hinge pocket floors, flat or tilted: one answer for every kernel and the CAM.

A hinge pocket's floor was a single height, `top - depth`, restated in six
places. The **pocket angle** tilts it. One edge of the pocket keeps the set
depth and the floor falls (or rises) away from it at the angle:

  * **Front.** The *superior* edge keeps the depth; the inferior edge moves.
    The tilt is about the lateral axis, so the temple leaves the endpiece at a
    different pantoscopic angle.
  * **Temple.** The *anterior* edge (the one nearer the temple's hinge end)
    keeps the depth; the posterior edge moves. The tilt is about the vertical
    axis, so it takes out splay a hinge has built into it.

A positive angle deepens the moving edge; a negative one makes it shallower.
Every pocket is tilted about its own fixed edge, so two pockets of different
heights keep the same set depth where the hinge leaf starts.

At 0° every floor is exactly the flat `top - depth` of before, and the callers
take their historical code path for it, so nothing already posted changes.

Nothing here imports a kernel, Qt or the CAM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

__all__ = ["FRONT_AXIS", "PocketFloor", "aligned", "castle_pocket_floors",
           "hinge_on_plus_x", "pocket_span", "temple_axis",
           "temple_pocket_floors"]

#: Below this the tilt is treated as none: the flat path runs unchanged.
FLAT_EPS_DEG = 1e-9


@dataclass(frozen=True)
class PocketFloor:
    """The floor plane of one pocket.

    `axis` is a unit vector in XY pointing from the fixed edge into the pocket;
    `edge` is that edge's coordinate along it (the smallest `p·axis` over the
    pocket). The floor is `z_fixed` on the edge and drops `slope` mm per mm
    away from it.
    """

    z_fixed: float
    axis: tuple[float, float] = (0.0, -1.0)
    edge: float = 0.0
    slope: float = 0.0

    @property
    def flat(self) -> bool:
        return self.slope == 0.0

    def z(self, x, y):
        """Floor height at (x, y); broadcasts over numpy arrays."""
        if self.flat:
            return np.full_like(np.asarray(x, dtype=np.float64), self.z_fixed) \
                if np.ndim(x) else self.z_fixed
        d = np.asarray(x) * self.axis[0] + np.asarray(y) * self.axis[1] - self.edge
        out = self.z_fixed - self.slope * d
        return float(out) if np.ndim(out) == 0 else out

    def extremes(self, poly: Polygon) -> tuple[float, float]:
        """(lowest, highest) floor height over `poly`: a plane over a polygon
        peaks at a vertex, so the exterior ring is enough."""
        if self.flat:
            return self.z_fixed, self.z_fixed
        xs, ys = np.asarray(poly.exterior.coords).T
        zs = self.z(xs, ys)
        return float(np.min(zs)), float(np.max(zs))

    def plane(self) -> tuple[tuple[float, float, float], float]:
        """`(unit normal, offset)` of the floor plane, normal pointing up.

        The half-space `n·p >= offset` is everything on or above the floor, which
        is the form `Manifold.trim_by_plane` and a B-Rep half-space both take.
        """
        ax, ay = self.axis
        n = np.array([self.slope * ax, self.slope * ay, 1.0])
        length = float(np.linalg.norm(n))
        offset = (self.z_fixed + self.slope * self.edge) / length
        return (float(n[0] / length), float(n[1] / length),
                float(n[2] / length)), offset


def _floor_for(poly: Polygon, z_fixed: float, axis: tuple[float, float],
               angle_deg: float) -> PocketFloor:
    if abs(angle_deg) <= FLAT_EPS_DEG:
        return PocketFloor(z_fixed=z_fixed)
    xs, ys = np.asarray(poly.exterior.coords).T
    edge = float(np.min(xs * axis[0] + ys * axis[1]))
    return PocketFloor(z_fixed=z_fixed, axis=axis, edge=edge,
                       slope=math.tan(math.radians(angle_deg)))


def _usable(hinges) -> list[Polygon]:
    return [p for p in hinges or []
            if p is not None and not p.is_empty and p.area > 0.0]


#: Posterior coordinates put superior on +y (`geometry.regions`), so the floor
#: runs from the superior edge toward -y.
FRONT_AXIS = (0.0, -1.0)


def castle_pocket_floors(hinges, castle) -> list[tuple[Polygon, PocketFloor]]:
    """Each usable front hinge pocket with its floor."""
    z_fixed = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    angle = float(getattr(castle, "hinge_pocket_angle_deg", 0.0))
    return [(p, _floor_for(p, z_fixed, FRONT_AXIS, angle)) for p in _usable(hinges)]


def hinge_on_plus_x(outline: Polygon | None, hinges) -> bool:
    """True when a temple's hinge end is its +x extreme (its long axis is x).

    The same rule `relief.flat` snaps the temple with, so it holds before and
    after the snap's 180° turn."""
    polys = _usable(hinges)
    if outline is None or outline.is_empty:
        return True
    minx, _, maxx, _ = outline.bounds
    hx = unary_union(polys).centroid.x if polys else maxx
    return abs(hx - maxx) <= abs(hx - minx)


def temple_axis(outline: Polygon | None, hinges) -> tuple[float, float]:
    """From the anterior (hinge-end) edge of a temple pocket toward posterior."""
    return (-1.0, 0.0) if hinge_on_plus_x(outline, hinges) else (1.0, 0.0)


def temple_pocket_floors(hinges, temple, outline: Polygon | None = None,
                         ) -> list[tuple[Polygon, PocketFloor]]:
    """Each usable temple hinge pocket with its floor. `outline` locates the
    hinge end; without it the hinge is taken to be at +x, as `relief.flat`
    does when it has nothing better."""
    z_fixed = temple.blank_thickness_mm - temple.hinge_pocket_depth_mm
    angle = float(getattr(temple, "hinge_pocket_angle_deg", 0.0))
    axis = temple_axis(outline, hinges)
    return [(p, _floor_for(p, z_fixed, axis, angle)) for p in _usable(hinges)]


def aligned(pairs, hinges) -> list[PocketFloor | None]:
    """The floors of `pairs` in the order of `hinges`, None where a hinge polygon
    was not usable, for callers that walk the original list."""
    by_id = {id(p): f for p, f in pairs}
    return [by_id.get(id(p)) for p in hinges or []]


def pocket_span(hinges, axis: tuple[float, float]) -> float:
    """The longest run any pocket has along `axis`: the lever the angle acts on."""
    span = 0.0
    for p in _usable(hinges):
        xs, ys = np.asarray(p.exterior.coords).T
        d = xs * axis[0] + ys * axis[1]
        span = max(span, float(d.max() - d.min()))
    return span
