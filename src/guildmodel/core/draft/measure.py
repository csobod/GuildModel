"""The dimensions of the assembled, formed frame (2.3; research section
6.5): what the blueprint's views carry, each with its status, as factory
tech packs mark them.

* **LOCKED**: as cut from the drawing; the flat part fixes it.
* **TARGET**: what the forming or the bench is set to.
* **OPEN**: a result the bench may move (a temple spread).
* **REF**: for reference; not a dimension to hold.

The lens is measured in its plane, where ISO 8624 measures, at the groove
line (`LensGrooveParams.anterior_offset_mm` behind the anterior face), and
head-on beside it, as GuildDraw's Formed Measurements do.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .assembly import DraftAssembly, _local_frame, _ring_xy

__all__ = ["Dimension", "DraftMeasures", "measure"]

LOCKED, TARGET, OPEN, REF = "LOCKED", "TARGET", "OPEN", "REF"
STATUS_TAG = {LOCKED: "L", TARGET: "T", OPEN: "O", REF: "ref"}


@dataclass
class Dimension:
    key: str
    label: str
    value: float | None
    unit: str = "mm"
    status: str = LOCKED
    view: str = "front"
    text: str = ""              # the value as written; "" = formatted from value
    note: str = ""              # a second line (the head-on value, the hinge's own)

    @property
    def shown(self) -> str:
        if self.text:
            return self.text
        if self.value is None:
            return "—"
        if self.unit == "°":
            return f"{self.value:.1f}°"
        if self.unit == "mm":
            return f"{self.value:.1f}"
        return f"{self.value:g}{self.unit}"

    @property
    def tagged(self) -> str:
        return f"{self.shown} [{STATUS_TAG[self.status]}]"


@dataclass
class DraftMeasures:
    dims: list = field(default_factory=list)
    marking: str = ""
    lens_boxes: dict = field(default_factory=dict)   # lateral -> (u0, v0, u1, v1) lens-plane box
    head_on_boxes: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)

    def get(self, key: str) -> Dimension | None:
        for d in self.dims:
            if d.key == key:
                return d
        return None

    def for_view(self, view: str) -> list:
        return [d for d in self.dims if d.view == view]


def _lens_plane_box(asm: DraftAssembly, lens, depth_mm: float):
    """The formed lens projected onto its own plane (tangent at the lens
    center at the groove depth): (u0, v0, u1, v1) and the head-on box."""
    ring = _ring_xy(lens)
    c = lens.centroid
    P = asm.form(np.column_stack([ring, np.full(len(ring), depth_mm)]))
    C = asm.form(np.array([[float(c.x), float(c.y), depth_mm]]))[0]
    e_x, e_y, _n = _local_frame(asm.form, np.array([float(c.x), float(c.y), depth_mm]))
    u = (P - C) @ e_x
    v = (P - C) @ e_y
    plane = (float(u.min()), float(v.min()), float(u.max()), float(v.max()))
    head_on = (float(P[:, 0].min()), float(P[:, 1].min()),
               float(P[:, 0].max()), float(P[:, 1].max()))
    return plane, head_on


def _vertical_span_at(outline, x: float) -> float | None:
    """The outline's vertical extent on the line x = const (the bridge's
    width, measured as the trade does, top to the nose cut)."""
    from shapely.geometry import LineString
    if outline is None or outline.is_empty:
        return None
    b = outline.bounds
    line = LineString([(x, b[1] - 1.0), (x, b[3] + 1.0)])
    cut = line.intersection(outline)
    if cut.is_empty:
        return None
    return float(cut.length)


def _x_at_depth(core, z: float):
    """Where a temple's placed core crosses the plane z = const, by x; None
    when it never does."""
    if core is None or len(core) < 2:
        return None
    zs = core[:, 2]
    for i in range(len(core) - 1):
        z0, z1 = zs[i], zs[i + 1]
        if (z0 - z) * (z1 - z) <= 0 and z1 != z0:
            t = (z - z0) / (z1 - z0)
            return float(core[i, 0] + t * (core[i + 1, 0] - core[i, 0]))
    return None


def _ray_gap(outline, start, direction, reach: float = 40.0) -> float | None:
    """How far a ray from `start` runs inside the outline before leaving it
    (the rim's width at that point), or None when it starts outside."""
    from shapely.geometry import LineString, Point
    if outline is None or outline.is_empty or not outline.contains(Point(start)):
        return None
    ux, uy = direction
    ray = LineString([start, (start[0] + ux * reach, start[1] + uy * reach)])
    hit = ray.intersection(outline.boundary)
    if hit.is_empty:
        return None
    pts = []
    for g in getattr(hit, "geoms", [hit]):
        pts.extend(list(g.coords) if g.geom_type != "Point" else [(g.x, g.y)])
    d = [(p[0] - start[0]) * ux + (p[1] - start[1]) * uy for p in pts]
    d = [v for v in d if v > 1e-6]
    return float(min(d)) if d else None


def rim_widths(outline, lens) -> dict:
    """The rim's width around one lens, flat: at the lens box's top,
    bottom, temporal and nasal extremes, cast outward (`top`, `bottom`,
    `outer`, `inner`); the temporal one is the endpiece's width at the
    lens's center height. Missing where the ray starts outside the body."""
    if outline is None or lens is None or lens.is_empty:
        return {}
    x0, y0, x1, y1 = lens.bounds
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    lateral = 1.0 if cx >= 0 else -1.0
    probes = {
        "top": ((cx, y1 + 0.05), (0.0, 1.0)),
        "bottom": ((cx, y0 - 0.05), (0.0, -1.0)),
        "outer": ((cx + lateral * (0.5 * (x1 - x0) + 0.05), cy), (lateral, 0.0)),
        "inner": ((cx - lateral * (0.5 * (x1 - x0) + 0.05), cy), (-lateral, 0.0)),
    }
    out = {}
    for key, (start, direction) in probes.items():
        v = _ray_gap(outline, start, direction)
        if v is not None:
            out[key] = v + 0.05
    return out


def temple_heights(placement) -> tuple[float | None, float | None]:
    """The flat temple's height (across) near the butt and near the tip, mm."""
    if placement is None or len(placement.outline_norm) < 3:
        return None, None
    from shapely.geometry import LineString, Polygon
    Q = placement.outline_norm
    L = placement.bend.overall_mm
    poly = Polygon([(float(x), float(y)) for x, y in Q])
    if not poly.is_valid:
        poly = poly.buffer(0)
    lo, hi = float(Q[:, 1].min()) - 1.0, float(Q[:, 1].max()) + 1.0

    def height_at(s_mm):
        cut = LineString([(s_mm, lo), (s_mm, hi)]).intersection(poly)
        return float(cut.length) if not cut.is_empty else None

    return height_at(3.0), height_at(L - 3.0)


def measure(asm: DraftAssembly) -> DraftMeasures:
    out = DraftMeasures()
    f, fm = asm.front, asm.forming
    castle = f.castle
    depth = float(getattr(getattr(castle, "lens_groove", None), "anterior_offset_mm", 1.5) or 1.5)
    dims = out.dims

    def add(key, label, value, unit="mm", status=LOCKED, view="front", text="", note=""):
        d = Dimension(key, label, value, unit, status, view, text, note)
        dims.append(d)
        out.values[key] = value
        return d

    # ---- the front view
    a_plane, b_plane, a_head = [], [], []
    for lateral, lens in ((1.0, f.lens_od), (-1.0, f.lens_os)):
        if lens is None or lens.is_empty:
            continue
        plane, head = _lens_plane_box(asm, lens, depth)
        out.lens_boxes[lateral] = plane
        out.head_on_boxes[lateral] = head
        a_plane.append(plane[2] - plane[0])
        b_plane.append(plane[3] - plane[1])
        a_head.append(head[2] - head[0])
    if a_plane:
        A = float(np.mean(a_plane))
        add("a", "A, lens plane", A, status=LOCKED,
            note=f"head-on {np.mean(a_head):.1f}")
        add("b", "B, lens plane", float(np.mean(b_plane)), status=LOCKED)
    if len(out.head_on_boxes) == 2:
        r, l = out.head_on_boxes[1.0], out.head_on_boxes[-1.0]
        # OD sits on +x in this frame; its nasal edge is its min x
        dbl = float(r[0] - l[2])
        add("dbl", "DBL", dbl, status=LOCKED)
        add("bcd", "Boxed-center distance",
            float(0.5 * (r[0] + r[2]) - 0.5 * (l[0] + l[2])), status=LOCKED)
    if asm.outline_rings:
        xs = np.concatenate([r[:, 0] for r in asm.outline_rings])
        ys = np.concatenate([r[:, 1] for r in asm.outline_rings])
        add("front_width", "Total front width", float(xs.max() - xs.min()), status=LOCKED)
        out.values["front_height"] = float(ys.max() - ys.min())
    R, L = asm.right, asm.left
    if R is not None and L is not None:
        add("frontal_width", "Frontal width, dowel to dowel",
            float(R.axis_point[0] - L.axis_point[0]), status=LOCKED)
        add("joint_height", "Joint height", float(0.5 * (R.joint_height_mm + L.joint_height_mm)),
            status=LOCKED)
    bw = _vertical_span_at(f.outline, float(fm.bridge_offset_mm))
    if bw is not None:
        add("bridge_width", "Bridge width", bw, status=LOCKED)
    cons = (f.guides or {}).get("construction") or {}
    if "crest_height_mm" in cons:
        add("crest_height", "Crest height", float(cons["crest_height_mm"]), status=REF)
    if fm.apical_radius_mm > 0.0:
        add("apical_radius", "Apical radius", float(fm.apical_radius_mm), status=REF,
            text=f"R{fm.apical_radius_mm:.1f}")

    # ---- the top view
    per_side = 0.5 * float(fm.face_form_wrap_deg)
    add("face_form", "Face form", per_side, unit="°", status=TARGET, view="top",
        text=f"{per_side:.1f}° per side ({180.0 - fm.face_form_wrap_deg:.1f}° included)")
    if fm.base_curve > 0.0:
        add("base_curve", "Base curve", float(fm.base_curve), unit="D", status=TARGET, view="top",
            text=f"{fm.base_curve:.2f} D, R {fm.base_radius_mm:.0f} (die radius)"
            if fm.press_preset else
            f"{fm.base_curve:.2f} D, R {fm.base_radius_mm:.0f} ({fm.base_radius_mm * fm.base_curve:.0f} / D)")
    else:
        add("base_curve", "Base curve", 0.0, unit="D", status=TARGET, view="top", text="flat")
    add("projection", "Bridge projection", float(fm.bridge_projection_mm), status=TARGET, view="top")
    for s in asm.ordered_sides():
        add(f"splay_{s.label}", f"Splay {s.label}", s.splay_target_deg, unit="°",
            status=TARGET, view="top", note=f"hinge alone {s.splay_from_hinge_deg:.1f}°; "
            f"butt cut {s.splay_cut_deg:.1f}°")
    if R is not None and L is not None and R.temple is not None and L.temple is not None:
        t = 0.5 * (R.temple.thickness_mm + L.temple.thickness_mm)
        add("tip_spread", "Tip spread, inner faces",
            float(R.temple.tip[0] - L.temple.tip[0]) - t, status=OPEN, view="top")
        add("front_to_bend", "Front to bend",
            float(0.5 * (R.temple.ear_point[2] + L.temple.ear_point[2])), status=REF, view="top")
        add("temple_thickness", "Temple thickness", t, status=LOCKED, view="top")
        tb = R.temple.bend
        add("inward_angle", "Inward angle of drop", R.temple.bend3d.inward_angle_deg,
            unit="°", status=TARGET, view="top")
    if zones_thick := getattr(getattr(castle, "zones", None), "endpiece_mm", None):
        add("front_thickness", "Front thickness at the endpiece", float(zones_thick),
            status=LOCKED, view="top")
    rims = rim_widths(f.outline, f.lens_od)
    for key, label in (("top", "Rim width, top"), ("bottom", "Rim width, bottom"),
                       ("outer", "Endpiece width at the lens center"),
                       ("inner", "Rim width, nasal")):
        if key in rims:
            add(f"rim_{key}", label, rims[key], status=LOCKED)

    # ---- the side view
    for s in asm.ordered_sides():
        add(f"side_{s.label}", f"Angle of side {s.label}", s.side_target_deg, unit="°",
            status=TARGET, view="side", note=f"hinge alone {s.side_from_hinge_deg:.1f}°; "
            f"butt cut {s.panto_cut_deg:.1f}°")
    if R is not None:
        add("as_worn", "Pantoscopic angle, as worn", R.side_target_deg, unit="°",
            status=TARGET, view="side")
    tb = None
    for s in asm.ordered_sides():
        if s.temple is not None:
            tb = s.temple.bend
            break
    if tb is not None:
        side = next(s_ for s_ in asm.ordered_sides() if s_.temple is not None)
        h_butt, h_tip = temple_heights(side.temple)
        if h_butt is not None:
            add("temple_height_butt", "Temple height at the butt", h_butt, status=LOCKED, view="side")
        if h_tip is not None:
            add("temple_height_tip", "Temple height at the tip", h_tip, status=LOCKED, view="side")
        add("length_to_bend", "Length to bend", tb.length_to_bend_mm, status=TARGET, view="side")
        add("drop", "Drop", tb.drop_mm, status=TARGET, view="side")
        add("overall", "Overall length, straightened", tb.overall_mm, status=LOCKED, view="side")
        add("drop_angle", "Downward angle of drop", tb.drop_angle_deg, unit="°",
            status=TARGET, view="side")
        add("bend_radius", "Bend radius", tb.bend_radius_mm, status=TARGET, view="side",
            text=f"R{tb.bend_radius_mm:.0f}")

    # ---- the marking
    a = out.values.get("a")
    dbl = out.values.get("dbl")
    overall = out.values.get("overall")
    if a is not None and dbl is not None:
        out.marking = f"{a:.0f}□{dbl:.0f}" + (f"-{overall:.0f}" if overall else "")
    return out
