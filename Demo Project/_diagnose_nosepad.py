"""Diagnose contour/relief incompleteness across the nosepad (BUILDPLAN M4.x).

Miniature cut simulation: sweep the flat tool along every *cutting* move and
record the lowest Z it reaches at each XY cell ("achieved floor"). Compare to the
target posterior relief surface inside the body — cells where the floor stays
well above the target are uncut. Run on our generated program and on the Fusion
control (Demo Program.nc) and diff the uncut maps.
"""
import re
from pathlib import Path

import numpy as np
import yaml

from guildcam.core.geometry.regions import partition_zones
from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.project.schema import CastleParams
from guildcam.core.relief.castle import build_castle_relief
from guildcam.core.cam.castle_ops import generate_castle_program, write_castle_program
from guildcam.core.post.grbl import GRBLPost

DEMO = Path(__file__).parent
CONFIG = DEMO.parent / "src" / "guildcam" / "config"
RES = 0.4
TOOL_R = 1.5875


def _densify(pts, spacing=0.3):
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        a = np.asarray(a, float); b = np.asarray(b, float)
        d = np.linalg.norm(b[:2] - a[:2])
        n = max(1, int(d / spacing))
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(a + (b - a) * t)
    out.append(np.asarray(pts[-1], float))
    return out


def achieved_floor(cut_points, origin, shape, init):
    """Min Z reached at each cell by a flat tool of radius TOOL_R swept through
    cut_points (list of (x,y,z))."""
    floor = np.full(shape, init, float)
    r_px = int(round(TOOL_R / RES))
    dj, di = np.mgrid[-r_px:r_px + 1, -r_px:r_px + 1]
    disc = (di**2 + dj**2) <= r_px**2
    odi, odj = di[disc], dj[disc]
    ox, oy = origin
    rows, cols = shape
    P = np.asarray(cut_points, float)
    ci = ((P[:, 0] - ox) / RES).round().astype(int)
    ri = ((P[:, 1] - oy) / RES).round().astype(int)
    z = P[:, 2]
    allc = (ci[:, None] + odi[None, :]).ravel()
    allr = (ri[:, None] + odj[None, :]).ravel()
    allz = np.repeat(z, odi.size)
    ok = (allc >= 0) & (allc < cols) & (allr >= 0) & (allr < rows)
    np.minimum.at(floor, (allr[ok], allc[ok]), allz[ok])
    return floor


def our_cut_points(ops):
    pts = []
    for op in ops:
        for path in op.paths:
            pts += _densify(path)
    return pts


def fusion_cut_points(nc_path, origin_shift):
    """Parse Demo Program.nc -> cutting-move points, shifted into frame coords.
    The Fusion program is in its own frame (matches our outline after the M2
    translation registration); we align by centering both on the body centroid."""
    x = y = z = 0.0
    motion = 0
    raw_pts = []
    for line in Path(nc_path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("("):
            continue
        if any(t in s for t in ("G28", "G30")):
            continue
        for g in re.findall(r"G(\d+)", s):
            gi = int(g)
            if gi in (0, 1, 2, 3):
                motion = gi
        d = dict((m[0], float(m[1])) for m in re.findall(r"([XYZ])(-?\d*\.?\d+)", s))
        nx = d.get("X", x); ny = d.get("Y", y); nz = d.get("Z", z)
        if motion in (1, 2, 3) and (("X" in d) or ("Y" in d) or ("Z" in d)):
            raw_pts.append((nx, ny, nz))
        x, y, z = nx, ny, nz
    P = np.asarray(raw_pts, float)
    P[:, 0] += origin_shift[0]
    P[:, 1] += origin_shift[1]
    return [tuple(p) for p in _densify(P.tolist())]


def main():
    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    tool = yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"]
    relief = build_castle_relief(part, castle, hinges, resolution=RES)

    f = relief.field
    shape = f.z.shape
    origin = f.origin
    inside = relief.inside
    target = np.where(inside, f.z, np.nan)
    init = castle.stock.total_pad_height_mm + 1.0

    ops = generate_castle_program(relief, castle, hinges, tool)
    ours = achieved_floor(our_cut_points(ops), origin, shape, init)

    # uncut = inside the body, floor still well above the target surface
    tol = 0.5
    uncut = inside & (ours - target > tol) & np.isfinite(target)
    print(f"grid {shape} res {RES} | body cells {inside.sum()}")
    print(f"OURS  uncut cells (floor>target+{tol}): {uncut.sum()} "
          f"({100*uncut.sum()/inside.sum():.1f}% of body)")
    _report_regions(uncut, ours, target, origin, part)

    # Fusion comparison — center both on body centroid for rough alignment
    cen = part.body.centroid
    fus_pts = fusion_cut_points(DEMO / "Demo Program.nc", (0.0, 0.0))
    fa = np.asarray(fus_pts); fcx, fcy = fa[:, 0].mean(), fa[:, 1].mean()
    shift = (cen.x - fcx, cen.y - fcy)
    fus = achieved_floor(fusion_cut_points(DEMO / "Demo Program.nc", shift),
                         origin, shape, init)
    fus_uncut = inside & (fus - target > tol) & np.isfinite(target)
    print(f"\nFUSION uncut cells: {fus_uncut.sum()} "
          f"({100*fus_uncut.sum()/inside.sum():.1f}% of body)  "
          f"[rough centroid alignment, shift {shift[0]:.1f},{shift[1]:.1f}]")
    _report_regions(fus_uncut, fus, target, origin, part)


def _report_regions(mask, floor, target, origin, part):
    if not mask.any():
        print("   (none)")
        return
    rr, cc = np.nonzero(mask)
    ox, oy = origin
    xs = cc * RES + ox; ys = rr * RES + oy
    excess = (floor - target)[mask]
    print(f"   bbox x[{xs.min():.1f},{xs.max():.1f}] y[{ys.min():.1f},{ys.max():.1f}]  "
          f"max excess {excess.max():.2f} mm  mean {excess.mean():.2f} mm")
    for z in part.zones:
        b = z.polygon.bounds
        inzone = (xs >= b[0]) & (xs <= b[2]) & (ys >= b[1]) & (ys <= b[3])
        if inzone.sum() > 3:
            print(f"     in {z.kind:18s} bbox: {inzone.sum():4d} cells, "
                  f"max excess {excess[inzone].max():.2f} mm")


if __name__ == "__main__":
    main()
