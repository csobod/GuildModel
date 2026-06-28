"""Build a watertight two-sided mesh from front and back heightfields + profile outline."""
from __future__ import annotations
import numpy as np
from shapely.geometry import Polygon

from ..relief.heightfield import Heightfield


def build_mesh(
    front_field: Heightfield,
    back_field: Heightfield,
    outline: Polygon,
) -> "trimesh.Trimesh":  # noqa: F821
    """Return a watertight trimesh.Trimesh of the frame solid.

    Triangulates the front surface, back surface, and stitches a wall
    along the profile boundary to close the mesh.
    """
    import trimesh

    front_verts, front_faces = _heightfield_to_mesh(front_field, outline, flip=False)
    back_verts, back_faces = _heightfield_to_mesh(back_field, outline, flip=True)

    n_front = len(front_verts)
    combined_verts = np.vstack([front_verts, back_verts])
    combined_faces = np.vstack([front_faces, back_faces + n_front])

    wall_verts, wall_faces = _build_wall(outline, front_field, back_field)
    n_prev = len(combined_verts)
    combined_verts = np.vstack([combined_verts, wall_verts])
    combined_faces = np.vstack([combined_faces, wall_faces + n_prev])

    mesh = trimesh.Trimesh(vertices=combined_verts, faces=combined_faces, process=True)
    return mesh


def _heightfield_to_mesh(
    field: Heightfield,
    outline: Polygon,
    flip: bool,
) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = field.z.shape
    verts = []
    for r in range(rows):
        for c in range(cols):
            x, y = field.pixel_to_world(r, c)
            z = field.z[r, c]
            verts.append([x, y, z])
    verts = np.array(verts, dtype=np.float64)

    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i00 = r * cols + c
            i10 = (r + 1) * cols + c
            i01 = r * cols + (c + 1)
            i11 = (r + 1) * cols + (c + 1)
            if flip:
                faces.append([i00, i10, i01])
                faces.append([i10, i11, i01])
            else:
                faces.append([i00, i01, i10])
                faces.append([i10, i01, i11])

    return verts, np.array(faces, dtype=np.int64)


def _build_wall(
    outline: Polygon,
    front_field: Heightfield,
    back_field: Heightfield,
) -> tuple[np.ndarray, np.ndarray]:
    coords = list(outline.exterior.coords)
    n = len(coords)
    verts = []
    for x, y in coords:
        r_f, c_f = front_field.world_to_pixel(x, y)
        r_b, c_b = back_field.world_to_pixel(x, y)
        rf = np.clip(r_f, 0, front_field.z.shape[0] - 1)
        cf = np.clip(c_f, 0, front_field.z.shape[1] - 1)
        rb = np.clip(r_b, 0, back_field.z.shape[0] - 1)
        cb = np.clip(c_b, 0, back_field.z.shape[1] - 1)
        z_front = float(front_field.z[rf, cf])
        z_back = float(back_field.z[rb, cb])
        verts.append([x, y, z_front])
        verts.append([x, y, z_back])

    faces = []
    for i in range(n - 1):
        a, b = i * 2, i * 2 + 1
        c, d = (i + 1) * 2, (i + 1) * 2 + 1
        faces.append([a, b, c])
        faces.append([b, d, c])

    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64)
