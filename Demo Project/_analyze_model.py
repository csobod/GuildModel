"""Inspect Model.stl (mesh stats) and Model.step (surface types, Z levels, radii)."""
import re
from collections import Counter
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).parent

# ---- STL ----
mesh = trimesh.load(HERE / "Model.stl")
print("== STL ==")
print("verts:", len(mesh.vertices), " faces:", len(mesh.faces), " watertight:", mesh.is_watertight)
b = mesh.bounds
print(f"bounds X {b[0][0]:.3f}..{b[1][0]:.3f} (w={b[1][0]-b[0][0]:.3f})")
print(f"       Y {b[0][1]:.3f}..{b[1][1]:.3f} (h={b[1][1]-b[0][1]:.3f})")
print(f"       Z {b[0][2]:.3f}..{b[1][2]:.3f} (t={b[1][2]-b[0][2]:.3f})")

# distribution of distinct Z values among vertices (flat levels show as spikes)
z = np.round(mesh.vertices[:, 2], 3)
zc = Counter(z)
print("top Z levels (value: vertex count):")
for val, n in sorted(zc.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {val:8.3f}: {n}")

# ---- STEP ----
print("\n== STEP ==")
text = (HERE / "Model.step").read_text(errors="replace")

surf_types = Counter(re.findall(r"=\s*(PLANE|CYLINDRICAL_SURFACE|TOROIDAL_SURFACE|CONICAL_SURFACE|SPHERICAL_SURFACE|B_SPLINE_SURFACE\w*|SURFACE_OF_LINEAR_EXTRUSION|SURFACE_OF_REVOLUTION)\b", text))
print("surface types:", dict(surf_types))

cyl_r = Counter(re.findall(r"CYLINDRICAL_SURFACE\('[^']*',#\d+,([\d.]+)\)", text))
print("cylinder radii:", sorted(((float(r), n) for r, n in cyl_r.items())))

tor = Counter(re.findall(r"TOROIDAL_SURFACE\('[^']*',#\d+,([\d.]+),([\d.]+)\)", text))
print("torus (major,minor) radii:", sorted(((float(a), float(b_), n) for (a, b_), n in tor.items())))

# Z levels of axis-aligned planes: find AXIS2_PLACEMENT_3D referenced by PLANE,
# then the CARTESIAN_POINT it references.
ids = {}
for m in re.finditer(r"#(\d+)\s*=\s*(.+?);\s*$", text, re.M):
    ids[m.group(1)] = m.group(2)

plane_z = Counter()
for eid, body in ids.items():
    if body.startswith("PLANE"):
        m = re.search(r"#(\d+)", body)
        if not m:
            continue
        placement = ids.get(m.group(1), "")
        refs = re.findall(r"#(\d+)", placement)
        if not refs:
            continue
        pt = ids.get(refs[0], "")
        mm = re.search(r"CARTESIAN_POINT\('[^']*',\(([^)]+)\)\)", pt)
        if not mm:
            continue
        coords = [float(v) for v in mm.group(1).split(",")]
        # check axis direction is Z-aligned
        if len(refs) >= 2:
            ax = ids.get(refs[1], "")
            ma = re.search(r"DIRECTION\('[^']*',\(([^)]+)\)\)", ax)
            if ma:
                d = [float(v) for v in ma.group(1).split(",")]
                if abs(abs(d[2]) - 1.0) < 1e-6:
                    plane_z[round(coords[2], 3)] += 1
print("Z-normal plane levels:", dict(sorted(plane_z.items())))
