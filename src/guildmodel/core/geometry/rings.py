"""Ring geometry shared by both model kernels (BUILDPLAN-NEW M-N1).

These answer *where* things go — stations around an aperture, which way is into
the material, and what the rim lip is once the groove has shrunk it. None of it
is about triangles or trimmed surfaces, and both `core/solid` (OpenCASCADE) and
`core/model` (Manifold) need every one of them.

They lived in `core/solid/features.py` until the mesh kernel needed them, which
would have meant importing OCP — ~70 MB of shared libraries — to ask a Shapely
question. Moved rather than copied: a port that duplicates its geometry grows a
second set of subtly different answers, and these are exactly the functions
whose answers must not drift between the two paths.

`core/solid/features.py` re-exports them under their old private names, so the
B-Rep path and its tests are untouched.

**One exception, stated because it is a wart.** `offset_aperture` samples the
*exact* parallel curve, and the only sampler we have is OCCT's. It imports that
lazily, so this module still costs nothing to import — but a groove build on the
mesh path does pull OCP in. Replacing that sampler is M-N1 work; until then the
rim lip is the one place the mesh kernel is not yet independent.

Moving it here surfaced the hazard immediately: `nurbs_edge` came along as an
undefined name, `offset_aperture`'s bare `except Exception` swallowed the
`NameError`, and every lip ring silently fell back to the Shapely buffer with no
curve attached. Valid output, quietly worse — the same shape as the two
swallowed-exception bugs in BUILDPLAN-NEW §3.2.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import prep

from .curves import OffsetCurve
from .regions import CastlePartition

__all__ = ["crest_inside", "inward_normals", "lip_body", "lip_partition",
           "offset_aperture", "ring_stations"]

def ring_stations(ring: LineString, n: int):
    """Points and unit tangents evenly spaced around a closed ring."""
    total = ring.length
    ss = np.linspace(0.0, total, n, endpoint=False)
    pts, tans = [], []
    eps = max(total / (8 * n), 1e-4)
    for s in ss:
        p = ring.interpolate(float(s))
        a = ring.interpolate(float((s - eps) % total))
        b = ring.interpolate(float((s + eps) % total))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([p.x, p.y])
        tans.append(t)
    return np.array(pts), np.array(tans)


def inward_normals(body: Polygon, pts: np.ndarray, tans: np.ndarray,
            probe: float = 0.05) -> np.ndarray:
    """Unit normals pointing into the material, voted rather than assumed.

    An aperture ring's winding is whatever Shapely handed over; guessing it
    wrong would cut the chamfer into thin air inside the lens hole.
    """
    n = np.column_stack([-tans[:, 1], tans[:, 0]])
    votes = 0
    for p, nn in zip(pts, n):
        if body.contains(Point(*(p + nn * probe))):
            votes += 1
        elif body.contains(Point(*(p - nn * probe))):
            votes -= 1
    return n if votes >= 0 else -n


# ---------------------------------------------------------------- lens groove

#: Sections lofted around an aperture ring for the groove V. Matched to
#: `BEZEL_STATIONS` — same rings, same chord-error argument, and the two cutters
#: meet at the rim, so a mismatch would put a step where they overlap.
GROOVE_STATIONS = 180


def lip_body(body: Polygon, depth_mm: float, is_hole=lambda r: False) -> Polygon:
    """The body with each lens aperture shrunk inward by the groove depth.

    Mirrors `relief.castle._undersized_lens_body`: with the groove on, the
    visible aperture is the rim *lip*, cut `depth_mm` smaller, and the groove is
    cut back outward from it so its apex lands exactly on the original LENS
    contour — which is what keeps the boxed dimension honest. Decorative OUTLINE
    holes are through-cuts and take no groove, so they keep their size.
    """
    from shapely.geometry import Polygon as _P

    holes = []
    for ring in body.interiors:
        if is_hole(ring):
            holes.append(ring)
            continue
        shrunk = _P(ring).buffer(-abs(depth_mm))
        if shrunk.is_empty:
            holes.append(ring)                    # degenerate: keep it closed
            continue
        biggest = max(getattr(shrunk, "geoms", [shrunk]), key=lambda g: g.area)
        holes.append(biggest.exterior)
    return _P(body.exterior, holes)


#: Chord tolerance for sampling an offset aperture back to points, in mm. The
#: same 0.01 the importers flatten at, so the lip polyline is no coarser than
#: the contour it came from and every consumer that wants points is unaffected.
_LIP_CHORD_TOL_MM = 0.01


#: How far the exact offset may disagree in area with the Shapely buffer of the
#: same ring, as a fraction. They describe the same shrink by two routes, so the
#: agreement is close where the input is finely flattened — 2e-5 on the demo
#: apertures — and looser on a coarse ring, where the buffer is offsetting
#: visibly straight chords (1.5e-3 on a 256-segment circle). One percent leaves
#: room for the coarse case while still being far below any way of getting the
#: offset genuinely wrong, all of which miss by tens of percent.
_LIP_AREA_TOL = 0.01


def offset_aperture(curve, reference, depth: float):
    """`(points, OffsetCurve)` for the aperture shrunk by `depth`, or None.

    The exact parallel curve, sampled — not `lens.buffer(-depth)`, which offsets
    the *flattened* ring and so approximates an approximation. Both land in the
    same place; the difference is that this one still knows what it is, so the
    rim lip stays a curve all the way into the kernel.

    `reference` is that Shapely buffer, and it does two jobs. It **picks the
    sign**: OCCT offsets along `Z x tangent`, so which sign shrinks depends on
    how the curve winds, and the demo frame's two lens rings wind opposite ways
    — assume a sign and one eye grows while the other shrinks. And it **bounds
    the answer**: `Geom_OffsetCurve` does not trim, so where a contour's
    curvature radius dips below `depth` it hands back a self-intersecting curve,
    and an offset larger than the aperture passes clean through the middle and
    comes back as a smaller ring wound the other way — valid, simple, smaller in
    area, and completely wrong. Requiring agreement with the buffer catches both
    without needing to enumerate them.

    Returns None on any of that, and the caller falls back to the buffer.
    """
    if curve is None or reference is None or depth <= 0.0:
        return None
    from shapely.geometry import Polygon as _P
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection

    from ..solid.occ import nurbs_edge
    from .curves import OffsetCurve

    for signed in (-depth, depth):
        offset = OffsetCurve(basis=curve, distance=signed,
                             layer=getattr(curve, "layer", ""))
        try:
            adaptor = BRepAdaptor_Curve(nurbs_edge(offset, 0.0))
            sampler = GCPnts_QuasiUniformDeflection(adaptor, _LIP_CHORD_TOL_MM)
            pts = [(sampler.Value(i).X(), sampler.Value(i).Y())
                   for i in range(1, sampler.NbPoints() + 1)]
            poly = _P(pts)
        except Exception:                                    # noqa: BLE001
            continue
        if len(pts) < 4 or not poly.is_valid or not poly.exterior.is_simple:
            continue
        if abs(poly.area - reference.area) <= _LIP_AREA_TOL * reference.area:
            return pts, offset
    return None


def lip_partition(partition: CastlePartition, depth_mm: float):
    """Re-partition the frame against the *shrunk* apertures.

    The terraces have to reach the rim lip, and the raster gets that for free —
    it shrinks only the `inside` mask and lets its orphan-fill hand every newly
    exposed annulus cell to the nearest zone. A solid has to own the material.

    The obvious route — buffering each zone outward into the annulus — does not
    survive the kernel. Even handing the annulus out as a strict partition so no
    two zones claim the same sliver, the buffered rings carry enough
    near-coincident geometry that fusing the terrace prisms **collapses to an
    empty solid while still reporting `IsValid()`**. Re-running the existing
    partitioner on shrunk lens polygons instead produces zones that tile the lip
    body exactly, with no buffer artifacts, and it reuses code that is already
    proven: same nine zone names, still `classified`, same ten SCULPT edges.
    """
    from .regions import curves_by_ring, partition_zones
    from shapely.geometry import Polygon as _P

    holes = [r for r in partition.body.interiors if partition.is_hole(r)]
    lens_rings = [r for r in partition.body.interiors if not partition.is_hole(r)]
    if not lens_rings:
        return partition
    outline = _P(partition.body.exterior, holes)

    shrunk, lip_points, lip_curves = [], [], []
    for ring in lens_rings:
        lens = _P(ring)
        buffered = lens.buffer(-abs(depth_mm))
        buffered = (None if buffered.is_empty else
                    max(getattr(buffered, "geoms", [buffered]), key=lambda g: g.area))
        made = offset_aperture(partition.ring_curve(ring), buffered, abs(depth_mm))
        if made is not None:
            pts, offset = made
            shrunk.append(_P(pts))
            lip_points.append(pts)
            lip_curves.append(offset)
            continue
        # No authored curve, or the exact offset disagreed with the buffer:
        # take the buffer. Empty means the aperture vanished at this depth —
        # leave it alone rather than punch it out.
        shrunk.append(lens if buffered is None else buffered)

    cuts = [list(e.cut.coords) for e in partition.edges]
    # The outline exterior and the decorative holes are untouched by the shrink,
    # so their keys still match and they carry straight through — on the demo
    # frame that alone is 342 of the body's flattened vertices against the two
    # apertures' 266. The apertures then come back as offsets, above.
    source = dict(partition.source_curves)
    source.update(curves_by_ring(lip_points, lip_curves))

    lip = partition_zones(outline, shrunk, cuts, source_curves=source)
    if not lip.classified or len(lip.zones) != len(partition.zones):
        raise BooleanError("re-partitioning against the rim lip changed the castle")
    return lip


def crest_inside(body: Polygon, pts: np.ndarray, inward: np.ndarray,
                  c: np.ndarray, steps: int = 24) -> np.ndarray:
    """Shorten each crest offset until the crest point is inside the material.

    **Inward from the outline is not the same as into the body.** At the bottom
    centre a frame has the nose notch, and the default 6 mm crest offset steps
    straight out through it. The anchor ray then finds nothing, `surface_z_at`
    reports its `missing` value — 0.0, indistinguishable from "the surface is
    at the anterior face" — and the chamfer, which spans from the cut surface
    *up* to `top`, removes the entire thickness at that station.

    On the Gabriel fixture that cut the frame into two halves: left
    x[-67.65, -1.38], right x[1.38, 67.65], watertight, `IsValid` true, zero
    holes. Only the body count caught it.

    Clamping here rather than repairing the anchor afterwards, because a crest
    outside the body is wrong on its own terms — every downstream quantity
    (drop, width, anchor) is measured from it.
    """
    prepared = prep(body)
    out = np.asarray(c, dtype=float).copy()
    for i, (point, normal, offset) in enumerate(zip(pts, inward, c)):
        if offset <= 0.0:
            continue
        for t in np.linspace(float(offset), 0.0, steps):
            q = point + normal * t
            if t <= 0.0 or prepared.contains(Point(float(q[0]), float(q[1]))):
                out[i] = t
                break
    return out
