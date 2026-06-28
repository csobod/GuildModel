"""Plane cross-section of a triangle mesh (BUILDPLAN M7.13).

Slice a mesh with a plane and return the cut as polylines — used to verify terrace
heights and footing depths (the castle teaching ethos, §2) and to back the 3D
section view. pyvista does the slicing; this wraps it behind a plain
``(points, faces) -> polylines`` API so the geometry is unit-testable.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

Point3 = tuple[float, float, float]


def _to_polydata(points, faces):
    import pyvista as pv

    pts = np.asarray(points, dtype=float)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    pv_faces = np.hstack([np.full((len(f), 1), 3, dtype=np.int64), f]).ravel()
    return pv.PolyData(pts, pv_faces)


def _polylines_of(sliced) -> list[list[Point3]]:
    """Pull connected polylines out of a pyvista line PolyData (the slice result)."""
    if sliced is None or sliced.n_points == 0:
        return []
    pts = np.asarray(sliced.points, dtype=float)
    lines = np.asarray(sliced.lines, dtype=np.int64)
    out: list[list[Point3]] = []
    i = 0
    while i < len(lines):
        n = int(lines[i])
        idx = lines[i + 1: i + 1 + n]
        if n >= 2:
            out.append([(float(pts[j][0]), float(pts[j][1]), float(pts[j][2]))
                        for j in idx])
        i += 1 + n
    return out


def mesh_section(points: Sequence[Point3], faces, origin: Point3,
                 normal: Point3) -> list[list[Point3]]:
    """Cross-section polylines where the plane ``(origin, normal)`` cuts the mesh.

    ``points`` is (N, 3); ``faces`` is (M, 3) triangle indices. Returns a list of
    polylines (each a list of (x, y, z)); empty if the plane misses the mesh. Line
    segments are stitched into connected polylines where possible.
    """
    mesh = _to_polydata(points, faces)
    sliced = mesh.slice(normal=normal, origin=origin)
    if sliced is None or sliced.n_points == 0:
        return []
    try:                                      # join the cut segments into polylines
        sliced = sliced.strip(join=True)
    except Exception:                         # fall back to raw segments
        pass
    return _polylines_of(sliced)
