"""Measure footing cross-sections from the STL at edge midpoints and compare
against candidate constructions:
  A) simultaneous: arcs meet at the cut line (current implementation)
  B) ext-first sequential: convex arc tangent-to-top through bottom corner,
     concave then tangent to it and the bottom plane
  C) int-first sequential: mirror-image construction (concave through top
     corner first)
"""
from pathlib import Path

import numpy as np
import trimesh

from guildcam.core.geometry.regions import partition_zones
from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.project.schema import CastleParams

HERE = Path(__file__).parent
raw = import_dxf(HERE / "GuildDraw DXF Export.dxf")
outline = points_to_polygon(raw["OUTLINE"][0])
lenses = [points_to_polygon(c) for c in raw["LENS"]]
part = partition_zones(outline, lenses, raw["SCULPT"])
castle = CastleParams()
heights = {z.name: castle.zones.for_kind(z.kind) for z in part.zones}

stl = trimesh.load(HERE / "Model.stl")
v = stl.vertices.copy()
b = part.body.bounds
sb = stl.bounds
v[:, 0] += (b[0] + b[2]) / 2 - (sb[0][0] + sb[1][0]) / 2
v[:, 1] += (b[1] + b[3]) / 2 - (sb[0][1] + sb[1][1]) / 2
stl.vertices = v


def stl_z(pxy):
    o = np.column_stack([pxy[:, 0], pxy[:, 1], np.full(len(pxy), 25.0)])
    d = np.tile([0.0, 0.0, -1.0], (len(pxy), 1))
    locs, ridx, _ = stl.ray.intersects_location(o, d, multiple_hits=True)
    out = np.full(len(pxy), np.nan)
    for (x, y, zz), ri in zip(locs, ridx):
        if np.isnan(out[ri]) or zz > out[ri]:
            out[ri] = zz
    return out


def candidates(s, ha, hb, re_, ri_):
    dh = ha - hb
    out = {}
    # A) simultaneous, arcs meet at s=0
    tot = re_ + ri_
    cos_t = max(-1.0, 1.0 - dh / tot)
    sin_t = np.sqrt(1 - cos_t**2)
    sh, sl = re_ * sin_t, ri_ * sin_t
    zA = np.where(s <= 0, ha, hb).astype(float)
    m = (s > -sh) & (s <= 0)
    zA[m] = ha - (re_ - np.sqrt(np.maximum(0, re_**2 - (s[m] + sh) ** 2)))
    m = (s > 0) & (s < sl)
    zA[m] = hb + (ri_ - np.sqrt(np.maximum(0, ri_**2 - (sl - s[m]) ** 2)))
    out["A_simul"] = zA

    # B) ext-first: C1 center (a, ha-re) tangent top, through (0, hb)
    if dh < 2 * re_:
        a = -np.sqrt(re_**2 - (dh - re_) ** 2)
        bx = a + np.sqrt((re_ + ri_) ** 2 - (re_ + ri_ - dh) ** 2)
        # tangency point between circles
        zB = np.where(s <= a, ha, hb).astype(float)
        cx1, cz1 = a, ha - re_
        cx2, cz2 = bx, hb + ri_
        tx = cx1 + (cx2 - cx1) * re_ / (re_ + ri_)
        m = (s > a) & (s <= tx)
        zB[m] = cz1 + np.sqrt(np.maximum(0, re_**2 - (s[m] - cx1) ** 2))
        m = (s > tx) & (s < cx2)
        zB[m] = cz2 - np.sqrt(np.maximum(0, ri_**2 - (s[m] - cx2) ** 2))
        out["B_ext1st"] = zB

    # C) int-first: C2 center (b2, hb+ri) tangent bottom, through (0, ha)
    if dh < 2 * ri_:
        b2 = np.sqrt(ri_**2 - (dh - ri_) ** 2)
        a2 = b2 - np.sqrt((re_ + ri_) ** 2 - (re_ + ri_ - dh) ** 2)
        zC = np.where(s <= a2, ha, hb).astype(float)
        cx1, cz1 = a2, ha - re_
        cx2, cz2 = b2, hb + ri_
        tx = cx1 + (cx2 - cx1) * re_ / (re_ + ri_)
        m = (s > a2) & (s <= tx)
        zC[m] = cz1 + np.sqrt(np.maximum(0, re_**2 - (s[m] - cx1) ** 2))
        m = (s > tx) & (s < cx2)
        zC[m] = cz2 - np.sqrt(np.maximum(0, ri_**2 - (s[m] - cx2) ** 2))
        out["C_int1st"] = zC
    return out


zone_h = dict(heights)
PROBES = [
    ("endpiece_superior_od", 0.15), ("endpiece_superior_od", 0.85),
    ("endpiece_inferior_od", 0.5),
    ("bridge_superior_od", 0.25), ("bridge_superior_od", 0.75),
    ("nosepad_superior_od", 0.3), ("nosepad_superior_od", 0.7),
    ("nosepad_inferior_od", 0.5),
]
for name, tpos in PROBES:
    e = next(e for e in part.edges if e.name == name)
    f = castle.footing.for_edge(e.canonical)
    za, zb = (zone_h[n] for n in e.zone_names)
    if za < zb:
        e_hi, e_lo = e.zone_names[1], e.zone_names[0]
        ha, hb = zb, za
    else:
        e_hi, e_lo = e.zone_names
        ha, hb = za, zb
    # probe station + normal pointing toward the low zone
    mid = e.cut.interpolate(tpos, normalized=True)
    p0 = np.array(e.cut.interpolate(max(0.0, tpos - 0.05), normalized=True).coords[0])
    p1 = np.array(e.cut.interpolate(min(1.0, tpos + 0.05), normalized=True).coords[0])
    t = (p1 - p0) / np.linalg.norm(p1 - p0)
    nvec = np.array([-t[1], t[0]])
    probe = np.array(mid.coords[0]) + nvec * 1.0
    lo_poly = part.zone(e_lo).polygon
    from shapely.geometry import Point
    if not lo_poly.contains(Point(probe)):
        nvec = -nvec

    s = np.arange(-14.0, 14.0, 0.5)
    pts = np.array(mid.coords[0])[None, :] + s[:, None] * nvec[None, :]
    z_meas = stl_z(pts)
    cands = candidates(s, ha, hb, f.exterior_mm, f.interior_mm)
    # mask out contamination: only trust samples where the STL is within the
    # step's height range (pockets and lens-hole drops fall outside it)
    ok = ~np.isnan(z_meas) & (z_meas > hb - 0.05) & (z_meas < ha + 0.05)
    print(f"\n== {name} @t={tpos}  ha={ha} hb={hb} re={f.exterior_mm} ri={f.interior_mm}  ({ok.sum()}/{len(s)} clean) ==")
    for k, zz in cands.items():
        print(f"  {k}: rms {np.sqrt(np.mean((zz[ok]-z_meas[ok])**2)):.4f}  max {np.max(np.abs(zz[ok]-z_meas[ok])):.4f}")
