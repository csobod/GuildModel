"""Build a relief mesh for live 3D preview.

Everything runs on a single shared grid (same origin, rows, cols) so front
and back surfaces are always aligned.  Shapely 2.0 vectorised containment
masks the grid to the frame outline before meshing.

Entry point: build_preview_mesh()
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon


PREVIEW_RES_MM = 0.3    # mm per pixel for live preview
EXPORT_RES_MM  = 0.05   # mm per pixel for G-code export


@dataclass
class ReliefBuildParams:
    stock_thickness_mm: float = 6.0

    scallop_enabled: bool = True
    scallop_central_zone_mm: float = 10.0
    scallop_slope_extent_mm: float = 8.0
    scallop_min_edge_mm: float = 1.2

    nosepad_enabled: bool = True
    nosepad_height_mm: float = 1.5
    nosepad_footprint_mm: float = 12.0
    nosepad_blend_radius_mm: float = 4.0

    groove_enabled: bool = True
    groove_depth_mm: float = 0.8
    groove_width_mm: float = 0.8

    resolution: float = PREVIEW_RES_MM


# ------------------------------------------------------------------ public API

def build_preview_mesh(
    outline: Polygon,
    lens_od: Polygon,
    lens_os: Polygon,
    params: ReliefBuildParams,
) -> "trimesh.Trimesh":  # noqa: F821
    """Return a trimesh.Trimesh ready for PyVista, masked to *outline*.

    outline  — frame outer profile (cut boundary)
    lens_od  — right lens aperture
    lens_os  — left lens aperture
    params   — build parameters
    """
    import trimesh

    res = params.resolution

    # ---- Unified grid covering outline + small margin ----
    minx, miny, maxx, maxy = outline.bounds
    margin = 2.0
    ox, oy = minx - margin, miny - margin
    width  = (maxx - minx) + 2 * margin
    height = (maxy - miny) + 2 * margin

    rows = max(2, int(round(height / res)))
    cols = max(2, int(round(width  / res)))

    # World coordinates of every cell
    xs = ox + np.arange(cols) * res          # shape (cols,)
    ys = oy + np.arange(rows) * res          # shape (rows,)
    Xs, Ys = np.meshgrid(xs, ys)             # both shape (rows, cols)

    # ---- Containment mask (vectorised Shapely 2.0) ----
    from shapely import contains_xy
    flat_x = Xs.ravel()
    flat_y = Ys.ravel()
    inside = contains_xy(outline, flat_x, flat_y).reshape(rows, cols)

    # ---- Front heightfield ----
    z_front = np.full((rows, cols), params.stock_thickness_mm, dtype=np.float64)

    if params.nosepad_enabled:
        _apply_nosepad(
            z_front, Xs, Ys, lens_od, lens_os,
            params.nosepad_height_mm,
            params.nosepad_footprint_mm,
            params.nosepad_blend_radius_mm,
            res,
        )

    if params.groove_enabled:
        _apply_groove(z_front, Xs, Ys, lens_od, params.groove_depth_mm, params.groove_width_mm, res)
        _apply_groove(z_front, Xs, Ys, lens_os, params.groove_depth_mm, params.groove_width_mm, res)

    # ---- Back heightfield (scallop) — same grid ----
    if params.scallop_enabled:
        z_back = _compute_scallop(
            Xs, Ys, outline,
            params.stock_thickness_mm,
            params.scallop_central_zone_mm,
            params.scallop_slope_extent_mm,
            params.scallop_min_edge_mm,
            res,
        )
        # Back must never exceed front − a minimum web of 0.3 mm
        z_back = np.minimum(z_back, z_front - 0.3)
        z_back = np.maximum(z_back, 0.0)
    else:
        z_back = np.zeros((rows, cols), dtype=np.float64)

    # ---- Build mesh from masked grid ----
    return _masked_mesh(Xs, Ys, z_front, z_back, inside, trimesh)


# ------------------------------------------------------------------ relief helpers

def _apply_nosepad(
    z: np.ndarray,
    Xs: np.ndarray, Ys: np.ndarray,
    lens_od: Polygon, lens_os: Polygon,
    height_mm: float, footprint_mm: float, blend_radius_mm: float,
    res: float,
) -> None:
    """Add a hemispherical nosepad dome between the two lens apertures."""
    from scipy.ndimage import gaussian_filter

    # Centre: midpoint between inner nasal edges, vertically centred on lenses
    od_b = lens_od.bounds   # (minx, miny, maxx, maxy)
    os_b = lens_os.bounds
    sorted_bounds = sorted([od_b, os_b], key=lambda b: b[0])
    left_inner_x  = sorted_bounds[0][2]   # maxx of left lens
    right_inner_x = sorted_bounds[1][0]   # minx of right lens
    pad_cx = (left_inner_x + right_inner_x) / 2.0
    pad_cy = (lens_od.centroid.y + lens_os.centroid.y) / 2.0

    r = footprint_mm / 2.0
    dist2 = (Xs - pad_cx) ** 2 + (Ys - pad_cy) ** 2
    dome = np.where(dist2 < r ** 2, height_mm * np.sqrt(np.maximum(0.0, 1.0 - dist2 / r ** 2)), 0.0)

    sigma = max(1.0, blend_radius_mm / res)
    dome = gaussian_filter(dome, sigma=sigma)
    z += dome


def _apply_groove(
    z: np.ndarray,
    Xs: np.ndarray, Ys: np.ndarray,
    lens: Polygon,
    depth_mm: float,
    width_mm: float,
    res: float,
) -> None:
    """Carve a narrow bevel groove along the lens exterior ring."""
    import shapely as shp

    pts = shp.points(Xs.ravel(), Ys.ravel())
    d = shp.distance(pts, lens.exterior).reshape(Xs.shape)

    t = np.clip(1.0 - d / width_mm, 0.0, 1.0)
    z -= depth_mm * t


def _compute_scallop(
    Xs: np.ndarray, Ys: np.ndarray,
    outline: Polygon,
    stock_thickness_mm: float,
    central_zone_mm: float,
    slope_extent_mm: float,
    min_edge_mm: float,
    res: float,
) -> np.ndarray:
    """Vectorised back-scallop: ramps from full thickness at centre to min at edge."""
    from scipy.ndimage import gaussian_filter

    cx = (outline.bounds[0] + outline.bounds[2]) / 2.0
    cy = (outline.bounds[1] + outline.bounds[3]) / 2.0

    # Distance from centrepoint, capped so only the horizontal band matters
    dx = np.maximum(np.abs(Xs - cx) - central_zone_mm, 0.0)

    z = np.where(
        dx <= 0,
        stock_thickness_mm,
        np.where(
            dx < slope_extent_mm,
            min_edge_mm + (1.0 - dx / slope_extent_mm) * (stock_thickness_mm - min_edge_mm),
            min_edge_mm,
        )
    )

    sigma = max(1.0, 2.0 / res)
    z = gaussian_filter(z, sigma=sigma)
    return z


# ------------------------------------------------------------------ mesh builder

def _masked_mesh(
    Xs: np.ndarray, Ys: np.ndarray,
    z_front: np.ndarray, z_back: np.ndarray,
    inside: np.ndarray,
    trimesh_mod,
) -> "trimesh.Trimesh":
    """Build a closed trimesh from two heightfields masked to *inside*."""

    rows, cols = Xs.shape

    # Vertex index map — -1 means outside mask
    vid = np.full((rows, cols), -1, dtype=np.int32)
    valid_rc = np.argwhere(inside)            # shape (n, 2)
    n_valid = len(valid_rc)
    if n_valid == 0:
        return trimesh_mod.Trimesh()

    vid[inside] = np.arange(n_valid, dtype=np.int32)

    r_idx = valid_rc[:, 0]
    c_idx = valid_rc[:, 1]
    x_v = Xs[r_idx, c_idx]
    y_v = Ys[r_idx, c_idx]
    zf_v = z_front[r_idx, c_idx]
    zb_v = z_back[r_idx, c_idx]

    # Top vertices (front surface) then bottom vertices (back surface)
    verts = np.vstack([
        np.column_stack([x_v, y_v, zf_v]),
        np.column_stack([x_v, y_v, zb_v]),
    ])                                        # shape (2*n_valid, 3)
    n = n_valid                               # offset to bottom layer

    # ---- Quad cells where all four corners are inside ----
    r0, c0 = np.mgrid[0:rows - 1, 0:cols - 1]
    r0, c0 = r0.ravel(), c0.ravel()
    r1, c1 = r0 + 1, c0 + 1

    i00 = vid[r0, c0];  i10 = vid[r1, c0]
    i01 = vid[r0, c1];  i11 = vid[r1, c1]
    quad_ok = (i00 >= 0) & (i10 >= 0) & (i01 >= 0) & (i11 >= 0)

    i00 = i00[quad_ok]; i10 = i10[quad_ok]
    i01 = i01[quad_ok]; i11 = i11[quad_ok]

    # Top faces (CCW from above)
    top_a = np.column_stack([i00, i01, i10])
    top_b = np.column_stack([i10, i01, i11])
    # Bottom faces (CW from above = CCW from below)
    bot_a = np.column_stack([i00 + n, i10 + n, i01 + n])
    bot_b = np.column_stack([i10 + n, i11 + n, i01 + n])

    faces = np.vstack([top_a, top_b, bot_a, bot_b])

    mesh = trimesh_mod.Trimesh(vertices=verts, faces=faces, process=True)
    return mesh
