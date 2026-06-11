"""Back scallop (déforçage) heightfield generator."""
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter
from shapely.geometry import Polygon

from .heightfield import Heightfield


def back_scallop(
    outline: Polygon,
    stock_thickness_mm: float,
    central_zone_mm: float,
    slope_extent_mm: float,
    min_edge_thickness_mm: float,
    resolution: float = 0.1,
) -> Heightfield:
    """Build the back-face heightfield for the scallop (déforçage) operation.

    The back face is sculpted so the frame is full thickness through a central
    zone, then ramps down to min_edge_thickness_mm toward the outer rim.

    Returns Z values representing the back surface height (from stock bottom),
    so the CAM layer can compute the material to remove.
    """
    minx, miny, maxx, maxy = outline.bounds
    margin = slope_extent_mm + central_zone_mm
    ox = minx - margin
    oy = miny - margin
    width = (maxx - minx) + 2 * margin
    height = (maxy - miny) + 2 * margin

    rows = max(1, int(round(height / resolution)))
    cols = max(1, int(round(width / resolution)))
    z = np.full((rows, cols), min_edge_thickness_mm, dtype=np.float64)

    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    for row in range(rows):
        for col in range(cols):
            x = ox + col * resolution
            y = oy + row * resolution
            dist_from_center = max(abs(x - cx) - central_zone_mm, 0.0)
            if dist_from_center <= 0:
                z[row, col] = stock_thickness_mm
            elif dist_from_center < slope_extent_mm:
                t = 1.0 - dist_from_center / slope_extent_mm
                z[row, col] = min_edge_thickness_mm + t * (stock_thickness_mm - min_edge_thickness_mm)

    sigma_px = 2.0 / resolution
    z = gaussian_filter(z, sigma=sigma_px)

    return Heightfield(z=z, origin=(ox, oy), resolution=resolution)
