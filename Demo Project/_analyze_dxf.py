"""Inspect the GuildDraw demo DXF: layers, entity types, extents."""
from collections import Counter
from pathlib import Path

import ezdxf
import numpy as np

DXF = Path(__file__).parent / "GuildDraw DXF Export.dxf"

doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

counts = Counter((e.dxf.layer, e.dxftype()) for e in msp)
for (layer, kind), n in sorted(counts.items()):
    print(f"{layer:12s} {kind:12s} x{n}")

xs, ys = [], []
for e in msp:
    if e.dxftype() == "SPLINE":
        pts = np.array(e.control_points)
        xs += list(pts[:, 0])
        ys += list(pts[:, 1])
    elif e.dxftype() == "CIRCLE":
        cx, cy, _ = e.dxf.center
        r = e.dxf.radius
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]
    elif e.dxftype() == "ARC":
        cx, cy, _ = e.dxf.center
        r = e.dxf.radius
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]

print(f"\nextents (ctrl pts): X {min(xs):.2f} .. {max(xs):.2f}  (w={max(xs)-min(xs):.2f})")
print(f"                    Y {min(ys):.2f} .. {max(ys):.2f}  (h={max(ys)-min(ys):.2f})")
print("INSUNITS:", doc.header.get("$INSUNITS", "unset"))
