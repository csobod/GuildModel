"""The part's edges, read off the mesh (BUILDPLAN-NEW §8.2 / M-N2).

**Why this exists, and why it was backed out once.** The viewer's four display
modes are drawings *of the edges*. A B-Rep knows its own — `solid.tessellate`
hands over real topological curves — and a mesh does not, so the mesh kernel
shipped with `edges=None` and three of the four modes disabled.

Deriving them from dihedral angle was built, measured and reverted, on numbers
that looked damning: 89% of the B-Rep's creases found, but only **43.7%** of
what would be drawn had any counterpart, and the surplus was "exact 90 degree
creases running up to 13.9 mm" that could not be explained. Drawing unexplained
lines on a maker's part is worse than drawing none.

The explanation turned up a milestone later, from the other end. Those were
**zero-area triangles**: Manifold emitted them, their normal is the zero vector,
and the angle between a zero vector and a unit one is exactly 90 degrees — so
every one of them arrived as a right-angle crease. They were also the stitches
holding the surface's self-contacts together, and fixing that (BUILDPLAN-NEW
risk 0) removed both at once. `mesh_check.welded_surface` drops whatever is
left.

Re-measured on all three drawings with them gone, bare:

| | demo | aviator | gabriel |
|---|---|---|---|
| drawn length that is a real edge of the part | 98.6% | 98.8% | 98.8% |
| *the B-Rep's own tessellation*, same detector | 98.2% | 98.5% | 98.4% |
| B-Rep creases this finds | 100.0% | 99.9% | 100.0% |

So it is as precise as running the same detector on the B-Rep's mesh, and it
misses none of what that detector finds. The ~1.4% that is not a topological
edge is the residue; the ~6% this draws that the B-Rep's mesh does *not* is real
topological edges its coarser tessellation did not resolve as creases.

**What it deliberately does not draw.** The topological set is ~6,200-6,800 mm
against ~1,400-1,700 mm of actual crease — roughly three quarters of what the
B-Rep viewer draws today is tangent patch seams, the "5,878 curves for a part
with perhaps a hundred features" already on record. Those are not edges of the
part and their absence here is the feature, not the shortfall.

**Segments, not chains.** The first attempt chained sharp edges with
`trimesh.graph.traversals`, which returns the order nodes were *visited* rather
than a walk along adjacent ones, so it drew a straight line across the frame at
every depth-first backtrack: 92% accurate loose, 62% once "chained". VTK draws a
two-point polyline exactly the same as a long one, so there is nothing to win
here and a whole class of error to avoid.
"""
from __future__ import annotations

import numpy as np

__all__ = ["CREASE_ANGLE_DEG", "feature_edges"]

#: Angle between adjacent face *normals* above which the shared edge is drawn,
#: degrees. Note the convention: coplanar faces read 0, so a 30 degree chamfer
#: meeting a flat face reads 30 — which is how the raster's `feature_angle=40.0`
#: came to smooth 30 degree chamfers away.
#:
#: 20 is the middle of a measured gap rather than a taste. Below it lie the
#: facets of the curved footing blends, and drawing those would lay a contour
#: map over every blend; above it lie the features. Length drawn against
#: threshold on the demo frame, fully featured: 6584 mm at 1 degree, 3273 at 5,
#: 2639 at 12, then **flat** — 2527 at 20, 2517 at 25, 2508 at 28 — before the
#: 30 degree eyewire bezel drops out at 32 (2266) and the 45 degree features at
#: 40 (1744). The blend noise is spent by 12 and the shallowest real feature is
#: at 30, so anywhere in 12-28 behaves identically; 20 has the most room either
#: side.
#:
#: A bezel or edge feature configured shallower than this would not be drawn.
#: The schema allows it; at that angle the cut is not visible as an edge either.
CREASE_ANGLE_DEG = 20.0


def feature_edges(mesh, angle_deg: float = CREASE_ANGLE_DEG) -> list[np.ndarray]:
    """The mesh's creases, as the list of polylines the viewer draws.

    Each is a single (2, 3) segment — see the module docstring on why they are
    not chained. Returns `[]` rather than raising for anything unreadable: a
    display aid must not be able to fail a build.
    """
    from ..mesh_check import welded_surface

    welded = welded_surface(mesh)
    if welded is None or not len(welded.faces):
        return []
    try:
        angles = welded.face_adjacency_angles
        pairs = welded.face_adjacency_edges
    except Exception:                                        # noqa: BLE001
        return []

    sharp = np.asarray(angles) > np.radians(float(angle_deg))
    if not sharp.any():
        return []
    return list(np.asarray(welded.vertices)[np.asarray(pairs)[sharp]])
