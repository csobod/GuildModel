from __future__ import annotations
from dataclasses import dataclass
from shapely.geometry import Polygon


@dataclass
class FrameRegions:
    """Named polygon regions extracted from the imported drawing.

    All polygons are in world coordinates (mm), normalized so that
    OD (right eye) is on viewer's right (positive X).
    """
    outline: Polygon             # outer profile of the frame front
    lens_od: Polygon             # right-eye (OD) lens opening
    lens_os: Polygon             # left-eye (OS) lens opening
    bridge: Polygon | None = None      # bridge reference region (optional)
    hinge_od: Polygon | None = None    # right hinge/shield pocket location
    hinge_os: Polygon | None = None    # left hinge/shield pocket location
