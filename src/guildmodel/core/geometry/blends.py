"""Cross-section blends shared by all three kernels.

`relief/castle.py` owns `_footing_z`, the S-blend that rolls one terrace into
the next, and all three paths already call it. This module is the same idea for
the shapes a *scoop* is made of, and it lives here rather than there for the
reason `rings.py` and `footings.py` give: a second copy of a profile becomes a
second, subtly different profile, and these are exactly the numbers that must
not drift between the raster, the mesh and the B-Rep.

The one profile here is the bridge relief's U (`scoop_drop`). See its docstring
for the geometry; the short version is that it is the footing's own vocabulary —
an exterior radius rolling off the surface, an interior radius landing on the
floor, a straight ramp between them — applied to a cut of fixed width instead of
to a step of fixed height.
"""
from __future__ import annotations

import numpy as np

__all__ = ["MIN_RIM_RADIUS_MM", "scoop_drop", "scoop_max_slope_deg",
           "scoop_ramp_angle", "scoop_section_x"]

#: The smallest rim round-over the scoop is built with, mm.
#:
#: A scoop whose exterior radius is exactly zero leaves the demo frame with
#: **gaps along 15 edges** — the cutter's rim runs into the surface it exits
#: instead of crossing it, which is the failure `model.features.EDGE_CROSS_MM`
#: and `model.build.FOOTING_CROSS_MM` are each a floor against elsewhere in this
#: project. Measured on all three fixtures: 0 fails, **0.01 mm and everything
#: above it is clean**, and the interior radius makes no difference either way
#: (0 / 0.01 / 0.05 all fail while `exterior = 0`).
#:
#: 0.05 mm is five times the measured threshold and still far below anything
#: that reaches the part: no cutter this app posts leaves a rim sharper than its
#: own corner radius, so a scoop rim is physically round at a larger figure than
#: this whatever the model says. The trough radius has no such floor — a sharp
#: V trough builds clean — so `interior_radius_mm = 0` means what it says.
MIN_RIM_RADIUS_MM = 0.05


def _fit_radii(a: np.ndarray, d: np.ndarray, r_ext: float, r_int: float):
    """Shrink the two radii, in proportion, until the profile can be built.

    A U of half-width `a` and depth `d` can only carry so much radius: past the
    point where the two arcs meet each other there is no straight ramp left to
    shorten, and the section stops existing rather than becoming something
    cruder. That limit is exactly ``(a**2 + d**2) / (2 * d)`` on the *sum* of the
    radii — the derivation is in `scoop_ramp_angle` — and this clamps to it.

    **Proportional, and clamped per station rather than once for the scoop.**
    The scoop tapers, so `a` and `d` shrink toward the tip and a radius pair that
    fits at the base will not fit near the point. Scaling both by the same factor
    keeps the section's *shape* while it shrinks, and because the factor is a
    continuous function of `a` and `d` the swept surface stays smooth through the
    region where the clamp starts to bite. Clamping one radius, or clamping to a
    constant, would put a crease there.
    """
    # The rim floor is applied here, once, so every kernel sweeps the same
    # section and `scoop_max_slope_deg` reports the angle of the one built.
    r_ext = max(float(r_ext), MIN_RIM_RADIUS_MM)
    s = r_ext + float(r_int)
    # A hair under the true limit: at the limit itself the ramp has exactly zero
    # length and `asin` is evaluated at exactly 1.0, where float error decides
    # whether it returns or raises.
    s_max = 0.999 * (a * a + d * d) / np.maximum(2.0 * d, 1e-12)
    k = np.minimum(1.0, s_max / s)
    return k * float(r_ext), k * float(r_int)


def scoop_ramp_angle(a, d, r_ext: float, r_int: float):
    """`(theta, r_ext, r_int)` — the ramp angle in radians, and the radii as
    actually used once `_fit_radii` has had them.

    The section runs, from the rim inward: a convex arc of radius `r_ext`
    tangent to the surface, a straight ramp at `theta` to the horizontal, then a
    concave arc of radius `r_int` tangent to the floor. Continuity at both
    tangencies gives two equations in the ramp's angle and length,

        L*cos(theta) = a - (r_ext + r_int) * sin(theta)
        L*sin(theta) = d - (r_ext + r_int) * (1 - cos(theta))

    and eliminating `L` collapses them — the `sin**2 + cos**2` cancels — to a
    single linear-in-(sin, cos) equation,

        a*sin(theta) + (S - d)*cos(theta) = S,     S = r_ext + r_int

    which is `R*sin(theta + phi) = S` for `R = hypot(a, S - d)` and
    `phi = atan2(S - d, a)`. The smaller root is the one with a ramp of positive
    length; the larger is the same arcs run the wrong way round. Solvable
    whenever `S <= (a**2 + d**2) / (2*d)`, which is what `_fit_radii` enforces,
    and at that bound the ramp length is exactly zero and the two arcs meet.

    With both radii at zero this is a straight V but for the `MIN_RIM_RADIUS_MM`
    floor on the rim, which rounds it over the first 0.05 mm and no further.
    """
    a = np.asarray(a, dtype=float)
    d = np.asarray(d, dtype=float)
    re, ri = _fit_radii(a, d, r_ext, r_int)
    s = re + ri
    r = np.hypot(a, s - d)
    phi = np.arctan2(s - d, a)
    theta = np.arcsin(np.clip(s / np.maximum(r, 1e-12), -1.0, 1.0)) - phi
    return np.clip(theta, 0.0, 0.5 * np.pi), re, ri


def scoop_drop(x, half_width, depth, r_ext: float, r_int: float) -> np.ndarray:
    """How far the scoop cuts below the local surface, at signed offset `x`.

    `x` is measured from the scoop's centerline; `half_width` and `depth` are the
    section's own at this station and may vary with it (they do — the scoop is a
    cone). Returns 0 outside the section and `depth` at the centerline.

    The shape is a **U with both of its corners named**: `r_ext` rounds the rim
    where the cut leaves the surrounding face, `r_int` rounds the trough where it
    lands on the floor, and a straight ramp joins them. That is the footing's own
    exterior/interior vocabulary, which is what the feature was asked for; the
    cosine bell this replaced had neither number and no way to ask for one.
    """
    x = np.abs(np.asarray(x, dtype=float))
    a = np.asarray(half_width, dtype=float)
    d = np.asarray(depth, dtype=float)
    theta, re, ri = scoop_ramp_angle(a, d, r_ext, r_int)

    t = a - x                                   # distance inward from the rim
    sin_t, cos_t = np.sin(theta), np.cos(theta)
    t1 = re * sin_t                             # convex arc -> ramp
    t2 = a - ri * sin_t                         # ramp -> concave arc
    tan_t = np.tan(np.minimum(theta, 0.5 * np.pi - 1e-9))

    convex = re - np.sqrt(np.maximum(re * re - t * t, 0.0))
    ramp = re * (1.0 - cos_t) + (t - t1) * tan_t
    concave = d - ri + np.sqrt(np.maximum(ri * ri - (t - a) ** 2, 0.0))

    w = np.where(t <= t1, convex, np.where(t < t2, ramp, concave))
    # Outside the section nothing is removed; past the centerline the section is
    # its own mirror, which `x = |x|` has already taken care of.
    return np.clip(np.where(t <= 0.0, 0.0, w), 0.0, d)


def scoop_section_x(half_width: float, n: int) -> np.ndarray:
    """Where to sample one scoop section across x: `n` points, **odd**, so that
    the centerline is one of them.

    An even count puts the two innermost samples either side of the trough and
    replaces it with a chord. On a rounded section that is a rounding error; on
    a sharp V (both radii 0) the flanks are straight lines the polyline
    reproduces exactly and the *only* error is that missing apex — the section
    comes out **3.7% shallow** at the 28 samples the solid kernels lofted. It is
    not only a depth error: as the cone tapers, consecutive sections' chords
    close on each other and the strip between them degenerates, which is how a
    sharp-V scoop reached the demo frame as a surface with gaps along 14 edges
    while every rounded one was clean.

    The count is fixed rather than adapted to the profile because
    `kernel._strip_mesh` builds the tube from rails and needs every section to
    have the same length; a section set of varying length silently falls back to
    the hull chain, which spans a concave trough instead of following it.
    """
    return np.linspace(-float(half_width), float(half_width),
                       max(int(n) | 1, 5))


def scoop_max_slope_deg(width_mm: float, depth_mm: float,
                        r_ext: float, r_int: float) -> float:
    """The steepest slope anywhere on the scoop, in degrees.

    That is the ramp angle: both arcs are tangent to it at one end and to a
    horizontal at the other, so neither is ever steeper. The CAM turns this into
    a feature-finish stepover, and the scoop's whole taper is a scaling of one
    section — `a` and `d` shrink together — so the base station is the steepest
    and one number covers the feature.
    """
    a = max(float(width_mm) / 2.0, 1e-9)
    d = max(float(depth_mm), 1e-9)
    theta, _re, _ri = scoop_ramp_angle(a, d, r_ext, r_int)
    return float(np.degrees(theta))
