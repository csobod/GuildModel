"""Bounding boxes / closure of SCULPT, REF, HINGE entities in the demo DXF."""
from pathlib import Path

import ezdxf
import numpy as np

doc = ezdxf.readfile(Path(__file__).parent / "GuildDraw DXF Export.dxf")
msp = doc.modelspace()

for e in msp:
    layer = e.dxf.layer
    if layer not in ("SCULPT", "REF", "HINGE"):
        continue
    if e.dxftype() == "LWPOLYLINE":
        pts = np.array([(p[0], p[1]) for p in e.get_points()])
        closed = bool(e.closed)
    elif e.dxftype() == "SPLINE":
        pts = np.array([(p[0], p[1]) for p in e.control_points])
        closed = e.closed
    else:
        continue
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    print(f"{layer:7s} {e.dxftype():11s} n={len(pts):3d} closed={closed!s:5s} "
          f"X {x0:7.2f}..{x1:7.2f}  Y {y0:7.2f}..{y1:7.2f}")
