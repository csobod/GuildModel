"""The hinge the draft view fills in from the drawn pocket (2.3; research
section 6.4), and its reference-only detail.

A drawn pocket is an outline, not a hinge: it says how long and wide the
plate is and where it sits. The shipped library puts each entry's origin on
the butt face (the endpiece's end face on the front, the temple's butt) with
a REF line from it to the pocket's near edge: the setback. So the datum of a
placed pocket is found by casting a ray from the pocket toward the frame's
edge: where it leaves the outline is the butt face, and the barrel axis sits
just beyond it, by the barrel's radius. The rest, the kind, the barrels, the
screw, the slant and the stop, is the maker's `DraftHinge`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from guildmodel.core.project.schema import (SCREW_LENGTH_STEP_MM, DraftHinge,
                                            HingeKind)

__all__ = ["HingeFill", "HingeLeaf", "PocketFit", "fill_hinge", "fit_pocket",
           "hinge_detail", "knuckle_split", "leaf_from_pocket", "screw_length"]


@dataclass(frozen=True)
class PocketFit:
    """One drawn pocket, read for the hinge: its rotated rectangle, and the
    butt face it is set back from."""
    center: tuple[float, float]
    along_axis_mm: float          # the long side, along the barrel axis
    across_mm: float              # the short side, across it
    axis_angle_deg: float         # the long side's direction from +y, CCW
    direction: tuple[float, float]   # unit vector from the pocket toward the butt face
    datum: tuple[float, float]    # where that ray leaves the outline: the butt face
    setback_mm: float             # the datum to the pocket's near edge
    found: bool                   # the ray met the outline
    length_mm: float = 0.0        # the pocket's extent along the ray: the plate's length
    width_mm: float = 0.0         # its extent across the ray: along the barrel axis

    @property
    def far_edge(self) -> tuple[float, float]:
        """The pocket's edge nearest the butt face, on the ray."""
        ux, uy = self.direction
        return (self.datum[0] - ux * self.setback_mm, self.datum[1] - uy * self.setback_mm)


def _rect_sides(poly: Polygon) -> tuple[float, float, float, tuple[float, float]]:
    """(long side, short side, the long side's angle from +y, the center) of
    a pocket's minimum rotated rectangle."""
    rect = poly.minimum_rotated_rectangle
    if rect.geom_type != "Polygon" or len(rect.exterior.coords) < 5:
        b = poly.bounds
        w, h = b[2] - b[0], b[3] - b[1]
        cx, cy = 0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3])
        if h >= w:
            return h, w, 0.0, (cx, cy)
        return w, h, 90.0, (cx, cy)
    c = np.asarray(rect.exterior.coords)[:4]
    e0, e1 = c[1] - c[0], c[2] - c[1]
    l0, l1 = float(np.hypot(*e0)), float(np.hypot(*e1))
    long_e, long_l, short_l = (e0, l0, l1) if l0 >= l1 else (e1, l1, l0)
    # the long side's direction from +y, as an angle in (-90, 90]
    ang = math.degrees(math.atan2(long_e[0], long_e[1]))
    while ang <= -90.0:
        ang += 180.0
    while ang > 90.0:
        ang -= 180.0
    cen = rect.centroid
    return long_l, short_l, ang, (float(cen.x), float(cen.y))


def fit_pocket(poly: Polygon, outline, direction: tuple[float, float],
               reach_mm: float = 60.0) -> PocketFit:
    """Read a pocket against the part's outline. `direction` points from the
    pocket toward the butt face: lateral on a front, toward the hinge end on
    a temple. Without an outline, or when the ray never leaves it, the datum
    is the pocket's own far edge (setback 0) and `found` is False."""
    long_l, short_l, ang, center = _rect_sides(poly)
    ux, uy = direction
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    # the pocket's far edge along the ray: its extent in that direction
    coords = np.asarray(poly.exterior.coords)
    proj = coords[:, 0] * ux + coords[:, 1] * uy
    across = -coords[:, 0] * uy + coords[:, 1] * ux
    length = float(proj.max() - proj.min())
    width = float(across.max() - across.min())
    c_proj = center[0] * ux + center[1] * uy
    far = float(proj.max())
    far_pt = (center[0] + ux * (far - c_proj), center[1] + uy * (far - c_proj))
    datum, setback, found = far_pt, 0.0, False
    if outline is not None and not outline.is_empty:
        ray = LineString([far_pt, (far_pt[0] + ux * reach_mm, far_pt[1] + uy * reach_mm)])
        hits = ray.intersection(outline.boundary)
        pts = []
        if not hits.is_empty:
            geoms = getattr(hits, "geoms", [hits])
            for g in geoms:
                if g.geom_type == "Point":
                    pts.append((g.x, g.y))
                else:
                    pts.extend(list(g.coords))
        if pts:
            # the nearest crossing beyond the pocket's far edge
            best = min(pts, key=lambda p: (p[0] - far_pt[0]) * ux + (p[1] - far_pt[1]) * uy)
            d = (best[0] - far_pt[0]) * ux + (best[1] - far_pt[1]) * uy
            if d >= -1e-6:
                datum, setback, found = (float(best[0]), float(best[1])), float(max(d, 0.0)), True
    return PocketFit(center=(float(center[0]), float(center[1])),
                     along_axis_mm=float(long_l), across_mm=float(short_l),
                     axis_angle_deg=float(ang), direction=(ux, uy),
                     datum=datum, setback_mm=setback, found=found,
                     length_mm=length, width_mm=width)


def knuckle_split(barrels: int) -> tuple[int, int]:
    """(front, temple) knuckles: the front half takes the odd one (research
    Q9, the convention: 5 = 3 + 2)."""
    b = int(barrels)
    return (b + 1) // 2, b // 2


def screw_length(width_mm: float, step_mm: float = SCREW_LENGTH_STEP_MM) -> float:
    """W + 0.5, snapped up to the catalog's step."""
    raw = float(width_mm) + 0.5
    return math.ceil(raw / step_mm - 1e-9) * step_mm


@dataclass(frozen=True)
class HingeFill:
    """What the pocket and the maker's choices say together: the hinge the
    detail view draws and the notes list."""
    spec: DraftHinge
    width_mm: float               # W, along the barrel axis (the pocket's long side)
    plate_length_mm: float        # the front leaf across the axis
    plate_thickness_mm: float     # the pocket's depth
    temple_plate_length_mm: float
    temple_plate_thickness_mm: float
    barrels_front: int
    barrels_temple: int
    screw_length_mm: float
    axis_setback_mm: float        # the barrel axis beyond the butt face

    @property
    def kind(self) -> HingeKind:
        return HingeKind(self.spec.kind)

    @property
    def screw_text(self) -> str:
        return (f"{self.spec.screw_thread} × {self.screw_length_mm:g}, "
                f"H{self.spec.screw_head_mm:g}")

    @property
    def installation_text(self) -> str:
        s = self.spec
        if self.kind == HingeKind.RIVET:
            return f"{s.rivet_count} × Ø{s.rivet_diameter_mm:g} rivets per leaf"
        if self.kind == HingeKind.HEAT_SET:
            return "cleat, heat-set into the pocket"
        return (f"spring box {s.spring_box_length_mm:g} × {self.width_mm:.1f} × "
                f"{s.spring_box_depth_mm:g} mm on the temple")

    @property
    def summary(self) -> str:
        s = self.spec
        return (f"{s.label} hinge, {s.barrels} barrels ({self.barrels_front} + "
                f"{self.barrels_temple}), W {self.width_mm:.1f} mm, screw {self.screw_text}")

    def lines(self) -> list[str]:
        """The hinge detail's note lines, as the research lists them."""
        s = self.spec
        return [
            f"{s.label}, {s.barrels} barrels ({self.barrels_front} front + "
            f"{self.barrels_temple} temple); W {self.width_mm:.1f} mm",
            f"Plates {self.plate_length_mm:.1f} × {self.plate_thickness_mm:.1f} (front), "
            f"{self.temple_plate_length_mm:.1f} × {self.temple_plate_thickness_mm:.1f} (temple)",
            f"Screw {self.screw_text} (ISO 11381); barrel Ø{s.barrel_diameter_mm:g}",
            f"Installation: {self.installation_text}",
            f"Stop {s.open_deg:g}°, slant {s.slant_deg:g}°; axis {s.axis_offset_mm:g} mm behind "
            f"the back face, {self.axis_setback_mm:g} mm beyond the butt",
            "Approved supplier or equivalent",
        ]


def fill_hinge(spec: DraftHinge, front: PocketFit | None, temple: PocketFit | None,
               front_depth_mm: float, temple_depth_mm: float) -> HingeFill:
    """The hinge for a pocket pair. W is the front pocket's extent along the
    barrel axis (across its ray to the butt face), less 0.2 mm of
    clearance; each plate's length is its pocket's extent toward the butt
    (a temple's pocket is usually longer along the temple than across)."""
    width = (front.width_mm if front is not None
             else temple.width_mm if temple is not None else 10.0)
    width = max(width - 0.2, 1.0)
    plate = front.length_mm if front is not None else 4.0
    t_plate = temple.length_mm if temple is not None else plate
    bf, bt = knuckle_split(spec.barrels)
    length = (spec.screw_length_mm if spec.screw_length_mm > 0.0
              else screw_length(width))
    setback = float(spec.axis_setback_mm)
    return HingeFill(spec=spec, width_mm=width, plate_length_mm=plate,
                     plate_thickness_mm=float(front_depth_mm),
                     temple_plate_length_mm=t_plate,
                     temple_plate_thickness_mm=float(temple_depth_mm),
                     barrels_front=bf, barrels_temple=bt,
                     screw_length_mm=length, axis_setback_mm=setback)


def _circle(cx: float, cy: float, r: float, n: int = 24) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


@dataclass(frozen=True)
class HingeLeaf:
    """One drawn pocket as the detail draws it: its ring in a frame whose
    x runs toward the butt face and y along the barrel axis, both measured
    from the pocket's own center, so the ring's edge nearest the butt is at
    x = `reach`; plus the part's thickness and the pocket's depth, for the
    plan's section."""
    ring: list                    # [(x, y)], the pocket's shape in that frame
    reach: float                  # the ring's extent toward the butt face
    setback_mm: float             # that edge to the butt face
    part_thickness_mm: float
    depth_mm: float

    @property
    def length(self) -> float:
        xs = [p[0] for p in self.ring]
        return (max(xs) - min(xs)) if xs else 0.0

    @property
    def half_width(self) -> float:
        ys = [p[1] for p in self.ring]
        return 0.5 * (max(ys) - min(ys)) if ys else 0.0


def leaf_from_pocket(ring_xy, direction, up, setback_mm: float,
                     part_thickness_mm: float, depth_mm: float) -> HingeLeaf:
    """A pocket's ring (any frame) read into a leaf: `direction` is the
    vector from the pocket toward the butt face in that frame, `up` the
    barrel axis's direction there; the leaf is centered on its own bounds."""
    P = np.asarray(ring_xy, dtype=np.float64).reshape(-1, 2)
    ux, uy = float(direction[0]), float(direction[1])
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    vx, vy = float(up[0]), float(up[1])
    n = math.hypot(vx, vy) or 1.0
    vx, vy = vx / n, vy / n
    x = P[:, 0] * ux + P[:, 1] * uy
    y = P[:, 0] * vx + P[:, 1] * vy
    if len(x):
        x = x - 0.5 * (x.min() + x.max())
        y = y - 0.5 * (y.min() + y.max())
    ring = [(float(a), float(b)) for a, b in zip(x, y)]
    return HingeLeaf(ring=ring, reach=float(x.max()) if len(x) else 0.0,
                     setback_mm=float(setback_mm), part_thickness_mm=float(part_thickness_mm),
                     depth_mm=float(depth_mm))


def _rect_leaf(length: float, half: float, thickness: float, depth: float) -> HingeLeaf:
    """A leaf without a drawn pocket: the plate's rectangle."""
    ring = [(-length, -half), (0.0, -half), (0.0, half), (-length, half)]
    return HingeLeaf(ring=ring, reach=0.0, setback_mm=0.0, part_thickness_mm=thickness,
                     depth_mm=depth)


def hinge_detail(fill: HingeFill, *, front_leaf: HingeLeaf | None = None,
                 temple_leaf: HingeLeaf | None = None, axis_inset_mm: float | None = None,
                 axis_offset_mm: float | None = None) -> dict:
    """The reference-only detail, two views in mm, y up, the barrel axis at
    x = 0, drawn from the pockets as they were drawn when the leaves are
    given, else from the fill's plate rectangles.

    ``elevation``: the hinge opened flat and seen from behind the front, the
    front's pocket shape to the left of the barrel column, the temple's to
    the right, each with its edge nearest the butt face against the column,
    their centers on one axis, the knuckles stacked along it (the front's
    joined to its leaf by a bar, the temple's to its), the installation on
    each leaf. ``plan``: the joint seen from above at the stop: the
    endpiece's section lying across with its pocket sunk in its back face,
    the barrel's circle at the axis, a temple's thickness inside the end
    face and `axis_offset_mm` behind the back face, and the temple's section
    swung to the stop with its pocket sunk in its inner face. Each is
    ``{"visible": [rings], "hidden": [rings], "center": [polylines],
    "labels": [(x, y, text)]}``."""
    s = fill.spec
    W, r = fill.width_mm, 0.5 * s.barrel_diameter_mm
    half = 0.5 * W
    if front_leaf is None:
        front_leaf = _rect_leaf(fill.plate_length_mm, half, fill.plate_thickness_mm + 3.0,
                                fill.plate_thickness_mm)
    if temple_leaf is None:
        temple_leaf = _rect_leaf(fill.temple_plate_length_mm, half,
                                 fill.temple_plate_thickness_mm + 3.0,
                                 fill.temple_plate_thickness_mm)
    gap = 0.3                       # between the barrel column and each leaf
    vis, hid, cen, labels = [], [], [], []
    # --- elevation: the front leaf to the left of the column, its butt
    # edge at -r - gap; the temple leaf to the right, opened flat, its butt
    # edge at r + gap (x runs away from the column on each side)
    fx0 = -r - gap
    fl_ring = [(fx0 - (front_leaf.reach - x), y) for x, y in front_leaf.ring]
    tx0 = r + gap
    tl_ring = [(tx0 + (temple_leaf.reach - x), y) for x, y in temple_leaf.ring]
    vis.append(fl_ring)
    vis.append(tl_ring)
    fl = (min(p[0] for p in fl_ring), fx0)
    tl = (tx0, max(p[0] for p in tl_ring))
    # the knuckles, alternating front / temple from the top; the front's are
    # drawn joined to its leaf by a bar, the temple's to its
    n = max(int(s.barrels), 1)
    kh = W / n
    for i in range(n):
        y1, y0 = half - i * kh, half - (i + 1) * kh
        vis.append([(-r, y0), (r, y0), (r, y1), (-r, y1)])
        if i % 2 == 0:              # the front's knuckle: a bar to the front leaf
            vis.append([(fl[1], y0 + 0.15 * kh), (-r, y0 + 0.15 * kh),
                        (-r, y1 - 0.15 * kh), (fl[1], y1 - 0.15 * kh)])
        else:
            vis.append([(r, y0 + 0.15 * kh), (tl[0], y0 + 0.15 * kh),
                        (tl[0], y1 - 0.15 * kh), (r, y1 - 0.15 * kh)])
    cen.append([(0.0, -half - 2.0), (0.0, half + 2.0)])
    # the screw head on top of the column
    hr = 0.5 * s.screw_head_mm
    vis.append(_circle(0.0, half + hr + 0.4, hr))
    # the installation, on each leaf's own shape
    leaves = ((fl_ring, fl), (tl_ring, tl))
    if fill.kind == HingeKind.RIVET:
        n_r, rr = s.rivet_count, 0.5 * s.rivet_diameter_mm
        for ring, leaf in leaves:
            ys = [p[1] for p in ring]
            y_lo, y_hi = min(ys), max(ys)
            cx = 0.5 * (leaf[0] + leaf[1])
            for k in range(n_r):
                cy = y_lo + (k + 1) * (y_hi - y_lo) / (n_r + 1)
                vis.append(_circle(cx, cy, rr, 16))
    elif fill.kind == HingeKind.HEAT_SET:
        # cleats: teeth along the leaf's long edges, hidden in the acetate,
        # on the leaf's own edge at each height (a rounded end narrows)
        for ring, leaf in leaves:
            ys = [p[1] for p in ring]
            y_lo, y_hi = min(ys), max(ys)
            shape = Polygon(ring)
            if not shape.is_valid:
                shape = shape.buffer(0)
            tooth = 0.6
            y = y_lo + 1.0
            while y < y_hi - 0.5:
                cut = shape.intersection(LineString([(leaf[0] - 1.0, y + 0.5),
                                                     (leaf[1] + 1.0, y + 0.5)]))
                if cut.is_empty:
                    y += 2.0
                    continue
                bx0, _b1, bx1, _b3 = cut.bounds
                for x, sign in ((bx0, 1.0), (bx1, -1.0)):
                    hid.append([(x, y), (x + sign * tooth, y + 0.5), (x, y + 1.0)])
                y += 2.0
    else:
        # the spring box on the temple leaf, past the leaf
        bl, bd = s.spring_box_length_mm, s.spring_box_depth_mm
        vis.append([(tl[1], -bd), (tl[1] + bl, -bd), (tl[1] + bl, bd), (tl[1], bd)])
        labels.append((tl[1] + 0.5 * bl, bd + 1.5, "spring box"))
    top = max(half + 2 * hr + 1.4, max(p[1] for p in fl_ring + tl_ring) + 1.6)
    labels.append((0.5 * (fl[0] + fl[1]), top, "front"))
    labels.append((0.5 * (tl[0] + tl[1]), top, "temple"))
    elevation = {"visible": vis, "hidden": hid, "center": cen, "labels": labels}
    # --- plan, from above at the stop: x runs along the front toward the
    # end face, y toward the wearer; the barrel axis at the origin
    vis, hid, cen, labels = [], [], [], []
    t_f, t_t = front_leaf.part_thickness_mm, temple_leaf.part_thickness_mm
    d_f, d_t = front_leaf.depth_mm, temple_leaf.depth_mm
    off = float(axis_offset_mm if axis_offset_mm is not None else s.axis_offset_mm)
    # the end face: the axis is a temple's thickness (and the inset) inside it
    inset = float(axis_inset_mm) if axis_inset_mm is not None else t_t + off
    f_len = front_leaf.length
    f_near = inset - front_leaf.setback_mm          # the pocket's edge nearest the end face
    x_left = f_near - f_len - 4.0
    back = -off                                     # the back face's y
    vis.append(_circle(0.0, 0.0, r))
    # the endpiece's section, open toward the frame's center
    vis.append([(x_left, back), (inset, back), (inset, back - t_f), (x_left, back - t_f)])
    # its pocket, sunk from the back face
    vis.append([(f_near - f_len, back), (f_near, back), (f_near, back - d_f),
                (f_near - f_len, back - d_f)])
    # the temple's section at the stop: the butt face through the axis,
    # the inner face `off` from it, the outer face a thickness beyond
    theta = math.radians(float(s.open_deg) - 90.0)
    d = (math.sin(theta), math.cos(theta))          # along the temple
    nrm = (math.cos(theta), -math.sin(theta))       # across it, toward the outer face

    def at(along: float, across: float) -> tuple[float, float]:
        return (d[0] * along + nrm[0] * across, d[1] * along + nrm[1] * across)

    t_len = temple_leaf.length
    butt = float(s.axis_setback_mm)                 # the butt beyond the axis
    s0 = butt + temple_leaf.setback_mm              # the pocket's near edge
    reach = s0 + t_len + 4.0
    endpiece = Polygon([(x_left - 1.0, back + 1e-6), (inset, back + 1e-6),
                        (inset, back - t_f - 1.0), (x_left - 1.0, back - t_f - 1.0)])

    def outside(ring):
        """The part of a section the endpiece does not occupy."""
        shape = Polygon(ring)
        try:
            left = shape.difference(endpiece)
        except Exception:                                   # noqa: BLE001
            return ring
        if left.is_empty:
            return None
        piece = max(getattr(left, "geoms", [left]), key=lambda g: g.area)
        return [(float(x), float(y)) for x, y in piece.exterior.coords[:-1]]

    for ring in ([at(butt, off), at(reach, off), at(reach, off + t_t), at(butt, off + t_t)],
                 [at(s0, off), at(s0 + t_len, off), at(s0 + t_len, off + d_t), at(s0, off + d_t)]):
        kept = outside(ring)
        if kept:
            vis.append(kept)
    cen.append([(x_left - 2.0, 0.0), (inset + 2.0, 0.0)])
    cen.append([at(-2.0, 0.0), at(reach + 2.0, 0.0)])
    labels.append((0.5 * (x_left + f_near - f_len), back - t_f - 3.2, "front"))
    lx, ly = at(reach + 1.0, 0.5 * (off + t_t))
    labels.append((lx + 2.0 * d[0], ly + 2.0 * d[1], "temple"))
    ax, ay = at(0.6 * reach, 0.0)
    labels.append((ax - 3.0 * nrm[0] - 1.5, ay - 3.0 * nrm[1], f"{s.open_deg:g}°"))
    plan = {"visible": vis, "hidden": hid, "center": cen, "labels": labels}
    return {"elevation": elevation, "plan": plan}
