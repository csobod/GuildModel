"""Mesh-domain CSG primitives (BUILDPLAN-NEW M-N1).

Everything in `core/model` speaks Manifold through this module, the way
`core/solid/occ.py` speaks OpenCASCADE — so that if the kernel is ever swapped
again, it is swapped in one file.

**Why a mesh kernel at all.** The property the frame actually needs is "this is
a closed solid of positive volume": it is what STL export requires, what the
CAM's stock model assumes, and what the app's own oracle checks. In a B-Rep that
property is an *outcome* you verify afterwards and frequently do not get. In
Manifold it is an invariant of the data structure — an operation either returns
a closed manifold or reports an error status. The whole of BUILDPLAN-NEW §3 is
the cost of the first arrangement.

Three things here were learned the hard way and must not be rediscovered:

* **Weld with the merge map, not with positions.** `to_mesh64()` hands back
  MeshGL, which splits vertices along property boundaries — the same point in
  space appears several times by design. Matching them back up by rounding
  coordinates is guesswork that silently opens seams; `merge_from_vert` /
  `merge_to_vert` is the library telling you exactly which duplicates are one
  vertex. `to_trimesh` below does it that way.
* **Extract at float64.** `to_mesh()` is float32; Manifold is not. Everything
  the app knows about a model comes through `to_trimesh`, and the downcast was
  quietly rewriting the answers — see there.
* **Sweep by building the strip, not by unioning hulls.** Every swept feature in
  this project (groove V, bezel, splay, scoop, footing blends) is a section
  carried along a ring, and a section of k points over n stations *is* a quad
  grid. It was originally a chain of per-segment convex hulls, chosen because
  that cannot self-intersect however tight the corner — which is precisely where
  `BRepOffsetAPI_MakePipeShell` produced 401-second invalid shapes. But those
  cells only *abut*, and the union does not reliably cancel the section they
  share. `hull_chain` is still here as `sweep_sections`'s fallback for the
  tight-corner case; it is no longer the way to sweep.
"""
from __future__ import annotations

import numpy as np
from manifold3d import CrossSection, FillRule, Manifold, OpType
from shapely.geometry import Polygon

__all__ = [
    "ManifoldError",
    "cross_section",
    "drop_degenerate",
    "extrude",
    "hull_chain",
    "intersect_all",
    "sweep_sections",
    "subtract_all",
    "surface_z_at",
    "swept_profile",
    "to_trimesh",
    "union_all",
    "volume",
]


class ManifoldError(RuntimeError):
    """An operation returned a non-empty error status, or could not be built.

    Raised rather than returned for the same reason `BooleanError` is: a
    silently dropped feature would post G-code for geometry nobody asked for.
    """


def _check(man: Manifold, what: str) -> Manifold:
    status = man.status()
    # `status()` returns an enum whose success member is falsey/zero-valued;
    # compare by name so this survives a binding change.
    if getattr(status, "name", str(status)) not in ("NoError", "0"):
        raise ManifoldError(f"{what}: {status}")
    return man


def cross_section(poly: Polygon) -> CrossSection:
    """A Shapely polygon (with holes) as a Manifold 2D cross-section.

    Even-odd fill, so interior rings punch holes regardless of the winding the
    partition happens to carry — Shapely does not promise a consistent
    orientation and the zone polygons come from several different producers.
    """
    rings = [list(poly.exterior.coords)[:-1]]
    rings.extend(list(r.coords)[:-1] for r in poly.interiors)
    return CrossSection(
        [[(float(x), float(y)) for x, y in ring] for ring in rings],
        fillrule=FillRule.EvenOdd)


def extrude(poly: Polygon, height: float, base: float = 0.0) -> Manifold:
    """`poly` swept from `base` to `base + height`."""
    if height <= 0.0:
        raise ManifoldError(f"cannot extrude to height {height}")
    man = Manifold.extrude(cross_section(poly), float(height))
    if base:
        man = man.translate([0.0, 0.0, float(base)])
    return _check(man, "extrude")


def union_all(parts: list[Manifold]) -> Manifold:
    """One batched union, not a fold.

    `batch_boolean` lets the library see every operand at once and plan the
    tree; folding `a + b + c` re-walks the accumulating result each time. Same
    reason `occ.fuse_all` is a single multi-tool BOP.
    """
    if not parts:
        raise ManifoldError("nothing to union")
    if len(parts) == 1:
        return parts[0]
    return _check(Manifold.batch_boolean(parts, OpType.Add), "union")


def intersect_all(parts: list[Manifold]) -> Manifold:
    """The common part of every operand, in one batched pass.

    Used to clip a build back to a boundary it was deliberately allowed to
    overrun — see `model.build.build_base`, where every zone is grown before
    extruding and the frame outline puts it back.
    """
    if not parts:
        raise ManifoldError("nothing to intersect")
    if len(parts) == 1:
        return parts[0]
    return _check(Manifold.batch_boolean(parts, OpType.Intersect), "intersect")


def subtract_all(solid: Manifold, tools: list[Manifold]) -> Manifold:
    """`solid` minus every tool, in one pass.

    Order-independent by construction — `(X \\ A) \\ B == X \\ (A ∪ B)` — which
    is worth stating because on the B-Rep path it was *not* true in practice:
    reordering the tools flipped the result between watertight and corrupt.
    """
    if not tools:
        return solid
    return _check(Manifold.batch_boolean([solid, *tools], OpType.Subtract),
                  "subtract")


#: Largest component volume treated as numerical debris rather than part of the
#: frame, in mm3. Exact booleans on near-tangent inputs answer with
#: zero-thickness shells — real triangles, correctly wound, enclosing nothing.
#: The footing blends produce them because a blend band's boundary runs along a
#: terrace wall by construction, and the finely triangulated blend surface then
#: gives every later feature something to be tangent to.
#:
#: Measured, not guessed. Across the three fixtures with every feature enabled
#: the strays total 1.6e-8, 2.5e-8 and 6.8e-7 mm3, the largest single one being
#: 2.7e-7 — a cube six microns on a side. This threshold sits ~370x above that
#: and orders of magnitude below the smallest fragment of frame that could
#: matter, so it separates debris from geometry with room on both sides.
DEGENERATE_VOLUME_MM3 = 1e-4


def drop_degenerate(man: Manifold,
                    max_volume: float = DEGENERATE_VOLUME_MM3) -> Manifold:
    """Discard connected components too small to be material.

    **This deletes components; it never moves a vertex.** That is the whole
    reason it is preferred to `Manifold.simplify`, which was tried first and
    made things worse: collapsing sub-tolerance edges across a finished part
    severed a genuine hair-thin connection and turned a clean bare frame into
    two pieces. A filter cannot do that — every surviving triangle is bit-for-bit
    what the boolean produced.

    It also cannot hide a real disconnection, which is the failure this project
    has actually suffered: when the pad splay cut Gabriel's frame in half the
    halves were thousands of mm3 each. Anything that survives the filter is
    still counted, so `verify_mesh` still reports "the model is in N separate
    pieces" for a part that genuinely is.

    An inverted shell — an internal void, which `volume()` reports negative —
    fails the comparison and is dropped too, which is correct: seven of the ten
    strays on the first footing build were voids.
    """
    parts = man.decompose()
    if len(parts) < 2:
        return man
    keep = [p for p in parts if p.volume() > float(max_volume)]
    if len(keep) == len(parts):
        return man
    if not keep:
        raise ManifoldError("every component was below the degeneracy floor")
    if len(keep) == 1:
        return keep[0]
    # Disjoint by construction, so compose rather than union: no boolean to run
    # and nothing for it to get wrong.
    return _check(Manifold.compose(keep), "compose")


def _cap_triangles(section: np.ndarray):
    """Triangles closing one end of an open sweep, or None.

    Indices are into `section`, traversing it in **index order** — which is what
    the strip's sides do, so the caller only has to reverse one of the two ends.

    **Ear-clipped in the section's own plane, not fanned from a corner.** A fan
    is only valid for a convex section, and several of these are not: the
    footing blend's S-curve closed off to `far`, and the round-over edge
    feature. Fanning those puts triangles outside the polygon — a cap that
    self-intersects while still being index-manifold, so nothing complains. It
    has never yet mattered, and that is luck rather than design: the blend
    bands' caps sit beyond the ends of the SCULPT cut, outside the body, and the
    zone prism clips them away. The pad splay's caps land on the part.

    **Projected onto the section's own plane, via Newell's normal.** The obvious
    shortcut — drop the axis the section spans least — is wrong here and was
    tried: these sections stand in *vertical* planes, so a band running
    diagonally spans x and y more than z, the shortcut projects it onto XY, and
    the polygon collapses to a line. That took 11 of the demo frame's 26 sweeps
    into the `hull_chain` fallback, silently, and only
    `test_the_sweep_never_falls_back_to_the_hull_chain` said so.
    """
    from manifold3d import triangulate

    pts = np.asarray(section, dtype=np.float64)
    nxt = np.roll(pts, -1, axis=0)
    normal = np.array([
        np.sum((pts[:, 1] - nxt[:, 1]) * (pts[:, 2] + nxt[:, 2])),
        np.sum((pts[:, 2] - nxt[:, 2]) * (pts[:, 0] + nxt[:, 0])),
        np.sum((pts[:, 0] - nxt[:, 0]) * (pts[:, 1] + nxt[:, 1]))])
    length = float(np.linalg.norm(normal))
    if length < 1e-12:                      # no area to cap
        return None
    normal /= length

    helper = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(helper, normal))) > 0.9:
        helper = np.array([1.0, 0.0, 0.0])
    u_axis = np.cross(helper, normal)
    u_axis /= np.linalg.norm(u_axis)
    v_axis = np.cross(normal, u_axis)

    rel = pts - pts[0]
    flat = np.ascontiguousarray(np.column_stack([rel @ u_axis, rel @ v_axis]))
    try:
        tris = np.asarray(triangulate([flat]), dtype=np.int64)
    except Exception:                                        # noqa: BLE001
        return None
    if len(tris) == 0:
        return None
    return tris


def _strip_mesh(profiles: list[np.ndarray], closed: bool) -> Manifold | None:
    """The tube as an explicit triangle strip, or None if it cannot be built.

    A section of `k` points carried over `n` stations *is* a quad grid: two
    triangles per (station gap x section edge), plus a fan cap at each end when
    the path does not close. No booleans, so nothing has to cancel and nothing
    is left over.

    **The sections must be ordered around the section boundary.** `hull_chain`
    never needed that — a hull ignores order — but all four callers already do
    it, and this makes it load-bearing.

    Returns None rather than raising, so `sweep_sections` can fall back, when:

    * the sections are not all the same length, so there are no rails to build;
    * a rail runs *backwards* against the sweep. That is the fold `hull_chain`
      was chosen to be immune to: where the path turns tighter than the section
      is deep, the offset surface passes through itself, and a strip would
      faithfully build the self-intersection where a union of convex cells
      quietly does the right thing. The test is that every rail advance has a
      positive component along the centroid step;
    * Manifold rejects the result as not an oriented 2-manifold.
    """
    from manifold3d import Mesh64

    n = len(profiles)
    if n < 2:
        return None
    sections = [np.asarray(p, dtype=np.float64) for p in profiles]
    k = len(sections[0])
    if k < 3 or any(len(s) != k for s in sections):
        return None

    last = n if closed else n - 1
    for i in range(last):
        a, b = sections[i], sections[(i + 1) % n]
        step = b.mean(axis=0) - a.mean(axis=0)
        if not np.any(step) or np.any((b - a) @ step <= 0.0):
            return None

    tris = []
    for i in range(last):
        a, b = i * k, ((i + 1) % n) * k
        for j in range(k):
            j2 = (j + 1) % k
            tris.append((a + j, a + j2, b + j2))
            tris.append((a + j, b + j2, b + j))
    if not closed:
        # Wound to match the sides, which follow the section's index order
        # whatever that order happens to mean geometrically. The side quads
        # leave the first station's boundary running j -> j+1, so its cap has to
        # run the other way, and the last station's the same way. Orienting the
        # caps from geometry instead — outward along the sweep — was tried and
        # is wrong: it agrees with the sides for one section winding and
        # contradicts them for the other, and both windings are in use here, so
        # exactly half the blend bands came back rejected. `_strip_mesh` flips
        # the finished shell if it turns out inside-out, which is the right
        # place for that decision because there it can be made once.
        for start, cap in ((0, _cap_triangles(sections[0])),
                           ((n - 1) * k, _cap_triangles(sections[-1]))):
            if cap is None:
                return None
            wound = cap[:, ::-1] if start == 0 else cap
            for t0, t1, t2 in wound:
                tris.append((start + t0, start + t1, start + t2))

    verts = np.vstack(sections)
    faces = np.asarray(tris, dtype=np.uint64)
    man = Manifold(Mesh64(vert_properties=verts, tri_verts=faces))
    if getattr(man.status(), "name", str(man.status())) not in ("NoError", "0"):
        return None
    if man.volume() < 0.0:                  # section wound the other way
        man = Manifold(Mesh64(vert_properties=verts,
                              tri_verts=np.ascontiguousarray(faces[:, ::-1])))
        if getattr(man.status(), "name",
                   str(man.status())) not in ("NoError", "0"):
            return None
    return man


def sweep_sections(profiles: list[np.ndarray], closed: bool = True) -> Manifold:
    """Sweep an ordered section along a path. The project's sweep primitive.

    Builds the tube directly (`_strip_mesh`) and falls back to `hull_chain` for
    the cases a strip cannot express.

    **Why not the hull chain, which is what this used to be.** A union of
    per-segment convex hulls leaves consecutive cells *abutting* on a shared
    section rather than overlapping, and Manifold fails to cancel that shared
    face often enough to matter — about 0.65 sections per station, measured on
    synthetic sweeps with nothing else in the scene, and invariant to everything
    tried: circle, off-centre circle and ellipse; a V, a scalene triangle and a
    tapering section; open and closed; 60, 120 and 240 stations. It reached the
    part as 76 / 94 / 82 self-touching edges on the lens groove.

    Overlapping the cells so they genuinely intersect **was tried and is not the
    answer**: at 2% of a step it makes slivers, which are worse than the exact
    coincidence they replace; at 25% it still does not reach zero and the tube
    has bulged by 0.6%; and applied to `swept_profile` it took the footing base
    from 0 contacts to 2,500. The rejected constant is in the history if it is
    ever wanted again.

    The strip is exact instead of approximate, and cheaper — no booleans at all.
    Against the hull chain on the same sections it is contact-free at every
    density and its volume converges to the hull's from below, the difference
    being the bulge the convex cells add: -0.0023% at 60 stations, -0.0003% at
    120, -0.0000% at 240.
    """
    strip = _strip_mesh(profiles, closed)
    return strip if strip is not None else hull_chain(profiles, closed)


def hull_chain(profiles: list[np.ndarray], closed: bool = True) -> Manifold:
    """Sweep a profile along a path as the union of per-segment convex hulls.

    **Kept as `sweep_sections`'s fallback, not as the way to sweep.** It is the
    construction that cannot self-intersect however tight the corner, which is
    why it is still here; it is also the construction that leaves membranes, so
    reach for `sweep_sections` unless you specifically need this.

    `profiles[i]` is the (k, 3) section at station i. Each consecutive pair is
    hulled into a convex cell and the cells are unioned.

    **Consecutive cells abut rather than overlap** — the section at station i+1
    is a face of the cell before it and of the cell after, as the same coplanar
    triangle, and the union is left to cancel two faces that are the same face.
    At roughly one station in ten it does not, and that section stays inside the
    tube as a membrane: a triangle swept round a plain circle self-touches on 3
    edges at 12 stations, 12 at 60, 33 at 120, and the groove V reaches the part
    with 60 to 72 before it has met anything. Running the cells past each other
    so they genuinely overlap was tried and is not the answer — it helped at 12
    stations, hurt at 60, and when applied to `swept_profile` took the footing
    base from 0 contacts to 2,500 by breaking the exact agreement between a
    blend's two halves at the seam. Open, and the reason the lens groove is
    still on BUILDPLAN-NEW's risk list.

    Requires each profile to be convex, and a concave one is filled in
    **silently** — the hull simply spans the dent and the feature comes out as
    something smoother than it should be. No error, no clue.

    Which sections qualify, checked rather than assumed:

    * groove V — a triangle. Convex.
    * bezel band — a trapezoid. Convex.
    * bridge scoop — a half-ellipse closed upward. The lower boundary is
      `-sqrt(1 - x^2)`, which is a convex *function*, and the region above a
      convex function is a convex set. Convex.
    * edge feature, `profile="chamfer"` — region above a straight line. Convex.
    * edge feature, `profile="fillet"` — **not convex.** The round-over is
      `v = anchor - r + sqrt(r^2 - (r-u)^2)`, the upper half of a circle, which
      is concave; the region above it is not a convex set. Hulling it would
      quietly turn every round-over into a chamfer.
    * footing blend, **both halves — not convex.** Measured `z''` over every
      fillet in the default schedule at three step heights: the high half's
      curve is concave throughout (-0.031 to -0.188), so the region above it is
      not convex, and the low half's is convex (up to +0.32), so the region
      below it is not either. The nosepad pair are S-shaped *within* a single
      half. All ten blends go through `swept_profile`.

    So neither the fillet nor the footings come through here at all.
    `swept_profile` below decomposes them into per-sample convex slabs; use that
    for anything whose convexity you have not checked.
    """
    if len(profiles) < 2:
        raise ManifoldError("a sweep needs at least two stations")
    n = len(profiles)
    last = n if closed else n - 1
    cells = []
    for i in range(last):
        pts = np.vstack([profiles[i], profiles[(i + 1) % n]])
        cells.append(Manifold.hull_points([tuple(map(float, p)) for p in pts]))
    return union_all(cells)


def swept_profile(points, normals, profile_uv, far: float,
                  closed: bool = True) -> Manifold:
    """Sweep a possibly-concave (u, v) profile along a ring.

    `profile_uv[k]` is the profile at station k as an (m, 2) array of
    `(u, v)` — `u` measured along `normals[k]` from `points[k]`, `v` in Z. The
    region swept is everything between the profile and `far`, which is the
    shape all four of this project's surface features describe: a boundary
    curve, and material to be removed above or below it.

    Closing the profile off to `far` makes it an ordinary ordered section —
    the `m` profile points, then the two corners on the `far` plane — so this
    goes through `sweep_sections` like everything else.

    **The fallback is the slab decomposition below, not `hull_chain`**, and the
    difference is not cosmetic: these sections are allowed to be concave, and a
    hull would span the dent *silently*, delivering a chamfer where the maker
    asked for a fillet. The slabs slice the section into one convex trapezoid
    per profile segment; they share faces and their union is the section
    exactly. They also abut along the path, with the membranes that implies,
    which is why they are the fallback rather than the route.
    """
    profile_uv = [np.asarray(p, dtype=float) for p in profile_uv]
    n = len(points)
    if n < 2 or len(profile_uv) != n:
        raise ManifoldError("a sweep needs a profile at every station")
    m = len(profile_uv[0])
    if m < 2:
        raise ManifoldError("a profile needs at least two points")

    if all(len(p) == m for p in profile_uv):
        sections = []
        for k in range(n):
            p = np.asarray(points[k], dtype=float)
            d = np.asarray(normals[k], dtype=float)
            uv = profile_uv[k]
            xy = p[None, :] + d[None, :] * uv[:, :1]
            sections.append(np.vstack([
                np.column_stack([xy, uv[:, 1]]),
                [xy[-1, 0], xy[-1, 1], far],
                [xy[0, 0], xy[0, 1], far]]))
        strip = _strip_mesh(sections, closed)
        if strip is not None:
            return strip

    def slab(k: int, i: int) -> np.ndarray:
        """Profile segment i at station k, closed off to `far`."""
        p, d = np.asarray(points[k], dtype=float), np.asarray(normals[k], float)
        (u0, v0), (u1, v1) = profile_uv[k][i], profile_uv[k][i + 1]
        a, b = p + d * u0, p + d * u1
        return np.array([[a[0], a[1], v0], [b[0], b[1], v1],
                         [b[0], b[1], far], [a[0], a[1], far]])

    last = n if closed else n - 1
    cells = []
    for i in range(m - 1):
        for k in range(last):
            nxt = (k + 1) % n
            pts = np.vstack([slab(k, i), slab(nxt, i)])
            cells.append(Manifold.hull_points([tuple(map(float, q))
                                               for q in pts]))
    return union_all(cells)


def volume(man: Manifold) -> float:
    return float(man.volume())


def surface_z_at(mesh, pts_xy, missing: float = float("nan"),
                 face: str = "top") -> np.ndarray:
    """Surface height above each (x, y), by vertical ray. The mesh counterpart
    of `core.solid.occ.surface_z_at`.

    `face="bottom"` takes the lowest hit instead — the anterior face.

    **`missing` defaults to NaN, not 0.0.** The B-Rep version defaults to 0.0,
    and that cost a real bug: a ray that hits nothing is indistinguishable from
    a surface sitting exactly on the anterior face, so the pad splay treated the
    empty nose notch as solid material at z=0 and cut Gabriel's frame in half.
    A caller here has to decide what a miss means, and NaN makes forgetting
    loud instead of silent.
    """
    origins = np.column_stack([np.asarray(pts_xy, dtype=float),
                               np.full(len(pts_xy), -1e4)])
    directions = np.tile([0.0, 0.0, 1.0], (len(origins), 1))
    locations, index_ray, _tri = mesh.ray.intersects_location(
        origins, directions, multiple_hits=True)

    out = np.full(len(origins), float(missing), dtype=float)
    if len(locations) == 0:
        return out
    take_top = face != "bottom"
    for i, z in zip(index_ray, locations[:, 2]):
        current = out[i]
        if np.isnan(current) or (z > current if take_top else z < current):
            out[i] = z
    return out


def to_trimesh(man: Manifold):
    """The mesh, welded by Manifold's own merge map, at full precision.

    MeshGL duplicates vertices along property boundaries by design, so the raw
    triangle soup looks open. `merge_from_vert`/`merge_to_vert` is the library
    stating which duplicates are the same point; applying it is the difference
    between a watertight answer and a spurious 33,036 boundary edges.

    **`to_mesh64`, not `to_mesh`.** Manifold keeps float64 internally — it
    round-trips 50.000000123456789 exactly — but `to_mesh()` hands back
    **float32**, and this function is the one place the whole app reads a model
    through: `verify_mesh`, every volume gate, the anchor rays, STL export. At a
    50 mm coordinate the float32 spacing is about 4e-6 mm, so the downcast was
    merging distinct vertices and splitting others.

    It was measured before it was believed. Extracting the same builds both ways,
    the eyewire bezel's zero-area triangle count falls from 308 / 400 / 428 to
    2 / 4 / 4 — around 99% of them were our own downcast — while the aviator's
    self-touching edges *rise* from 2 to 6, because quantisation does not only
    invent contacts: merging turns faces degenerate, and a degenerate face
    carries its edges out of the count with it. Float32 was hiding as much as it
    was inventing.

    `process=False` on purpose: trimesh's cleanup drops degenerate slivers, and
    dropping a sliver can itself open a closed mesh. The mesh is already welded
    correctly by the time it gets here, so there is nothing to clean and
    cleaning could only introduce error.
    """
    import trimesh

    mesh = man.to_mesh64()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)

    remap = np.arange(len(verts))
    merge_from = np.asarray(mesh.merge_from_vert, dtype=np.int64)
    if len(merge_from):
        remap[merge_from] = np.asarray(mesh.merge_to_vert, dtype=np.int64)

    return trimesh.Trimesh(vertices=verts, faces=remap[faces], process=False)
