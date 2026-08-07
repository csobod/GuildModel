"""The exact curve a drawing was made of, carried instead of thrown away.

**Why this exists.** GuildDraw draws frames as NURBS and exports them as DXF
`SPLINE` entities: the demo outline is 64 control points of a closed cubic, the
lens rings 13 and 7. The importer used to call `entity.flattening(chord_tol)` on
line 81 and hand the rest of the program a 342-point polyline, so every stage
downstream — regions, relief, the B-Rep solid, the CAM — has only ever seen
polygons. The solid's "3,850 real edges that are one-segment lines" is not a
limitation of the wire builder; it is faithfully building a polygon out of a
polygon.

**Why not re-fit.** `scripts/spike_spline_wires.py` tried exactly that — fitting
B-splines back onto the flattened points — and it is recorded in BUILDPLAN as
rejected: 5.2 um worst-case deviation and faces that misbehaved at every
tolerance. That deviation is the tell. It is a *fit error against the original
curve's own approximation*, and it should not exist at all. Reconstructing
information that was discarded two stages earlier cannot beat not discarding it.

A DXF `SPLINE` already carries precisely what a B-spline needs — control points,
knots, multiplicities, degree, periodic flag, optional rational weights — so
handing that straight to the kernel is exact by construction. No fit, no
tolerance, no error term.

**Kernel-neutral on purpose.** `core/io_import` must not import OCP: the
importer runs on every startup and OCP is ~70 MB of shared libraries. This
module is plain data. `core/solid/occ.py` is the only place that turns it into a
`Geom_BSplineCurve`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["NurbsCurve", "mirror_x"]


@dataclass(frozen=True)
class NurbsCurve:
    """A B-spline curve, exactly as its source defined it.

    `knots` is the *full* knot vector, one entry per knot repetition, which is
    the DXF convention. OCCT wants knots and multiplicities separately;
    `knots_and_multiplicities()` does that conversion so the arithmetic lives
    here next to the data rather than in the kernel bridge.
    """

    control_points: np.ndarray          # (n, 2) float — xy, the drawing is planar
    knots: np.ndarray                   # (n + degree + 1,) float, full vector
    degree: int
    closed: bool = False
    weights: np.ndarray | None = None   # (n,) float, or None for non-rational

    #: Where this came from, for diagnostics ("OUTLINE", "LENS", …).
    layer: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_points",
                           np.asarray(self.control_points, dtype=float))
        object.__setattr__(self, "knots", np.asarray(self.knots, dtype=float))
        if self.weights is not None:
            object.__setattr__(self, "weights",
                               np.asarray(self.weights, dtype=float))

    @property
    def rational(self) -> bool:
        return self.weights is not None and len(self.weights) > 0

    def knots_and_multiplicities(self) -> tuple[np.ndarray, np.ndarray]:
        """The distinct knot values and how many times each repeats.

        OCCT's `Geom_BSplineCurve` takes these as two arrays; DXF stores the
        expanded vector. Equality is exact rather than tolerant on purpose — a
        knot vector is authored data, not a measurement, and collapsing two
        knots that were genuinely distinct changes the curve's continuity.
        """
        values, counts = np.unique(self.knots, return_counts=True)
        return values, counts

    def is_consistent(self) -> bool:
        """True when the knot count matches the control points and degree.

        For a clamped/open curve `len(knots) == n + degree + 1`. Periodic curves
        from DXF often carry a different count, which is why this is a *report*
        rather than an assertion — an inconsistent curve is a reason to fall
        back to the polyline, not to fail the import.
        """
        n = len(self.control_points)
        if n <= self.degree or self.degree < 1:
            return False
        if self.rational and len(self.weights) != n:
            return False
        return len(self.knots) in (n + self.degree + 1,          # clamped
                                   n + 2 * self.degree + 1,      # periodic, DXF
                                   n + 1)                        # periodic, tight


def mirror_x(curve: NurbsCurve) -> NurbsCurve:
    """The curve with x negated.

    The importer's `posterior=True` flip (BUILDPLAN M1.2, the single flip point
    in the pipeline) has to apply to the curve as well as to the points, or the
    two representations describe different frames. Mirroring a B-spline is just
    mirroring its control points: knots, degree and weights are unaffected,
    because the basis functions do not move when the hull does.
    """
    cp = curve.control_points.copy()
    cp[:, 0] = -cp[:, 0]
    return NurbsCurve(control_points=cp, knots=curve.knots, degree=curve.degree,
                      closed=curve.closed, weights=curve.weights,
                      layer=curve.layer)
