"""Axis direction of each CYLINDRICAL_SURFACE in Model.step."""
import re
from collections import Counter
from pathlib import Path

text = (Path(__file__).parent / "Model.step").read_text(errors="replace")
ids = {m.group(1): m.group(2) for m in re.finditer(r"#(\d+)\s*=\s*(.+?);\s*$", text, re.M)}

axes = Counter()
for eid, body in ids.items():
    m = re.match(r"CYLINDRICAL_SURFACE\('[^']*',#(\d+),([\d.]+)\)", body)
    if not m:
        continue
    placement = ids.get(m.group(1), "")
    refs = re.findall(r"#(\d+)", placement)
    direction = "?"
    if len(refs) >= 2:
        ma = re.search(r"DIRECTION\('[^']*',\(([^)]+)\)\)", ids.get(refs[1], ""))
        if ma:
            d = [float(v) for v in ma.group(1).split(",")]
            if abs(abs(d[2]) - 1.0) < 1e-3:
                direction = "vertical(Z)"
            elif abs(d[2]) < 1e-3:
                direction = "horizontal"
            else:
                direction = f"tilted {d}"
    axes[(float(m.group(2)), direction)] += 1

for (r, d), n in sorted(axes.items()):
    print(f"r={r:6.2f}  {d:12s} x{n}")
