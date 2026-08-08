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

Two things here were learned the hard way in the spike and must not be
rediscovered:

* **Weld with the merge map, not with positions.** `to_mesh()` hands back
  MeshGL, which splits vertices along property boundaries — the same point in
  space appears several times by design. Matching them back up by rounding
  coordinates is guesswork that silently opens seams; `merge_from_vert` /
  `merge_to_vert` is the library telling you exactly which duplicates are one
  vertex. `to_trimesh` below does it that way.
* **Sweep as a chain of per-segment convex hulls.** Every swept feature in this
  project (groove V, bezel, splay, scoop, footing blends) is a profile carried
  along a ring. Hulling each consecutive pair of profiles cannot
  self-intersect however tight the corner, which is precisely where
  `BRepOffsetAPI_MakePipeShell` produced 401-second invalid shapes.
"""
from __future__ import annotations

import numpy as np
from manifold3d import CrossSection, FillRule, Manifold, OpType
from shapely.geometry import Polygon

__all__ = [
    "ManifoldError",
    "cross_section",
    "extrude",
    "hull_chain",
    "subtract_all",
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


def hull_chain(profiles: list[np.ndarray], closed: bool = True) -> Manifold:
    """Sweep a profile along a path as the union of per-segment convex hulls.

    `profiles[i]` is the (k, 3) section at station i. Each consecutive pair is
    hulled into a convex cell and the cells are unioned. The cells overlap at
    shared stations, which is what makes the union a solid tube rather than a
    string of beads.

    Requires each profile to be convex — every section this project sweeps is (a
    triangle, a trapezoid, a half-ellipse closed upward). A concave profile
    would have its hull fill in the concavity silently, so callers that grow one
    must decompose it first.
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


def volume(man: Manifold) -> float:
    return float(man.volume())


def to_trimesh(man: Manifold):
    """The mesh, welded by Manifold's own merge map.

    MeshGL duplicates vertices along property boundaries by design, so the raw
    triangle soup looks open. `merge_from_vert`/`merge_to_vert` is the library
    stating which duplicates are the same point; applying it is the difference
    between a watertight answer and a spurious 33,036 boundary edges.

    `process=False` on purpose: trimesh's cleanup drops degenerate slivers, and
    dropping a sliver can itself open a closed mesh. The mesh is already welded
    correctly by the time it gets here, so there is nothing to clean and
    cleaning could only introduce error.
    """
    import trimesh

    mesh = man.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)

    remap = np.arange(len(verts))
    merge_from = np.asarray(mesh.merge_from_vert, dtype=np.int64)
    if len(merge_from):
        remap[merge_from] = np.asarray(mesh.merge_to_vert, dtype=np.int64)

    return trimesh.Trimesh(vertices=verts, faces=remap[faces], process=False)
