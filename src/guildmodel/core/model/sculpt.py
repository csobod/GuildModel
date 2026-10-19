"""Sculpts: an STL dropped on the frame, repaired, mounted and baked in
(BUILDPLAN M22 §7.2).

A sculpt is a mesh the maker made elsewhere — a crest, a rivet head, a
plaque, a scooped channel — and wants on the frame as material added
(*emboss*) or taken away (*deboss*). This module is the kernel side of that,
Qt-free and importable headless:

* **Import.** `load_sculpt` reads the bytes with trimesh, splits the soup
  into shells, welds each through Manifold's merge map, flips a shell whose
  winding is inside out, hands a shell Manifold rejects to pymeshfix, and
  unions the shells. A shell nothing can mend is offered as its hull, and
  the record says so. Two traps the constructor does not catch, both
  tested: a self-intersecting single shell constructs with NoError and the
  wrong volume (so the shells are split first, always), and a sculpt
  hovering a hair off the host unions into two bodies (`contact_gap`).
* **The flat back.** `flat_back` ranks the candidate mounting faces: the
  exactly planar facets of a sculpt cut by a plane (the common case), or,
  on a scanned back, a plane grown from coarse normal bins, a robust plane
  per bin, connected components and a PCA refit.
* **Mounting.** `snap_target` reads where the back goes on the host —
  anterior, posterior, the rim wall, or a picked point — and
  `mount_transform` builds the 4 x 4 that puts the back there, sunk by
  `overlap_mm` so the union is one body. `sag_under` reads how far the host
  falls away under the back's footprint, which sets the default overlap.
* **Baking.** `bake` unions the embosses, then subtracts the debosses, so a
  deboss can cut an emboss; the result is degenerate-dropped like every
  other model. `mirror_twin` is the x-mirrored sculpt, derived and never
  stored. `undercuts` reports what a three-axis tool cannot reach after the
  bake.

The transform a feature stores is the whole placement of the source mesh
into the castle frame, scale included; the snap computes it once and the
viewer's widget edits it after.
"""
from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import Error, Manifold, Mesh64, OpType

from .kernel import ManifoldError, drop_degenerate, surface_z_at, to_trimesh

__all__ = [
    "BackCandidate", "PlacedSculpt", "SculptSource", "SnapTarget", "UndercutReport",
    "SIMPLIFY_ABOVE", "bake", "contact_gap", "flat_back", "load_sculpt",
    "manifold_from_arrays", "mirror_twin", "mount_transform", "placed_sculpts",
    "sag_under", "snap_target", "undercuts",
]

#: A sculpt with more triangles than this is offered `simplify` on import.
SIMPLIFY_ABOVE = 250_000
#: How far a back plane's inlier may sit off it, mm, on a scanned back, and
#: how far a face on it may lean before it is read as the wall beside it. The
#: lean is loose on purpose: a sliver triangle on a capped back tilts by ten
#: degrees under ten microns of noise, so the distance test does the work.
PLANE_DIST_MM = 0.05
PLANE_ANGLE_DEG = 60.0
#: The least overlap that makes a union one body; measured on a flat back
#: tangent to a curved host, which unions into two bodies at zero.
MIN_OVERLAP_MM = 0.05
#: A gap wider than this between the placed sculpt and the host is a hover.
HOVER_MM = 1e-6


# ------------------------------------------------------------------ records

@dataclass
class SculptSource:
    """One imported sculpt: its solid, its mesh, and what import did to it."""
    manifold: Manifold
    mesh: object                       # trimesh.Trimesh of `manifold`
    name: str = ""
    sha256: str = ""
    triangles: int = 0
    shells: int = 1
    repaired: int = 0                  # shells pymeshfix mended
    hulled: int = 0                    # shells replaced by their hull
    flipped: int = 0                   # shells whose winding was inside out
    simplify_tol: float = 0.0

    @property
    def volume(self) -> float:
        return float(self.manifold.volume())

    def notes(self) -> list[str]:
        out = []
        if self.shells > 1:
            out.append(f"{self.shells} shells unioned")
        if self.flipped:
            out.append(f"{self.flipped} inside-out, flipped")
        if self.repaired:
            out.append(f"{self.repaired} repaired")
        if self.hulled:
            out.append(f"{self.hulled} replaced by its hull")
        if self.simplify_tol > 0:
            out.append(f"simplified to {self.simplify_tol:g} mm")
        return out


@dataclass
class BackCandidate:
    """A candidate mounting face: a plane through `point` with outward
    `normal`, the faces on it, their area, and how it was found."""
    normal: np.ndarray
    point: np.ndarray
    area: float
    faces: np.ndarray
    exact: bool = True

    def boundary_points(self, mesh) -> np.ndarray:
        """The vertices on the back's rim: those of its faces that an edge
        shared with a face off the back touches. Falls back to every vertex
        of the back when the back is the whole mesh."""
        faces = np.asarray(mesh.faces)[self.faces]
        on = np.zeros(len(mesh.faces), dtype=bool)
        on[self.faces] = True
        adj = np.asarray(mesh.face_adjacency)
        edges = np.asarray(mesh.face_adjacency_edges)
        cross = on[adj[:, 0]] != on[adj[:, 1]]
        verts = np.unique(edges[cross]) if cross.any() else np.unique(faces)
        return np.asarray(mesh.vertices)[verts]


@dataclass
class SnapTarget:
    """Where a back goes on the host: a point and the host's outward normal
    there, and which face it is."""
    face: str
    point: np.ndarray
    normal: np.ndarray


@dataclass
class PlacedSculpt:
    """A sculpt transformed into the castle frame, ready to bake."""
    manifold: Manifold
    op: str                            # emboss | deboss
    feature_id: str = ""
    mirrored: bool = False


@dataclass
class UndercutReport:
    area_mm2: float
    faces: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))

    def __bool__(self) -> bool:
        return self.area_mm2 > 0.0


# ------------------------------------------------------------------ import

def manifold_from_arrays(vertices, faces) -> Manifold:
    """A Manifold from a triangle soup, welded by the merge map rather than by
    rounding positions (the rule `kernel.to_trimesh` states from the other
    side). Returns whatever the constructor made; the caller reads `status`."""
    v = np.ascontiguousarray(np.asarray(vertices, dtype=np.float64)[:, :3])
    f = np.ascontiguousarray(np.asarray(faces, dtype=np.int64)).astype(np.uint64)
    mesh = Mesh64(vert_properties=v, tri_verts=f)
    mesh.merge()
    return Manifold(mesh)


def _shells(mesh) -> list:
    """The mesh's connected components as meshes, open or not. Not
    `Trimesh.split`, whose submesh step tries to fill every hole on the way
    (and wants networkx for it); the shells go to the repair step as they are."""
    import trimesh

    if len(mesh.faces) == 0:
        return [mesh]
    comps = trimesh.graph.connected_components(
        edges=mesh.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1,
        engine="scipy")
    if len(comps) <= 1:
        return [mesh]
    return list(mesh.submesh(comps, repair=False, only_watertight=False, append=False))


def _shell_solid(shell) -> tuple[Manifold | None, dict]:
    """One shell as a solid: constructed, flipped if inside out, repaired by
    pymeshfix when Manifold rejects it, or None when nothing helped."""
    info = {"flipped": 0, "repaired": 0, "hulled": 0}
    v = np.asarray(shell.vertices, dtype=np.float64)
    f = np.asarray(shell.faces, dtype=np.int64)
    if len(f) < 4:
        return None, info
    man = manifold_from_arrays(v, f)
    if man.status() == Error.NoError and man.volume() < 0:
        man = manifold_from_arrays(v, f[:, ::-1])
        info["flipped"] = 1
    if man.status() != Error.NoError or man.is_empty():
        try:
            import pymeshfix
            fix = pymeshfix.MeshFix(v, f)
            fix.repair(joincomp=False, remove_smallest_components=False)
            rv = np.asarray(fix.points, dtype=np.float64)
            rf = np.asarray(fix.faces, dtype=np.int64)
            if len(rf) >= 4:
                cand = manifold_from_arrays(rv, rf)
                if cand.status() == Error.NoError and cand.volume() < 0:
                    cand = manifold_from_arrays(rv, rf[:, ::-1])
                    info["flipped"] = 1
                if cand.status() == Error.NoError and not cand.is_empty():
                    man = cand
                    info["repaired"] = 1
        except Exception:
            pass
    if man.status() != Error.NoError or man.is_empty():
        return None, info
    return man, info


def load_sculpt(data: bytes, name: str = "", *, simplify_tol: float = 0.0,
                file_type: str = "stl") -> SculptSource:
    """Read `data` (an STL by default) into a `SculptSource`.

    Shells are split first, always: a self-intersecting single shell
    constructs with NoError and the wrong volume, and two overlapping shells
    in one soup read as the sum of their volumes rather than their union.
    A shell nothing can mend becomes its convex hull, and the record counts
    it. With `simplify_tol` > 0 the union is simplified to that tolerance.
    """
    import trimesh

    # An STL carries every triangle with its own three vertices, so the
    # file is welded by position first (`process=True` merges exact
    # duplicates); without it every triangle is a shell of its own. Manifold's
    # merge map then settles what that leaves.
    raw = trimesh.load(io.BytesIO(data), file_type=file_type, process=True, force="mesh")
    if raw.is_empty or len(raw.faces) == 0:
        raise ManifoldError(f"{name or 'the sculpt'} has no triangles")
    shells = _shells(raw)
    solids, counts = [], {"flipped": 0, "repaired": 0, "hulled": 0}
    for shell in shells:
        man, info = _shell_solid(shell)
        if man is None and len(shell.faces) >= 4:
            try:
                hull = Manifold.hull_points(np.asarray(shell.vertices, dtype=np.float64))
                if (hull.status() == Error.NoError and not hull.is_empty()
                        and hull.volume() > 1e-9):
                    man, info["hulled"] = hull, 1
            except Exception:
                man = None
        if man is None:
            continue
        for k in counts:
            counts[k] += info[k]
        solids.append(man)
    if not solids:
        raise ManifoldError(f"{name or 'the sculpt'} holds no closed shell")
    man = solids[0] if len(solids) == 1 else Manifold.batch_boolean(solids, OpType.Add)
    if man.status() != Error.NoError or man.is_empty():
        raise ManifoldError(f"{name or 'the sculpt'}: the shells do not union")
    if simplify_tol > 0:
        man = man.simplify(float(simplify_tol))
    man = drop_degenerate(man)
    return SculptSource(
        manifold=man, mesh=to_trimesh(man), name=name,
        sha256=hashlib.sha256(data).hexdigest(), triangles=int(man.num_tri()),
        shells=len(solids), repaired=counts["repaired"], hulled=counts["hulled"],
        flipped=counts["flipped"], simplify_tol=float(simplify_tol))


# ------------------------------------------------------------------ the flat back

def _plane_fit(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """PCA plane through `points`: (unit normal, centroid)."""
    c = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - c, full_matrices=False)
    n = vt[-1]
    return n / np.linalg.norm(n), c


def _components(face_ids: np.ndarray, adjacency: np.ndarray) -> list[np.ndarray]:
    """Connected components of `face_ids` under the mesh's face adjacency."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    keep = np.zeros(int(adjacency.max()) + 1 if len(adjacency) else 1, dtype=bool)
    keep[face_ids] = True
    pairs = adjacency[keep[adjacency[:, 0]] & keep[adjacency[:, 1]]] if len(adjacency) else adjacency
    index = -np.ones(len(keep), dtype=np.int64)
    index[face_ids] = np.arange(len(face_ids))
    n = len(face_ids)
    if n == 0:
        return []
    if len(pairs) == 0:
        return [np.array([f]) for f in face_ids]
    a, b = index[pairs[:, 0]], index[pairs[:, 1]]
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    _, labels = connected_components(g, directed=False)
    return [face_ids[labels == k] for k in range(labels.max() + 1)]


def _grown_backs(mesh, dist_tol: float, angle_deg: float, max_bins: int = 12,
                 passes: int = 3) -> list[BackCandidate]:
    """Planes grown from coarse normal bins, for a scanned back.

    A bin's seed is its area-weighted normal; the plane's offset is the
    median of the faces that lean that way. Then, `passes` times: the inliers
    are the faces whose three vertices all lie within `dist_tol` of the plane
    and whose normal leans no more than `angle_deg` from it, the largest
    connected component of those is kept, and the plane is refit by PCA
    through its vertices. Vertex distance rather than face normal is what
    makes it robust: ten microns of noise tilts a small triangle by degrees
    but moves its corners by ten microns.
    """
    V = np.asarray(mesh.vertices, dtype=np.float64)
    F = np.asarray(mesh.faces, dtype=np.int64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    centers = np.asarray(mesh.triangles_center, dtype=np.float64)
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    cos_tol = math.cos(math.radians(angle_deg))
    # bins about 15 degrees wide: the normal rounded to a quarter on each axis
    keys = np.round(normals * 4.0).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    bin_area = np.bincount(inverse, weights=areas)
    out: list[BackCandidate] = []
    for b in np.argsort(-bin_area)[:max_bins]:
        members = np.flatnonzero(inverse == b)
        n = (normals[members] * areas[members, None]).sum(axis=0)
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        leaning = np.flatnonzero(normals @ n > cos_tol)
        if len(leaning) == 0:
            continue
        d = float(np.median(centers[leaning] @ n))
        comp = None
        for _ in range(passes):
            dist = np.abs(V @ n - d)
            ok = np.flatnonzero((dist[F] < dist_tol).all(axis=1) & (normals @ n > cos_tol))
            if len(ok) == 0:
                break
            comp = max(_components(ok, adjacency), key=lambda c: areas[c].sum())
            n_new, c = _plane_fit(V[np.unique(F[comp])])
            if n_new @ n < 0:
                n_new = -n_new
            n, d = n_new, float(c @ n_new)
        if comp is None or len(comp) == 0:
            continue
        point = (centers[comp] * areas[comp, None]).sum(axis=0) / areas[comp].sum()
        point = point - n * float((point - c) @ n)          # onto the plane
        cand = BackCandidate(normal=n, point=point, area=float(areas[comp].sum()),
                             faces=np.asarray(comp, dtype=np.int64), exact=False)
        if any(abs(c0.normal @ cand.normal) > 0.999
               and abs((c0.point - cand.point) @ cand.normal) < dist_tol for c0 in out):
            continue                                        # the same plane, from another bin
        out.append(cand)
    out.sort(key=lambda c: -c.area)
    return out


def flat_back(mesh, *, dist_tol: float = PLANE_DIST_MM,
              angle_deg: float = PLANE_ANGLE_DEG, min_fraction: float = 0.02
              ) -> list[BackCandidate]:
    """The candidate mounting faces of a sculpt, largest first.

    A sculpt cut by a plane has an exactly planar facet, and trimesh finds it
    directly; that answer is taken whenever the largest facet is at least
    `min_fraction` of the surface. A scanned back has no exact facet, so the
    plane is grown instead (`_grown_backs`). The maker can always pick a
    face by hand; this is the default.
    """
    total = float(mesh.area)
    facets = list(mesh.facets)
    cands: list[BackCandidate] = []
    if facets:
        f_area = np.asarray(mesh.facets_area, dtype=np.float64)
        f_norm = np.asarray(mesh.facets_normal, dtype=np.float64)
        order = np.argsort(-f_area)
        if f_area[order[0]] >= min_fraction * total:
            for i in order:
                faces = np.asarray(facets[i], dtype=np.int64)
                if f_area[i] < min_fraction * total:
                    break
                pts = np.asarray(mesh.triangles_center)[faces]
                w = np.asarray(mesh.area_faces)[faces]
                point = (pts * w[:, None]).sum(axis=0) / w.sum()
                n = f_norm[i] / np.linalg.norm(f_norm[i])
                cands.append(BackCandidate(normal=n, point=point, area=float(f_area[i]),
                                           faces=faces, exact=True))
    if not cands:
        cands = _grown_backs(mesh, dist_tol, angle_deg)
    if not cands:
        raise ManifoldError("no planar face to mount on; pick one by hand")
    return cands


# ------------------------------------------------------------------ mounting

def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-15:
        raise ValueError("zero vector")
    return v / n


def _rotation_between(a, b) -> np.ndarray:
    """The rotation taking unit vector `a` onto unit vector `b` (Rodrigues)."""
    a, b = _unit(a), _unit(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -1.0 + 1e-12:
        # opposite: a half turn about any axis perpendicular to a
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis = _unit(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1.0 + c)


def _axis_rotation(axis, deg: float) -> np.ndarray:
    axis = _unit(axis)
    t = math.radians(deg)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K


def snap_target(host_mesh, face: str, point=None, *, outline=None,
                pick_normal=None) -> SnapTarget:
    """Where a back goes on the host.

    `face` is ``posterior`` (the top surface, outward normal +z), ``anterior``
    (the front, -z), ``rim`` (the outline wall at the nearest point of
    `outline` to `point`, outward normal horizontal) or ``pick`` (the picked
    surface point with its own normal). For the two faces the height is the
    host's surface under `point`'s x, y — the terrace the sculpt lands on,
    not the model's extreme — and `point` defaults to the host's center (on a
    front with separated rims, whose center is the gap, the nearest point on
    a rim). The rim is the nearest rim's wall.
    """
    from ..geometry.regions import body_exteriors, body_parts, point_on_body

    bounds = np.asarray(host_mesh.bounds, dtype=np.float64)
    center = bounds.mean(axis=0)
    if point is None:
        p = center.copy()
        if outline is not None and len(body_parts(outline)) > 1:
            p[0], p[1] = point_on_body(outline, float(p[0]), float(p[1]))
    else:
        p = np.asarray(point, dtype=np.float64)
    if face in ("posterior", "anterior"):
        z = surface_z_at(host_mesh, [p[:2]], face="top" if face == "posterior" else "bottom")[0]
        if not np.isfinite(z):
            z = bounds[1, 2] if face == "posterior" else bounds[0, 2]
        n = np.array([0.0, 0.0, 1.0 if face == "posterior" else -1.0])
        return SnapTarget(face, np.array([p[0], p[1], float(z)]), n)
    if face == "rim":
        if outline is None:
            raise ValueError("the rim needs the outline polygon")
        from shapely.geometry import Point
        from shapely.ops import nearest_points
        ring = min(body_exteriors(outline), key=lambda r: r.distance(Point(p[0], p[1])))
        q, _ = nearest_points(ring, Point(p[0], p[1]))
        # outward: away from the polygon's interior, along the wall's normal
        s = ring.project(q)
        a = np.array(ring.interpolate(max(s - 0.05, 0.0)).coords[0])
        b = np.array(ring.interpolate(min(s + 0.05, ring.length)).coords[0])
        t = b - a
        n2 = np.array([t[1], -t[0]])
        if np.linalg.norm(n2) < 1e-12:
            n2 = np.array([1.0, 0.0])
        n2 /= np.linalg.norm(n2)
        probe = Point(q.x + n2[0] * 0.1, q.y + n2[1] * 0.1)
        if outline.contains(probe):
            n2 = -n2
        z = p[2] if len(p) > 2 and np.isfinite(p[2]) else (bounds[0, 2] + bounds[1, 2]) / 2
        return SnapTarget(face, np.array([q.x, q.y, float(z)]), np.array([n2[0], n2[1], 0.0]))
    if face == "pick":
        if pick_normal is None:
            raise ValueError("a pick needs the surface normal at the point")
        return SnapTarget(face, p, _unit(pick_normal))
    raise ValueError(f"unknown mount face {face!r}")


def mount_transform(back: BackCandidate, target: SnapTarget, *,
                    overlap_mm: float = MIN_OVERLAP_MM, spin_deg: float = 0.0,
                    scale: float = 1.0) -> np.ndarray:
    """The 4 x 4 that puts the sculpt's back on the target: scaled about the
    back's point, turned so the back faces into the host, spun `spin_deg`
    about the host normal, and sunk `overlap_mm` below the target point."""
    R = _axis_rotation(target.normal, spin_deg) @ _rotation_between(back.normal, -target.normal)
    T = np.eye(4)
    T[:3, :3] = R * float(scale)
    T[:3, 3] = target.point - target.normal * float(overlap_mm) - (R * float(scale)) @ back.point
    return T


def apply_transform(man: Manifold, T) -> Manifold:
    """`man` under a 4 x 4 (Manifold takes the top three rows)."""
    T = np.asarray(T, dtype=np.float64).reshape(4, 4)
    return man.transform(np.ascontiguousarray(T[:3, :]))


def transform_points(points, T) -> np.ndarray:
    T = np.asarray(T, dtype=np.float64).reshape(4, 4)
    P = np.asarray(points, dtype=np.float64)
    return P @ T[:3, :3].T + T[:3, 3]


def sag_under(host_mesh, back: BackCandidate, source_mesh, T, target: SnapTarget) -> float:
    """How far the host falls away under the back, mm: the largest drop from
    the mounting plane to the host surface over the back's boundary, read by
    vertical ray for the two faces. Zero on a flat terrace, the step height
    across a seam, and the sag of a curve. Zero for the rim and a pick,
    whose hosts are read at the point alone."""
    if target.face not in ("posterior", "anterior"):
        return 0.0
    pts = transform_points(back.boundary_points(source_mesh), T)
    if len(pts) == 0:
        return 0.0
    z = surface_z_at(host_mesh, pts[:, :2], face="top" if target.face == "posterior" else "bottom")
    z = z[np.isfinite(z)]
    if len(z) == 0:
        return 0.0
    plane_z = float(target.point[2])
    drop = (plane_z - z) if target.face == "posterior" else (z - plane_z)
    return float(max(0.0, drop.max()))


def default_overlap(sag: float) -> float:
    """The plan's rule: sink by the sag under the back plus the minimum."""
    return max(MIN_OVERLAP_MM, float(sag) + MIN_OVERLAP_MM)


def contact_gap(host: Manifold, placed: Manifold, search_mm: float = 5.0) -> float:
    """The gap between the placed sculpt and the host, 0 when they touch or
    overlap. A gap wider than `HOVER_MM` is a hover: the union would be two
    bodies, and the placement is refused with this number named."""
    return float(placed.min_gap(host, float(search_mm)))


# ------------------------------------------------------------------ placing and baking

def mirror_twin(placed: Manifold) -> Manifold:
    """The x-mirrored sculpt, across the frame's center line. Manifold's
    mirror keeps a positive volume; nothing here re-orients faces."""
    return placed.mirror([1.0, 0.0, 0.0])


def placed_sculpts(features, sources: dict) -> list[PlacedSculpt]:
    """Every enabled sculpt feature under its stored transform, each followed
    by its mirror twin where `mirror` is set — the list `bake` walks.
    `sources` maps a feature's `source_sha256` to a `SculptSource` or to the
    STL bytes, which are loaded here and left as they came (a save needs
    them). A feature whose source is missing is skipped."""
    out: list[PlacedSculpt] = []
    loaded: dict = {}
    for f in features:
        if not getattr(f, "enabled", True):
            continue
        src = sources.get(f.source_sha256)
        if src is None:
            continue
        if isinstance(src, (bytes, bytearray)):
            key = (f.source_sha256, float(f.simplify_tol))
            if key not in loaded:
                loaded[key] = load_sculpt(bytes(src), f.source_name, simplify_tol=f.simplify_tol)
            src = loaded[key]
        man = apply_transform(src.manifold, f.transform_matrix()).as_original()
        out.append(PlacedSculpt(man, f.op, f.id, False))
        if f.mirror:
            out.append(PlacedSculpt(mirror_twin(man).as_original(), f.op, f.id, True))
    return out


def bake(host: Manifold, placed: list[PlacedSculpt]) -> Manifold:
    """The host with the embosses added, then the debosses taken away, so a
    deboss can cut an emboss. Each input is `as_original`, so the result's
    `run_original_id` colors it by source."""
    adds = [p.manifold for p in placed if p.op == "emboss"]
    subs = [p.manifold for p in placed if p.op == "deboss"]
    solid = host
    if adds:
        solid = Manifold.batch_boolean([solid] + adds, OpType.Add)
    if subs:
        solid = Manifold.batch_boolean([solid] + subs, OpType.Subtract)
    if solid.status() != Error.NoError:
        raise ManifoldError(f"baking the sculpts: {solid.status()}")
    return drop_degenerate(solid)


# ------------------------------------------------------------------ undercuts

def undercuts(mesh, resolution: float = 0.3, tol: float = 1e-3) -> UndercutReport:
    """What a three-axis tool cannot reach: every down-facing triangle whose
    centroid lies below the upper envelope and above the lower one. The
    posted program is the envelope regardless; this says what it leaves."""
    from ..zmap import triangle_envelopes

    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces, dtype=np.int64)
    if len(f) == 0:
        return UndercutReport(0.0)
    lo = v.min(axis=0)
    hi = v.max(axis=0)
    origin = (lo[0] - resolution, lo[1] - resolution)
    cols = int(math.ceil((hi[0] - lo[0]) / resolution)) + 3
    rows = int(math.ceil((hi[1] - lo[1]) / resolution)) + 3
    up, dn = triangle_envelopes(v, f, origin, rows, cols, resolution, background=np.nan)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    down = np.flatnonzero(normals[:, 2] < -1e-6)
    if len(down) == 0:
        return UndercutReport(0.0)
    c = np.asarray(mesh.triangles_center, dtype=np.float64)[down]
    px = np.clip(np.round((c[:, 0] - origin[0]) / resolution).astype(np.int64), 0, cols - 1)
    py = np.clip(np.round((c[:, 1] - origin[1]) / resolution).astype(np.int64), 0, rows - 1)
    above = up[py, px]
    below = dn[py, px]
    hidden = (np.isfinite(above) & np.isfinite(below)
              & (c[:, 2] < above - tol) & (c[:, 2] > below + tol))
    faces = down[hidden]
    area = float(np.asarray(mesh.area_faces)[faces].sum()) if len(faces) else 0.0
    return UndercutReport(area, faces)
