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

__all__ = ["HingeFill", "PocketFit", "fill_hinge", "fit_pocket", "hinge_detail",
           "knuckle_split", "screw_length"]


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
                     datum=datum, setback_mm=setback, found=found)


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
    """The hinge for a pocket pair. W is the front pocket's long side, less
    0.2 mm of clearance; the temple's pocket, when drawn, says its plate."""
    width = (front.along_axis_mm if front is not None
             else temple.along_axis_mm if temple is not None else 10.0)
    width = max(width - 0.2, 1.0)
    plate = front.across_mm if front is not None else 4.0
    t_plate = temple.across_mm if temple is not None else plate
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


def hinge_detail(fill: HingeFill) -> dict:
    """The reference-only detail, two schematic views in mm, y up, the
    barrel axis at x = 0: ``elevation`` (seen from behind the front: the
    front leaf to the left of the barrel column, the temple leaf to the
    right, the knuckles stacked along the axis) and ``plan`` (seen from
    above: the front leaf lying across, the barrel's circle, the temple leaf
    swung to the stop). Each is ``{"visible": [rings], "hidden": [rings],
    "center": [polylines], "labels": [(x, y, text)]}``."""
    s = fill.spec
    W, r = fill.width_mm, 0.5 * s.barrel_diameter_mm
    plate, tplate = fill.plate_length_mm, fill.temple_plate_length_mm
    gap = 0.3                       # between the barrel column and each leaf
    vis, hid, cen, labels = [], [], [], []
    # --- elevation
    half = 0.5 * W
    # the front leaf, left of the column; the temple leaf, right of it
    fl = (-r - gap - plate, -r - gap)
    tl = (r + gap, r + gap + tplate)
    vis.append([(fl[0], -half), (fl[1], -half), (fl[1], half), (fl[0], half)])
    vis.append([(tl[0], -half), (tl[1], -half), (tl[1], half), (tl[0], half)])
    # the knuckles, alternating front / temple from the top; the front's are
    # drawn joined to its leaf by a bar, the temple's to its
    n = s.barrels
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
    # the installation
    if fill.kind == HingeKind.RIVET:
        n_r, rr = s.rivet_count, 0.5 * s.rivet_diameter_mm
        for leaf in (fl, tl):
            cx = 0.5 * (leaf[0] + leaf[1])
            for k in range(n_r):
                cy = -half + (k + 1) * W / (n_r + 1)
                vis.append(_circle(cx, cy, rr, 16))
    elif fill.kind == HingeKind.HEAT_SET:
        # cleats: teeth along the leaf's long edges, hidden in the acetate
        for leaf in (fl, tl):
            for x in leaf:
                sign = -1.0 if x < 0 else 1.0
                tooth = 0.6
                k = 0
                y = -half + 1.0
                while y < half - 0.5:
                    hid.append([(x, y), (x + sign * tooth, y + 0.5), (x, y + 1.0)])
                    y += 2.0
                    k += 1
    else:
        # the spring box on the temple leaf, past the leaf
        bl, bd = s.spring_box_length_mm, s.spring_box_depth_mm
        vis.append([(tl[1], -0.5 * bd * 2.0), (tl[1] + bl, -0.5 * bd * 2.0),
                    (tl[1] + bl, 0.5 * bd * 2.0), (tl[1], 0.5 * bd * 2.0)])
        labels.append((tl[1] + 0.5 * bl, 0.5 * bd * 2.0 + 1.5, "spring box"))
    labels.append((0.5 * (fl[0] + fl[1]), half + 2 * hr + 1.4, "front"))
    labels.append((0.5 * (tl[0] + tl[1]), half + 2 * hr + 1.4, "temple"))
    elevation = {"visible": vis, "hidden": hid, "center": cen, "labels": labels}
    # --- plan: the front leaf lies along -x from the barrel, the temple leaf
    # swings to the stop (the open angle from the front leaf's line)
    vis, hid, cen, labels = [], [], [], []
    t_f, t_t = fill.plate_thickness_mm, fill.temple_plate_thickness_mm
    vis.append(_circle(0.0, 0.0, r))
    vis.append([(-r - gap - plate, -0.5 * t_f), (-r - gap, -0.5 * t_f),
                (-r - gap, 0.5 * t_f), (-r - gap - plate, 0.5 * t_f)])
    a = math.radians(180.0 - s.open_deg)   # the temple leaf's direction from +x
    ca, sa = math.cos(a), math.sin(a)
    x0 = r + gap
    corners = [(x0, -0.5 * t_t), (x0 + tplate, -0.5 * t_t),
               (x0 + tplate, 0.5 * t_t), (x0, 0.5 * t_t)]
    vis.append([(x * ca - y * sa, x * sa + y * ca) for x, y in corners])
    cen.append([(-r - gap - plate - 2.0, 0.0), (r + 2.0, 0.0)])
    reach = x0 + tplate + 2.0
    cen.append([(0.0, 0.0), (reach * ca, reach * sa)])
    labels.append((0.5 * reach * ca + 1.5, 0.5 * reach * sa + 1.5, f"{s.open_deg:g}°"))
    plan = {"visible": vis, "hidden": hid, "center": cen, "labels": labels}
    return {"elevation": elevation, "plan": plan}
