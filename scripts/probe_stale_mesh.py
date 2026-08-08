"""Is the in-session corruption stale TRIANGULATION rather than bad geometry?

`probe_occt_history.py` showed the groove build is watertight from a cold
process and leaking after a bare->splay->bridge sequence — at *identical*
mesh_volume (9152.358 both ways). Identical volume means the B-Rep is the same;
only the mesh differs. That points at `BRepMesh_IncrementalMesh`, which caches a
`Poly_Triangulation` on every face it meshes and *skips* any face already
carrying one at least as fine.

The cached base's faces are shared by TShape with the faces of every solid built
from it, so tessellating one build attaches triangulation to the cached base;
the next build's booleans hand those faces on to their result with the old
triangles still on them, and the mesher leaves them alone.

Measures the shared triangulation directly, then A/Bs `BRepTools.Clean_s`.
"""
import tempfile
import zipfile
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid import build_castle_solid, clear_base_cache
from guildmodel.core.solid.build import _BASE_CACHE
from guildmodel.core.solid.tessellate import tessellate
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

src = Path("tests/fixtures/aviator")
tmp = Path(tempfile.mkdtemp()) / "aviator.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)
front = build_workspaces_from_gdraw(tmp)[0][0]
part = front.partition


def meshed_faces(shape):
    """(faces, faces already carrying a triangulation)."""
    total = meshed = 0
    exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        exp.Next()
        total += 1
        if BRep_Tool.Triangulation_s(face, TopLoc_Location()) is not None:
            meshed += 1
    return total, meshed


def cached_base():
    return _BASE_CACHE[-1][2][3] if _BASE_CACHE else None


def build(mutate, label, clean):
    c = CastleParams()
    mutate(c)
    before = cached_base()
    stale = meshed_faces(before) if before is not None else (0, 0)
    solid = build_castle_solid(part, c, front.hinge_polys)
    if clean:
        # Drop every cached triangulation so the mesher starts from geometry.
        BRepTools.Clean_s(solid)
    tm = tessellate(solid).to_trimesh()
    print(f"  {label:<16} wt={tm.is_watertight!s:<5} "
          f"base carried {stale[1]:4d}/{stale[0]:4d} meshed faces  "
          f"open_edges={len(tm.facets_boundary) if not tm.is_watertight else 0}")


def splay(c): c.pad_splay.enabled = True
def bridge(c): c.bridge_relief.enabled = True
def groove(c): c.lens_groove.enabled = True
def bare(c): pass


SEQ = ((bare, "bare"), (splay, "splay"), (bridge, "bridge"),
       (groove, "groove"), (groove, "groove again"))

for clean in (False, True):
    print(f"\nGUI sequence, warm cache, Clean_s={clean}:")
    clear_base_cache()
    for mut, lbl in SEQ:
        build(mut, lbl, clean)
