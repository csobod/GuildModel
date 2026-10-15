"""Tool shapes for the stock engine (BUILDPLAN M21 §6.2): what a tool occupies
along each column it covers.

For a **vertical pose** a shape yields a *footprint*: integer cell offsets
``(di, dj)`` around the tip's cell and, for each, the tool's occupancy
interval ``[z_lo, z_hi]`` relative to the tip. The heightfield simulator's
kernel is the case ``z_hi = +inf`` — a flat, ball, toroid or V-bit removes
everything above its lower surface — and the drop-profile arithmetic here is
`sim.toolsim.ToolProfile.kernel`'s, operation for operation, so a stock cut
with a footprint is bit-identical to the floor that kernel stamps.

The **groove form** is the one that needed the dexel. The drageoir is a
side-cutting V on a relieved neck: at the apex radius the head has no height,
at the root radius it is `groove_width_mm` tall, the root cylinder is
`flute_length_mm` high, and above it the neck is narrower than the head. Its
occupancy is a *finite* interval for every column under the head and outside
the neck, which is what takes a slot out of a wall and leaves the material
above it standing (`test_stock_reference`). The heightfield simulator stamps
nothing for it and the Lens Groove op is checked geometrically instead; the
stock engine simulates it.

For a **general pose** (§6.7, M26) a shape yields the closed-form crossing of
each column with the tool: quadratic for a cylinder or a sphere, piecewise for
a cone or a bull-nose corner. Written and tested against the footprint for a
vertical axis; unused by the vertical fast path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Footprint", "ToolShape"]

#: The flat tool's body goes up for ever, as far as the stock is concerned:
#: the shank and holder are tested as a second shape (§6.5), never stamped.
_UP = np.inf


@dataclass(frozen=True)
class Footprint:
    """The occupancy of a vertical tool, per covered cell, relative to its tip."""
    di: np.ndarray      # column offsets (x), intp
    dj: np.ndarray      # row offsets (y), intp
    z_lo: np.ndarray    # lowest occupied z above the tip, float64
    z_hi: np.ndarray    # highest occupied z above the tip; +inf for a top-down tool

    @property
    def finite(self) -> bool:
        """True when some cell's interval has a top — an undercutting form."""
        return bool(np.isfinite(self.z_hi).any())

    def __len__(self) -> int:
        return int(self.di.size)


@dataclass(frozen=True)
class ToolShape:
    """A tool from `tools.yaml`, as the stock sees it."""
    kind: str = "flat"                  # flat | ball | toroid | vbit | groove
    radius_mm: float = 1.5875
    corner_radius_mm: float = 0.0       # toroid corner radius
    included_angle_deg: float = 0.0     # vbit tip (included) angle
    # the groove form (type "groove")
    flute_length_mm: float = 0.0        # the head's height
    groove_depth_mm: float = 0.0        # radial depth of the V, apex to root
    groove_width_mm: float = 0.0        # the V's opening height at the root
    neck_diameter_mm: float = 0.0       # the relieved neck above the head
    shank_diameter_mm: float = 0.0

    @classmethod
    def from_tool(cls, tool: dict) -> "ToolShape":
        g = lambda key: float(tool.get(key, 0.0) or 0.0)       # noqa: E731
        return cls(kind=tool.get("type", "flat"), radius_mm=float(tool["radius_mm"]),
                   corner_radius_mm=g("corner_radius_mm"),
                   included_angle_deg=g("included_angle_deg"),
                   flute_length_mm=g("flute_length_mm"), groove_depth_mm=g("groove_depth_mm"),
                   groove_width_mm=g("groove_width_mm"), neck_diameter_mm=g("neck_diameter_mm"),
                   shank_diameter_mm=g("shank_diameter_mm"))

    # ------------------------------------------------------------- vertical

    def drop(self, d: np.ndarray) -> np.ndarray:
        """The lower surface above the tip at radial offset `d` (clipped to the
        radius): `ToolProfile.kernel`'s arithmetic, kept identical so the two
        agree bit for bit."""
        R = self.radius_mm
        dd = np.minimum(d, R)
        if self.kind == "ball":
            return R - np.sqrt(np.maximum(0.0, R * R - dd * dd))
        if self.kind == "toroid" and self.corner_radius_mm > 0:
            rc = self.corner_radius_mm
            Rf = max(0.0, R - rc)
            return np.where(dd <= Rf, 0.0,
                            rc - np.sqrt(np.maximum(0.0, rc * rc - (dd - Rf) ** 2)))
        if self.kind == "vbit" and self.included_angle_deg > 0:
            t = math.tan(math.radians(self.included_angle_deg / 2.0))
            return dd / t if t > 1e-9 else np.zeros_like(dd)
        return np.zeros_like(dd)

    def footprint(self, resolution: float) -> Footprint:
        """Cells within the radius and their occupancy intervals, vertical."""
        R = self.radius_mm
        r_px = max(1, int(round(R / resolution)))
        jj, ii = np.mgrid[-r_px:r_px + 1, -r_px:r_px + 1]
        d = np.hypot(ii, jj) * resolution
        inside = d <= R + 1e-9
        di = ii[inside].astype(np.intp)
        dj = jj[inside].astype(np.intp)
        dd = d[inside]
        if self.kind == "groove":
            lo, hi = self._groove_intervals(np.minimum(dd, R))
            return Footprint(di, dj, lo.astype(np.float64), hi.astype(np.float64))
        lo = self.drop(dd).astype(np.float64)
        return Footprint(di, dj, lo, np.full_like(lo, _UP))

    def _groove_intervals(self, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The drageoir's occupancy by radial offset.

        * under the neck (``d <= neck radius``): head, neck and shank — the
          tool goes up for ever from the tip;
        * over the root cylinder: the head alone, ``[0, flute_length]``;
        * over the V (root to apex): ``[h/2 - h·t/2, h/2 + h·t/2]`` with
          ``t`` running 1 at the root to 0 at the apex, ``h`` the groove width
          — the V's two flanks closing on the apex at mid-height.
        The posted Z is the tip (`castle_ops.lens_groove_op`): the apex sits
        at ``tip + groove_width / 2``.
        """
        R = self.radius_mm
        depth = max(self.groove_depth_mm, 1e-9)
        width = self.groove_width_mm if self.groove_width_mm > 0 else self.flute_length_mm
        height = self.flute_length_mm if self.flute_length_mm > 0 else width
        neck_r = self.neck_diameter_mm / 2.0
        root_r = max(R - depth, 0.0)
        lo = np.zeros_like(d)
        hi = np.full_like(d, height)
        v = d > root_r
        t = np.clip((R - d[v]) / depth, 0.0, 1.0)
        lo[v] = width / 2.0 - (width / 2.0) * t
        hi[v] = width / 2.0 + (width / 2.0) * t
        under_neck = d <= neck_r + 1e-9
        hi[under_neck] = _UP
        return lo, hi

    # -------------------------------------------------------------- general

    def column_intervals(self, tip, axis, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        """The tool's occupancy along vertical columns at ``(xs, ys)`` for a
        general pose: tip position and unit axis, pointing up the tool away
        from the tip. Returns ``(z_lo, z_hi)``; a column the tool misses gets
        ``(+inf, -inf)``.

        A vertical pose is answered in closed form from the drop profile and
        agrees with `footprint` to float precision — the footprint path is
        what the production kernel runs. A tilted pose is answered per column
        (§6.7): a cylinder or a sphere is a quadratic in the column parameter,
        a cone piecewise so; the bull-nose corner and the groove form are
        bracketed and bisected on their implicit solids. Unused until M26.
        """
        tip = np.asarray(tip, dtype=np.float64)
        a = np.asarray(axis, dtype=np.float64)
        a = a / np.linalg.norm(a)
        xs = np.asarray(xs, dtype=np.float64).ravel()
        ys = np.asarray(ys, dtype=np.float64).ravel()
        n = xs.size
        lo = np.full(n, np.inf)
        hi = np.full(n, -np.inf)
        if abs(a[2]) < 1e-12:
            return lo, hi                       # a horizontal tool crosses no column
        px, py = xs - tip[0], ys - tip[1]
        R = self.radius_mm
        if abs(abs(a[2]) - 1.0) < 1e-12:
            d = np.hypot(px, py)
            inside = d <= R + 1e-9
            if self.kind == "groove":
                glo, ghi = self._groove_intervals(np.minimum(d[inside], R))
            else:
                glo = self.drop(d[inside])
                ghi = np.full_like(glo, _UP)
            if a[2] > 0:
                lo[inside] = tip[2] + glo
                hi[inside] = tip[2] + ghi
            else:                               # the tool comes up from below
                lo[inside] = tip[2] - ghi
                hi[inside] = tip[2] - glo
            return lo, hi
        for i in range(n):
            lo[i], hi[i] = self._tilted_column(float(px[i]), float(py[i]), float(tip[2]),
                                               float(a[0]), float(a[1]), float(a[2]))
        return lo, hi

    def _tilted_column(self, px: float, py: float, tz: float,
                       ax: float, ay: float, az: float) -> tuple[float, float]:
        """One column against a tilted tool. The column is ``p(s) = (px, py,
        s - tz)`` from the tip; ``u(s) = c0 + (s - tz) az`` is its coordinate
        along the axis and ``w(s)`` its distance from the axis."""
        R = self.radius_mm
        c0 = px * ax + py * ay
        A = 1.0 - az * az
        B = -2.0 * az * c0
        C = px * px + py * py - c0 * c0
        miss = (np.inf, -np.inf)

        def within(r: float):
            """The s-interval where the column lies within `r` of the axis."""
            cc = C - r * r
            if A < 1e-15:
                return (-np.inf, np.inf) if cc <= 0 else None
            disc = B * B - 4.0 * A * cc
            if disc < 0:
                return None
            sq = math.sqrt(disc)
            s1, s2 = (-B - sq) / (2.0 * A), (-B + sq) / (2.0 * A)
            return (tz + min(s1, s2), tz + max(s1, s2))

        def s_at_u(u: float) -> float:
            return tz + (u - c0) / az

        def above(seg, u_min: float):
            """`seg` clipped to the half space ``u >= u_min``."""
            if seg is None:
                return None
            s_lo, s_hi = seg
            s_min = s_at_u(u_min)
            s_lo, s_hi = (max(s_lo, s_min), s_hi) if az > 0 else (s_lo, min(s_hi, s_min))
            return (s_lo, s_hi) if s_lo <= s_hi else None

        def hull(*segs):
            """One interval per column per pose: the hull of the body's
            pieces. Exact where they meet, as they do on every column of a
            vertical tool; on a steep tilt a ball's sphere and its shank-side
            cylinder can leave a sliver between them that the hull fills, a
            conservative error M26 weighs against a per-pose interval list."""
            segs = [sg for sg in segs if sg is not None]
            if not segs:
                return miss
            return min(sg[0] for sg in segs), max(sg[1] for sg in segs)

        if self.kind == "flat" or (self.kind == "vbit" and self.included_angle_deg <= 0) \
                or (self.kind == "toroid" and self.corner_radius_mm <= 0):
            return hull(above(within(R), 0.0))
        if self.kind == "ball":
            # the sphere about the point R up the axis, and the cylinder above it
            cx, cy, cz = px - R * ax, py - R * ay, tz + R * az
            disc = R * R - cx * cx - cy * cy
            sphere = (cz - math.sqrt(disc), cz + math.sqrt(disc)) if disc >= 0 else None
            return hull(sphere, above(within(R), R))
        if self.kind == "vbit":
            t = math.tan(math.radians(self.included_angle_deg / 2.0))
            # Inside the double cone where w² < (t u)²: a quadratic in (s - tz)
            # whose leading coefficient changes sign when the column leans
            # past the cone's half-angle — then the inside is *outside* the
            # roots, two half-lines, and the tip plane and the full-radius
            # plane cut each back to the real cone.
            A2 = A - t * t * az * az
            B2 = B - 2.0 * t * t * c0 * az
            C2 = C - t * t * c0 * c0
            cands = []
            if abs(A2) < 1e-15:
                if abs(B2) > 1e-15:
                    root = tz - C2 / B2
                    cands.append((root, np.inf) if B2 < 0 else (-np.inf, root))
                elif C2 < 0:
                    cands.append((-np.inf, np.inf))
            else:
                disc = B2 * B2 - 4.0 * A2 * C2
                if disc >= 0:
                    sq = math.sqrt(disc)
                    r1, r2 = sorted(((-B2 - sq) / (2.0 * A2), (-B2 + sq) / (2.0 * A2)))
                    r1, r2 = tz + r1, tz + r2
                    cands += [(r1, r2)] if A2 > 0 else [(-np.inf, r1), (r2, np.inf)]
                elif A2 < 0:
                    cands.append((-np.inf, np.inf))
            u_full = R / t
            s0, s1 = sorted((s_at_u(0.0), s_at_u(u_full)))
            cone_parts = []
            for a_s, b_s in cands:
                a_s, b_s = max(a_s, s0), min(b_s, s1)
                if a_s <= b_s:
                    cone_parts.append((a_s, b_s))
            return hull(*cone_parts, above(within(R), u_full))
        # toroid and groove: bracket the implicit solid along the column and
        # bisect its two ends
        seg = above(within(R), 0.0)
        if seg is None:
            return miss
        return self._bracketed(seg, px, py, tz, ax, ay, az)

    def _inside(self, u: float, w: float) -> bool:
        """Is the point at axial `u`, radial `w` inside the tool's solid?"""
        R = self.radius_mm
        if u < 0.0 or w > R:
            return False
        if self.kind == "toroid":
            rc = self.corner_radius_mm
            Rf = max(0.0, R - rc)
            if u >= rc or w <= Rf:
                return True
            return (w - Rf) ** 2 + (u - rc) ** 2 <= rc * rc
        if self.kind == "groove":
            lo, hi = self._groove_intervals(np.array([min(w, R)]))
            return lo[0] <= u <= hi[0]
        return True

    def _bracketed(self, seg, px, py, tz, ax, ay, az, samples: int = 64):
        s_lo, s_hi = seg
        if not np.isfinite(s_lo) or not np.isfinite(s_hi):
            span = (s_lo if np.isfinite(s_lo) else tz) - 50.0, (s_hi if np.isfinite(s_hi) else tz) + 50.0
            s_lo, s_hi = span

        def inside_at(s: float) -> bool:
            u = px * ax + py * ay + (s - tz) * az
            w2 = px * px + py * py + (s - tz) ** 2 - u * u
            return self._inside(u, math.sqrt(max(w2, 0.0)))

        ss = np.linspace(s_lo, s_hi, samples)
        hits = [inside_at(float(s)) for s in ss]
        if not any(hits):
            return (np.inf, -np.inf)
        first = hits.index(True)
        last = len(hits) - 1 - hits[::-1].index(True)

        def refine(a_s: float, b_s: float, want_inside_at_b: bool) -> float:
            for _ in range(40):
                m = 0.5 * (a_s + b_s)
                if inside_at(m) == want_inside_at_b:
                    b_s = m
                else:
                    a_s = m
            return b_s

        lo = ss[first] if first == 0 else refine(ss[first - 1], ss[first], True)
        hi = ss[last] if last == len(ss) - 1 else refine(ss[last + 1], ss[last], True)
        return float(lo), float(hi)
