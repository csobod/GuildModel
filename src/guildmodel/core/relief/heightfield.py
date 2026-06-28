from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class Heightfield:
    """2D raster of Z values (mm) over the frame region.

    Cells are square with side length `resolution` mm.
    Cell (0, 0) corresponds to world position `origin`.
    Array shape is (rows, cols) == (height_mm / resolution, width_mm / resolution).
    """
    z: np.ndarray          # shape (rows, cols), dtype float64, values in mm
    origin: tuple[float, float]   # (x, y) world coordinate of cell [0, 0]
    resolution: float      # mm per pixel

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape  # type: ignore[return-value]

    @property
    def width_mm(self) -> float:
        return self.z.shape[1] * self.resolution

    @property
    def height_mm(self) -> float:
        return self.z.shape[0] * self.resolution

    def world_to_pixel(self, x: float, y: float) -> tuple[int, int]:
        col = int((x - self.origin[0]) / self.resolution)
        row = int((y - self.origin[1]) / self.resolution)
        return row, col

    def pixel_to_world(self, row: int, col: int) -> tuple[float, float]:
        x = self.origin[0] + col * self.resolution
        y = self.origin[1] + row * self.resolution
        return x, y

    @classmethod
    def flat(
        cls,
        width_mm: float,
        height_mm: float,
        z_value: float,
        resolution: float,
        origin: tuple[float, float] = (0.0, 0.0),
    ) -> "Heightfield":
        rows = max(1, int(round(height_mm / resolution)))
        cols = max(1, int(round(width_mm / resolution)))
        z = np.full((rows, cols), z_value, dtype=np.float64)
        return cls(z=z, origin=origin, resolution=resolution)
