"""The rough assembly: the formed front, the hinge axes, the temples bent
and opened (2.3; research section 6.2).

Coordinates are the front's posterior frame throughout: x across the frame
(OD on +x), y up, z toward the wearer, the anterior face at z = 0. The front
is formed by `ThermoformMap`; the length-keeping surface's depth
(`FormingMetadata.neutral_fraction`) is applied around the map, never inside
it, so the map stays the one GuildDraw's parity test holds. A temple comes in
its own frame (x along the temple, the hinge end at one extreme, y across it,
z through its thickness with the hinge face at z = thickness) and is placed
on the hinge axis by the pocket's local frame.

What the view asserts, so the maker can disagree with any of it:

* The temple hangs with its outer face flush with the endpiece's end face
  (the library entry's datum), moved in by the hinge's `temple_inset_mm`;
  the barrel axis sits a temple's thickness inside that edge, on the
  endpiece's back face (`axis_offset_mm` behind it), where the shipped
  library's front pockets end; the temple's butt face passes through the
  axis (`axis_setback_mm` beyond it), as a butt joint's does.
* The angle of side and the splay the temples are drawn at are the
  targets (`pantoscopic_tilt_deg`, `DraftParams.splay_deg`); what the
  hinge alone would give (the pocket floor's angle, the formed surface's
  own tilt and turn at the pocket, the hinge's slant and stop) is reported
  beside them, and the butt is cut where the temple meets the endpiece's
  back face: the panto and splay cut into the butt are the difference.
* The temple bends as a bar: the drop from the drawing's tip bend and the
  inward angle (`TipBendParams.inward_angle_deg`, seen from above) are
  composed along the core (`tipbend.TempleBend3D`). The curl a bent drop
  takes toward the head is not drawn: the drawing's temple tab has no
  third dimension for it (research section 5.1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from guildmodel.core.forming.thermoform import (ThermoformMap, bridge_geometry,
                                                neutral_map)
from guildmodel.core.geometry.pocket_floor import (castle_pocket_floors,
                                                   temple_pocket_floors)
from guildmodel.core.project.schema import (ComponentKind, DraftParams,
                                            FormingMetadata, TempleParams)

from .hinges import HingeFill, PocketFit, fill_hinge, fit_pocket, leaf_from_pocket
from .tipbend import TempleBend3D, TipBend, resolve_tip_bend, temple_axes

__all__ = ["Check", "DraftAssembly", "FrontInput", "SideResult", "TempleInput",
           "TemplePlacement", "build_assembly", "clip_ring", "folded_basis",
           "front_silhouette", "rotation"]


# ------------------------------------------------------------------ inputs

@dataclass
class FrontInput:
    """The front as the window holds it (`ComponentWorkspace`), without Qt."""
    outline: object                       # Polygon | MultiPolygon
    lens_od: object = None
    lens_os: object = None
    hinge_polys: list = field(default_factory=list)
    component_kinds: list = field(default_factory=list)
    partition: object = None
    castle: object = None                 # CastleParams
    forming: FormingMetadata = field(default_factory=FormingMetadata)
    boxing: object = None                 # BoxingDimensions
    guides: dict = field(default_factory=dict)
    job_name: str = ""
    material: str = ""
    # The front as built, flat (a closed trimesh from the kernel), when the
    # window has it: the blueprint then draws the formed solid's own edges
    # with hidden lines removed. Without it the views are composed from the
    # drawing's curves.
    mesh: object = None


@dataclass
class TempleInput:
    kind: ComponentKind
    outline: object = None                # Polygon
    hinge_polys: list = field(default_factory=list)
    params: TempleParams = field(default_factory=TempleParams)
    enabled: bool = True


# ------------------------------------------------------------------ helpers

def rotation(axis: str, deg: float) -> np.ndarray:
    """A right-handed rotation about a world axis."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def clip_ring(ring, plane_point, normal) -> np.ndarray:
    """A closed ring, ``(N, 3)``, kept on the side of the plane its normal
    points to (Sutherland-Hodgman against one half-space). Empty when the
    whole ring is cut away."""
    P = np.asarray(ring, dtype=np.float64)
    if len(P) == 0:
        return P
    n = np.asarray(normal, dtype=np.float64)
    d = (P - np.asarray(plane_point, dtype=np.float64)) @ n
    if np.all(d >= -1e-9):
        return P
    if np.all(d < 0):
        return np.zeros((0, 3))
    out = []
    m = len(P)
    for i in range(m):
        a, b = P[i], P[(i + 1) % m]
        da, db = d[i], d[(i + 1) % m]
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append(a + t * (b - a))
    return np.asarray(out)


def _ring_xy(poly: Polygon) -> np.ndarray:
    c = np.asarray(poly.exterior.coords, dtype=np.float64)
    if len(c) > 1 and np.allclose(c[0], c[-1]):
        c = c[:-1]
    return c


def _bodies(outline) -> list:
    if outline is None or outline.is_empty:
        return []
    if isinstance(outline, MultiPolygon):
        return list(outline.geoms)
    return [outline]


# ------------------------------------------------------------------ results

@dataclass
class TemplePlacement:
    """A temple bent and placed, in the world frame."""
    kind: ComponentKind
    bend: TipBend
    bend3d: TempleBend3D
    origin: np.ndarray              # the axis point, world
    basis: np.ndarray               # 3x3: columns X (along), Y (up), Z (toward the head)
    axis_local: np.ndarray          # the axis in the temple's normalized frame, unbent
    thickness_mm: float
    outline_norm: np.ndarray        # the flat OUTLINE in the normalized frame (s, up), unbent
    pockets_norm: list              # the COMPONENT pockets likewise
    outer_ring: np.ndarray          # the OUTLINE at the outer face, bent, placed, butt cut
    inner_ring: np.ndarray          # the same at the hinge face
    pocket_rings: list              # the COMPONENT pockets at the hinge face
    core: np.ndarray                # the bent core line, placed
    ear_point: np.ndarray
    tip: np.ndarray
    butt_cut: bool                  # the butt met the endpiece's back face
    bend_note: str | None           # out of range, when the bend is not drawn
    face_point: np.ndarray = field(default_factory=lambda: np.zeros(3))
    face_normal: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))

    def to_world(self, pts_norm, basis=None) -> np.ndarray:
        """Bent normalized coordinates (x along, y up, z toward the head) to
        world, through `basis` (the placement's own by default)."""
        B = self.basis if basis is None else basis
        P = np.asarray(pts_norm, dtype=np.float64) - self.axis_local
        return self.origin + P @ B.T

    def bent(self, flat_xy, depth_in: float) -> np.ndarray:
        """A flat (s, up) ring at a depth through the thickness (0 the
        core, +t/2 the hinge face), bent, in normalized coordinates."""
        Q = np.asarray(flat_xy, dtype=np.float64)
        return self.bend3d.map(np.column_stack([Q[:, 0], Q[:, 1], np.full(len(Q), depth_in)]))

    def rings_in(self, basis) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(outer ring, inner ring, core) placed through another basis: the
        folded temple, for one. Not butt cut."""
        t = self.thickness_mm
        outer = self.to_world(self.bent(self.outline_norm, -0.5 * t), basis)
        inner = self.to_world(self.bent(self.outline_norm, 0.5 * t), basis)
        n = max(int(math.ceil(self.bend.overall_mm)), 2)
        core = np.column_stack([np.linspace(0.0, self.bend.overall_mm, n), np.zeros(n)])
        return outer, inner, self.to_world(self.bent(core, 0.0), basis)

    def mesh(self):
        """The temple as a closed trimesh: the flat outline extruded, bent,
        placed and cut by the endpiece's back face; None without an outline."""
        import trimesh
        from shapely.geometry import Polygon as _P

        if len(self.outline_norm) < 3:
            return None
        poly = _P([(float(x), float(y)) for x, y in self.outline_norm])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon":
            return None
        t = self.thickness_mm
        m = trimesh.creation.extrude_polygon(poly, t)
        V = np.asarray(m.vertices, dtype=np.float64)
        V = np.column_stack([V[:, 0], V[:, 1], V[:, 2] - 0.5 * t])   # the core at mid-thickness
        verts = self.to_world(self.bend3d.map(V))
        faces = np.asarray(m.faces)
        if np.linalg.det(self.basis) < 0:          # the left's basis is a mirror
            faces = faces[:, ::-1]
        out = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        if self.butt_cut:
            try:
                cut = trimesh.intersections.slice_mesh_plane(
                    out, plane_normal=self.face_normal, plane_origin=self.face_point, cap=True)
                if cut is not None and len(cut.faces) > 0:
                    out = cut
            except Exception:                                   # noqa: BLE001
                pass
        return out


def folded_basis(lateral: float) -> np.ndarray:
    """The basis of a temple folded across the back: along toward the
    center line, up up, the hinge face toward the front."""
    X = np.array([-lateral, 0.0, 0.0])
    Y = np.array([0.0, 1.0, 0.0])
    Z = lateral * np.cross(X, Y)
    return np.column_stack([X, Y, Z])


@dataclass
class SideResult:
    """One side of the frame: the pocket, the axis and the temple."""
    lateral: float                  # +1 OD (x > 0), -1 OS
    kind: ComponentKind
    pocket: PocketFit | None
    temple_pocket: PocketFit | None
    axis_point: np.ndarray          # world
    axis_dir: np.ndarray            # world, unit, up along the barrel
    face_point: np.ndarray          # the pocket's center on the endpiece's back face, world
    frame: tuple                    # (e_x, e_y, n) at the pocket, world, unit
    surface_turn_deg: float         # the endpiece's turn toward the wearer, from the map
    surface_tilt_deg: float         # the endpiece's lean, top toward the wearer, from the map
    floor_angle_deg: float          # the front pocket's floor angle
    temple_pocket_angle_deg: float
    slant_deg: float
    side_from_hinge_deg: float      # the angle of side the hinge alone gives
    splay_from_hinge_deg: float  # the splay the hinge alone gives
    side_target_deg: float
    splay_target_deg: float
    temple: TemplePlacement | None
    joint_height_mm: float          # the axis above the boxed center line, flat
    hinge: HingeFill
    front_leaf: object = None       # HingeLeaf: the drawn front pocket, for the detail
    temple_leaf: object = None      # HingeLeaf: the drawn temple pocket
    axis_inset_mm: float = 0.0      # the end face to the axis, along the front

    @property
    def panto_cut_deg(self) -> float:
        """What the butt is cut by, in the side view: the target less what
        the endpiece's own back face already leans."""
        return self.side_target_deg - self.surface_tilt_deg

    @property
    def splay_cut_deg(self) -> float:
        """What the butt is cut by, in the top view: the target plus what the
        endpiece's turn takes back."""
        return self.splay_target_deg + self.surface_turn_deg

    @property
    def floor_angle_for_target(self) -> float:
        """The pocket floor angle that makes the hinge agree with the target."""
        return self.side_target_deg - self.surface_tilt_deg - self.slant_deg

    @property
    def label(self) -> str:
        return "R" if self.lateral > 0 else "L"


@dataclass
class Check:
    name: str
    ok: bool
    text: str


@dataclass
class DraftAssembly:
    front: FrontInput
    forming: FormingMetadata
    draft: DraftParams
    fmap: ThermoformMap
    thickness_mm: float
    sides: dict                       # lateral -> SideResult
    outline_rings: list               # the OUTLINE bodies' exteriors, anterior, world (N,3)
    posterior_rings: list             # the same at the rim's back face
    lens_rings: list                  # the LENS apertures, anterior
    terrace_rings: list               # (name, ring at its own height), from the partition
    pocket_rings: list                # the COMPONENT pockets on the back face
    checks: list
    notes: list
    terrace_pairs: list = field(default_factory=list)   # (ring at the rim's back, ring at its height)
    zone_edges: list = field(default_factory=list)      # the SCULPT cuts between the zones, on the back
    # The formed front as a closed trimesh and its feature edges (chained
    # polylines, world), when the front came with its built mesh.
    front_mesh: object = None
    front_edges: list = field(default_factory=list)
    _temple_meshes: list | None = field(default=None, repr=False)
    _depth_views: dict = field(default_factory=dict, repr=False)

    def form(self, pts) -> np.ndarray:
        """Flat (N, 3) -> formed, the neutral surface applied around the map
        (`forming.neutral_map`)."""
        P = np.asarray(pts, dtype=np.float64)
        if len(P) == 0:
            return P.reshape(0, 3)
        return neutral_map(self.fmap, self.forming, self.thickness_mm)(P)

    @property
    def right(self) -> SideResult | None:
        return self.sides.get(1.0)

    @property
    def left(self) -> SideResult | None:
        return self.sides.get(-1.0)

    def ordered_sides(self) -> list:
        return [s for s in (self.right, self.left) if s is not None]

    def temple_meshes(self) -> list:
        if self._temple_meshes is None:
            out = []
            for s in self.ordered_sides():
                if s.temple is not None:
                    m = s.temple.mesh()
                    if m is not None:
                        out.append(m)
            self._temple_meshes = out
        return list(self._temple_meshes)

    def scene_meshes(self) -> list:
        """The formed front (when built) and the temples, for a depth test."""
        return ([self.front_mesh] if self.front_mesh is not None else []) + self.temple_meshes()

    @property
    def has_solid(self) -> bool:
        return self.front_mesh is not None

    def depth_view(self, key, project3):
        """The depth buffer of the scene in a view's direction, built once
        per key (`draft.hidden.DepthView`)."""
        dv = self._depth_views.get(key)
        if dv is None:
            from .hidden import DepthView
            dv = DepthView(project3)
            for m in self.scene_meshes():
                dv.add(m.vertices, m.faces)
            self._depth_views[key] = dv
        return dv

    def silhouette_edges(self, direction) -> list:
        """The formed front's silhouette seen along `direction` (toward the
        viewer): the mesh edges whose two faces face opposite ways, chained."""
        m = self.front_mesh
        if m is None:
            return []
        from .hidden import chain_segments
        d = _unit(np.asarray(direction, dtype=np.float64))
        n = np.asarray(m.face_normals)
        adj = np.asarray(m.face_adjacency)
        if len(adj) == 0:
            return []
        s1, s2 = n[adj[:, 0]] @ d, n[adj[:, 1]] @ d
        on = (s1 * s2) < 0
        edges = np.asarray(m.face_adjacency_edges)[on]
        V = np.asarray(m.vertices)
        return chain_segments(V[edges])


# ------------------------------------------------------------------ the build

_H_MM = 0.5     # the finite-difference step for the local frame


def _local_frame(form, p_flat) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(e_x, e_y, n) at a flat point: the formed surface's tangents along x
    and y and its normal toward the wearer, unit."""
    p = np.asarray(p_flat, dtype=np.float64)
    dx, dy = np.array([_H_MM, 0, 0]), np.array([0, _H_MM, 0])
    pts = form(np.array([p + dx, p - dx, p + dy, p - dy]))
    e_x = _unit(pts[0] - pts[1])
    e_y = _unit(pts[2] - pts[3])
    n = _unit(np.cross(e_x, e_y))
    return e_x, e_y, n


def _rotate_about(v, axis, deg) -> np.ndarray:
    """Rodrigues: v turned about the unit axis by deg."""
    a = _unit(axis)
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    v = np.asarray(v, dtype=np.float64)
    return v * c + np.cross(a, v) * s + a * float(a @ v) * (1 - c)


def _is_hinge_pocket(i: int, kinds: list) -> bool:
    """A COMPONENT curve placed from any folder but Bridges, or drawn by hand,
    is read as a hinge pocket; a bridge's mount is not."""
    kind = kinds[i] if i < len(kinds) else None
    return not (isinstance(kind, str) and kind.strip().lower() == "bridges")


def _front_pockets(front: FrontInput, floors) -> dict:
    """The hinge pocket per side: the outermost usable one on each half,
    with its floor."""
    out: dict = {}
    for i, poly in enumerate(front.hinge_polys):
        if poly is None or poly.is_empty or not _is_hinge_pocket(i, front.component_kinds):
            continue
        floor = floors[i] if i < len(floors) else None
        if floor is None:
            continue
        cx = float(poly.centroid.x)
        lateral = 1.0 if cx >= 0 else -1.0
        best = out.get(lateral)
        if best is None or abs(cx) > abs(float(best[0].centroid.x)):
            out[lateral] = (poly, floor)
    return out


def _temple_pocket(temple: TempleInput):
    """The temple's hinge pocket: the one nearest its hinge end, with its floor."""
    if temple.outline is None or not temple.hinge_polys:
        return None, None
    x_hinge, along, _down = temple_axes(temple.outline, temple.hinge_polys, temple.kind)
    floors = temple_pocket_floors(temple.hinge_polys, temple.params, temple.outline)
    if not floors:
        return None, None
    poly, floor = min(floors, key=lambda pf: abs(float(pf[0].centroid.x) - x_hinge))
    return poly, floor


def _place_temple(side_lateral: float, temple: TempleInput, pocket: PocketFit | None,
                  floor, fill: HingeFill, axis_point: np.ndarray, basis: np.ndarray,
                  face_point: np.ndarray, face_normal: np.ndarray) -> TemplePlacement | None:
    if temple.outline is None or temple.outline.is_empty:
        return None
    outline = temple.outline if isinstance(temple.outline, Polygon) else max(
        _bodies(temple.outline), key=lambda p: p.area)
    p = temple.params
    bend = resolve_tip_bend(p.tip_bend, outline, temple.hinge_polys, temple.kind)
    x_hinge, along, down = bend.x_hinge, bend.along, bend.down
    t = float(p.blank_thickness_mm)
    tb = p.tip_bend
    bend3d = TempleBend3D(bend, float(tb.inward_angle_deg) if bend.overall_mm > 0 else 0.0,
                          float(tb.inward_start_mm))

    def norm2(xy):
        """The temple's drawn frame -> normalized (s along, up), unbent."""
        xy = np.asarray(xy, dtype=np.float64)
        return np.column_stack([(xy[:, 0] - x_hinge) * along, -(xy[:, 1] - bend.core_y) * down])

    # the axis in the temple's frame: beyond the butt by the setback, beyond
    # the hinge face by the offset, at the pocket's height across; before
    # the bends begin, so unbent
    y_c = pocket.center[1] if pocket is not None else bend.core_y
    axis_local = np.array([-fill.axis_setback_mm, -(y_c - bend.core_y) * down,
                           0.5 * t + fill.spec.axis_offset_mm])
    outline_norm = norm2(_ring_xy(outline))
    pockets_norm = [norm2(_ring_xy(hp)) for hp in temple.hinge_polys
                    if hp is not None and not hp.is_empty]
    placement = TemplePlacement(
        kind=temple.kind, bend=bend, bend3d=bend3d,
        origin=np.asarray(axis_point, dtype=np.float64),
        basis=basis, axis_local=axis_local, thickness_mm=t,
        outline_norm=outline_norm, pockets_norm=pockets_norm,
        outer_ring=np.zeros((0, 3)), inner_ring=np.zeros((0, 3)), pocket_rings=[],
        core=np.zeros((0, 3)), ear_point=np.zeros(3), tip=np.zeros(3),
        butt_cut=False, bend_note=bend.out_of_range() if not bend.is_straight else None,
        face_point=np.asarray(face_point, dtype=np.float64),
        face_normal=_unit(face_normal))

    outer, inner, core = placement.rings_in(basis)
    n_face = placement.face_normal
    placement.butt_cut = bool(min(float(((outer - face_point) @ n_face).min()),
                                  float(((inner - face_point) @ n_face).min())) < -1e-6)
    placement.outer_ring = clip_ring(outer, face_point, n_face)
    placement.inner_ring = clip_ring(inner, face_point, n_face)
    for pn in pockets_norm:
        pr = placement.to_world(placement.bent(pn, 0.5 * t))
        placement.pocket_rings.append(clip_ring(pr, face_point, n_face))
    placement.core = core
    placement.ear_point = placement.to_world(
        placement.bent([[bend.length_to_bend_mm, 0.0]], 0.0))[0]
    placement.tip = placement.to_world(placement.bent([[bend.overall_mm, 0.0]], 0.0))[0]
    return placement


def front_silhouette(asm: "DraftAssembly", project, axis: str = "x", step_mm: float = 1.5) -> list:
    """The front's outline as seen in a view: the formed body sliced along
    `axis` ("x" for a plan, "y" for a side view), each slice's material
    carried from the anterior face to its own back (the zone's height) and
    projected by `project` (world (N, 3) -> (N, 2)); the union of the
    slices' hulls, one closed polyline per boundary, holes included."""
    from shapely.geometry import LineString, MultiPoint, Point
    from shapely.ops import unary_union

    body = asm.front.outline
    if body is None or body.is_empty:
        return []
    zones = getattr(asm.front.castle, "zones", None)
    part = asm.front.partition
    heights = []
    if part is not None and zones is not None:
        for z in getattr(part, "zones", []):
            try:
                heights.append((z.polygon, float(zones.for_kind(z.kind))))
            except AttributeError:
                continue
    rim_z = float(getattr(zones, "eyewire_superior_mm", asm.thickness_mm)) if zones else asm.thickness_mm

    def back_z(x, y):
        # a point on a zone's boundary belongs to the taller zone it touches
        pt = Point(x, y).buffer(0.05)
        hs = [h for poly, h in heights if poly.intersects(pt)]
        return max(hs) if hs else rim_z

    minx, miny, maxx, maxy = body.bounds
    lo, hi = (minx, maxx) if axis == "x" else (miny, maxy)
    levels = np.arange(lo, hi + step_mm, step_mm)
    slices = []          # per level: one projected point set per segment of material
    for c in levels:
        line = (LineString([(c, miny - 1.0), (c, maxy + 1.0)]) if axis == "x"
                else LineString([(minx - 1.0, c), (maxx + 1.0, c)]))
        cut = line.intersection(body)
        segs = []
        for g in getattr(cut, "geoms", [cut]):
            if g.is_empty or g.geom_type != "LineString":
                continue
            (a0, a1), (b0, b1) = g.coords[0], g.coords[-1]
            n = max(int(math.hypot(b0 - a0, b1 - a1) / 1.5) + 2, 2)
            xs = np.linspace(a0, b0, n)
            ys = np.linspace(a1, b1, n)
            # the heights are read a hair inside the segment's ends, which
            # lie on the outline where a zone's edge is a coin toss
            ux, uy = b0 - a0, b1 - a1
            L = math.hypot(ux, uy) or 1.0
            ux, uy = ux / L, uy / L
            nudge = min(0.1, 0.25 * L)
            zs = np.array([back_z(x + ux * (nudge if i == 0 else -nudge if i == n - 1 else 0.0),
                                  y + uy * (nudge if i == 0 else -nudge if i == n - 1 else 0.0))
                           for i, (x, y) in enumerate(zip(xs, ys))])
            flat = np.vstack([np.column_stack([xs, ys, np.zeros(n)]),
                              np.column_stack([xs, ys, zs])])
            segs.append(project(asm.form(flat)))
        slices.append(segs)
    polys = []
    for i in range(len(slices)):
        for pts in slices[i]:
            polys.append(MultiPoint([tuple(p) for p in pts]).convex_hull.buffer(0.05))
        if i + 1 < len(slices):
            # bridge to the next slice so the band has no gaps
            for pts in slices[i]:
                for nxt in slices[i + 1]:
                    both = np.vstack([pts, nxt])
                    polys.append(MultiPoint([tuple(p) for p in both]).convex_hull.buffer(0.05))
    if not polys:
        return []
    u = unary_union(polys).buffer(-0.05).simplify(0.05)
    out = []
    for g in getattr(u, "geoms", [u]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        # the boundary only: a hole in the union is a gap between slices,
        # not a hole through the front
        out.append(np.asarray(g.exterior.coords)[:-1])
    return out


def build_assembly(front: FrontInput, temples: list, draft: DraftParams,
                   forming: FormingMetadata | None = None) -> DraftAssembly:
    """The assembly of a front and its temples. `forming` defaults to the
    front's own; the draft's hinge and splay come from `draft`."""
    forming = forming if forming is not None else front.forming
    castle = front.castle
    thickness = float(getattr(getattr(castle, "stock", None), "blank_thickness_mm", 6.0) or 6.0)
    bridge = bridge_geometry(front.partition, front.lens_od, front.lens_os)
    fmap = ThermoformMap.from_metadata(forming, bridge=bridge)

    asm = DraftAssembly(front=front, forming=forming, draft=draft, fmap=fmap,
                        thickness_mm=thickness, sides={}, outline_rings=[],
                        posterior_rings=[], lens_rings=[], terrace_rings=[],
                        pocket_rings=[], checks=[], notes=[])
    form = asm.form
    if front.mesh is not None:
        # the built front formed, closed, with its creases as edges: what
        # the views draw when they can
        try:
            from guildmodel.core.forming import FormingMesh
            from .hidden import chain_segments
            nmap = neutral_map(fmap, forming, thickness)
            fm = FormingMesh(front.mesh)
            asm.front_mesh = fm.formed(nmap)
            asm.front_edges = chain_segments(fm.formed_edges(nmap))
        except Exception as exc:                                  # noqa: BLE001
            asm.notes.append(f"The built front could not be formed for the views ({exc}); "
                             "they are composed from the drawing's curves.")
            asm.front_mesh = None
            asm.front_edges = []

    # the front's rings
    zones = getattr(castle, "zones", None)
    rim_z = float(getattr(zones, "eyewire_superior_mm", 4.8)) if zones is not None else thickness
    endpiece_z = float(getattr(zones, "endpiece_mm", 5.5)) if zones is not None else thickness
    for body in _bodies(front.outline):
        ring = _ring_xy(body)
        asm.outline_rings.append(form(np.column_stack([ring, np.zeros(len(ring))])))
        asm.posterior_rings.append(form(np.column_stack([ring, np.full(len(ring), rim_z)])))
    for lens in (front.lens_od, front.lens_os):
        if lens is not None and not lens.is_empty:
            ring = _ring_xy(lens)
            asm.lens_rings.append(form(np.column_stack([ring, np.zeros(len(ring))])))
    part = front.partition
    if part is not None and zones is not None:
        for e in getattr(part, "edges", []):
            cut = getattr(e, "cut", None)
            if cut is None:
                continue
            try:
                inside = cut.intersection(front.outline)
            except Exception:                                   # noqa: BLE001
                continue
            for g in getattr(inside, "geoms", [inside]):
                if g.is_empty or g.geom_type != "LineString" or len(g.coords) < 2:
                    continue
                pts = np.asarray(g.coords, dtype=np.float64)
                asm.zone_edges.append(form(np.column_stack([pts, np.full(len(pts), rim_z)])))
        for z in getattr(part, "zones", []):
            try:
                h = zones.for_kind(z.kind)
            except AttributeError:
                continue
            for body in _bodies(z.polygon):
                ring = _ring_xy(body)
                asm.terrace_rings.append(
                    (z.name, form(np.column_stack([ring, np.full(len(ring), h)]))))
                if h > rim_z + 1e-6:
                    asm.terrace_pairs.append(
                        (form(np.column_stack([ring, np.full(len(ring), rim_z)])),
                         form(np.column_stack([ring, np.full(len(ring), h)]))))

    # the pockets and their floors
    heights = None
    if part is not None and zones is not None:
        try:
            heights = {z.name: zones.for_kind(z.kind) for z in part.zones}
        except AttributeError:
            heights = None
    pairs = castle_pocket_floors(front.hinge_polys, castle, part, heights) if castle is not None else []
    floors_by_id = {id(p): f for p, f in pairs}
    floors = [floors_by_id.get(id(p)) for p in front.hinge_polys]
    for i, poly in enumerate(front.hinge_polys):
        if floors[i] is None:
            continue
        ring = _ring_xy(poly)
        z = np.asarray(floors[i].z(ring[:, 0], ring[:, 1]), dtype=np.float64)
        z = z + float(getattr(castle, "hinge_pocket_depth_mm", 1.0))
        asm.pocket_rings.append(form(np.column_stack([ring, z])))

    # the boxed center line, for the joint height
    center_y = 0.0
    if front.lens_od is not None and front.lens_os is not None:
        b1, b2 = front.lens_od.bounds, front.lens_os.bounds
        center_y = 0.25 * (b1[1] + b1[3] + b2[1] + b2[3])

    by_kind = {ComponentKind(t.kind): t for t in temples if t.enabled}
    pockets = _front_pockets(front, floors)
    depth_f = float(getattr(castle, "hinge_pocket_depth_mm", 1.0)) if castle is not None else 1.0
    floor_angle = float(getattr(castle, "hinge_pocket_angle_deg", 0.0)) if castle is not None else 0.0
    side_target = float(forming.pantoscopic_tilt_deg)
    splay_target = float(draft.splay_deg)

    for lateral in (1.0, -1.0):
        kind = ComponentKind.TEMPLE_RIGHT if lateral > 0 else ComponentKind.TEMPLE_LEFT
        temple = by_kind.get(kind)
        got = pockets.get(lateral)
        if got is None:
            # no pocket drawn on this side: the hinge sits at the outline's
            # extreme at the lens centers' height, and the view says so
            if front.outline is None or front.outline.is_empty:
                continue
            b = front.outline.bounds
            x_edge = b[2] if lateral > 0 else b[0]
            fit = PocketFit(center=(x_edge - lateral * 6.0, center_y + 5.0), along_axis_mm=10.0,
                            across_mm=4.0, axis_angle_deg=0.0, direction=(lateral, 0.0),
                            datum=(x_edge, center_y + 5.0), setback_mm=2.0, found=False)
            floor = None
            asm.notes.append(f"No hinge pocket drawn on the {'right' if lateral > 0 else 'left'}; "
                             "the hinge is assumed at the endpiece's edge.")
        else:
            poly, floor = got
            fit = fit_pocket(poly, front.outline, (lateral, 0.0))
            if not fit.found:
                asm.notes.append(f"The {'right' if lateral > 0 else 'left'} pocket's ray never "
                                 "left the outline; the butt face is taken at the pocket's edge.")
        t_poly, t_floor = _temple_pocket(temple) if temple is not None else (None, None)
        t_fit = None
        if t_poly is not None and temple is not None:
            x_hinge, along, _down = temple_axes(temple.outline, temple.hinge_polys, temple.kind)
            t_fit = fit_pocket(t_poly, temple.outline, (-along, 0.0))
        depth_t = float(temple.params.hinge_pocket_depth_mm) if temple is not None else 1.0
        fill = fill_hinge(draft.hinge, fit, t_fit, depth_f, depth_t)

        # the axis in the flat frame: a temple's thickness (and the inset)
        # inside the endpiece's end face, on its back face; and the local
        # frame at the pocket
        cx, cy = fit.center
        z_post = endpiece_z
        dx, dy = fit.direction
        t_temple = float(temple.params.blank_thickness_mm) if temple is not None else 4.0
        inset = float(draft.hinge.temple_inset_mm) + t_temple + float(draft.hinge.axis_offset_mm)
        axis_flat = np.array([fit.datum[0] - dx * inset,
                              fit.datum[1] - dy * inset,
                              z_post + fill.spec.axis_offset_mm])
        e_x, e_y, n = _local_frame(form, np.array([cx, cy, z_post]))
        axis_point = form(axis_flat[None, :])[0]
        face_point = form(np.array([[cx, cy, z_post]]))[0]
        # the endpiece's turn toward the wearer: its lateral tangent's climb
        turn = math.degrees(math.asin(max(-1.0, min(1.0, lateral * float(e_x[2])))))
        # its lean, top toward the wearer: the vertical tangent against the
        # normal's horizontal part (the surface's own normal at the lens
        # centers' height)
        n_h = _unit(np.array([float(n[0]), 0.0, float(n[2])]))
        tilt = math.degrees(math.atan2(float(e_y @ n_h), float(e_y[1])))
        slant = float(draft.hinge.slant_deg)
        axis_dir = _unit(_rotate_about(e_y, e_x, floor_angle + slant))
        side_h = math.degrees(math.atan2(float(axis_dir[2]), float(axis_dir[1])))
        t_angle = float(temple.params.hinge_pocket_angle_deg) if temple is not None else 0.0
        splay_h = (float(draft.hinge.open_deg) - 90.0) - turn - t_angle

        # the temple's basis at the targets
        R = rotation("y", lateral * splay_target) @ rotation("x", side_target)
        X = R @ np.array([0.0, 0.0, 1.0])
        Y = R @ np.array([0.0, 1.0, 0.0])
        Z = lateral * np.cross(X, Y)
        basis = np.column_stack([X, Y, Z])
        placement = None
        if temple is not None:
            placement = _place_temple(lateral, temple, t_fit, t_floor, fill, axis_point,
                                      basis, face_point, n)
        # the pockets as drawn, for the hinge detail: the front's in the
        # flat frame, the temple's in its normalized frame (s along from
        # the hinge end, up), each read toward its butt face
        front_leaf = temple_leaf = None
        if got is not None:
            front_leaf = leaf_from_pocket(_ring_xy(poly), (dx, dy), (0.0, 1.0), fit.setback_mm,
                                          z_post, depth_f)
        if placement is not None and t_poly is not None and t_fit is not None:
            valid = [hp for hp in temple.hinge_polys if hp is not None and not hp.is_empty]
            idx = next((j for j, hp in enumerate(valid) if hp is t_poly), None)
            if idx is not None and idx < len(placement.pockets_norm):
                temple_leaf = leaf_from_pocket(placement.pockets_norm[idx], (-1.0, 0.0),
                                               (0.0, 1.0), t_fit.setback_mm, t_temple, depth_t)
        asm.sides[lateral] = SideResult(
            lateral=lateral, kind=kind, pocket=fit if got is not None else None,
            temple_pocket=t_fit, axis_point=axis_point, axis_dir=axis_dir,
            face_point=face_point, frame=(e_x, e_y, n),
            surface_turn_deg=turn, surface_tilt_deg=tilt, floor_angle_deg=floor_angle,
            temple_pocket_angle_deg=t_angle, slant_deg=slant,
            side_from_hinge_deg=side_h, splay_from_hinge_deg=splay_h,
            side_target_deg=side_target, splay_target_deg=splay_target,
            temple=placement, joint_height_mm=float(axis_flat[1] - center_y), hinge=fill,
            front_leaf=front_leaf, temple_leaf=temple_leaf, axis_inset_mm=inset)

    asm.checks = _checks(asm, endpiece_z, depth_f)
    return asm


# ------------------------------------------------------------------ the checks

def _lens_plane_elevation(asm: DraftAssembly, lens) -> float | None:
    """The lens plane's normal's lean from the horizontal, degrees."""
    if lens is None or lens.is_empty:
        return None
    c = lens.centroid
    _e_x, _e_y, n = _local_frame(asm.form, np.array([float(c.x), float(c.y), 0.0]))
    return math.degrees(math.asin(max(-1.0, min(1.0, float(n[1])))))


def _checks(asm: DraftAssembly, endpiece_z: float, depth_f: float) -> list:
    out = []
    tol = float(asm.draft.side_tolerance_deg)
    R, L = asm.right, asm.left
    if R is not None and L is not None:
        d = abs(R.side_from_hinge_deg - L.side_from_hinge_deg)
        out.append(Check("Angle of side, L against R", d <= tol,
                         f"hinges give {R.side_from_hinge_deg:.1f}° / {L.side_from_hinge_deg:.1f}°, "
                         f"Δ {d:.1f}° ({'within' if d <= tol else 'over'} {tol:g}°)"))
        d = abs(R.splay_from_hinge_deg - L.splay_from_hinge_deg)
        out.append(Check("Splay symmetric", d <= tol,
                         f"hinges give {R.splay_from_hinge_deg:.1f}° / "
                         f"{L.splay_from_hinge_deg:.1f}°, Δ {d:.1f}°"))
        dy = abs(float(R.axis_point[1] - L.axis_point[1]))
        dz = abs(float(R.axis_point[2] - L.axis_point[2]))
        out.append(Check("Four-point touch", dy <= 0.5 and dz <= 0.5,
                         f"joints {dy:.2f} mm apart in height, {dz:.2f} mm in depth"))
        if R.temple is not None and L.temple is not None:
            if R.temple.bend_note or L.temple.bend_note:
                out.append(Check("Tips on a common plane", False,
                                 "a tip bend is out of range"))
            else:
                dt = abs(float(R.temple.tip[1] - L.temple.tip[1]))
                de = abs(float(R.temple.ear_point[1] - L.temple.ear_point[1]))
                out.append(Check("Tips on a common plane", dt <= 1.0 and de <= 1.0,
                                 f"tips {dt:.2f} mm apart, ear points {de:.2f} mm"))
    eo, es = (_lens_plane_elevation(asm, asm.front.lens_od),
              _lens_plane_elevation(asm, asm.front.lens_os))
    if eo is not None and es is not None:
        d = abs(eo - es)
        out.append(Check("No X-ing", d <= 0.5,
                         f"lens planes lean {eo:.2f}° / {es:.2f}°, Δ {d:.2f}°"))
    # folded temples: across the back at the axis height; cross centrally,
    # and clear the front's back face
    for s in asm.ordered_sides():
        if s.temple is None or s.temple.bend is None:
            continue
        reach = s.temple.bend.length_to_bend_mm + 0.5 * s.temple.bend.arc_mm
        reach = reach if s.temple.bend.applies else s.temple.bend.overall_mm
        span = abs(float(s.axis_point[0]))
        crosses = reach >= span
        # the clearance of the folded temple's hinge face over the back face,
        # sampled from 10 mm in to the center line
        z_face = float(s.axis_point[2]) - s.hinge.spec.axis_offset_mm
        xs = np.linspace(s.lateral * max(span - 10.0, 0.0), 0.0, 24)
        y = s.pocket.center[1] if s.pocket is not None else 0.0
        back = asm.form(np.column_stack([xs, np.full(len(xs), y), np.full(len(xs), endpiece_z)]))
        clearance = float(np.min(z_face - back[:, 2]))
        ok = crosses and clearance >= -0.05
        out.append(Check(f"Folded temple {s.label}", ok,
                         f"reaches {reach:.0f} of {span:.0f} mm to the center, clears the back "
                         f"by {clearance:.1f} mm"))
    return out
