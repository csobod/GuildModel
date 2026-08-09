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

The same holds for the `.gdraw` path, which is the *primary* intake and had the
same hole. GuildDraw stores a spline there as cubic Bezier nodes rather than as
poles and knots, but a chain of cubic Beziers is a cubic B-spline — see
`cubic_bezier_chain`, which re-spells one as the other with no tolerance either.

**Kernel-neutral on purpose.** `core/io_import` must not import OCP: the
importer runs on every startup and OCP is ~70 MB of shared libraries. This
module is plain data. `core/solid/occ.py` is the only place that turns it into a
`Geom_BSplineCurve`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["NurbsCurve", "OffsetCurve", "circle_curve", "cubic_bezier_chain",
           "mirror_x", "mirror_y", "sample_curve"]


def _de_boor(poles: np.ndarray, knots: np.ndarray, degree: int,
             span: int, u: float) -> np.ndarray:
    """One point of a B-spline, by the de Boor recursion.

    `poles` are homogeneous `(x*w, y*w, w)` so the same routine serves rational
    and non-rational curves; the caller divides through. Degree 0 is the
    recursion's own base case and falls out without a special path.
    """
    d = np.array(poles[span - degree:span + 1], dtype=float)
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            lo = knots[j + span - degree]
            hi = knots[j + 1 + span - r]
            a = 0.0 if hi <= lo else (u - lo) / (hi - lo)
            d[j] = (1.0 - a) * d[j - 1] + a * d[j]
    return d[degree]


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

    # -------------------------------------------------------- evaluation
    #
    # De Boor, on the clamped interpretation — which is what the data is.
    # `occ.nurbs_edge` builds every one of these with `Periodic=False` because
    # closed DXF splines arrive clamped with coincident first and last poles,
    # measured, and OCCT rejects them outright as periodic. Reading them any
    # other way here would put this evaluator and the kernel on different
    # curves, so `test_curve_eval_mn4` holds the two to 1e-9 rather than
    # trusting the agreement.

    @property
    def domain(self) -> tuple[float, float]:
        """The parameter interval the curve is defined on, `[U[p], U[n]]`."""
        n = len(self.control_points)
        return float(self.knots[self.degree]), float(self.knots[n])

    def _span(self, u: float) -> int:
        """Index `k` with `U[k] <= u < U[k+1]`, clamped into the live range."""
        n, p = len(self.control_points), self.degree
        lo, hi = self.domain
        if u >= hi:
            return n - 1
        if u <= lo:
            return p
        k = int(np.searchsorted(self.knots, u, side="right")) - 1
        return min(max(k, p), n - 1)

    def _poles4(self) -> np.ndarray:
        """Poles as `(x*w, y*w, w)`, so one routine covers rational and not."""
        pts = self.control_points
        w = (self.weights if self.rational
             else np.ones(len(pts), dtype=float))
        return np.column_stack([pts[:, 0] * w, pts[:, 1] * w, w])

    def point(self, u: float) -> np.ndarray:
        """The curve at `u`, as `(x, y)`."""
        h = _de_boor(self._poles4(), self.knots, self.degree, self._span(u), u)
        return h[:2] / h[2]

    def tangent(self, u: float) -> np.ndarray:
        """The unit tangent at `u`.

        Taken from the hodograph — the derivative of a B-spline of degree `p` is
        a B-spline of degree `p-1` over the same knots with the interior removed
        — rather than by differencing two nearby points, which loses half the
        digits and is what a chord-tolerance sampler is most sensitive to. The
        rational case then needs the quotient rule, because the homogeneous
        derivative is not the derivative of the projection.
        """
        p, knots = self.degree, self.knots
        poles = self._poles4()
        n = len(poles)
        span = self._span(u)

        # Hodograph poles, in homogeneous coordinates.
        gaps = knots[p + 1:n + p] - knots[1:n]
        dpoles = np.zeros((n - 1, 3))
        live = gaps > 0.0
        dpoles[live] = (p * (poles[1:][live] - poles[:-1][live])
                        / gaps[live, None])

        h = _de_boor(poles, knots, p, span, u)
        dh = _de_boor(dpoles, knots[1:-1], p - 1,
                      min(max(span - 1, p - 1), n - 2), u)
        # C = A/w  ->  C' = (A' - w' C) / w
        d = (dh[:2] - dh[2] * (h[:2] / h[2])) / h[2]
        norm = float(np.linalg.norm(d))
        return d / norm if norm > 0 else np.array([1.0, 0.0])


@dataclass(frozen=True)
class OffsetCurve:
    """A curve running parallel to `basis` at a fixed distance, in the XY plane.

    **Why this is a type and not a fitted `NurbsCurve`.** The exact offset of a
    B-spline is not a B-spline — only lines and circles offset to their own kind
    — so writing one down as poles and knots means approximating, and the whole
    point of `NurbsCurve` is that nothing here approximates. Saying instead
    *"the lens curve, 0.6 mm in"* is exact, and the kernel has a matching
    representation (`Geom_OffsetCurve`) that evaluates it without ever fitting.

    This exists for the rim lip. With the lens groove on, the visible aperture
    is the lens contour shrunk by the groove depth; `features.lip_partition`
    used to get that from a Shapely buffer of the *flattened* ring, which is an
    approximation of an approximation and left the aperture polygonal even when
    the drawing was curved.

    `distance` is signed in OCCT's convention — the offset direction is
    `Z x tangent`, so the sign that points inward depends on which way the curve
    winds, and the two lens rings of the demo frame wind opposite ways.
    `lip_partition` therefore picks the sign by measuring, not by assuming.
    """

    basis: NurbsCurve
    distance: float
    layer: str = ""

    @property
    def control_points(self) -> np.ndarray:
        """The basis hull.

        Read only for the curve's *winding* (`occ.ring_wire`), which a parallel
        offset preserves — so the basis answers correctly and there is nothing
        to compute. It is emphatically not a control polygon of this curve.
        """
        return self.basis.control_points

    @property
    def closed(self) -> bool:
        return self.basis.closed

    @property
    def domain(self) -> tuple[float, float]:
        return self.basis.domain

    def point(self, u: float) -> np.ndarray:
        """The offset curve at `u`.

        `C(u) + d * (T x Z)`, which in the plane is the tangent turned a quarter
        turn *clockwise*: `(tx, ty) -> (ty, -tx)`.

        **That is the opposite of the documented reading, and it is measured.**
        `Geom_OffsetCurve`'s reference direction argument reads like `V x T`,
        which would be `(-ty, tx)`. It is not: written that way this sat
        `2 * distance` from OCCT's own answer on every curve — 1.21 mm on a
        0.6 mm offset. The class docstring above and
        `solid.features._swept_groove_cutter` both record having been caught by
        the same thing from the other side.

        The sign has to be OCCT's exactly, because the same curve still reaches
        the kernel through `occ.nurbs_edge` as a real `Geom_OffsetCurve`; if the
        two disagreed, the sampled rim lip and the B-Rep's own aperture wire
        would sit `2 * distance` apart with nothing to say so. `test_curve_eval_mn4`
        pins it against OCCT rather than against a circle, whose offset is a
        circle either way and so hides a flip completely.
        """
        t = self.basis.tangent(u)
        return self.basis.point(u) + self.distance * np.array([t[1], -t[0]])

    def tangent(self, u: float) -> np.ndarray:
        """The unit tangent, which a parallel offset shares with its basis.

        True wherever the offset is regular. It fails at a cusp — where the
        basis curvature radius drops below `|distance|` the offset reverses —
        and that is exactly the case `rings.offset_aperture` refuses by
        comparing against the Shapely buffer, so nothing here has to detect it.
        """
        return self.basis.tangent(u)


#: Largest parameter step `sample_curve` will accept without checking the chord
#: between its ends. A curve can return to the same place with the same tangent
#: — a closed ring does exactly that at its seam — so bisection that only asks
#: "is the midpoint far from the chord?" can stop before it has started. Ten
#: spans is enough to break that symmetry on any contour a frame is drawn with.
_MAX_SAMPLE_STEP = 0.1


def sample_curve(curve, chord_tol: float, max_depth: int = 20) -> np.ndarray:
    """The curve as a polyline no further than `chord_tol` from it, in mm.

    Adaptive bisection: keep a chord only when the true midpoint lies within
    `chord_tol` of it, otherwise split. That spends points where the curve
    bends and none where it does not, which is the whole reason not to sample
    uniformly — the demo's apertures come back around 1300 points, and uniform
    sampling fine enough for the tightest corner would be several times that.

    Replaces `GCPnts_QuasiUniformDeflection`, the last thing pulling
    OpenCASCADE into a mesh-kernel G-code build.
    """
    lo, hi = curve.domain
    if not (hi > lo):
        return np.empty((0, 2))

    def refine(a, b, pa, pb, depth):
        m = 0.5 * (a + b)
        pm = curve.point(m)
        if depth < max_depth and (b - a) > _MAX_SAMPLE_STEP * (hi - lo):
            pass                                  # too coarse to judge yet
        else:
            chord = pb - pa
            length = float(np.linalg.norm(chord))
            if length <= 1e-12:
                err = float(np.linalg.norm(pm - pa))
            else:
                # Perpendicular distance of the true midpoint from the chord.
                # Spelled out rather than `np.cross`, which stopped accepting
                # 2-D vectors in numpy 2.0.
                ux, uy = chord / length
                vx, vy = pm - pa
                err = abs(ux * vy - uy * vx)
            if depth >= max_depth or err <= chord_tol:
                return [pb]
        return refine(a, m, pa, pm, depth + 1) + refine(m, b, pm, pb, depth + 1)

    p0 = curve.point(lo)
    out = [p0]
    out += refine(lo, hi, p0, curve.point(hi), 0)
    return np.asarray(out, dtype=float)


def mirror_x(curve):
    """The curve with x negated.

    The importer's `posterior=True` flip (BUILDPLAN M1.2, the single flip point
    in the pipeline) has to apply to the curve as well as to the points, or the
    two representations describe different frames. Mirroring a B-spline is just
    mirroring its control points: knots, degree and weights are unaffected,
    because the basis functions do not move when the hull does.
    """
    return _mirrored(curve, 0)


def mirror_y(curve):
    """The curve with y negated.

    The `.gdraw` reader's scene → posterior transform is (x, y) → (-x, -y) —
    GuildDraw scene space is Y-down — so that path needs both mirrors where the
    DXF path (already Y-up) needs only :func:`mirror_x`.
    """
    return _mirrored(curve, 1)


def _mirrored(curve, axis: int):
    if isinstance(curve, OffsetCurve):
        # A reflection reverses handedness, so the `Z x tangent` direction flips
        # and the signed distance has to flip with it — otherwise the mirrored
        # aperture would be offset outward. No importer produces an offset
        # today; this keeps the operation total rather than silently wrong if
        # one ever does.
        return OffsetCurve(basis=_mirrored(curve.basis, axis),
                           distance=-curve.distance, layer=curve.layer)
    cp = curve.control_points.copy()
    cp[:, axis] = -cp[:, axis]
    return NurbsCurve(control_points=cp, knots=curve.knots, degree=curve.degree,
                      closed=curve.closed, weights=curve.weights,
                      layer=curve.layer)


#: Below this, a Bézier segment's four control points are one point and the
#: segment contributes no geometry. A picometre: far under any real drawing
#: coordinate, so this only ever catches true duplicates.
_DEGENERATE_MM = 1e-9


def cubic_bezier_chain(segments, closed: bool = False,
                       layer: str = "") -> NurbsCurve | None:
    """One cubic B-spline through a chain of cubic Bézier segments.

    **Not an approximation.** A chain of cubic Béziers *is* a cubic B-spline —
    the same curve written a different way. Interleave the segments' control
    points and give each interior joint a knot of multiplicity 3, and the basis
    functions reproduce each segment's Bernstein polynomials exactly. So this
    conversion has no tolerance and no error term, the same way
    :func:`io_import.dxf._spline_curve` has none.

    That is what makes it worth doing. GuildDraw's ``.gdraw`` — the primary
    intake — stores its splines as Bézier nodes, and the reader flattened them
    to polylines exactly as the DXF importer used to, so a ``.gdraw`` reached the
    B-Rep kernel as a polygon no matter how smoothly it was drawn.

    ``segments`` is a sequence of ``(p0, p1, p2, p3)`` xy tuples, consecutive
    segments sharing an endpoint. For ``closed=True`` the caller supplies the
    wrap-around segment, so the last pole coincides with the first; the curve is
    *clamped*, not periodic, which is what `occ.nurbs_edge` builds and what
    closed DXF splines are too.

    Returns None when nothing survives — the caller then falls back to the
    flattened polyline, which is always produced anyway.
    """
    segs = [s for s in segments if len(s) == 4 and _extent(s) > _DEGENERATE_MM]
    if not segs:
        return None

    poles: list[tuple[float, float]] = [tuple(segs[0][0])]
    for _p0, p1, p2, p3 in segs:
        poles.extend((tuple(p1), tuple(p2), tuple(p3)))

    # Clamped cubic: multiplicity 4 at both ends, 3 at every interior joint.
    # len(knots) == 3m + 5 == len(poles) + degree + 1, so `is_consistent` holds.
    m = len(segs)
    knots = [0.0] * 4
    for j in range(1, m):
        knots.extend([float(j)] * 3)
    knots.extend([float(m)] * 4)

    return NurbsCurve(control_points=poles, knots=knots, degree=3,
                      closed=closed, layer=layer)


def _extent(segment) -> float:
    """The largest gap between any two of a Bézier segment's control points."""
    return max(math.dist(a, b) for a in segment for b in segment)


#: A quarter circle as a rational quadratic needs its corner pole weighted by
#: cos(45°); the nine-pole form below is the textbook exact circle.
_W = math.sqrt(2.0) / 2.0


def circle_curve(center: tuple[float, float], radius: float,
                 layer: str = "") -> NurbsCurve | None:
    """A full circle as an exact rational quadratic B-spline (nine poles).

    Exact, not sampled: the rational form reproduces a circle to machine
    precision, which a polyline cannot do at any vertex count. It also spares
    the pipeline a genuinely bad approximation — the ``.gdraw`` circle flattener
    divides *circumference* by the chord tolerance, so a 20 mm hole arrives as
    roughly twelve thousand points.

    Wound counter-clockwise from angle 0. Returns None for a non-positive
    radius.
    """
    if radius <= 0.0:
        return None
    cx, cy = float(center[0]), float(center[1])
    r = float(radius)
    #  (1,0) (1,1) (0,1) (-1,1) (-1,0) (-1,-1) (0,-1) (1,-1) (1,0)
    unit = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0),
            (-1, -1), (0, -1), (1, -1), (1, 0)]
    poles = [(cx + r * ux, cy + r * uy) for ux, uy in unit]
    return NurbsCurve(
        control_points=poles,
        knots=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0, 4.0],
        degree=2,
        closed=True,
        weights=[1.0, _W, 1.0, _W, 1.0, _W, 1.0, _W, 1.0],
        layer=layer,
    )
