"""Sculpts: an STL dropped on the frame, repaired, mounted and baked in
(BUILDPLAN M22 §7.2).

A sculpt is a mesh the maker made elsewhere — a crest, a rivet head, a
plaque, a scooped channel — and wants on the frame as material added
(*emboss*) or taken away (*deboss*). This module is the kernel side of that,
Qt-free and importable headless:

* **Import.** `load_sculpt` reads the bytes with trimesh, splits the soup
  into shells, welds each through Manifold's merge map, flips a shell whose
  winding is inside out, and climbs `mesh_repair`'s ladder for a shell
  Manifold rejects: its holes capped along the faces' own fans (a relief
  whose back was cut away at export, a filigree with pinched holes), then
  rebuilt as a heightfield over its back plane, then pymeshfix behind a
  loss guard (it handed back one corner of a 326 mm panel with NoError);
  the shells are unioned. A shell nothing can mend is offered as its hull,
  and the record says what each step did. Two traps the constructor does
  not catch, both tested: a self-intersecting single shell constructs with
  NoError and the wrong volume (so the shells are split first, always), and
  a sculpt hovering a hair off the host unions into two bodies
  (`contact_gap`). `SculptSource.simplified` coarsens a loaded sculpt in
  place of a second read.
* **The flat back.** `flat_back` ranks the candidate mounting faces: the
  exactly planar facets of a sculpt cut by a plane (the common case), or,
  on a scanned back, a plane grown from coarse normal bins, a robust plane
  per bin, connected components and a PCA refit.
* **Mounting.** `snap_target` reads where the back goes on the host —
  anterior, posterior, the rim wall, or a picked point — and
  `mount_transform` builds the 4 x 4 that puts the sculpt there. Relief
  out (the default), the back sits on the surface sunk by `overlap_mm`, so
  the union is one body; `flip` turns the relief into the frame, the back
  up, and `overlap_mm` is then how deep the crown goes: a deboss imprints
  the relief as a stamp. `sag_under` reads how far the host falls away
  under the back's footprint, which sets the default overlap of an emboss.
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
from .mesh_repair import boundary_loops, cap_holes, kept_enough, relief_remesh

__all__ = [
    "BackCandidate", "PlacedSculpt", "SculptSource", "SnapTarget", "UndercutReport",
    "SIMPLIFY_ABOVE", "apply_transform", "bake", "contact_gap", "default_overlap", "flat_back",
    "load_sculpt", "manifold_from_arrays", "mirror_twin", "mount_transform",
    "placed_sculpts", "relief_height", "sag_under", "snap_target", "transform_points",
    "undercuts",
]

#: A sculpt with more triangles than this is offered `simplify` on import.
SIMPLIFY_ABOVE = 250_000
#: How far a back plane's inlier may sit off it, mm, on a scanned back, and
#: how far a face on it may lean before it is read as the wall beside it. The
#: lean is loose on purpose: a sliver triangle on a capped back tilts by ten
#: degrees under ten microns of noise, so the distance test does the work.
PLANE_DIST_MM = 0.05
PLANE_ANGLE_DEG = 60.0
#: Facets whose fitted normals lean less than this from each other lie on one
#: plane as far as `flat_back` is concerned: float noise on one cap, or the
#: caps of a back in pieces, never a scanned back's jitter (which the grown
#: path finds, inexact).
FACET_MERGE_DEG = 0.5
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
    capped: int = 0                    # holes closed along the faces' fans
    remeshed: int = 0                  # shells rebuilt as a relief over their back
    remesh_mm: float = 0.0             # the finest grid such a rebuild used
    repaired: int = 0                  # shells pymeshfix mended
    hulled: int = 0                    # shells replaced by their hull
    flipped: int = 0                   # shells whose winding was inside out
    simplify_tol: float = 0.0
    #: The mounting face, once `flat_back` has been asked; the GUI keeps it here.
    back: BackCandidate | None = None

    @property
    def volume(self) -> float:
        return float(self.manifold.volume())

    @property
    def extent_mm(self) -> float:
        """The longest side of the sculpt's box: what *Size* in the panel scales."""
        b = np.asarray(self.mesh.bounds, dtype=np.float64)
        return float((b[1] - b[0]).max())

    @property
    def height_mm(self) -> float:
        """The relief's height off the back, 0 until the back is known."""
        return relief_height(self.mesh, self.back) if self.back is not None else 0.0

    def notes(self) -> list[str]:
        out = []
        if self.shells > 1:
            out.append(f"{self.shells} shells unioned")
        if self.flipped:
            out.append(f"{self.flipped} inside-out, flipped")
        if self.capped:
            out.append(f"{self.capped} hole{'s' if self.capped > 1 else ''} capped")
        if self.remeshed:
            out.append(f"{self.remeshed} rebuilt as a relief at {self.remesh_mm:.2g} mm")
        if self.repaired:
            out.append(f"{self.repaired} repaired")
        if self.hulled:
            out.append(f"{self.hulled} replaced by its hull")
        if self.simplify_tol > 0:
            out.append(f"simplified to {self.simplify_tol:g} mm")
        return out

    def simplified(self, tol: float) -> "SculptSource":
        """This sculpt coarsened to `tol` (mm), the repair kept: what the
        GUI offers a large sculpt instead of reading the file again."""
        man = drop_degenerate(self.manifold.simplify(float(tol)))
        out = SculptSource(
            manifold=man, mesh=to_trimesh(man), name=self.name, sha256=self.sha256,
            triangles=int(man.num_tri()), shells=self.shells, capped=self.capped,
            remeshed=self.remeshed, remesh_mm=self.remesh_mm, repaired=self.repaired,
            hulled=self.hulled, flipped=self.flipped, simplify_tol=float(tol))
        if self.back is not None:
            # the same back, found again on the coarser mesh: the candidate
            # facing the way the chosen one faces, not the largest, which
            # a merge could reorder (the 2.1 bug hunt)
            try:
                cands = flat_back(out.mesh)
            except ManifoldError:
                cands = []
            n0 = np.asarray(self.back.normal, dtype=float)
            out.back = (max(cands, key=lambda c: float(np.asarray(c.normal) @ n0))
                        if cands else None)
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


def _construct(v: np.ndarray, f: np.ndarray, info: dict) -> Manifold | None:
    """A solid from the arrays, winding corrected, or None when Manifold
    rejects them or they enclose nothing."""
    man = manifold_from_arrays(v, f)
    flipped = False
    if man.status() == Error.NoError and man.volume() < 0:
        man = manifold_from_arrays(v, f[:, ::-1])
        flipped = True
    if man.status() != Error.NoError or man.is_empty() or man.volume() <= 1e-12:
        return None
    if flipped:
        info["flipped"] = 1       # counted only when the turned shell is the one kept
    return man


def _shell_back_plane(shell) -> tuple[np.ndarray, np.ndarray] | None:
    """(outward normal, point) of a shell's back, for the relief remesh.

    A hole as wide as the shell is the back cut away at export (the
    maker's ornament, a box without its bottom): its plane, facing away
    from the shell's bulk. Otherwise the largest exact facet, when nothing
    of the shell lies beyond it. Otherwise the largest hole's plane anyway,
    and None when there is neither.
    """
    V = np.asarray(shell.vertices, dtype=np.float64)
    if len(V) == 0:
        return None
    extent = float((V.max(axis=0) - V.min(axis=0)).max())
    loops, _ = boundary_loops(np.asarray(shell.faces, dtype=np.int64))
    loop_plane = None
    if loops:
        loop = max(loops, key=lambda lp: float((V[lp].max(axis=0) - V[lp].min(axis=0)).max()))
        P = V[loop]
        n, c = _plane_fit(P)
        if float((c - V.mean(axis=0)) @ n) < 0:
            n = -n
        loop_plane = (n, c)
        if float((P.max(axis=0) - P.min(axis=0)).max()) >= 0.5 * extent:
            return loop_plane
    try:
        facets = list(shell.facets)
        if facets:
            areas = np.asarray(shell.facets_area, dtype=np.float64)
            i = int(np.argmax(areas))
            if areas[i] >= 0.02 * float(shell.area):
                faces = np.asarray(facets[i], dtype=np.int64)
                n = np.asarray(shell.facets_normal[i], dtype=np.float64)
                n = n / np.linalg.norm(n)
                pts = np.asarray(shell.triangles_center)[faces]
                w = np.asarray(shell.area_faces)[faces]
                pt = (pts * w[:, None]).sum(axis=0) / w.sum()
                if float(((V - pt) @ n).max()) <= PLANE_DIST_MM:
                    return n, pt
    except Exception:                                      # noqa: BLE001
        pass
    return loop_plane


def _shell_solid(shell) -> tuple[Manifold | None, dict]:
    """One shell as a solid, up the ladder: as it came (flipped if inside
    out); its holes capped and its fins dropped; rebuilt as a relief over
    its back plane; mended by pymeshfix when that keeps enough of it; or
    None, for the hull."""
    info = {"flipped": 0, "capped": 0, "remeshed": 0, "remesh_mm": 0.0,
            "repaired": 0, "hulled": 0}
    v = np.asarray(shell.vertices, dtype=np.float64)
    f = np.asarray(shell.faces, dtype=np.int64)
    if len(f) < 4:
        return None, info
    man = _construct(v, f, info)
    if man is not None:
        return man, info
    try:
        cv, cf, cinfo = cap_holes(v, f)
        if cinfo["capped"] or cinfo["fins"]:
            man = _construct(cv, cf, info)
            if man is not None:
                info["capped"] = cinfo["capped"]
                return man, info
    except Exception:                                      # noqa: BLE001
        pass
    plane = _shell_back_plane(shell)
    if plane is not None:
        try:
            rv, rf, res = relief_remesh(v, f, plane[0], plane[1])
            man = _construct(rv, rf, info)
            if man is not None:
                info["remeshed"], info["remesh_mm"] = 1, float(res)
                return man, info
        except Exception:                                  # noqa: BLE001
            pass
    try:
        import pymeshfix
        fix = pymeshfix.MeshFix(v, f)
        fix.repair(joincomp=False, remove_smallest_components=False)
        rv = np.asarray(fix.points, dtype=np.float64)
        rf = np.asarray(fix.faces, dtype=np.int64)
        if len(rf) >= 4 and kept_enough(v, f, rv, rf):
            man = _construct(rv, rf, info)
            if man is not None:
                info["repaired"] = 1
                return man, info
    except Exception:                                      # noqa: BLE001
        pass
    return None, info


def load_sculpt(data: bytes, name: str = "", *, simplify_tol: float = 0.0,
                file_type: str = "stl") -> SculptSource:
    """Read `data` (an STL by default) into a `SculptSource`.

    Shells are split first, always: a self-intersecting single shell
    constructs with NoError and the wrong volume, and two overlapping shells
    in one soup read as the sum of their volumes rather than their union.
    A shell Manifold rejects climbs `mesh_repair`'s ladder (capped, rebuilt
    as a relief, pymeshfix behind the loss guard); one nothing can mend
    becomes its convex hull, and the record counts each. With
    `simplify_tol` > 0 the union is simplified to that tolerance.
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
    solids = []
    counts = {"flipped": 0, "capped": 0, "remeshed": 0, "repaired": 0, "hulled": 0}
    remesh_mm = 0.0
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
        if info.get("remesh_mm"):
            # the finest grid a rebuild used, as the field says
            remesh_mm = (float(info["remesh_mm"]) if not remesh_mm
                         else min(remesh_mm, float(info["remesh_mm"])))
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
        shells=len(solids), capped=counts["capped"], remeshed=counts["remeshed"],
        remesh_mm=remesh_mm, repaired=counts["repaired"], hulled=counts["hulled"],
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
        f_norm = f_norm / np.maximum(np.linalg.norm(f_norm, axis=1, keepdims=True), 1e-15)
        centers = np.asarray(mesh.triangles_center, dtype=np.float64)
        w_all = np.asarray(mesh.area_faces, dtype=np.float64)
        # One back can come as many facets: a relief in pieces, each capped
        # on the same plane (the maker's 16-piece ornament), or a cap split
        # by a sliver. Facets on one plane (normal and offset alike, within
        # the tolerances) are one candidate, so the whole back is mounted,
        # read for sag and counted toward `min_fraction`.
        # facets grouped by normal within the angle (not by rounding the
        # normal, which split one plane whose fitted normals straddled a
        # rounding boundary, the 2.1 bug hunt); the first facet of a group
        # is its reference
        by_normal: list[tuple[np.ndarray, list[int]]] = []
        cos_tol = float(np.cos(np.radians(FACET_MERGE_DEG)))
        points = []
        offsets = []
        for i in range(len(facets)):
            faces_i = np.asarray(facets[i], dtype=np.int64)
            w = w_all[faces_i]
            pt = (centers[faces_i] * w[:, None]).sum(axis=0) / w.sum()
            points.append(pt)
            n = f_norm[i]
            offsets.append(float(pt @ n))
            for ref, members in by_normal:
                if float(ref @ n) >= cos_tol:
                    members.append(i)
                    break
            else:
                by_normal.append((n, [i]))
        # facets with one normal, clustered by offset where a gap exceeds
        # the tolerance (not by rounding the offset, which splits a plane
        # on float noise at a half-unit)
        groups: list[list[int]] = []
        for _ref, members in by_normal:
            members = sorted(members, key=lambda i: offsets[i])
            run = [members[0]]
            for i in members[1:]:
                if offsets[i] - offsets[run[-1]] > dist_tol:
                    groups.append(run)
                    run = [i]
                else:
                    run.append(i)
            groups.append(run)
        merged = []
        for members in groups:
            area = float(f_area[members].sum())
            faces = np.concatenate([np.asarray(facets[i], dtype=np.int64) for i in members])
            n = (f_norm[members] * f_area[members, None]).sum(axis=0)
            n = n / max(np.linalg.norm(n), 1e-15)
            pt = (np.asarray([points[i] for i in members]) * f_area[members, None]
                  ).sum(axis=0) / area
            merged.append((area, n, pt, faces))
        merged.sort(key=lambda m: -m[0])
        if merged and merged[0][0] >= min_fraction * total:
            for area, n, pt, faces in merged:
                if area < min_fraction * total:
                    break
                cands.append(BackCandidate(normal=n, point=pt, area=area, faces=faces,
                                           exact=True))
    if not cands:
        cands = _grown_backs(mesh, dist_tol, angle_deg)
    if not cands:
        raise ManifoldError("no planar face to mount on; pick one by hand")
    return cands


def relief_height(mesh, back: BackCandidate) -> float:
    """How far the relief stands off the back plane, mm: the farthest
    vertex against the back's outward normal. What a flipped mount lifts
    the back by, less the sink, so the crown goes in by the sink."""
    V = np.asarray(mesh.vertices, dtype=np.float64)
    if len(V) == 0:
        return 0.0
    return float(max(0.0, ((back.point - V) @ back.normal).max()))


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
                    scale: float = 1.0, flip: bool = False,
                    height_mm: float = 0.0) -> np.ndarray:
    """The 4 x 4 that puts the sculpt on the target, scaled about the back's
    point and spun `spin_deg` about the host normal.

    Relief out (`flip` False): the back faces into the host and sits
    `overlap_mm` below the target point, so an emboss unions into one body.
    Relief in (`flip` True): the back faces away, the relief points into the
    host, and the crown (`height_mm` off the back, in the sculpt's own
    units) sits `overlap_mm` below the target point; the back then stands
    `height_mm * scale - overlap_mm` above the surface. A deboss so placed
    imprints the relief as a stamp would.
    """
    n = _unit(target.normal)
    facing = n if flip else -n
    R = _axis_rotation(n, spin_deg) @ _rotation_between(back.normal, facing)
    lift = (float(height_mm) * float(scale) - float(overlap_mm)) if flip else -float(overlap_mm)
    T = np.eye(4)
    T[:3, :3] = R * float(scale)
    T[:3, 3] = target.point + n * lift - (R * float(scale)) @ back.point
    return T


def apply_transform(man: Manifold, T) -> Manifold:
    """`man` under a 4 x 4 (Manifold takes the top three rows)."""
    T = np.asarray(T, dtype=np.float64).reshape(4, 4)
    return man.transform(np.ascontiguousarray(T[:3, :]))


def transform_points(points, T) -> np.ndarray:
    T = np.asarray(T, dtype=np.float64).reshape(4, 4)
    P = np.asarray(points, dtype=np.float64)
    return P @ T[:3, :3].T + T[:3, 3]


def sag_under(host_mesh, back: BackCandidate, source_mesh, T, target: SnapTarget,
              reach_mm: float = 5.0) -> float:
    """How far the back must sink for the host to hold it, mm.

    On the two faces, the largest drop from the mounting plane to the host
    surface over the back's boundary, by vertical ray: zero on a flat
    terrace, the step height across a seam, the sag of a curve; the whole
    back then bears. On the rim and a pick, the *smallest* drop, by a ray
    along the mount normal from `reach_mm` out: a wide back on a curved or
    short wall touches at its middle and stands clear at its ends, and
    sinking it by the largest drop would bury it in the frame (a 15 mm
    ornament on the nose wall went 9.6 mm in); what is needed is contact,
    which the nearest point gives, and the depth of a recess only when the
    whole back floats over one."""
    pts = transform_points(back.boundary_points(source_mesh), T)
    if len(pts) == 0:
        return 0.0
    if target.face in ("posterior", "anterior"):
        z = surface_z_at(host_mesh, pts[:, :2], face="top" if target.face == "posterior" else "bottom")
        z = z[np.isfinite(z)]
        if len(z) == 0:
            return 0.0
        plane_z = float(target.point[2])
        drop = (plane_z - z) if target.face == "posterior" else (z - plane_z)
        return float(max(0.0, drop.max()))
    n = _unit(target.normal)
    # the boundary points lie on the mounting plane: cast from `reach_mm`
    # outside it, along -n, and read where the host is met. A back taller
    # than the wall it stands on has its rim above and below the wall, so
    # the samples are held within the host's own height first.
    hb = np.asarray(host_mesh.bounds, dtype=np.float64)
    eps = 1e-3 * max(float((hb[1] - hb[0]).max()), 1e-6)
    pts = pts.copy()
    pts[:, 2] = np.clip(pts[:, 2], hb[0, 2] + eps, hb[1, 2] - eps)
    origins = pts + n * float(reach_mm)
    directions = np.tile(-n, (len(pts), 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        hits, index_ray, _ = host_mesh.ray.intersects_location(origins, directions,
                                                               multiple_hits=False)
    if len(hits) == 0:
        return 0.0
    depth = ((hits - origins[index_ray]) @ (-n)) - float(reach_mm)
    return float(max(0.0, depth.min()))


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
