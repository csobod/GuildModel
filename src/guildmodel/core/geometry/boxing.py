from __future__ import annotations
import math
from dataclasses import dataclass

from shapely.geometry import Polygon


@dataclass
class BoxingDimensions:
    """Parametric drivers in Guild Design Brief vocabulary.

    All measurements in millimeters. These are the only values the maker
    must consciously set; everything else is derived from the imported outline
    or defaulted.
    """
    # Standard boxing system (ISO 8624 / BS EN ISO 8624)
    a: float = 50.0          # lens width: horizontal box dimension, mm
    b: float = 38.0          # lens height: vertical box dimension, mm
    dbl: float = 18.0        # distance between lenses (bridge), mm
    ed: float = 54.0         # effective diameter (minimum blank size), mm

    # Frame front envelope
    frame_width: float = 0.0   # total front width; 0 = derive from a + dbl
    frame_height: float = 0.0  # total front height; 0 = derive from b

    # Bridge geometry (keel / saddle)
    bridge_depth: float = 4.0    # keel depth, mm
    bridge_width: float = 5.0    # bridge width at narrowest, mm

    # End-piece geometry
    endpiece_width: float = 8.0  # end-piece width, mm

    # Temple length (recorded; temples machined in v2)
    temple_length: float = 145.0  # mm

    # Symmetry
    symmetric: bool = True   # if False, OD/OS are edited independently

    def derived_frame_width(self) -> float:
        if self.frame_width > 0:
            return self.frame_width
        return self.a * 2 + self.dbl

    def derived_frame_height(self) -> float:
        if self.frame_height > 0:
            return self.frame_height
        return self.b


def measure_from_polygon(lens_od: Polygon, lens_os: Polygon) -> BoxingDimensions:
    """Derive standard boxing dimensions from the two imported lens polygons.

    Implements ISO 8624 boxing system:
      A   = lens width  (horizontal bounding-box extent of each lens)
      B   = lens height (vertical  bounding-box extent of each lens)
      DBL = distance between lenses: gap between the inner nasal edges of the
            two bounding boxes
      ED  = effective diameter: diameter of the smallest circle centerd at the
            MRP (bounding-box center) that fully circumscribes the lens outline

    The two polygons are sorted left→right by centroid X so OD (right in wearer
    terms, smaller display-X for standard left-to-right layouts) is handled
    consistently.  A, B, and ED are averaged across the two lenses; DBL is
    always the gap between the inner edges.
    """
    polys = sorted([lens_od, lens_os], key=lambda p: p.centroid.x)
    left, right = polys[0], polys[1]

    def _bounding(p: Polygon) -> tuple[float, float, float, float]:
        b = p.bounds  # (minx, miny, maxx, maxy)
        return b

    lb = _bounding(left)
    rb = _bounding(right)

    a_left  = lb[2] - lb[0]
    a_right = rb[2] - rb[0]
    b_left  = lb[3] - lb[1]
    b_right = rb[3] - rb[1]

    a = (a_left + a_right) / 2.0
    b = (b_left + b_right) / 2.0
    dbl = rb[0] - lb[2]   # inner nasal edge of right minus inner temporal edge of left

    def _ed(poly: Polygon, bounds: tuple[float, float, float, float]) -> float:
        mrp_x = (bounds[0] + bounds[2]) / 2.0
        mrp_y = (bounds[1] + bounds[3]) / 2.0
        coords = list(poly.exterior.coords)
        max_r = max(
            math.sqrt((x - mrp_x) ** 2 + (y - mrp_y) ** 2)
            for x, y in coords
        )
        return max_r * 2.0

    ed = (_ed(left, lb) + _ed(right, rb)) / 2.0

    return BoxingDimensions(a=round(a, 2), b=round(b, 2), dbl=round(dbl, 2), ed=round(ed, 2))
