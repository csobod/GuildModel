"""Feasibility spike: the aviator castle via Manifold mesh-CSG.

Same workload that leaks in OCCT: 8 terraces + 2 hinge pockets + the groove V
(the undercut that justified solids). Built from the same partition, flattened
at the same 0.01 mm chord tolerance. Watertightness is guaranteed by the
library; what we measure is time, volume agreement, and whether the undercut
survives.
"""
import time, zipfile, tempfile
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, Manifold, OpType

from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid.build import zone_heights
from guildmodel.core.solid.features import lip_partition, _ring_stations, _inward
from shapely.geometry import LineString

src = Path('tests/fixtures/aviator')
tmp = Path(tempfile.mkdtemp()) / "aviator.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)
front = build_workspaces_from_gdraw(tmp)[0][0]
part = front.partition
c = CastleParams(); c.lens_groove.enabled = True
g = c.lens_groove

t_all = time.perf_counter()

# --- terraces: extrude each zone of the LIP partition to its height
lip = lip_partition(part, g.depth_mm)
h = zone_heights(lip, c, None)

def poly_to_cs(poly):
    rings = [list(poly.exterior.coords)[:-1]] + \
            [list(r.coords)[:-1] for r in poly.interiors]
    return CrossSection([[(float(x), float(y)) for x, y in ring] for ring in rings],
                        fillrule=FillRule.EvenOdd)

from manifold3d import FillRule
t = time.perf_counter()
terraces = [Manifold.extrude(poly_to_cs(z.polygon), float(h[z.name]))
            for z in lip.zones]
solid = terraces[0]
for m in terraces[1:]:
    solid = solid + m
t_terr = time.perf_counter() - t

# --- hinge pockets
top = max(h.values()) + 1.0
floor = c.zones.endpiece_mm - c.hinge_pocket_depth_mm
t = time.perf_counter()
for hp in front.hinge_polys:
    tool = Manifold.extrude(poly_to_cs(hp), top - floor).translate([0, 0, floor])
    solid = solid - tool
t_hinge = time.perf_counter() - t

# --- the groove V: swept triangular tube around each lip ring (the undercut)
def v_tube(ring, depth, half_w, apex_z, lead=0.3):
    """Union of per-segment convex wedges — no self-intersection possible,
    however tight the corner. This is the construction a port would use."""
    pts, tans = _ring_stations(LineString(ring), 360)
    outward = _inward(lip.body, pts, tans)          # into the wall
    n = len(pts)
    lead_hw = half_w * (1.0 + lead / depth)

    def profile(i):
        p, o = pts[i % n], outward[i % n]
        return [(*(p - o * lead), apex_z + lead_hw),
                (*(p + o * depth), apex_z),
                (*(p - o * lead), apex_z - lead_hw)]

    wedges = [Manifold.hull_points(profile(i) + profile(i + 1)) for i in range(n)]
    return Manifold.batch_boolean(wedges, OpType.Add)

t = time.perf_counter()
for ring in lip.body.interiors:
    if lip.is_hole(ring):
        continue
    solid = solid - v_tube(ring, float(g.depth_mm), float(g.width_mm) / 2.0,
                           float(g.anterior_offset_mm))
t_groove = time.perf_counter() - t
t_total = time.perf_counter() - t_all

print(f"terraces union      {t_terr*1000:7.1f} ms")
print(f"hinge pockets       {t_hinge*1000:7.1f} ms")
print(f"groove V (undercut) {t_groove*1000:7.1f} ms")
print(f"TOTAL               {t_total*1000:7.1f} ms   (OCCT: 8,600 ms this build)")
print()
print(f"status={solid.status()}  genus={solid.genus()}  "
      f"volume={solid.volume():.3f}  (OCCT mesh_volume: 9152.358)")
mesh = solid.to_mesh()
print(f"verts={len(mesh.vert_properties)} tris={len(mesh.tri_verts)}")

# watertight by construction, but verify through the same trimesh oracle
import trimesh
tm = trimesh.Trimesh(vertices=np.array(mesh.vert_properties)[:, :3],
                     faces=np.array(mesh.tri_verts), process=True)
print(f"trimesh watertight={tm.is_watertight}  trimesh volume={tm.volume:.3f}")

# and the undercut is real: ray crossings through the wall must be 4
ring = next(r for r in lip.body.interiors if not lip.is_hole(r))
pts, tans = _ring_stations(LineString(ring), 40)
inward = _inward(lip.body, pts, tans)
deep = 0
for k in range(len(pts)):
    p = pts[k] + inward[k] * 0.35
    hits = tm.ray.intersects_location([[p[0], p[1], -100]], [[0, 0, 1]])[0]
    zs = sorted(set(np.round(h[2], 6) for h in hits))
    deep += len(zs) >= 4
print(f"undercut present at {deep}/40 stations")

# The MeshGL format splits vertices along property boundaries; merge by
# position and re-ask the same oracle.
tm2 = trimesh.Trimesh(vertices=np.array(mesh.vert_properties)[:, :3],
                      faces=np.array(mesh.tri_verts), process=False)
tm2.merge_vertices(merge_tex=True, merge_norm=True, digits_vertex=7)
print(f"after positional merge: watertight={tm2.is_watertight} "
      f"volume={tm2.volume:.3f} euler={tm2.euler_number} (genus 3 -> euler -4)")

# --- isolate: library-built primitives only (no hand-rolled tube)
base_only = terraces[0]
for m in terraces[1:]:
    base_only = base_only + m
for hp in front.hinge_polys:
    tool = Manifold.extrude(poly_to_cs(hp), top - floor).translate([0, 0, floor])
    base_only = base_only - tool
mm = base_only.to_mesh()
t3 = trimesh.Trimesh(vertices=np.array(mm.vert_properties)[:, :3],
                     faces=np.array(mm.tri_verts), process=True)
print(f"terraces+pockets only: manifold_status={base_only.status()} "
      f"trimesh_wt={t3.is_watertight} euler={t3.euler_number} vol={t3.volume:.3f}")

# and my tube alone — is IT the problem?
ring0 = next(r for r in lip.body.interiors if not lip.is_hole(r))
tube = v_tube(ring0, float(g.depth_mm), float(g.width_mm) / 2.0,
              float(g.anterior_offset_mm))
tmesh = tube.to_mesh()
t4 = trimesh.Trimesh(vertices=np.array(tmesh.vert_properties)[:, :3],
                     faces=np.array(tmesh.tri_verts), process=True)
print(f"hand-rolled V tube:    manifold_status={tube.status()} "
      f"trimesh_wt={t4.is_watertight} self_intersecting_bbox_vol={tube.volume():.1f}")

# --- the correct weld: MeshGL's own merge map, not positional matching
def welded(man):
    mm = man.to_mesh()
    verts = np.array(mm.vert_properties)[:, :3]
    faces = np.array(mm.tri_verts, dtype=np.int64)
    remap = np.arange(len(verts))
    mf = np.array(mm.merge_from_vert, dtype=np.int64)
    mt = np.array(mm.merge_to_vert, dtype=np.int64)
    if len(mf):
        remap[mf] = mt
    return trimesh.Trimesh(vertices=verts, faces=remap[faces], process=True)

w = welded(solid)
print(f"WELDED full build:  watertight={w.is_watertight} euler={w.euler_number} "
      f"volume={w.volume:.3f}  (Manifold's own: {solid.volume():.3f})")

# --- decisive: count boundary edges DIRECTLY on the welded index mesh,
# no trimesh cleanup involved (its process=True drops degenerate slivers,
# which can itself open a closed mesh).
mm = solid.to_mesh()
verts = np.array(mm.vert_properties)[:, :3]
faces = np.array(mm.tri_verts, dtype=np.int64)
remap = np.arange(len(verts))
mf = np.array(mm.merge_from_vert, dtype=np.int64)
mt = np.array(mm.merge_to_vert, dtype=np.int64)
print(f"merge map entries: {len(mf)}")
if len(mf):
    remap[mf] = mt
f = remap[faces]
edges = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
keys = edges[:, 0] * len(verts) + edges[:, 1]
rkeys = edges[:, 1] * len(verts) + edges[:, 0]
import collections
count = collections.Counter(keys.tolist())
open_edges = sum(1 for k, r in zip(keys.tolist(), rkeys.tolist())
                 if count.get(r, 0) == 0)
print(f"directed edges: {len(keys)}, unmatched (boundary) edges: {open_edges}")
degen = np.sum((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2]))
print(f"degenerate faces after weld: {degen} of {len(f)}")
