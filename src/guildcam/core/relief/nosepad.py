"""Nosepad buildup heightfield generator."""
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter
from .heightfield import Heightfield


def nosepad_buildup(
    base_field: Heightfield,
    pad_center_x: float,
    pad_center_y: float,
    height_mm: float,
    footprint_mm: float,
    blend_radius_mm: float,
) -> Heightfield:
    """Add a rounded nosepad buildup to an existing front heightfield."""
    z = base_field.z.copy()
    rows, cols = z.shape

    for row in range(rows):
        for col in range(cols):
            x, y = base_field.pixel_to_world(row, col)
            d = np.sqrt((x - pad_center_x) ** 2 + (y - pad_center_y) ** 2)
            r = footprint_mm / 2
            if d < r:
                dome = height_mm * np.sqrt(max(0.0, 1.0 - (d / r) ** 2))
                z[row, col] += dome

    sigma_px = blend_radius_mm / base_field.resolution
    z = gaussian_filter(z, sigma=sigma_px)

    return Heightfield(z=z, origin=base_field.origin, resolution=base_field.resolution)
