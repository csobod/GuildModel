"""Locate landmark features in the raw STL to pin down its coordinate frame
relative to the DXF (no transform applied to either)."""
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).parent
stl = trimesh.load(HERE / "Model.stl")
v = stl.vertices

def report(label, mask):
    if not mask.any():
        print(f"{label}: none")
        return
    sel = v[mask]
    print(f"{label}: n={len(sel)}  X {sel[:,0].min():7.2f}..{sel[:,0].max():7.2f}  "
          f"Y {sel[:,1].min():7.2f}..{sel[:,1].max():7.2f}")

report("nosepad tops   (z>9.5)         ", v[:, 2] > 9.5)
report("pocket floors  (4.45<z<4.55)   ", (v[:, 2] > 4.45) & (v[:, 2] < 4.55))
report("endpiece tops  (5.45<z<5.55)   ", (v[:, 2] > 5.45) & (v[:, 2] < 5.55))
report("bridge top     (5.25<z<5.35)   ", (v[:, 2] > 5.25) & (v[:, 2] < 5.35))
report("inferior wires (4.15<z<4.25)   ", (v[:, 2] > 4.15) & (v[:, 2] < 4.25))

print("\nDXF (as read, no flip) for comparison:")
print("  nosepad superior cuts: X +-(2.25..12.21)   Y   1.40..  3.93")
print("  hinge pockets:         X +-(53.70..57.78)  Y   3.45.. 17.00")
print("  endpiece sup cuts:     X +-(46.60..53.33)  Y  15.44.. 22.88")
print("  inferior eyewire cuts: X +-(9.96..15.72)   Y -16.14..-10.39")
