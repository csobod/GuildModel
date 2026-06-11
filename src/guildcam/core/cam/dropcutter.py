"""Drop-cutter (cutter-location surface) via grayscale morphological dilation.

For a heightfield Z(x,y) and a tool of radius R:
  - Ball-nose:   CLS = grey_dilation(Z, structure=hemisphere(R, res))
  - Flat endmill: CLS = grey_dilation(Z, structure=flat_disc(R, res))
  - Toroidal:    CLS = grey_dilation(Z, structure=toroid(R_outer, R_corner, res))

The structuring element encodes the tool's shape as a height offset surface
(the amount by which the tool center must be raised above each offset point
to avoid gouging). This is the mathematical dual of the standard drop-cutter
algorithm and runs in C via scipy — no OpenCAMLib needed.
"""
from __future__ import annotations
import numpy as np
from scipy.ndimage import grey_dilation

from ..relief.heightfield import Heightfield


def _hemisphere(radius_mm: float, resolution: float) -> np.ndarray:
    r_px = radius_mm / resolution
    size = int(np.ceil(r_px)) * 2 + 1
    cx = cy = size // 2
    y, x = np.ogrid[:size, :size]
    d2 = ((x - cx) ** 2 + (y - cy) ** 2) * resolution ** 2
    with np.errstate(invalid="ignore"):
        h = np.where(d2 <= radius_mm ** 2, np.sqrt(np.maximum(radius_mm ** 2 - d2, 0)), -np.inf)
    return h - h.max()   # normalize so center = 0


def _flat_disc(radius_mm: float, resolution: float) -> np.ndarray:
    r_px = radius_mm / resolution
    size = int(np.ceil(r_px)) * 2 + 1
    cx = cy = size // 2
    y, x = np.ogrid[:size, :size]
    d2 = ((x - cx) ** 2 + (y - cy) ** 2) * resolution ** 2
    return np.where(d2 <= radius_mm ** 2, 0.0, -np.inf)


def _toroid(outer_radius_mm: float, corner_radius_mm: float, resolution: float) -> np.ndarray:
    """Structuring element for a toroidal (bull-nose) cutter."""
    r_px = outer_radius_mm / resolution
    size = int(np.ceil(r_px)) * 2 + 1
    cx = cy = size // 2
    y, x = np.ogrid[:size, :size]
    d = np.sqrt(((x - cx) ** 2 + (y - cy) ** 2)) * resolution
    torus_center_r = outer_radius_mm - corner_radius_mm
    radial_dist = np.abs(d - torus_center_r)
    in_flat = d <= torus_center_r
    in_torus = radial_dist <= corner_radius_mm
    h = np.full_like(d, -np.inf)
    h[in_flat] = 0.0
    h[in_torus] = np.sqrt(np.maximum(corner_radius_mm ** 2 - radial_dist[in_torus] ** 2, 0)) - corner_radius_mm
    return h


def cutter_location_surface(
    field: Heightfield,
    tool_type: str,        # "ball" | "flat" | "toroid"
    tool_radius_mm: float,
    corner_radius_mm: float = 0.0,   # toroid only
) -> Heightfield:
    """Return the cutter-location surface for the given tool and heightfield."""
    res = field.resolution
    if tool_type == "ball":
        struct = _hemisphere(tool_radius_mm, res)
    elif tool_type == "flat":
        struct = _flat_disc(tool_radius_mm, res)
    elif tool_type == "toroid":
        struct = _toroid(tool_radius_mm, corner_radius_mm, res)
    else:
        raise ValueError(f"Unknown tool_type: {tool_type!r}")

    cls_z = grey_dilation(field.z, structure=struct)
    return Heightfield(z=cls_z, origin=field.origin, resolution=res)


def drop_cutter_paths(
    field: Heightfield,
    tool_type: str,
    tool_radius_mm: float,
    stepover_mm: float,
    corner_radius_mm: float = 0.0,
) -> list[list[tuple[float, float, float]]]:
    """Generate raster cutter-location paths over the heightfield.

    Returns a list of polylines, each a list of (x, y, z) tool-center positions.
    Stepover is in mm; paths run along X, stepping in Y.
    """
    cls = cutter_location_surface(field, tool_type, tool_radius_mm, corner_radius_mm)
    step_px = max(1, int(round(stepover_mm / field.resolution)))

    paths: list[list[tuple[float, float, float]]] = []
    rows, cols = cls.z.shape
    for row in range(0, rows, step_px):
        line: list[tuple[float, float, float]] = []
        for col in range(cols):
            x, y = cls.pixel_to_world(row, col)
            z = float(cls.z[row, col])
            line.append((x, y, z))
        if row // step_px % 2 == 1:
            line = line[::-1]   # boustrophedon (zigzag) to minimize rapids
        paths.append(line)
    return paths
