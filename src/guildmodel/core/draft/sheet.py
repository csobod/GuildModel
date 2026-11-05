"""The blueprint's sheets, composed from the assembly's curves (2.3;
research section 6.5), Qt-free: a sheet is strokes, fills and texts in
page millimeters (y down, the page's top-left at the origin) plus the views
placed on it, each a set of the same primitives in view millimeters (y up)
at a scale. `gui.draft_render` paints a sheet on any QPainter and
`dxf_out` writes it for the factory's CAD; both walk the same model, so the
PDF and the DXF say the same thing.

Sheet 1 is the dimensioned assembly after forming: the plan, the front and
the side view stacked down the page in third-angle projection by default
(first on request), the hinge detail (reference only), the notes with the
tolerance table and the checks, and the ISO 7200 title block. Sheet 2 is
the 1:1 alignment template: the plan of the open frame with the tip
targets, and the tip-bend profile.

Each view is an edge rendering of the formed solid with hidden lines
removed (`hidden.py`, a depth buffer of the scene; the maker's reading of
the trade's sheets reversed research Q9b): the built front's creases and
its silhouette for the view's direction, the temples' rings, the pockets
dashed where hidden. Without a built front the views fall back to the
drawing's curves. A dimension's value sits in a break in its line or above
it (`set_lettering`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from guildmodel.core.project.schema import STANDARD_SCALES, BlueprintSettings

from .assembly import DraftAssembly, folded_basis, front_silhouette, rotation
from .hinges import hinge_detail
from .measure import DraftMeasures

__all__ = ["Fill", "Placed", "Sheet", "Stroke", "Text", "View", "compose_sheets",
           "page_size", "projection_symbol", "set_lettering"]

MARGIN_MM = 10.0
TITLE_H_MM = 28.0
GAP_MM = 8.0
RULER_STRIP_MM = 14.0
#: Text sizes, the font's em height in mm.
DIM_TEXT = 2.6
LABEL_TEXT = 3.4
SMALL_TEXT = 2.2
TITLE_TEXT = 5.0
#: An average glyph's advance as a fraction of the em, for the layout's
#: estimate of a text's width; `compose_sheets` sets it from the settings,
#: where the window has measured the chosen font.
_GLYPH_W = 0.52
#: Where a dimension's value sits: "inline", in a break in the dimension
#: line (ASME Y14.5), or "above" it (ISO 129). Set with the glyph width.
_DIM_TEXT = "inline"


def set_lettering(text_width_em: float = 0.52, dim_text: str = "inline") -> None:
    """The lettering the sheets are composed with, from the blueprint's
    settings: the font's average glyph advance (a fraction of the em) and
    the dimension-text practice."""
    global _GLYPH_W, _DIM_TEXT
    _GLYPH_W = min(max(float(text_width_em), 0.3), 0.9)
    _DIM_TEXT = "above" if dim_text == "above" else "inline"


# ------------------------------------------------------------------ the model

@dataclass
class Stroke:
    pts: list
    style: str = "visible"        # visible | hidden | center | thin | dim | border | heavy
    closed: bool = False


@dataclass
class Fill:
    pts: list
    style: str = "ink"


@dataclass
class Text:
    x: float
    y: float
    text: str
    size: float = DIM_TEXT
    align: str = "left"           # left | center | right
    valign: str = "baseline"      # baseline | top | middle
    angle: float = 0.0            # degrees, CCW in view coordinates
    style: str = "normal"         # normal | bold | muted | warning

    @property
    def width_mm(self) -> float:
        return _GLYPH_W * self.size * len(self.text)


def _text_box(t: Text) -> tuple[float, float, float, float]:
    w, h = t.width_mm, t.size
    if t.align == "center":
        x0 = t.x - 0.5 * w
    elif t.align == "right":
        x0 = t.x - w
    else:
        x0 = t.x
    if t.valign == "top":
        y1 = t.y
    elif t.valign == "middle":
        y1 = t.y + 0.5 * h
    else:
        y1 = t.y + 0.75 * h
    y0 = y1 - h
    if abs(t.angle) > 1e-9:
        # the rotated box's extent, about the anchor
        c, s = math.cos(math.radians(t.angle)), math.sin(math.radians(t.angle))
        corners = [(x0, y0), (x0 + w, y0), (x0 + w, y1), (x0, y1)]
        rot = [((x - t.x) * c - (y - t.y) * s + t.x, (x - t.x) * s + (y - t.y) * c + t.y)
               for x, y in corners]
        xs, ys = [p[0] for p in rot], [p[1] for p in rot]
        return min(xs), min(ys), max(xs), max(ys)
    return x0, y0, x0 + w, y1


@dataclass
class View:
    key: str
    title: str
    strokes: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    scale_note: str = ""

    def add(self, pts, style: str = "visible", closed: bool = False) -> None:
        pts = [(float(x), float(y)) for x, y in np.asarray(pts, dtype=np.float64)[:, :2]] \
            if len(pts) else []
        if len(pts) >= 2:
            self.strokes.append(Stroke(pts, style, closed))

    def text(self, x, y, s, size=DIM_TEXT, align="left", valign="baseline",
             angle=0.0, style="normal") -> Text:
        t = Text(float(x), float(y), str(s), size, align, valign, float(angle), style)
        self.texts.append(t)
        return t

    def bbox(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for s in self.strokes:
            xs.extend(p[0] for p in s.pts)
            ys.extend(p[1] for p in s.pts)
        for f in self.fills:
            xs.extend(p[0] for p in f.pts)
            ys.extend(p[1] for p in f.pts)
        for t in self.texts:
            x0, y0, x1, y1 = _text_box(t)
            xs.extend((x0, x1))
            ys.extend((y0, y1))
        if not xs:
            return 0.0, 0.0, 1.0, 1.0
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def is_empty(self) -> bool:
        return not (self.strokes or self.fills or self.texts)


@dataclass
class Placed:
    """A view on a page: its bbox's top-left lands at (x, y) page mm."""
    view: View
    x: float
    y: float
    scale: float
    bbox: tuple = (0.0, 0.0, 1.0, 1.0)

    def to_page(self, vx: float, vy: float) -> tuple[float, float]:
        x0, _y0, _x1, y1 = self.bbox
        return self.x + (vx - x0) * self.scale, self.y + (y1 - vy) * self.scale

    @property
    def width(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * self.scale

    @property
    def height(self) -> float:
        return (self.bbox[3] - self.bbox[1]) * self.scale


@dataclass
class Sheet:
    width: float
    height: float
    number: int = 1
    count: int = 1
    title: str = ""
    placed: list = field(default_factory=list)
    strokes: list = field(default_factory=list)      # page mm, y down
    fills: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    clipped: bool = False                            # a 1:1 piece larger than the page
    scale: float = 1.0

    def line(self, x0, y0, x1, y1, style="thin") -> None:
        self.strokes.append(Stroke([(x0, y0), (x1, y1)], style))

    def rect(self, x0, y0, x1, y1, style="thin") -> None:
        self.strokes.append(Stroke([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], style, closed=True))

    def text(self, x, y, s, size=DIM_TEXT, align="left", valign="top", style="normal") -> Text:
        t = Text(float(x), float(y), str(s), size, align, valign, 0.0, style)
        self.texts.append(t)
        return t

    def place(self, view: View, x: float, y: float, scale: float) -> Placed:
        p = Placed(view, float(x), float(y), float(scale), view.bbox())
        self.placed.append(p)
        return p


def page_size(settings: BlueprintSettings, landscape: bool) -> tuple[float, float]:
    w, h = settings.page_size_mm()
    return (h, w) if landscape else (w, h)


# ------------------------------------------------------------------ dimensions

_ARROW_L, _ARROW_W = 2.4, 0.8


def _arrow(view: View, tip, direction, k: float = 1.0) -> None:
    """A filled arrowhead at `tip`, pointing along `direction`; `k` is the
    view's scale (paper mm per view mm), so the head is the same size on
    paper whatever the scale."""
    tx, ty = tip
    dx, dy = direction
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    al, aw = _ARROW_L / k, _ARROW_W / k
    base = (tx - dx * al, ty - dy * al)
    view.fills.append(Fill([(tx, ty), (base[0] + px * aw, base[1] + py * aw),
                            (base[0] - px * aw, base[1] - py * aw)]))


def linear_dim(view: View, p1, p2, offset: float, label: str, *, along=None,
               k: float = 1.0, ext_gap: float = 1.0, outside: str = "end") -> None:
    """An aligned linear dimension between p1 and p2, its line `offset` view
    mm to the left of p1->p2 (negative: to the right). `along`, when given,
    measures the projection on that direction instead (a horizontal
    dimension between two points at different heights). Everything sized
    for the paper (the text, the arrows, the overshoots) is divided by `k`.

    The value sits in a break in the line or above it (`set_lettering`);
    a value the dimension is too short for goes outside the extension
    lines, past the reading end (`outside="end"`: the right, or the top)
    or before the reading start (`"start"`), whichever the caller knows is
    clear."""
    p1, p2 = np.asarray(p1, dtype=np.float64), np.asarray(p2, dtype=np.float64)
    if along is None:
        d = p2 - p1
    else:
        d = np.asarray(along, dtype=np.float64)
    L = float(np.hypot(*d))
    if L < 1e-9:
        return
    u = d / L
    n = np.array([-u[1], u[0]])
    base = p1 + n * offset
    a = base
    b = base + u * float((p2 - p1) @ u)
    span = float((p2 - p1) @ u)
    if span < 0:
        # p2 lies before p1 along the direction: swap the points and their
        # feet, keeping u and n (the line's direction is the direction)
        p1, p2, a, b, span = p2, p1, b, a, -span
    # extension lines, from each point toward its dimension point, past it
    for p, q in ((p1, a), (p2, b)):
        gap = np.asarray(q) - np.asarray(p)
        g = float(np.hypot(*gap))
        if g > 1e-9:
            gu = gap / g
            start = np.asarray(p) + gu * min(ext_gap / k, 0.5 * g)
            end = np.asarray(q) + gu * (1.5 / k)
            view.add([start, end], "dim")
    al = _ARROW_L / k
    size = DIM_TEXT / k
    text_w = _GLYPH_W * size * len(label)
    pad = 1.0 / k                      # clear paper on each side of an inline value
    mid = 0.5 * (a + b)
    ang = math.degrees(math.atan2(u[1], u[0]))
    # read from the bottom or from the right
    flipped = ang > 90.0 or ang <= -90.0
    if flipped:
        ang += 180.0
    n_text = -n if flipped else n
    u_text = -u if flipped else u      # the reading direction along the line
    inline = _DIM_TEXT == "inline"
    arrows_in = span >= 2.6 * al
    # the value fits between the extension lines when the line can hold the
    # arrows and the value (inline) or the value alone (above)
    fits = (span >= text_w + 2.0 * pad + 2.0 * al) if inline else (span >= text_w + 2.0 * pad)
    if not arrows_in:
        fits = False
    if arrows_in:
        _arrow(view, a, -u, k)
        _arrow(view, b, u, k)
    else:
        _arrow(view, a, u, k)
        _arrow(view, b, -u, k)
        view.add([a - u * (al + 1.0 / k), a], "dim")
        view.add([b, b + u * (al + 1.0 / k)], "dim")
    if fits and inline:
        # the line broken for the value, centered in the break
        half = 0.5 * text_w + pad
        view.add([a, mid - u * half], "dim")
        view.add([mid + u * half, b], "dim")
        view.text(mid[0], mid[1], label, size, align="center", valign="middle", angle=ang)
        return
    view.add([a, b], "dim")
    if fits:
        # above the line, parallel, clear of it (ISO 129)
        tx, ty = mid + n_text * (0.7 / k)
        view.text(tx, ty, label, size, align="center", valign="baseline", angle=ang)
        return
    # too short for the value: it goes outside, past the reading end (or
    # before the start), on the line's extension (inline) or above it (ISO)
    tail = al + 1.0 / k if not arrows_in else 0.0
    if outside == "start":
        end = a if not flipped else b
        far = end - u_text * (tail + pad)              # the value's near edge
        line_end = far - u_text * (text_w + pad)
        anchor, align = far, "right"
    else:
        end = b if not flipped else a
        far = end + u_text * (tail + pad)
        line_end = far + u_text * (text_w + pad)
        anchor, align = far, "left"
    if inline:
        view.text(anchor[0], anchor[1], label, size, align=align, valign="middle", angle=ang)
    else:
        view.add([end + u_text * (tail if outside != "start" else -tail), line_end], "dim")
        tx, ty = anchor + n_text * (0.7 / k)
        view.text(tx, ty, label, size, align=align, valign="baseline", angle=ang)


def angular_dim(view: View, center, radius: float, a0_deg: float, a1_deg: float,
                label: str, *, k: float = 1.0, label_radius: float | None = None,
                legs: bool = True, label_angle: float | None = None) -> None:
    """An angle at `center` between the rays at a0 and a1 (degrees, CCW),
    drawn as an arc with arrowheads, the two rays as thin legs. `radius`
    and `label_radius` are view mm."""
    cx, cy = float(center[0]), float(center[1])
    if a1_deg < a0_deg:
        a0_deg, a1_deg = a1_deg, a0_deg
    size = DIM_TEXT / k
    text_w = _GLYPH_W * size * len(label)
    la = label_angle if label_angle is not None else 0.5 * (a0_deg + a1_deg)
    lr = label_radius if label_radius is not None else radius + 2.0 / k
    r0, r1 = math.radians(a0_deg), math.radians(a1_deg)
    al = _ARROW_L / k

    def _arc(d0, d1):
        n = max(int(abs(d1 - d0) / 4.0) + 2, 4)
        angs = np.radians(np.linspace(d0, d1, n))
        return np.column_stack([cx + radius * np.cos(angs), cy + radius * np.sin(angs)])

    # the value in a break in the arc when it sits on the arc and the arc
    # can hold it with its arrowheads; else beside the arc, as before
    half_deg = math.degrees((0.5 * text_w + 1.0 / k) / max(radius, 1e-6))
    on_arc = (abs(lr - radius) < 1e-9 and _DIM_TEXT == "inline"
              and a0_deg + math.degrees(al / max(radius, 1e-6)) < la - half_deg
              and la + half_deg < a1_deg - math.degrees(al / max(radius, 1e-6)))
    if on_arc:
        first, second = _arc(a0_deg, la - half_deg), _arc(la + half_deg, a1_deg)
        view.add(first, "dim")
        view.add(second, "dim")
        head, tail = first[0], second[-1]
    else:
        arc = _arc(a0_deg, a1_deg)
        view.add(arc, "dim")
        head, tail = arc[0], arc[-1]
    if legs:
        for a in (a0_deg, a1_deg):
            r = math.radians(a)
            view.add([(cx, cy), (cx + (radius + 2.0 / k) * math.cos(r),
                                 cy + (radius + 2.0 / k) * math.sin(r))], "dim")
    _arrow(view, head, (math.sin(r0), -math.cos(r0)), k)
    _arrow(view, tail, (-math.sin(r1), math.cos(r1)), k)
    am = math.radians(la)
    view.text(cx + lr * math.cos(am), cy + lr * math.sin(am), label, size,
              align="center", valign="middle")


def leader(view: View, anchor, text_at, label: str, *, k: float = 1.0,
           align: str = "left") -> None:
    """A leader from `anchor` to `text_at`, the text beside it."""
    ax, ay = float(anchor[0]), float(anchor[1])
    tx, ty = float(text_at[0]), float(text_at[1])
    view.add([(ax, ay), (tx, ty)], "dim")
    _arrow(view, (ax, ay), (ax - tx, ay - ty), k)
    shoulder = (3.0 if align == "left" else -3.0) / k
    view.add([(tx, ty), (tx + shoulder, ty)], "dim")
    view.text(tx + shoulder + (0.8 if align == "left" else -0.8) / k,
              ty - 0.35 * DIM_TEXT / k, label, DIM_TEXT / k, align=align, valign="baseline")


def tagged(dim, value_text: str | None = None) -> str:
    """A dimension's text with its status tag."""
    from .measure import STATUS_TAG
    return f"{value_text if value_text is not None else dim.shown} [{STATUS_TAG[dim.status]}]"


# ------------------------------------------------------------------ the views
#
# The three views as eyewear drawings lay them out: the plan with the
# temples running up the page (third angle, above the front view) or down
# it (first angle, below); the front view facing the wearer, the OD lens on
# the observer's left; the side view in the temple's own frame, the temple
# horizontal to the right and the front tilted by the angle of side, as a
# bench sees it. Each is an edge rendering of the formed solid when the
# front is built (`_draw_solid`), else the drawing's curves.


def _pts(P):
    return np.asarray(P, dtype=np.float64).reshape(-1, 3)


def _plan_proj3(projection: str):
    """World (N, 3) -> plan (u, v, depth toward the viewer, who looks down).
    Third angle: seen from above standing before the wearer, the front
    toward the front view below, the temples up the page, OD on the
    observer's left. First angle: seen from above standing behind, the
    front toward the front view above, the temples down the page."""
    if projection == "first":
        return lambda P: np.column_stack([_pts(P)[:, 0], -_pts(P)[:, 2], _pts(P)[:, 1]])
    return lambda P: np.column_stack([-_pts(P)[:, 0], _pts(P)[:, 2], _pts(P)[:, 1]])


def _front_proj3():
    """World -> front view (u, v, depth): the viewer faces the wearer."""
    return lambda P: np.column_stack([-_pts(P)[:, 0], _pts(P)[:, 1], -_pts(P)[:, 2]])


def _side_proj3(angle_of_side_deg: float):
    """World -> side view in the temple's frame: the assembly turned about
    the lateral axis so the open temple lies horizontal, then seen from the
    wearer's left, the front at the left and the temple to the right."""
    R = rotation("x", -float(angle_of_side_deg))

    def proj(P):
        Q = _pts(P) @ R.T
        return np.column_stack([Q[:, 2], Q[:, 1], -Q[:, 0]])
    return proj


def _flat(proj3):
    return lambda P: proj3(P)[:, :2]


def _plan_proj(projection: str):
    return _flat(_plan_proj3(projection))


def _front_proj():
    return _flat(_front_proj3())


def _side_proj(angle_of_side_deg: float):
    return _flat(_side_proj3(angle_of_side_deg))


#: The direction toward the viewer in world, per view, for the silhouettes.
_VIEW_DIRS = {"plan": np.array([0.0, 1.0, 0.0]), "front": np.array([0.0, 0.0, -1.0]),
              "side": np.array([-1.0, 0.0, 0.0])}


def _draw_solid(view: View, asm: DraftAssembly, key: str, proj3, *, pockets_dashed: bool = True,
                temples: bool = True) -> bool:
    """The formed solid's edges in a view, hidden lines removed: the
    front's creases and its silhouette from that direction, the temples'
    rings, every run tested against the scene's depth; the pockets' hidden
    runs dashed. False when the front came without its mesh, and the view
    composes its curves instead."""
    if not asm.has_solid:
        return False
    from .hidden import split_by_visibility
    proj = _flat(proj3)
    dv = asm.depth_view(key, proj3)
    edges = list(asm.front_edges) + asm.silhouette_edges(_VIEW_DIRS[key.split(":")[0]])
    for e in edges:
        seen, _hidden = split_by_visibility(e, dv)
        for run in seen:
            view.add(proj(run), "visible")
    for ring in asm.pocket_rings:
        seen, hidden = split_by_visibility(ring, dv, closed=True)
        for run in seen:
            view.add(proj(run), "visible")
        if pockets_dashed:
            for run in hidden:
                view.add(proj(run), "hidden")
    if temples:
        for s in asm.ordered_sides():
            t = s.temple
            if t is None:
                continue
            for ring in (t.outer_ring, t.inner_ring):
                seen, _hidden = split_by_visibility(ring, dv, closed=True)
                for run in seen:
                    view.add(proj(run), "visible")
            for ring in t.pocket_rings:
                seen, hidden = split_by_visibility(ring, dv, closed=True)
                for run in seen:
                    view.add(proj(run), "visible")
                if pockets_dashed:
                    for run in hidden:
                        view.add(proj(run), "hidden")
    return True


def _add_rings(view: View, rings, proj, style: str) -> None:
    for r in rings:
        if r is not None and len(r) >= 2:
            view.add(proj(r), style, closed=True)


def _folded_rings(asm: DraftAssembly) -> list:
    """Each temple folded across the back: its outer ring, world."""
    out = []
    for s in asm.ordered_sides():
        if s.temple is not None and len(s.temple.outline_norm) >= 3:
            outer, _inner, _core = s.temple.rings_in(folded_basis(s.lateral))
            out.append(outer)
    return out


def _front_view(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
                with_dims: bool = True, k: float = 1.0) -> View:
    v = View("front", "FRONT VIEW")
    proj = _front_proj()
    pm = lambda mm: mm / k      # noqa: E731  paper mm -> view mm
    # the temples are left out of the front view: seen end-on they only
    # clutter the front, and the plan and the side view have them
    if not _draw_solid(v, asm, "front", _front_proj3(), temples=False):
        _add_rings(v, asm.outline_rings, proj, "visible")
        _add_rings(v, asm.lens_rings, proj, "visible")
        _add_rings(v, asm.pocket_rings, proj, "hidden")
    # the folded temples on request, a reference: they should cross the
    # center and clear the lenses (the closed-temple check)
    if settings.view_folded:
        _add_rings(v, _folded_rings(asm), proj, "hidden")
    boxes = {}
    for lat, (hx0, hy0, hx1, hy1) in m.head_on_boxes.items():
        boxes[lat] = (-hx1, hy0, -hx0, hy1)
    for lat, (bx0, by0, bx1, by1) in boxes.items():
        cx, cy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
        v.add([(cx - pm(3.0), cy), (cx + pm(3.0), cy)], "center")
        v.add([(cx, cy - pm(3.0)), (cx, cy + pm(3.0))], "center")
    for s in asm.ordered_sides():
        a = proj(s.axis_point)[0]
        v.add([(a[0], a[1] - pm(4.0)), (a[0], a[1] + pm(4.0))], "center")
    if not with_dims:
        return v
    x0, y0, x1, y1 = v.bbox()
    # above: the DBL between the lenses, the front's width over all
    d = m.get("dbl")
    top = y1
    if d is not None and len(boxes) == 2:
        r, l = boxes[1.0], boxes[-1.0]
        yb = max(r[3], l[3])
        linear_dim(v, (r[2], yb), (l[0], yb), pm(5.0) + (y1 - yb), tagged(d),
                   along=(1.0, 0.0), k=k)
        top = y1 + pm(5.0)
    d = m.get("front_width")
    if d is not None and not settings.view_top:
        linear_dim(v, (x0, y1), (x1, y1), (top - y1) + pm(7.0), tagged(d), along=(1.0, 0.0), k=k)
    # below: A under the OD lens, then the boxed-center distance
    bottom = y0
    d = m.get("a")
    if d is not None and 1.0 in boxes:
        bx0, by0, bx1, by1 = boxes[1.0]
        label = tagged(d) + (f"  ({d.note})" if d.note else "")
        # too wide for a lens at 1:2: the value goes out the temporal side,
        # clear of the boxed-center line from the other lens
        linear_dim(v, (bx0, by0), (bx1, by0), -(by0 - y0 + pm(6.0)), label, k=k,
                   outside="start")
        bottom = y0 - pm(6.0)
    d = m.get("bcd")
    if d is not None and len(boxes) == 2:
        r, l = boxes[1.0], boxes[-1.0]
        cr, cl = 0.5 * (r[0] + r[2]), 0.5 * (l[0] + l[2])
        yc = 0.5 * (r[1] + r[3])
        linear_dim(v, (cr, yc), (cl, yc), -(yc - bottom + pm(7.0)), tagged(d),
                   along=(1.0, 0.0), k=k)
    # B at the left
    d = m.get("b")
    if d is not None and 1.0 in boxes:
        bx0, by0, bx1, by1 = boxes[1.0]
        linear_dim(v, (bx0, by0), (bx0, by1), (bx0 - x0 + pm(6.0)), tagged(d), k=k)
    # the joint height on the right, the bridge in the gap
    d = m.get("joint_height")
    if d is not None and asm.left is not None and -1.0 in boxes:
        al = proj(asm.left.axis_point)[0]
        l = boxes[-1.0]
        yc = 0.5 * (l[1] + l[3])
        xa = x1 + pm(6.0)
        v.add([(l[2] + pm(2.0), yc), (xa + pm(1.5), yc)], "center")
        v.add([(al[0] + pm(2.0), al[1]), (xa + pm(1.5), al[1])], "center")
        linear_dim(v, (xa, yc), (xa, al[1]), 0.0, tagged(d), along=(0.0, 1.0), k=k)
    d = m.get("bridge_width")
    if d is not None:
        bx = -float(asm.forming.bridge_offset_mm)
        pts = np.concatenate([proj(r) for r in asm.outline_rings])
        near = pts[np.abs(pts[:, 0] - bx) < 1.0]
        if len(near) >= 2:
            by0, by1 = float(near[:, 1].min()), float(near[:, 1].max())
            # a short dimension: its value goes below its foot, into the
            # bridge's gap, clear of the DBL above
            linear_dim(v, (bx, by0), (bx, by1), pm(3.0), tagged(d), along=(0.0, 1.0), k=k,
                       outside="start")
    return v


def _plan_view(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
               with_dims: bool = True, targets: bool = False, k: float = 1.0) -> View:
    v = View("plan", "PLAN")
    proj = _plan_proj(settings.projection)
    pm = lambda mm: mm / k      # noqa: E731
    up = -1.0 if settings.projection == "first" else 1.0     # the temples run this way
    solid = _draw_solid(v, asm, f"plan:{settings.projection}", _plan_proj3(settings.projection))
    if not solid:
        for ring in front_silhouette(asm, proj, "x"):
            v.add(ring, "visible", closed=True)
        _add_rings(v, asm.pocket_rings, proj, "hidden")
    for s in asm.ordered_sides():
        a = proj(s.axis_point)[0]
        v.add([(a[0] - pm(2.5), a[1]), (a[0] + pm(2.5), a[1])], "center")
        v.add([(a[0], a[1] - pm(2.5)), (a[0], a[1] + pm(2.5))], "center")
        if s.temple is None:
            continue
        if not solid:
            v.add(proj(s.temple.outer_ring), "visible", closed=True)
            v.add(proj(s.temple.inner_ring), "visible", closed=True)
            for pr in s.temple.pocket_rings:
                v.add(proj(pr), "hidden", closed=True)
        v.add(proj(s.temple.core), "center")
        if targets:
            for p_ in (s.temple.tip, s.temple.ear_point):
                q = proj(p_)[0]
                ang = np.linspace(0, 2 * math.pi, 33)
                v.add(np.column_stack([q[0] + 2.0 * np.cos(ang), q[1] + 2.0 * np.sin(ang)]),
                      "thin", closed=True)
                v.add([(q[0] - 3.0, q[1]), (q[0] + 3.0, q[1])], "thin")
                v.add([(q[0], q[1] - 3.0), (q[0], q[1] + 3.0)], "thin")
    if not with_dims:
        return v
    x0, y0, x1, y1 = v.bbox()
    R, L = asm.right, asm.left
    # the front's width across the front face, on the front's side of the
    # view; the hinge spread at the axes; the tip spread at the tips
    front_side = y0 if up > 0 else y1
    pts_front = np.concatenate([proj(r) for r in asm.outline_rings])
    d = m.get("front_width")
    if d is not None:
        xa, xb = float(pts_front[:, 0].min()), float(pts_front[:, 0].max())
        linear_dim(v, (xa, front_side), (xb, front_side), -up * pm(7.0),
                   tagged(d), along=(1.0, 0.0), k=k)
    d = m.get("frontal_width")
    if d is not None and R is not None and L is not None:
        # between the temples, just behind the front: dowel to dowel
        ar, al = proj(R.axis_point)[0], proj(L.axis_point)[0]
        ya = 0.5 * (ar[1] + al[1])
        back = float(pts_front[:, 1].max()) if up > 0 else float(pts_front[:, 1].min())
        linear_dim(v, (ar[0], ya), (al[0], ya), -up * (abs(back - ya) + pm(12.0)) * (-1.0),
                   tagged(d), along=(1.0, 0.0), k=k)
    d = m.get("tip_spread")
    if d is not None and R is not None and L is not None and R.temple is not None:
        t = R.temple.thickness_mm
        tr, tl = proj(R.temple.tip)[0], proj(L.temple.tip)[0]
        sr = -1.0 if tr[0] > tl[0] else 1.0
        pr = (tr[0] + sr * 0.5 * t, tr[1])
        pl = (tl[0] - sr * 0.5 * t, tl[1])
        # inside, between the temples, a little short of the tips
        linear_dim(v, pr, pl, -up * pm(10.0) * (1.0 if pl[0] > pr[0] else -1.0),
                   tagged(d), along=(1.0, 0.0), k=k)
    d = m.get("front_to_bend")
    if d is not None and R is not None and R.temple is not None:
        er = proj(R.temple.ear_point)[0]
        xe = x0 - pm(6.0) if er[0] < 0 else x1 + pm(6.0)
        side = 1.0 if er[0] < 0 else -1.0
        pts = np.concatenate([proj(r) for r in asm.outline_rings])
        y_front = float(pts[:, 1].min()) if up > 0 else float(pts[:, 1].max())
        linear_dim(v, (xe, y_front), (xe, er[1]), side * pm(4.0), tagged(d), along=(0.0, 1.0), k=k)
    d = m.get("front_thickness")
    if d is not None and R is not None:
        # across the slab at the endpiece: the silhouette's depth beside the axis
        a = proj(R.axis_point)[0]
        pts = np.concatenate(front_silhouette(asm, proj, "x")) if asm.outline_rings else None
        if pts is not None and len(pts):
            near = pts[np.abs(pts[:, 0] - (a[0] - np.sign(a[0]) * pm(3.0))) < pm(1.5)]
            if len(near) >= 2:
                ya, yb = float(near[:, 1].min()), float(near[:, 1].max())
                xa = a[0] + np.sign(a[0]) * pm(5.0)
                linear_dim(v, (xa, ya), (xa, yb), -np.sign(a[0]) * pm(3.0), tagged(d),
                           along=(0.0, 1.0), k=k)
    d = m.get("temple_thickness")
    if d is not None and R is not None and R.temple is not None:
        c = proj(R.temple.core)
        i = min(len(c) - 1, int(0.35 * len(c)))
        # inward, between the temples: outward crosses the front-to-bend line
        leader(v, (c[i][0], c[i][1]), (c[i][0] - np.sign(c[i][0]) * pm(10.0), c[i][1] + up * pm(4.0)),
               "t " + tagged(d), k=k, align="right" if c[i][0] > 0 else "left")
    d = m.get("base_curve")
    if d is not None:
        pts = np.concatenate([proj(r) for r in asm.outline_rings])
        i = int(np.argmin(np.abs(pts[:, 0])))
        bx, by = float(pts[i][0]), float(pts[i][1])
        note = (f"Base {asm.forming.base_curve * 100:.0f} [T]" if asm.forming.base_curve > 0
                else "flat [T]")
        leader(v, (bx + pm(10.0), by), (bx + pm(18.0), by - up * pm(14.0)), note, k=k)
    for s in asm.ordered_sides():
        if s.temple is None or abs(s.splay_target_deg) < 0.05:
            continue
        a = proj(s.axis_point)[0]
        d = m.get(f"splay_{s.label}")
        c0, c1 = proj(s.temple.core[0])[0], proj(s.temple.core[min(12, len(s.temple.core) - 1)])[0]
        ang = math.degrees(math.atan2(c1[1] - c0[1], c1[0] - c0[0]))
        base = 90.0 if up > 0 else -90.0
        lo, hi = min(base, ang), max(base, ang)
        if hi - lo < 0.5:
            continue
        out = 1.0 if a[0] < 0 else -1.0
        angular_dim(v, a, pm(30.0), lo, hi, tagged(d), label_radius=pm(14.0), legs=False,
                    k=k, label_angle=up * 90.0 + out * 20.0)
    return v


def _side_view(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
               with_dims: bool = True, k: float = 1.0) -> View:
    near = asm.left if asm.left is not None else asm.right
    far = asm.right if near is asm.left else asm.left
    alpha = float(asm.forming.pantoscopic_tilt_deg)
    v = View("side", "SIDE VIEW" + (f" ({'left' if near is not None and near.lateral < 0 else 'right'} temple)"
                                   if near is not None else ""))
    proj = _side_proj(alpha)
    pm = lambda mm: mm / k      # noqa: E731
    solid = _draw_solid(v, asm, f"side:{alpha:.3f}", _side_proj3(alpha))
    side_sil = [] if solid else front_silhouette(asm, proj, "y")
    for ring in side_sil:
        v.add(ring, "visible", closed=True)
    if near is not None:
        a = proj(near.axis_point)[0]
        v.add([(a[0], a[1] - pm(5.0)), (a[0], a[1] + pm(5.0))], "center")
        if near.temple is not None:
            if not solid:
                v.add(proj(near.temple.outer_ring), "visible", closed=True)
                for pr in near.temple.pocket_rings:
                    v.add(proj(pr), "hidden", closed=True)
            v.add(proj(near.temple.core), "center")
    if (not solid and far is not None and far.temple is not None and near is not None
            and near.temple is not None
            and (len(far.temple.outer_ring) != len(near.temple.outer_ring)
                 or not np.allclose(far.temple.outline_norm, near.temple.outline_norm))):
        v.add(proj(far.temple.outer_ring), "hidden", closed=True)
    if not with_dims or near is None or near.temple is None:
        return v
    x0, y0, x1, y1 = v.bbox()
    a = proj(near.axis_point)[0]
    bend = near.temple.bend
    ear, tip = proj(near.temple.ear_point)[0], proj(near.temple.tip)[0]
    # the angle of side at the front: the front's chord against the vertical,
    # at its lower end, as the trade marks the panto
    if side_sil:
        front_pts = np.concatenate(side_sil)
    else:
        # the front's extent in the view: everything left of the hinge
        pts = [np.asarray(st.pts) for st in v.strokes if st.style == "visible"]
        allp = np.vstack(pts) if pts else np.zeros((0, 2))
        front_pts = allp[allp[:, 0] < a[0] + 1.0] if len(allp) else None
        if front_pts is not None and len(front_pts) < 2:
            front_pts = None
    d = m.get(f"side_{near.label}")
    if d is not None and front_pts is not None and len(front_pts):
        top_i, bot_i = int(np.argmax(front_pts[:, 1])), int(np.argmin(front_pts[:, 1]))
        ptop, pbot = front_pts[top_i], front_pts[bot_i]
        chord = math.degrees(math.atan2(ptop[1] - pbot[1], ptop[0] - pbot[0]))
        ext = pm(14.0)
        v.add([(pbot[0], pbot[1]), (pbot[0], pbot[1] - ext)], "center")
        dx, dy = math.cos(math.radians(chord)), math.sin(math.radians(chord))
        v.add([(ptop[0], ptop[1]), (pbot[0] - dx * ext, pbot[1] - dy * ext)], "center")
        lo, hi = sorted((270.0, chord - 180.0 if chord > 90 else chord + 180.0))
        lo2, hi2 = sorted((270.0, (chord + 180.0) % 360.0))
        if hi2 - lo2 > 180.0:
            lo2, hi2 = hi2, lo2 + 360.0
        if hi2 - lo2 > 0.3:
            angular_dim(v, pbot, pm(11.0), lo2, hi2, tagged(d), label_radius=pm(14.0),
                        legs=False, k=k, label_angle=345.0)
    # along the temple: the length to bend, from the hinge to the ear point
    d = m.get("length_to_bend")
    if d is not None:
        above = y1 - max(a[1], ear[1]) + pm(8.0)
        linear_dim(v, (a[0], a[1]), (ear[0], a[1]), above, tagged(d), along=(1.0, 0.0), k=k)
    d = m.get("drop")
    if d is not None and bend.applies:
        linear_dim(v, (ear[0], ear[1]), (tip[0], tip[1]), -pm(10.0), tagged(d), k=k)
    d = m.get("drop_angle")
    if d is not None and bend.applies:
        core = proj(near.temple.core)
        i_ear = int(np.argmin(np.hypot(core[:, 0] - ear[0], core[:, 1] - ear[1])))
        j = min(i_ear + 10, len(core) - 1)
        a_out = math.degrees(math.atan2(core[j][1] - core[i_ear][1], core[j][0] - core[i_ear][0]))
        lo, hi = sorted((0.0, a_out))
        if hi - lo > 180.0:
            lo, hi = hi, lo + 360.0
        v.add([(ear[0], ear[1]), (ear[0] + pm(22.0), ear[1])], "center")
        angular_dim(v, ear, pm(16.0), lo, hi, tagged(d), label_radius=pm(21.0), legs=False, k=k)
    # the temple's height near the butt and near the tip
    outer = proj(near.temple.outer_ring)
    for key, x_at, side in (("temple_height_butt", a[0] + pm(4.0), 1.0),
                            ("temple_height_tip", None, -1.0)):
        d = m.get(key)
        if d is None:
            continue
        if x_at is None:
            # across the drop, near the tip: the points within 6 mm of the tip
            near_pts = outer[np.hypot(outer[:, 0] - tip[0], outer[:, 1] - tip[1]) < 8.0]
            if len(near_pts) < 2:
                continue
            # the drop's direction, and its normal
            dd = np.array([tip[0] - ear[0], tip[1] - ear[1]])
            dd = dd / (np.linalg.norm(dd) or 1.0)
            nn = np.array([-dd[1], dd[0]])
            w = (near_pts - tip) @ nn
            p1 = tip + nn * w.min()
            p2 = tip + nn * w.max()
            # beyond the tip, away from the drop angle's leg and arc
            linear_dim(v, p1, p2, -pm(6.0), tagged(d), k=k)
            continue
        near_pts = outer[np.abs(outer[:, 0] - x_at) < pm(1.5)]
        if len(near_pts) < 2:
            continue
        ya, yb = float(near_pts[:, 1].min()), float(near_pts[:, 1].max())
        linear_dim(v, (x_at, ya), (x_at, yb), -pm(5.0), tagged(d), along=(0.0, 1.0), k=k)
    return v


def _temples_view(asm: DraftAssembly, k: float = 1.0) -> View | None:
    """The temples as cut, flat: the right above the left, with their
    pockets, as a factory's sheet boxes them."""
    v = View("temples", "TEMPLES, AS CUT")
    y = 0.0
    pm = lambda mm: mm / k      # noqa: E731
    any_ = False
    for s in asm.ordered_sides():
        t = s.temple
        if t is None or len(t.outline_norm) < 3:
            continue
        Q = t.outline_norm
        h = float(Q[:, 1].max() - Q[:, 1].min())
        shift = y - float(Q[:, 1].max())
        v.add([(x_, y_ + shift) for x_, y_ in Q], "visible", closed=True)
        for pn in t.pockets_norm:
            v.add([(x_, y_ + shift) for x_, y_ in pn], "hidden", closed=True)
        v.text(float(Q[:, 0].min()), y + pm(1.0), s.label, SMALL_TEXT / k)
        y -= h + pm(6.0)
        any_ = True
    return v if any_ else None


def _hinge_view(asm: DraftAssembly, k: float = 1.0) -> View | None:
    s = asm.right or asm.left
    if s is None:
        return None
    v = View("hinge", "HINGE DETAIL (reference only)")
    pm = lambda mm: mm / k      # noqa: E731
    det = hinge_detail(s.hinge, front_leaf=s.front_leaf, temple_leaf=s.temple_leaf,
                       axis_inset_mm=s.axis_inset_mm, axis_offset_mm=s.hinge.spec.axis_offset_mm)
    el, pl = det["elevation"], det["plan"]
    el_xs = [p[0] for ring in el["visible"] for p in ring]
    pl_xs = [p[0] for ring in pl["visible"] + pl["center"] for p in ring]
    shift = ((max(el_xs) if el_xs else 0.0) - (min(pl_xs) if pl_xs else 0.0)) + pm(10.0)
    # the captions under the two views must not run into each other
    caption_w = _GLYPH_W * (SMALL_TEXT / k) * len("opened flat, seen from behind") + pm(4.0)
    shift = max(shift, (min(el_xs) if el_xs else 0.0) + caption_w - (min(pl_xs) if pl_xs else 0.0))
    for key, style in (("visible", "visible"), ("hidden", "hidden"), ("center", "center")):
        for ring in el[key]:
            v.add(ring, style, closed=(key != "center"))
        for ring in pl[key]:
            v.add([(x, y) for x, y in ((x + shift, y) for x, y in ring)], style,
                  closed=(key != "center"))
    for x, y, t in el["labels"]:
        v.text(x, y, t, SMALL_TEXT / k, align="center")
    for x, y, t in pl["labels"]:
        v.text(x + shift, y, t, SMALL_TEXT / k, align="center")
    x0, y0, x1, y1 = v.bbox()
    v.text(x0, y1 + pm(1.5), "opened flat, seen from behind", SMALL_TEXT / k, style="muted")
    v.text(x0 + shift, y1 + pm(1.5), "from above, at the stop", SMALL_TEXT / k, style="muted")
    return v


def projection_symbol(sheet: Sheet, x: float, y: float, projection: str, h: float = 6.0) -> None:
    """ISO 128's truncated cone: first angle has the cone before the circles,
    its small end toward them; third angle the circles first."""
    w = 2.0 * h
    big, small = 0.5 * h, 0.25 * h
    cy = y + 0.5 * h
    if projection == "first":
        cone_x, circ_x = x, x + w * 0.62
        trap = [(cone_x, cy - big), (cone_x + w * 0.45, cy - small),
                (cone_x + w * 0.45, cy + small), (cone_x, cy + big)]
    else:
        circ_x, cone_x = x + 0.5 * h, x + w * 0.5
        trap = [(cone_x, cy - small), (cone_x + w * 0.45, cy - big),
                (cone_x + w * 0.45, cy + big), (cone_x, cy + small)]
    sheet.strokes.append(Stroke(trap, "thin", closed=True))
    for r in (big, small):
        ang = np.linspace(0, 2 * math.pi, 25)
        sheet.strokes.append(Stroke([(circ_x + r * math.cos(a), cy + r * math.sin(a)) for a in ang],
                                    "thin", closed=True))


# ------------------------------------------------------------------ the pages

def _title_block(sheet: Sheet, settings: BlueprintSettings, fields: dict,
                 x0: float, y0: float, x1: float, y1: float) -> None:
    """ISO 7200's cells in two rows: the identification (owner, title,
    document type) above; the creator, approver, number, date, revision,
    sheet and scale below."""
    sheet.rect(x0, y0, x1, y1, "border")
    w = x1 - x0
    ymid = y0 + 0.5 * (y1 - y0)
    sheet.line(x0, ymid, x1, ymid, "thin")
    top = [("Legal owner", fields.get("owner", ""), 0.28),
           ("Title", fields.get("title", ""), 0.44),
           ("Document type", fields.get("document_type", ""), 0.28)]
    bottom = [("Created by", fields.get("author", ""), 0.17),
              ("Approved by", fields.get("approver", ""), 0.15),
              ("Identification number", fields.get("id_number", ""), 0.20),
              ("Date of issue", fields.get("issue_date", ""), 0.14),
              ("Rev.", fields.get("revision", ""), 0.08),
              ("Sheet", fields.get("sheet", ""), 0.10),
              ("Scale", fields.get("scale", ""), 0.16)]
    for row, (ya, yb) in ((top, (y0, ymid)), (bottom, (ymid, y1))):
        x = x0
        for label, value, frac in row:
            cw = w * frac
            if x > x0:
                sheet.line(x, ya, x, yb, "thin")
            sheet.text(x + 1.2, ya + 1.0, label, SMALL_TEXT * 0.85, style="muted")
            size = LABEL_TEXT if label == "Title" else DIM_TEXT
            sheet.text(x + 1.2, ya + 4.6, value, size, style="bold" if label == "Title" else "normal")
            x += cw
    projection_symbol(sheet, x1 - 15.0, ymid + 6.5, settings.projection, 5.5)


def _notes_views(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
                 material: str, width_mm: float = 74.0) -> tuple[View, View]:
    """The notes as two views of texts laid out in mm at scale 1: the text
    (the marking, the material, the forming, the temples and the bench, the
    hinge's lines, the maker's notes) and the tables (the tolerances, the
    checks), so the composer can put the tables where the page has room.
    The lines wrap to `width_mm`, the column they are placed in, in the
    font the sheet is lettered in."""
    import textwrap
    width_mm = max(float(width_mm), 40.0)
    width_chars = max(int((width_mm - 2.0) / (_GLYPH_W * SMALL_TEXT)), 20)
    lh = 3.3

    class _Col:
        def __init__(self, key, title):
            self.v = View(key, title)
            self.y = 0.0

        def line(self, t, size=SMALL_TEXT, style="normal", indent=0.0):
            self.v.text(indent, self.y, t, size, style=style)
            self.y -= lh * (size / SMALL_TEXT)

        def wrapped(self, t, **kw):
            for i, part in enumerate(textwrap.wrap(t, width_chars) or [""]):
                self.line(("  " if i else "") + part, **kw)

        def gap(self, mm=1.5):
            self.y -= mm

    c = _Col("notes", "NOTES")
    c.line("NOTES", LABEL_TEXT, "bold")
    if m.marking:
        c.wrapped(f"Marking: {m.marking}")
    if material:
        c.wrapped(f"Material: {material}")
    if settings.finish:
        c.wrapped(f"Finish: {settings.finish}")
    c.wrapped("After forming. [L] locked · [T] target · [O] open · [ref] reference")
    for key in ("crest_height", "apical_radius"):
        d = m.get(key)
        if d is not None:
            c.wrapped(f"{d.label}: {tagged(d)}")
    rims = [(lab, m.get(key)) for key, lab in (("rim_top", "top"), ("rim_bottom", "bottom"),
                                              ("rim_outer", "temporal"), ("rim_inner", "nasal"))]
    rims = [(lab, d) for lab, d in rims if d is not None]
    if rims:
        c.wrapped("Rim widths, OD, as cut: " + ", ".join(f"{lab} {d.value:.1f}" for lab, d in rims)
                  + " [L]")
    c.gap()
    c.line("FORMING", LABEL_TEXT, "bold")
    for key in ("base_curve", "face_form", "projection"):
        d = m.get(key)
        if d is not None:
            c.wrapped(f"{d.label}: {tagged(d)}")
    for s_ in asm.ordered_sides():
        c.wrapped(f"Endpiece {s_.label} turns {s_.surface_turn_deg:.1f}° and leans "
               f"{s_.surface_tilt_deg:.1f}° at the hinge")
    c.gap()
    c.line("TEMPLES AND BENCH", LABEL_TEXT, "bold")
    for key in ("overall", "bend_radius", "inward_angle"):
        d = m.get(key)
        if d is not None:
            c.wrapped(f"{d.label}: {tagged(d)}")
    for s_ in asm.ordered_sides():
        c.wrapped(f"Side {s_.label}: angle of side {s_.side_target_deg:.1f}° (hinge alone "
                  f"{s_.side_from_hinge_deg:.1f}°), butt cut {s_.panto_cut_deg:.1f}°; splay "
                  f"{s_.splay_target_deg:.1f}° (hinge alone {s_.splay_from_hinge_deg:.1f}°), "
                  f"butt cut {s_.splay_cut_deg:.1f}°; pocket angle for the target "
                  f"{s_.floor_angle_for_target:.1f}°")
    for s_ in asm.ordered_sides():
        if s_.temple is not None and s_.temple.bend_note:
            c.wrapped(f"Temple {s_.label}: tip bend out of range, drawn straight: "
                      f"{s_.temple.bend_note}", style="warning")
    side = asm.right or asm.left
    if side is not None:
        c.gap()
        c.line("HINGE", LABEL_TEXT, "bold")
        for t in side.hinge.lines():
            c.wrapped(t)
    if settings.notes:
        c.gap()
        for t in settings.notes.splitlines():
            c.wrapped(t)

    t = _Col("tables", "TOLERANCES")
    t.line("TOLERANCES", LABEL_TEXT, "bold")
    width = min(74.0, width_mm - 2.0)
    col = (0.0, width * 42.0 / 74.0, width * 60.0 / 74.0)
    top = t.y + 0.9 * SMALL_TEXT
    for name, value, source in (("Dimension", "Tolerance", "Source"),) + tuple(
            (r.name, r.value, r.source) for r in settings.tolerances):
        t.v.text(col[0] + 1.0, t.y, name, SMALL_TEXT, style="bold" if name == "Dimension" else "normal")
        t.v.text(col[1] + 1.0, t.y, value, SMALL_TEXT)
        t.v.text(col[2] + 1.0, t.y, source, SMALL_TEXT)
        t.y -= lh
    bottom = t.y + lh - 0.4 * SMALL_TEXT
    t.v.add([(0.0, top), (width, top), (width, bottom), (0.0, bottom)], "thin", closed=True)
    t.v.add([(col[1], top), (col[1], bottom)], "thin")
    t.v.add([(col[2], top), (col[2], bottom)], "thin")
    t.gap()
    t.line("QC CHECKLIST", LABEL_TEXT, "bold")
    for ch in asm.checks:
        t.wrapped(("☑ " if ch.ok else "☐ ") + f"{ch.name}: {ch.text}",
                  style="normal" if ch.ok else "warning")
    for n in asm.notes:
        t.wrapped("• " + n, style="warning")
    return c.v, t.v


def _scale_text(k: float) -> str:
    if abs(k - 1.0) < 1e-9:
        return "1:1"
    if k > 1.0:
        return f"{k:g}:1"
    return f"1:{round(1.0 / k, 2):g}"


def _views_at(asm, m, settings, k: float, with_dims: bool) -> dict:
    views = {}
    if settings.view_top:
        views["plan"] = _plan_view(asm, m, settings, with_dims, k=k)
    if settings.view_front:
        views["front"] = _front_view(asm, m, settings, with_dims, k)
    if settings.view_side:
        views["side"] = _side_view(asm, m, settings, with_dims, k)
    return views


def _stack_order(projection: str) -> tuple:
    """Top to bottom: third angle has the plan above the front and the side
    below; first angle the side above and the plan below."""
    return ("plan", "front", "side") if projection == "third" else ("side", "front", "plan")


def _stack_size(views: dict, k: float, gap: float, projection: str) -> tuple[float, float, float, float]:
    """(width, height, left extent, right extent) of the stacked views at
    scale k, paper mm; the plan and the front share their center line, the
    side view sits with its left edge at the front's."""
    order = [key for key in _stack_order(projection) if key in views]
    if not order:
        return 0.0, 0.0, 0.0, 0.0
    boxes = {key: views[key].bbox() for key in order}
    left = right = 0.0
    for key in order:
        b = boxes[key]
        if key in ("plan", "front"):
            left, right = max(left, -b[0] * k), max(right, b[2] * k)
    front_left = -boxes["front"][0] * k if "front" in boxes else left
    if "side" in boxes:
        b = boxes["side"]
        right = max(right, (b[2] - b[0]) * k - front_left)
    h = sum((boxes[key][3] - boxes[key][1]) * k for key in order) + gap * (len(order) - 1)
    return left + right, h, left, right


def _place_stack(sheet: Sheet, views: dict, k: float, gap: float, projection: str,
                 x: float, y: float) -> float:
    """Place the stack with its left extent at x and its top at y; returns
    the bottom."""
    order = [key for key in _stack_order(projection) if key in views]
    boxes = {key: views[key].bbox() for key in order}
    _w, _h, left, _right = _stack_size(views, k, gap, projection)
    x_center = x + left
    front_left = x_center - (boxes["front"][0] * k if "front" in boxes else 0.0) \
        if "front" in boxes else x
    yy = y
    for key in order:
        b = boxes[key]
        if key == "side":
            px = x_center + boxes["front"][0] * k if "front" in boxes else x
        else:
            px = x_center + b[0] * k
        sheet.place(views[key], px, yy, k)
        yy += (b[3] - b[1]) * k + gap
    return yy - gap


def _fit_stack(asm, m, settings, avail_w: float, avail_h: float, gap: float):
    """The largest standard scale the stacked, dimensioned views fit at, or
    the one requested; returns (k, views)."""
    candidates = [settings.scale] if settings.scale > 0 else list(STANDARD_SCALES)
    views = None
    for k in candidates:
        views = _views_at(asm, m, settings, k, True)
        w, h, _l, _r = _stack_size(views, k, gap, settings.projection)
        if w <= avail_w + 1e-9 and h <= avail_h + 1e-9:
            return k, views
    return candidates[-1], views


#: The narrowest column the notes are put beside the views in, paper mm.
_COLUMN_MIN_MM = 56.0


def compose_sheet1(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
                   fields: dict, landscape: bool | None = None) -> Sheet:
    hinge = _hinge_view(asm, 1.0) if settings.view_hinge else None
    column = settings.view_notes or hinge is not None
    if landscape is None:
        landscape = settings.orientation == "landscape"
    w, h = page_size(settings, landscape)
    sheet = Sheet(w, h, 1, 2 if settings.sheet_template else 1, title=fields.get("title", ""))
    x0, y0, x1, y1 = MARGIN_MM, MARGIN_MM, w - MARGIN_MM, h - MARGIN_MM
    if settings.border:
        sheet.rect(x0, y0, x1, y1, "border")
    tb_w = min(180.0, x1 - x0)
    tb_y0 = y1 - TITLE_H_MM
    area_y1 = tb_y0 - 4.0
    inner_w = x1 - x0 - 4.0
    avail_h = area_y1 - y0 - 4.0
    # the views first, leaving the column its least when there is one
    k, views = _fit_stack(asm, m, settings, inner_w - (_COLUMN_MIN_MM + 6.0 if column else 0.0),
                          avail_h, GAP_MM)
    sheet.scale = k
    sw, sh, _l, _r = _stack_size(views, k, GAP_MM, settings.projection)
    # the column takes what the views leave; the views are centered in the
    # rest when the page is wider than the stack and the column together
    col_w = (x1 - 2.0 - (x0 + 2.0 + sw + 6.0)) if column else 0.0
    if column and col_w < _COLUMN_MIN_MM:
        col_w = 0.0                    # no room beside: the notes go below
    stack_x = x0 + 2.0 + (0.0 if column and col_w else 0.5 * max(0.0, inner_w - sw))
    stack_y = y0 + 2.0 + 0.5 * max(0.0, avail_h - sh) * (0.0 if column else 1.0)
    bottom = _place_stack(sheet, views, k, GAP_MM, settings.projection, stack_x, stack_y)
    for p in sheet.placed:
        sheet.text(p.x, p.y + p.height + 1.5, p.view.title, SMALL_TEXT, style="muted")
    if sh > avail_h + 1e-6 or sw > inner_w + 1e-6:
        sheet.clipped = True
    temples = _temples_view(asm, 1.0)
    if column:
        if col_w:
            rx, ry, rw, r_bottom = x1 - 2.0 - col_w, y0 + 2.0, col_w, tb_y0 - 3.0
            sheet.line(rx - 3.0, y0, rx - 3.0, tb_y0, "thin")
        else:
            rx, ry, rw, r_bottom = x0 + 2.0, bottom + 8.0, inner_w, tb_y0 - 3.0
        notes = tables = None
        if settings.view_notes:
            notes, tables = _notes_views(asm, m, settings, fields.get("material", ""), rw)
        _place_column(sheet, [hinge, notes, tables, temples], rx, ry, rw, r_bottom,
                      recompose={"hinge": lambda kk: _hinge_view(asm, kk)})
    _title_block(sheet, settings, {**fields, "sheet": f"1 / {sheet.count}",
                                   "scale": _scale_text(k)}, x1 - tb_w, tb_y0, x1, y1)
    return sheet


def _place_column(sheet: Sheet, items: list, x: float, y: float, w: float, bottom: float,
                  recompose: dict | None = None) -> None:
    """The hinge detail, the notes, the tables and the as-cut temples down a
    column, each at the largest scale that fits its width, the whole
    shrunk together when the column is short; the temples are left out
    when they do not fit. `recompose` names views to compose again at the
    scale chosen, so their text stays at paper size."""
    items = [v for v in items if v is not None]
    if not items:
        return
    sizes = []
    for v in items:
        b = v.bbox()
        vw, vh = b[2] - b[0], b[3] - b[1]
        if v.key == "hinge":
            # the scale from the drawing alone (its captions are paper-sized
            # and do not scale), then checked with the captions once
            # recomposed at that scale
            xs = [pt[0] for st in v.strokes for pt in st.pts]
            sw = (max(xs) - min(xs)) if xs else vw
            k = 0.5
            for c in (3.0, 2.5, 2.0, 1.5, 1.0, 0.5):
                if sw * c > w - 2.0:
                    continue
                cand = recompose[v.key](c) if recompose and v.key in recompose else v
                cb = cand.bbox()
                if (cb[2] - cb[0]) * c <= w - 2.0 or c == 0.5:
                    v, b, k = cand, cb, c
                    vw, vh = b[2] - b[0], b[3] - b[1]
                    break
        elif v.key == "temples":
            k = min(1.0, (w - 2.0) / max(vw, 1e-6))
            k = next((c for c in (1.0, 0.5, 0.4) if c <= k + 1e-9), 0.4)
        else:
            k = min(1.0, (w - 2.0) / max(vw, 1e-6))
        sizes.append((v, k, vw * k, vh * k))
    title_h = 4.0
    gap = 5.0

    def total(scale_all: float, keep_temples: bool):
        return sum((vh + title_h + gap) * scale_all for v, _k, _vw, vh in sizes
                   if keep_temples or v.key != "temples")

    avail = bottom - y
    shrink, keep = 1.0, True
    if total(1.0, True) > avail:
        keep = False
        if total(1.0, False) > avail:
            shrink = max(0.55, avail / max(total(1.0, False), 1e-6))
            if total(shrink, False) > avail + 1e-6:
                sheet.clipped = True       # into the title block even so
    yy = y
    for v, k, vw, vh in sizes:
        if v.key == "temples" and not keep:
            continue
        kk = k * shrink
        if v.key in ("hinge", "temples"):
            sheet.text(x, yy, v.title, SMALL_TEXT, style="muted")
            yy += title_h * shrink
        px = x + (0.5 * (w - vw * shrink) if v.key in ("hinge", "temples") else 0.0)
        p = sheet.place(v, px, yy, kk)
        if v.key == "hinge":
            sheet.text(x, p.y + p.height + 1.0, f"scale {_scale_text(kk)}", SMALL_TEXT * 0.9,
                       style="muted")
        yy = p.y + p.height + gap * shrink


def _ruler(sheet: Sheet, x: float, y: float, length: float) -> None:
    sheet.line(x, y, x + length, y, "thin")
    mm = 0
    while mm <= length + 1e-9:
        tall = mm % 50 == 0
        sheet.line(x + mm, y, x + mm, y - (3.0 if tall else 1.5), "thin")
        if tall:
            sheet.text(x + mm, y + 0.8, f"{mm:d}" + (" mm" if mm == length else ""),
                       SMALL_TEXT, align="center")
        mm += 10


def compose_sheet2(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
                   fields: dict) -> Sheet:
    """The 1:1 alignment template: the plan of the open frame, the temple
    tips and ear points in ±2 mm targets, and the tip-bend profile; a ruler
    to check the print's scale. The orientation is whichever fits the plan;
    a plan wider than the page is cropped and the sheet says so."""
    plan = _plan_view(asm, m, settings, with_dims=False, targets=True)
    side = _side_view(asm, m, settings, with_dims=False)
    pb, sb = plan.bbox(), side.bbox()
    pieces = [(plan, pb[2] - pb[0], pb[3] - pb[1]), (side, sb[2] - sb[0], sb[3] - sb[1])]
    best = None
    for landscape in (False, True):
        w, h = page_size(settings, landscape)
        avail_w = w - 2 * MARGIN_MM - 4.0
        avail_h = h - 2 * MARGIN_MM - RULER_STRIP_MM - 10.0
        need_h = sum(ph for _v, _pw, ph in pieces) + 10.0 * (len(pieces) - 1) + 6.0 * len(pieces)
        fits = all(pw <= avail_w for _v, pw, _ph in pieces) and need_h <= avail_h
        score = (0 if fits else 1, max(pw - avail_w for _v, pw, _ph in pieces))
        if best is None or score < best[0]:
            best = (score, landscape)
    landscape = best[1]
    w, h = page_size(settings, landscape)
    sheet = Sheet(w, h, 2, 2, title=fields.get("title", ""))
    x0, y0, x1, y1 = MARGIN_MM, MARGIN_MM, w - MARGIN_MM, h - MARGIN_MM
    if settings.border:
        sheet.rect(x0, y0, x1, y1, "border")
    avail_w = x1 - x0 - 4.0
    sheet.text(x0 + 2.0, y0 + 2.0, f"{fields.get('title', '')} — 1:1 alignment template",
               LABEL_TEXT, style="bold")
    sheet.text(x1 - 2.0, y0 + 2.5, f"sheet 2 / 2 · {fields.get('issue_date', '')}", SMALL_TEXT,
               align="right", style="muted")
    y = y0 + 9.0
    for v, pw, ph in pieces:
        sheet.text(x0 + 2.0, y, v.title + " · 1:1"
                   + (" · tips and ear points in ±2 mm targets" if v is plan else ""),
                   SMALL_TEXT, style="muted")
        y += 4.0
        px = x0 + 2.0 + max(0.0, 0.5 * (avail_w - pw))
        sheet.place(v, px, y, 1.0)
        if pw > avail_w + 1e-6 or y + ph > y1 - RULER_STRIP_MM:
            sheet.clipped = True
        y += ph + 10.0
    strip_top = y1 - RULER_STRIP_MM
    note = ("Scale 1:1 — measure the ruler to verify. Print at 100 % with “fit to page” off."
            + ("  A piece larger than the page is cropped at the margin." if sheet.clipped else ""))
    sheet.text(x0 + 2.0, strip_top, note, SMALL_TEXT)
    _ruler(sheet, x0 + 4.0, strip_top + 8.5, 100.0 if avail_w >= 110.0 else 50.0)
    return sheet


def compose_sheets(asm: DraftAssembly, m: DraftMeasures, settings: BlueprintSettings,
                   *, job_name: str = "", material: str = "", issue_date: str = "") -> list:
    """Every sheet of the blueprint, in order."""
    set_lettering(settings.text_width_em, settings.dim_text)
    fields = {
        "owner": settings.owner,
        "author": settings.author,
        "title": settings.design_name or job_name or "Frame",
        "document_type": settings.document_type,
        "id_number": settings.id_number,
        "issue_date": settings.issue_date or issue_date,
        "revision": settings.revision,
        "approver": settings.approver,
        "material": settings.material or material,
    }
    landscape = None if settings.orientation == "auto" else settings.orientation == "landscape"
    if landscape is None:
        best = None
        for land in (False, True):
            s = compose_sheet1(asm, m, settings, fields, land)
            if best is None or s.scale > best.scale + 1e-9:
                best = s
        sheets = [best]
    else:
        sheets = [compose_sheet1(asm, m, settings, fields, landscape)]
    if settings.sheet_template:
        sheets.append(compose_sheet2(asm, m, settings, fields))
    return sheets
