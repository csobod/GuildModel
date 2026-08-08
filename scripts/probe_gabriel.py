"""Does the maker's own drawing build, and does it break where the others don't?

BUILDPLAN-NEW M-N0's last open item. The demo frame is clean under every probe
and the aviator only failed on one feature, so a third real drawing is the
cheapest protection available — M-N0's bug existed on exactly one of the two
fixtures we had, and the clean one proved nothing.

Sweeps each feature on alone, then all together, reporting what the app's own
oracle would say. Also runs the mesh kernel where it has parity, so M-N1 gets
its third fixture at the same time.
"""
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

from guildmodel.core.mesh_check import verify_mesh
from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid import build_castle_solid, clear_base_cache
from guildmodel.core.solid.occ import is_valid
from guildmodel.core.solid.tessellate import tessellate
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

src = Path("tests/fixtures/gabriel")
tmp = Path(tempfile.mkdtemp()) / "gabriel.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)

workspaces, _ = build_workspaces_from_gdraw(tmp)
print(f"components: {[w.label or w.kind.name for w in workspaces]}")
front = workspaces[0]
part = front.partition
print(f"zones      : {len(part.zones)}  classified={part.classified}")
print(f"apertures  : {sum(1 for r in part.body.interiors if not part.is_hole(r))}"
      f"  outline holes={sum(1 for r in part.body.interiors if part.is_hole(r))}")
print(f"hinges     : {len(front.hinge_polys)}")


def edge_use(mesh):
    return np.unique(mesh.edges_sorted, axis=0, return_counts=True)[1]


def build(label, mutate):
    castle = CastleParams()
    mutate(castle)
    clear_base_cache()
    t = time.perf_counter()
    try:
        solid = build_castle_solid(part, castle, front.hinge_polys)
    except Exception as exc:                                 # noqa: BLE001
        print(f"  {label:<16} RAISED {type(exc).__name__}: {exc}")
        return
    dt = time.perf_counter() - t
    mesh = tessellate(solid).to_trimesh()
    counts = edge_use(mesh)
    verdict = verify_mesh(mesh)
    flag = "ok " if verdict.ok else "BAD"
    print(f"  {flag} {label:<16} vol={mesh.volume:9.3f} "
          f"holes={int((counts == 1).sum()):<4} "
          f"nonmanifold={int((counts > 2).sum()):<4} "
          f"valid={is_valid(solid)!s:<5} {dt:6.2f}s")
    if not verdict.ok:
        for problem in verdict.problems:
            print(f"      - {problem}")


def everything(c):
    c.pad_splay.enabled = True
    c.bridge_relief.enabled = True
    c.lens_groove.enabled = True
    c.eyewire_bezel.enabled = True


print("\nB-Rep path, each feature alone then all together:")
build("bare", lambda c: None)
build("pad splay", lambda c: setattr(c.pad_splay, "enabled", True))
build("bridge relief", lambda c: setattr(c.bridge_relief, "enabled", True))
build("lens groove", lambda c: setattr(c.lens_groove, "enabled", True))
build("eyewire bezel", lambda c: setattr(c.eyewire_bezel, "enabled", True))
build("all features", everything)

print("\nmesh kernel (terraces + pockets, the ported stage):")
from guildmodel.core.model import build_castle_model, to_trimesh
from guildmodel.core.solid.build import build_terraces as occ_terraces
from guildmodel.core.solid.build import zone_heights
from guildmodel.core.solid.occ import mesh_volume

castle = CastleParams()
heights = zone_heights(part, castle, None)
t = time.perf_counter()
model = build_castle_model(part, castle, front.hinge_polys)
t_mesh = time.perf_counter() - t
mm = to_trimesh(model)
print(f"  built in {t_mesh*1000:.1f} ms  vol={mm.volume:.3f}  "
      f"watertight={mm.is_watertight}  tris={len(mm.faces)}")

occ_vol = mesh_volume(occ_terraces(part, heights, curved=False))
mesh_terr = to_trimesh(
    __import__("guildmodel.core.model", fromlist=["build_terraces"])
    .build_terraces(part, heights)).volume
print(f"  terrace parity: OCCT {occ_vol:.3f} vs mesh {mesh_terr:.3f} "
      f"({100*(mesh_terr-occ_vol)/occ_vol:+.4f}%)")
