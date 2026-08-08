"""Where does the pad splay cut the Gabriel frame in two?

The oracle says "2 separate pieces" with zero holes and zero non-manifold edges,
and `BRepCheck_Analyzer` calls it valid — so this is a clean cut in the wrong
place, not a corrupt boolean. Splits the mesh and reports what each piece is,
then checks the cutter against the material actually available beneath it.
"""
import tempfile
import zipfile
from pathlib import Path

import numpy as np

from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid import build_castle_solid, castle_base, clear_base_cache
from guildmodel.core.solid.features import splay_cutter
from guildmodel.core.solid.occ import surface_z_at
from guildmodel.core.solid.tessellate import tessellate
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

src = Path("tests/fixtures/gabriel")
tmp = Path(tempfile.mkdtemp()) / "gabriel.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)
front = build_workspaces_from_gdraw(tmp)[0][0]
part = front.partition

castle = CastleParams()
castle.pad_splay.enabled = True
clear_base_cache()
mesh = tessellate(build_castle_solid(part, castle, front.hinge_polys)).to_trimesh()

print(f"whole model: vol={mesh.volume:.3f}  bodies={mesh.body_count}")
for i, piece in enumerate(sorted(mesh.split(only_watertight=False),
                                 key=lambda m: -abs(m.volume))):
    lo, hi = piece.bounds
    print(f"  piece {i}: vol={piece.volume:10.3f}  tris={len(piece.faces):6d}  "
          f"x[{lo[0]:7.2f} {hi[0]:7.2f}] y[{lo[1]:7.2f} {hi[1]:7.2f}] "
          f"z[{lo[2]:6.2f} {hi[2]:6.2f}]")

# Is the cut deeper than the material under it? The splay drops from the crest
# toward the outline edge with no floor clamp, unlike the bridge scoop's
# `anterior_clamp_mm`.
print("\nhow much material sits under the splay run?")
clear_base_cache()
_p, _h, _top, base = castle_base(part, castle)
cutter = splay_cutter(base, part.body, castle.pad_splay)
cm = tessellate(cutter).to_trimesh()
lo, hi = cm.bounds
print(f"  cutter bbox z[{lo[2]:6.3f} {hi[2]:6.3f}]  vol={cm.volume:.3f}")
print(f"  cutter reaches BELOW the anterior face (z=0): {lo[2] < -1e-9}")

from shapely.geometry import LineString
from guildmodel.core.relief.features import _bottom_center_station

ring, L, s0 = _bottom_center_station(part.body)
run = min(float(castle.pad_splay.run_mm), 0.45 * L)
ss = np.mod(s0 + np.linspace(-run, run, 41), L)
pts = np.array([[ring.interpolate(float(s)).x, ring.interpolate(float(s)).y]
                for s in ss])
zs = surface_z_at(base, pts)
print(f"  surface height along the run: min={zs.min():.3f} max={zs.max():.3f}")
print(f"  stations where the surface is thinner than the deepest cut "
      f"({abs(lo[2]):.3f} mm): {(zs < abs(lo[2])).sum()} of {len(zs)}")
