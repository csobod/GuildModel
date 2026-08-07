"""Solid -> triangles **and edges** (BUILDPLAN Stage 2).

This is the module the display modes rest on, and the reason they were
impossible before Stage 2.

A heightfield mesh has no edges. At the 0.15 mm export grid the demo frame is
263,800 triangles and ~396,000 triangle borders, and not one of them is an edge
of the frame — they are the seams between adjacent grid cells. Drawing them is a
wall of noise, which is why the viewer had to guess creases from a dihedral
angle threshold (`feature_angle=40.0`) and got it wrong in both directions:
30 degree chamfers smoothed away, the 45 degree brow chamfer split
inconsistently.

A solid knows its edges exactly. The same frame carries ~3,850 of them — the
outline, each lens ring, each terrace step, each feature boundary — as real
topological curves. `tessellate()` returns them alongside the triangles, so the
viewer draws the actual edges of the part and nothing else. Hidden-edge handling
then falls out of depth testing rather than needing a heuristic.

Edges are discretised with `GCPnts_TangentialDeflection` off the curve itself
rather than lifted from the face triangulation: it gives a clean polyline at a
controlled chordal *and* angular tolerance, independent of how the surface
happened to mesh.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_TangentialDeflection
from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape

__all__ = ["Tessellation", "tessellate"]

#: Chordal deviation for the surface mesh, in mm. 0.02 keeps the visible
#: faceting below what the eye resolves on a 40 mm aperture without producing
#: the vertex counts the raster mesher did.
DEFAULT_DEFLECTION_MM = 0.02

#: Angular deviation, radians. Governs how finely a tight curve is chased.
DEFAULT_ANGLE_RAD = 0.2


@dataclass
class Tessellation:
    """Triangles for shading, plus the part's real edges for line drawing."""
    vertices: np.ndarray                       # (n, 3) float
    faces: np.ndarray                          # (m, 3) int, CCW outward
    edges: list[np.ndarray] = field(default_factory=list)   # each (k, 3) float

    @property
    def edge_segments(self) -> np.ndarray:
        """Every edge polyline as flat (s, 2, 3) line segments — the form a
        renderer wants for a line set."""
        segs = [np.stack([p[:-1], p[1:]], axis=1)
                for p in self.edges if len(p) >= 2]
        if not segs:
            return np.zeros((0, 2, 3), dtype=float)
        return np.concatenate(segs, axis=0)

    def to_trimesh(self):
        import trimesh
        return trimesh.Trimesh(vertices=self.vertices, faces=self.faces,
                               process=True)


def _face_triangles(face, loc: TopLoc_Location):
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return None, None
    trsf = loc.Transformation()
    n = tri.NbNodes()
    pts = np.empty((n, 3), dtype=float)
    for i in range(1, n + 1):
        p = tri.Node(i).Transformed(trsf)
        pts[i - 1] = (p.X(), p.Y(), p.Z())

    m = tri.NbTriangles()
    idx = np.empty((m, 3), dtype=np.int64)
    for i in range(1, m + 1):
        t = tri.Triangle(i)
        idx[i - 1] = (t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1)

    # A REVERSED face stores its triangles wound against the surface normal;
    # flipping here is what keeps the assembled mesh consistently outward, which
    # is what makes it watertight rather than merely closed-looking.
    if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
        idx = idx[:, [0, 2, 1]]
    return pts, idx


def tessellate(shape: TopoDS_Shape,
               deflection: float = DEFAULT_DEFLECTION_MM,
               angle: float = DEFAULT_ANGLE_RAD,
               with_edges: bool = True) -> Tessellation:
    """Mesh `shape`, returning triangles and its topological edge polylines."""
    BRepMesh_IncrementalMesh(shape, float(deflection), False, float(angle), True)

    verts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    offset = 0
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        exp.Next()
        loc = TopLoc_Location()
        pts, idx = _face_triangles(face, loc)
        if pts is None or len(idx) == 0:
            continue
        verts.append(pts)
        faces.append(idx + offset)
        offset += len(pts)

    if not verts:
        return Tessellation(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))

    tess = Tessellation(np.concatenate(verts), np.concatenate(faces))
    if with_edges:
        tess.edges = edge_polylines(shape, deflection, angle)
    return tess


def edge_polylines(shape: TopoDS_Shape,
                   deflection: float = DEFAULT_DEFLECTION_MM,
                   angle: float = DEFAULT_ANGLE_RAD) -> list[np.ndarray]:
    """One polyline per topological edge, de-duplicated across shared faces.

    Every edge is used by two faces, so exploring faces would yield each twice;
    exploring EDGE directly still repeats them, hence the key on the sampled
    geometry rather than on shape identity.
    """
    out: list[np.ndarray] = []
    seen: set[tuple] = set()
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        try:
            ad = BRepAdaptor_Curve(edge)
            d = GCPnts_TangentialDeflection(ad, float(angle), float(deflection))
            n = d.NbPoints()
            if n < 2:
                continue
            pts = np.array([(d.Value(i).X(), d.Value(i).Y(), d.Value(i).Z())
                            for i in range(1, n + 1)])
        except Exception:                                    # noqa: BLE001
            continue
        a = tuple(np.round(pts[0], 6))
        b = tuple(np.round(pts[-1], 6))
        key = (a, b, n) if a <= b else (b, a, n)
        if key in seen:
            continue
        seen.add(key)
        out.append(pts)
    return out
