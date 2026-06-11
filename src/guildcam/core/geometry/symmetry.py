from __future__ import annotations
from shapely.geometry import Polygon
from shapely.affinity import scale


def mirror_polygon(poly: Polygon, axis_x: float = 0.0) -> Polygon:
    """Reflect a polygon about a vertical axis at x = axis_x."""
    return scale(poly, xfact=-1, yfact=1, origin=(axis_x, 0))


def apply_symmetry(regions: "FrameRegions") -> "FrameRegions":  # noqa: F821
    """Mirror OD side onto OS side (or vice versa) when symmetric=True.

    Caller decides which side is the master before calling this.
    """
    from .regions import FrameRegions

    mid_x = regions.outline.centroid.x
    mirrored = mirror_polygon(regions.lens_od, axis_x=mid_x)

    return FrameRegions(
        outline=regions.outline,
        lens_od=regions.lens_od,
        lens_os=mirrored,
        bridge=regions.bridge,
        hinge_od=regions.hinge_od,
        hinge_os=mirror_polygon(regions.hinge_od, axis_x=mid_x)
        if regions.hinge_od is not None
        else None,
    )
