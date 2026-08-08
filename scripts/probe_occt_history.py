"""Does the groove build depend on which builds ran BEFORE it in the process?"""
import zipfile, tempfile
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid import build_castle_solid, clear_base_cache
from guildmodel.core.solid.occ import is_valid, mesh_volume
from guildmodel.core.solid.tessellate import tessellate

src = Path('tests/fixtures/aviator')
tmp = Path(tempfile.mkdtemp()) / "aviator.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)
front = build_workspaces_from_gdraw(tmp)[0][0]
part = front.partition
lens_polys = [prep(Polygon(r).buffer(-0.9))
              for r in part.body.interiors if not part.is_hole(r)]


def build(mutate, label, clear=True):
    c = CastleParams()
    mutate(c)
    if clear:
        clear_base_cache()
    solid = build_castle_solid(part, c, front.hinge_polys)
    tm = tessellate(solid).to_trimesh()
    junk = sum(1 for p in tm.vertices
               if any(lp.contains(Point(p[0], p[1])) for lp in lens_polys))
    print(f"  {label:<28} wt={tm.is_watertight!s:<5} junk={junk:4d} "
          f"vol={mesh_volume(solid):9.3f}")


def splay(c): c.pad_splay.enabled = True
def bridge(c): c.bridge_relief.enabled = True
def groove(c): c.lens_groove.enabled = True
def bare(c): pass

print("groove alone, cache cleared each time:")
build(groove, "groove")

print("the GUI sequence (cache NOT cleared between, like a session):")
for mut, lbl in ((bare, "bare"), (splay, "splay"), (bridge, "bridge"),
                 (groove, "groove  <-- watch this"), (groove, "groove again")):
    build(mut, lbl, clear=False)
