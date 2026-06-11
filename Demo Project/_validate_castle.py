"""M2 diagnostic: build the castle relief from the demo DXF and diff it
against Model.stl (the Fusion ground truth). Prints per-category stats."""
from pathlib import Path
import time

import numpy as np
import trimesh

from guildcam.core.geometry.regions import partition_zones
from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.project.schema import CastleParams
from guildcam.core.relief.castle import build_castle_relief, _footing_spans

HERE = Path(__file__).parent
RES = 0.2

t0 = time.perf_counter()
raw = import_dxf(HERE / "GuildDraw DXF Export.dxf")
outline = points_to_polygon(raw["OUTLINE"][0])
lenses = [points_to_polygon(c) for c in raw["LENS"]]
hinges = [points_to_polygon(c) for c in raw["HINGE"]]
part = partition_zones(outline, lenses, raw["SCULPT"])
castle = CastleParams()
relief = build_castle_relief(part, castle, hinges, resolution=RES)
print(f"build: {time.perf_counter() - t0:.2f}s  grid {relief.field.z.shape}")

stl = trimesh.load(HERE / "Model.stl")
b = stl.bounds
body = part.body
print(f"body bounds  X {body.bounds[0]:8.3f}..{body.bounds[2]:8.3f}  Y {body.bounds[1]:8.3f}..{body.bounds[3]:8.3f}")
print(f"stl  bounds  X {b[0][0]:8.3f}..{b[1][0]:8.3f}  Y {b[0][1]:8.3f}..{b[1][1]:8.3f}  Z {b[0][2]:.3f}..{b[1][2]:.3f}")

# Register the STL into our frame. Landmark probing (_probe_stl_frame.py)
# showed the Fusion model lives in the DXF's own frame, only translated
# (the user's Fusion y-mirror cancels GuildDraw's export y-negation); our
# import differs by the x-mirror. Robustly: try all four axis-sign
# combinations with bbox-center alignment and keep the best.
v = stl.vertices.copy()
bc = ((body.bounds[0] + body.bounds[2]) / 2.0, (body.bounds[1] + body.bounds[3]) / 2.0)


def registered(sx, sy):
    m = stl.copy()
    x, y = sx * v[:, 0], sy * v[:, 1]
    m.vertices = np.column_stack([
        x + (bc[0] - (x.min() + x.max()) / 2.0),
        y + (bc[1] - (y.min() + y.max()) / 2.0),
        v[:, 2],
    ])
    m.fix_normals()
    return m


candidates = {(sx, sy): registered(sx, sy) for sx in (1, -1) for sy in (1, -1)}

# ---- sample STL top surface by ray casting on a coarse grid ----
t0 = time.perf_counter()
step = 0.5
xs = np.arange(body.bounds[0] + 0.6, body.bounds[2] - 0.6, step)
ys = np.arange(body.bounds[1] + 0.6, body.bounds[3] - 0.6, step)
Xg, Yg = np.meshgrid(xs, ys)
from shapely import contains_xy, prepare
prepare(body)
inner = contains_xy(body.buffer(-0.5), Xg.ravel(), Yg.ravel())
px, py = Xg.ravel()[inner], Yg.ravel()[inner]
origins = np.column_stack([px, py, np.full(len(px), 20.0)])
dirs = np.tile([0.0, 0.0, -1.0], (len(px), 1))


def sample_top(mesh):
    locs, ray_idx, _ = mesh.ray.intersects_location(origins, dirs, multiple_hits=True)
    top = np.full(len(px), np.nan)
    for (x, y, zv), ri in zip(locs, ray_idx):
        if np.isnan(top[ri]) or zv > top[ri]:
            top[ri] = zv
    return top


ri_q = np.clip(((py - relief.field.origin[1]) / RES).round().astype(int), 0, relief.field.z.shape[0] - 1)
ci_q = np.clip(((px - relief.field.origin[0]) / RES).round().astype(int), 0, relief.field.z.shape[1] - 1)
ours_q = relief.field.z[ri_q, ci_q]

best_key, got, best_err = None, None, np.inf
for key, mesh in candidates.items():
    sampled = sample_top(mesh)
    err = np.nanmedian(np.abs(ours_q - sampled))
    miss = np.isnan(sampled).mean()
    print(f"  signs {key}: median |err| {err:.4f}  miss {miss:.1%}")
    if err < best_err:
        best_key, got, best_err = key, sampled, err
print(f"chosen registration: signs {best_key}")
print(f"stl sampling: {time.perf_counter() - t0:.2f}s  rays {len(px)}, hit {(~np.isnan(got)).sum()}")
field = relief.field
cols = field.z.shape[1]
ci = np.clip(((px - field.origin[0]) / field.resolution).round().astype(int), 0, cols - 1)
ri_ = np.clip(((py - field.origin[1]) / field.resolution).round().astype(int), 0, field.z.shape[0] - 1)
ours = field.z[ri_, ci]
valid = ~np.isnan(got)
diff = ours[valid] - got[valid]

# classify: band pixels = within any footing span of any edge; else plateau
heights = {z.name: castle.zones.for_kind(z.kind) for z in part.zones}
zone_pos = {z.name: i for i, z in enumerate(part.zones)}
from shapely import distance as sdist, points as spoints
band = np.zeros(valid.sum(), dtype=bool)
pv = spoints(px[valid], py[valid])
for e in part.edges:
    names = e.zone_names
    if len(names) != 2 or not e.canonical:
        continue
    ha, hb = heights[names[0]], heights[names[1]]
    f = castle.footing.for_edge(e.canonical)
    sh, sl = _footing_spans(abs(ha - hb), f.exterior_mm, f.interior_mm, f.first)
    d = sdist(pv, e.cut)
    band |= d < (max(sh, sl) + 0.6)
# hinge pocket neighborhoods are sharp-walled: exclude a thin rim from plateau stats
pocket_rim = np.zeros(valid.sum(), dtype=bool)
for h in hinges:
    d = sdist(pv, h.exterior)
    pocket_rim |= d < 0.6

plateau = ~band & ~pocket_rim
band_clean = band & ~pocket_rim   # pocket wall straddle reads as +-depth; not surface error
print(f"\nplateau pts {plateau.sum()}: |err| mean {np.abs(diff[plateau]).mean():.4f} "
      f"p95 {np.percentile(np.abs(diff[plateau]), 95):.4f} max {np.abs(diff[plateau]).max():.4f}")
print(f"band pts {band_clean.sum()}:  |err| mean {np.abs(diff[band_clean]).mean():.4f} "
      f"p95 {np.percentile(np.abs(diff[band_clean]), 95):.4f} max {np.abs(diff[band_clean]).max():.4f}")
print(f"signed band err: mean {diff[band_clean].mean():+.4f}  (ours - stl; + means we leave more material)")

# worst plateau offenders
worst = np.argsort(-np.abs(diff))[:10]
pxv, pyv = px[valid], py[valid]
print("\nworst 10 points:")
for w in worst:
    kind = "band" if band[w] else ("pocketrim" if pocket_rim[w] else "plateau")
    print(f"  ({pxv[w]:7.2f},{pyv[w]:7.2f}) ours {ours[valid][w]:6.3f} stl {got[valid][w]:6.3f} "
          f"err {diff[w]:+.3f} [{kind}]")
