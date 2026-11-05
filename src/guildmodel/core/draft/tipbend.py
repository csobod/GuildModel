"""A temple's tip bend, in GuildModel's frame (2.3; research section 5.3).

GuildDraw's `forming.TipBend`, ported: the core keeps its length (the
wire's), the ear point sits at the middle of the arc, so the straight run is
``length to bend - r*delta/2``, the arc ``r*delta`` and the tail the rest;
every point moves by its (arc length along the core, offset from the core)
coordinates. GuildDraw's temple tab has "down" at +y; this reader's intake
flips y, and the left temple is drawn as the right's mirror about the core
line (both tabs show the hinge face, the hinge end at min x), so here the
right temple's drop goes toward -y and the left's toward +y. `resolve_tip_bend`
reads both signs off the part: which end the hinge is at, and which temple
it is.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: The research's default drop (section 5.2), from the 35-40 mm the trade bends.
DEFAULT_DROP_MM = 37.0


@dataclass(frozen=True)
class TipBend:
    """The bend resolved against a drawn temple. `along` is +1 when the
    temple runs toward +x from its hinge end (every library temple), -1 when
    it runs toward -x; `down` is the sign of y the drop goes toward."""
    x_hinge: float
    overall_mm: float
    length_to_bend_mm: float
    drop_angle_deg: float
    bend_radius_mm: float
    core_y: float = 0.0
    along: float = 1.0
    down: float = -1.0

    @classmethod
    def resolve(cls, params, x_hinge: float, overall_mm: float, *,
                core_y: float = 0.0, along: float = 1.0, down: float = -1.0) -> "TipBend":
        ltb = float(params.length_to_bend_mm)
        if ltb <= 0.0:
            ltb = max(float(overall_mm) - DEFAULT_DROP_MM, 0.0)
        return cls(float(x_hinge), float(overall_mm), ltb, float(params.drop_angle_deg),
                   float(params.bend_radius_mm), float(core_y),
                   1.0 if along >= 0 else -1.0, 1.0 if down >= 0 else -1.0)

    @property
    def angle_rad(self) -> float:
        return math.radians(self.drop_angle_deg)

    @property
    def arc_mm(self) -> float:
        return self.bend_radius_mm * self.angle_rad

    @property
    def straight_mm(self) -> float:
        """The straight run from the hinge end to the arc's start."""
        return self.length_to_bend_mm - 0.5 * self.arc_mm

    @property
    def tail_mm(self) -> float:
        """The straight run from the arc's end to the tip."""
        return self.overall_mm - self.length_to_bend_mm - 0.5 * self.arc_mm

    @property
    def drop_mm(self) -> float:
        """ISO's length of drop: from the ear point to the tip, straightened."""
        return self.overall_mm - self.length_to_bend_mm

    @property
    def is_straight(self) -> bool:
        return self.drop_angle_deg <= 0.0 or self.overall_mm <= 0.0

    @property
    def auto_length(self) -> bool:
        return False

    def out_of_range(self) -> str | None:
        """Why the bend does not fit this temple, or None when it does."""
        if self.overall_mm <= 0.0:
            return None
        if self.length_to_bend_mm >= self.overall_mm:
            return (f"the length to bend ({self.length_to_bend_mm:.1f} mm) is the whole "
                    f"temple ({self.overall_mm:.1f} mm): nothing is left to drop")
        if self.straight_mm < 0.0:
            return (f"the bend (R {self.bend_radius_mm:.1f} mm over {self.drop_angle_deg:.0f}°) "
                    f"starts before the hinge: {0.5 * self.arc_mm:.1f} mm of arc each side "
                    f"of the ear point, with {self.length_to_bend_mm:.1f} mm to bend")
        if self.tail_mm < 0.0:
            return (f"the bend (R {self.bend_radius_mm:.1f} mm over {self.drop_angle_deg:.0f}°) "
                    f"runs past the tip: {0.5 * self.arc_mm:.1f} mm of arc each side of the "
                    f"ear point, with {self.drop_mm:.1f} mm to drop")
        return None

    @property
    def applies(self) -> bool:
        """The bend is drawn: not straight and within the temple."""
        return not self.is_straight and self.out_of_range() is None

    def _bend_sd(self, s, d):
        """The bend in the (along the core, down from the core) frame:
        GuildDraw's arithmetic verbatim, the core at d = 0."""
        s = np.asarray(s, dtype=np.float64)
        d = np.asarray(d, dtype=np.float64)
        xs, ds = s.copy(), d.copy()
        s1, r, delta = self.straight_mm, self.bend_radius_mm, self.angle_rad
        on_arc = (s > s1) & (s <= s1 + self.arc_mm)
        past = s > s1 + self.arc_mm
        # the arc: its center r below the core at the arc's start
        a = (s[on_arc] - s1) / r
        xs[on_arc] = s1 + (r - d[on_arc]) * np.sin(a)
        ds[on_arc] = r - (r - d[on_arc]) * np.cos(a)
        # the tail: from the arc's end, along its direction
        ex, ey = s1 + r * math.sin(delta), r - r * math.cos(delta)
        t = s[past] - s1 - self.arc_mm
        xs[past] = ex + t * math.cos(delta) - d[past] * math.sin(delta)
        ds[past] = ey + t * math.sin(delta) + d[past] * math.cos(delta)
        return xs, ds

    def map_points(self, xy) -> np.ndarray:
        """Bend the points, ``(N, 2)`` in the temple's frame; the identity
        when the bend is straight or out of range."""
        P = np.asarray(xy, dtype=np.float64)[:, :2].copy()
        if len(P) == 0 or not self.applies:
            return P
        s = (P[:, 0] - self.x_hinge) * self.along
        d = (P[:, 1] - self.core_y) * self.down
        xs, ds = self._bend_sd(s, d)
        out = P.copy()
        out[:, 0] = self.x_hinge + self.along * xs
        out[:, 1] = self.core_y + self.down * ds
        return out

    def map_points_3d(self, xyz) -> np.ndarray:
        """The bend acts in the temple's plane; z (through the thickness)
        rides along."""
        P = np.asarray(xyz, dtype=np.float64)
        out = P.copy()
        out[:, :2] = self.map_points(P[:, :2])
        return out

    def core_point(self, s_mm: float) -> tuple[float, float]:
        """Where the core's point `s_mm` along it lands."""
        p = self.map_points([[self.x_hinge + self.along * float(s_mm), self.core_y]])[0]
        return float(p[0]), float(p[1])

    def tip(self) -> tuple[float, float]:
        return self.core_point(self.overall_mm)

    def ear_point(self) -> tuple[float, float]:
        """The middle of the bend arc, where ISO measures the length to bend to."""
        return self.core_point(self.length_to_bend_mm)

    @property
    def reach_mm(self) -> float:
        """The bent temple's projected length, hinge end to tip along the temple."""
        return (self.tip()[0] - self.x_hinge) * self.along

    @property
    def tip_drop_mm(self) -> float:
        """How far the tip sits below the core, mm."""
        return (self.tip()[1] - self.core_y) * self.down

    def core_polyline(self, step_mm: float = 1.0) -> np.ndarray:
        """The bent core, ``(N, 2)``, for the center line of a view."""
        n = max(int(math.ceil(self.overall_mm / step_mm)), 1) + 1
        s = np.linspace(0.0, self.overall_mm, n)
        pts = np.column_stack([self.x_hinge + self.along * s, np.full(n, self.core_y)])
        return self.map_points(pts)


#: The integration step along the core for the 3D bend, mm.
_DS_MM = 0.25


@dataclass
class TempleBend3D:
    """The temple bent as a bar: the drop (`TipBend`, about the lateral
    axis) and the inward bend (about the vertical axis) composed along the
    core's arc length, in the temple's normalized frame: x along the temple
    from the hinge end, y up, z toward the head. A point at (s, up, in)
    lands at ``P(s) + up * U(s) + in * I(s)`` where P is the bent core and
    (T, U, I) its frame, integrated at `_DS_MM` from the hinge end; before
    the hinge end and past the tip the bar runs straight on.

    The drop's curvature is 1 / r over the arc `TipBend` defines; the
    inward bend's is the inward angle over the run from `inward_start_mm`
    to the ear point, so the drop leaves the ear point at the inward
    heading, as ISO's inward angle of drop describes it."""
    bend: TipBend
    inward_angle_deg: float = 0.0
    inward_start_mm: float = 0.0        # resolved: 0 = auto, 40 % of the length to bend

    def __post_init__(self) -> None:
        b = self.bend
        L = max(float(b.overall_mm), 1.0)
        if self.inward_start_mm <= 0.0:
            self.inward_start_mm = 0.4 * b.length_to_bend_mm
        n = int(math.ceil(L / _DS_MM)) + 1
        s = np.linspace(0.0, L, n)
        ds = s[1] - s[0] if n > 1 else L
        # the turn in each step, from its exact overlap with each bend's run
        # (a grid sample at the arc's ends smeared the drop by up to a step)
        def overlap(a0, a1):
            lo = np.maximum(s[:-1], a0)
            hi = np.minimum(s[1:], a1)
            return np.clip(hi - lo, 0.0, None)

        turn_drop = np.zeros(max(n - 1, 0))
        if b.applies:
            s1 = b.straight_mm
            turn_drop = overlap(s1, s1 + b.arc_mm) / b.bend_radius_mm
        turn_in = np.zeros(max(n - 1, 0))
        run = b.length_to_bend_mm - self.inward_start_mm
        if self.inward_angle_deg > 0.0 and run > 1e-6 and b.length_to_bend_mm < L:
            turn_in = overlap(self.inward_start_mm, b.length_to_bend_mm) * (
                math.radians(self.inward_angle_deg) / run)
        P = np.zeros((n, 3))
        T = np.zeros((n, 3)); U = np.zeros((n, 3)); I = np.zeros((n, 3))
        t, u, i = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
        for j in range(n):
            T[j], U[j], I[j] = t, u, i
            if j + 1 < n:
                # one exact rotation per step: the drop turns T toward -U
                # (about -I), the inward bend T toward +I (about -U)
                axis = -turn_drop[j] * i - turn_in[j] * u
                ang = float(np.linalg.norm(axis))
                if ang > 1e-12:
                    a = axis / np.linalg.norm(axis)
                    c, sn = math.cos(ang), math.sin(ang)
                    rot = lambda v: v * c + np.cross(a, v) * sn + a * float(a @ v) * (1 - c)  # noqa: E731
                    t2, u2, i2 = rot(t), rot(u), rot(i)
                else:
                    t2, u2, i2 = t, u, i
                P[j + 1] = P[j] + 0.5 * (t + t2) * ds
                t, u, i = t2, u2, i2
        self._s, self._P, self._T, self._U, self._I = s, P, T, U, I

    @property
    def is_identity(self) -> bool:
        return not self.bend.applies and self.inward_angle_deg <= 0.0

    def _frame_at(self, s):
        s = np.asarray(s, dtype=np.float64)
        sc = np.clip(s, self._s[0], self._s[-1])
        cols = []
        for arr in (self._P, self._T, self._U, self._I):
            cols.append(np.column_stack([np.interp(sc, self._s, arr[:, k]) for k in range(3)]))
        P, T, U, I = cols
        # straight on past either end
        over = (s - sc)[:, None]
        P = P + over * T
        return P, T, U, I

    def map(self, pts_norm) -> np.ndarray:
        """Normalized (s, up, in) points, (N, 3) -> bent, (N, 3)."""
        Q = np.asarray(pts_norm, dtype=np.float64).reshape(-1, 3)
        if len(Q) == 0:
            return Q
        if self.is_identity:
            return Q.copy()
        P, _T, U, I = self._frame_at(Q[:, 0])
        return P + Q[:, 1:2] * U + Q[:, 2:3] * I

    def heading_at(self, s_mm: float) -> np.ndarray:
        """The core's direction at `s`, unit, in the normalized frame."""
        return self._frame_at(np.array([float(s_mm)]))[1][0]


def temple_axes(outline, hinge_polys, kind) -> tuple[float, float, float]:
    """``(x_hinge, along, down)`` for a drawn temple: the hinge end is the
    end of the OUTLINE its pocket is nearer (`pocket_floor.hinge_on_plus_x`),
    and the drop goes toward -y on the right temple and +y on the left (the
    left tab is the right's mirror about the core line); a temple drawn with
    its hinge at +x is the same part turned, so its down flips too."""
    from guildmodel.core.geometry.pocket_floor import hinge_on_plus_x
    from guildmodel.core.project.schema import ComponentKind

    minx, _, maxx, _ = outline.bounds
    plus = hinge_on_plus_x(outline, hinge_polys)
    along = -1.0 if plus else 1.0
    right = ComponentKind(kind) != ComponentKind.TEMPLE_LEFT
    down = (-1.0 if right else 1.0) * along
    return (maxx if plus else minx), along, down


def resolve_tip_bend(params, outline, hinge_polys, kind, core_y: float = 0.0
                     ) -> TipBend | None:
    """The bend of a drawn temple, or None without an outline."""
    if outline is None or outline.is_empty:
        return None
    x_hinge, along, down = temple_axes(outline, hinge_polys, kind)
    minx, _, maxx, _ = outline.bounds
    return TipBend.resolve(params, x_hinge, maxx - minx, core_y=core_y,
                           along=along, down=down)
