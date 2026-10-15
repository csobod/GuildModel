"""Cutting a dexel stock (BUILDPLAN M21 §6.2 and §6.3; the plan's `cut.py`,
named `cutting` so the module and the function it exports do not collide
under `from guildmodel.core.stock import cut`).

`cut` subtracts a tool's occupancy interval from every column it covers, for
every pose. A pose is a tip position and a unit axis; in 1.9.0 every pose is
vertical and takes the footprint path, which is `sim.toolsim`'s stamp with the
interval arithmetic in place of a plain minimum. The general pose (§6.7) goes
through `ToolShape.column_intervals` and is otherwise unused until M26.

Two implementations, one answer:

* `cut_reference` — pure NumPy, one pose at a time. The oracle: the fewest
  moving parts, written to be read. For a top-down tool over a one-interval
  stock (every job today) it is one vectorized pass per pose; a finite
  interval or a column already split takes the per-column subtraction.
* `cut` — the production path: the `guildmodel_stock` C++ extension when it
  is installed (§6.3, band-parallel over rows), bit-identical to the
  reference at any thread count because each column's cuts happen in pose
  order within one thread, else the reference with one log line.

**Interval subtraction, per column.** A solid interval ``[t, b]`` (top above
bottom) less a cutter ``[lo, hi]`` is: itself when they do not meet; nothing
when the cutter covers it; ``[t, hi]`` when the cutter enters from below;
``[lo, b]`` when it enters from above; the pair ``[t, hi]`` and ``[lo, b]``
when it passes through the middle — the undercut, and the one case a
heightfield has no answer for. Columns keep their intervals topmost first;
when a split needs a slot the column does not have, the thinnest void is
filled (material kept, never lost) and `DexelStock.overflow_merges` counts it.
"""
from __future__ import annotations

import logging

import numpy as np

from .dexel import DexelStock
from .tools import Footprint, ToolShape

__all__ = ["collisions", "cut", "cut_reference", "extension_available", "poses_from_path",
           "shank_shape", "vertical_poses"]

_log = logging.getLogger(__name__)
_EXT_WARNED = False


def vertical_poses(points) -> np.ndarray:
    """``(N, 6)`` poses pointing straight up from ``(N, 3)`` tip positions."""
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    out = np.zeros((len(P), 6), dtype=np.float64)
    out[:, :3] = P
    out[:, 5] = 1.0
    return out


def poses_from_path(path, spacing: float) -> np.ndarray:
    """Vertical poses along a polyline at about `spacing` apart, by XY arc
    length — `sim.toolsim.densify`'s rule, so a stock cut from a path lands
    on the same positions the floor was stamped at."""
    pts = np.asarray(path, dtype=np.float64).reshape(-1, 3)
    if len(pts) < 2:
        return vertical_poses(pts)
    a, b = pts[:-1], pts[1:]
    d = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    n = np.maximum(1, (d / spacing).astype(np.int64))
    # every segment's k / n for k = 1..n, in one array: the same arithmetic
    # `densify` does one point at a time, so the positions are the same floats
    seg = np.repeat(np.arange(len(a)), n)
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 1
    frac = k / n[seg]
    out = np.vstack([pts[:1], a[seg] + (b[seg] - a[seg]) * frac[:, None]])
    return vertical_poses(out)


# ------------------------------------------------------------- one column

def subtract_interval(tops: list[float], bots: list[float], lo: float, hi: float,
                      k_max: int) -> tuple[list[float], list[float], int]:
    """One column less the cutter ``[lo, hi]``: the new ``(tops, bots)``,
    topmost first, and how many voids were filled for want of a slot."""
    new_t: list[float] = []
    new_b: list[float] = []
    for t, b in zip(tops, bots):
        if hi <= b or lo >= t:                 # no overlap
            new_t.append(t); new_b.append(b)
        elif lo <= b and hi >= t:              # covered
            continue
        elif lo <= b:                          # entered from below
            new_t.append(t); new_b.append(hi)
        elif hi >= t:                          # entered from above
            new_t.append(lo); new_b.append(b)
        else:                                  # through the middle: a split
            new_t.append(t); new_b.append(hi)
            new_t.append(lo); new_b.append(b)
    merges = 0
    while len(new_t) > k_max:
        # fill the thinnest void: the smallest gap between consecutive intervals
        gaps = [new_b[i] - new_t[i + 1] for i in range(len(new_t) - 1)]
        i = int(np.argmin(gaps))
        new_b[i] = new_b[i + 1]
        del new_t[i + 1], new_b[i + 1]
        merges += 1
    return new_t, new_b, merges


def _subtract_columns(stock: DexelStock, rr: np.ndarray, cc: np.ndarray,
                      lo: np.ndarray, hi: np.ndarray) -> None:
    """The cutter intervals ``[lo, hi]`` out of the columns ``(rr, cc)`` —
    distinct columns, one interval each, as one pose's footprint gives."""
    count = stock.count[rr, cc]
    simple = (count <= 1) & ~np.isfinite(hi)
    if simple.any():
        r, c = rr[simple], cc[simple]
        l = lo[simple]
        n = count[simple]
        t = stock.z_top[0, r, c]
        b = stock.z_bot[0, r, c]
        has = n == 1
        through = has & (l <= b)
        above = has & (l > b) & (l < t)
        # cut from above: the new top is the cutter's bottom — the same value
        # `np.minimum.at` lands on, so the heightfield case is bit-identical
        stock.z_top[0, r[above], c[above]] = l[above]
        stock.z_top[0, r[through], c[through]] = np.nan
        stock.z_bot[0, r[through], c[through]] = np.nan
        stock.count[r[through], c[through]] = 0
    rest = ~simple
    if rest.any():
        for r, c, l, h in zip(rr[rest], cc[rest], lo[rest], hi[rest]):
            n = int(stock.count[r, c])
            if n == 0:
                continue
            tops = stock.z_top[:n, r, c].tolist()
            bots = stock.z_bot[:n, r, c].tolist()
            nt, nb, merges = subtract_interval(tops, bots, float(l), float(h), stock.k)
            stock.overflow_merges += merges
            m = len(nt)
            stock.z_top[:, r, c] = np.nan
            stock.z_bot[:, r, c] = np.nan
            if m:
                stock.z_top[:m, r, c] = nt
                stock.z_bot[:m, r, c] = nb
            stock.count[r, c] = m


# ---------------------------------------------------------------- reference

def _is_vertical(axis: np.ndarray) -> bool:
    return abs(axis[0]) < 1e-12 and abs(axis[1]) < 1e-12 and abs(abs(axis[2]) - 1.0) < 1e-12


def cut_reference(stock: DexelStock, poses, shape: ToolShape,
                  footprint: Footprint | None = None) -> DexelStock:
    """Cut `stock` in place, one pose at a time, and return it.

    `poses` is ``(N, 6)``: tip x, y, z and the unit axis. A vertical pose uses
    `footprint` (the shape's, at the stock's grid, made here when not given);
    an inverted one (axis straight down) mirrors it, the cut from below; any
    other goes through the general column crossing.
    """
    P = np.asarray(poses, dtype=np.float64).reshape(-1, 6)
    if len(P) == 0:
        return stock
    fp = footprint if footprint is not None else shape.footprint(stock.resolution)
    rows, cols = stock.shape
    if len(fp) == 0:
        return stock
    for x, y, z, ax, ay, az in P:
        if _is_vertical((ax, ay, az)):
            r0, c0 = stock.cells_of(x, y)
            rr = r0 + fp.dj
            cc = c0 + fp.di
            if az > 0:
                lo = z + fp.z_lo
                hi = z + fp.z_hi
            else:
                lo = z - fp.z_hi
                hi = z - fp.z_lo
            ok = (cc >= 0) & (cc < cols) & (rr >= 0) & (rr < rows)
            if not ok.any():
                continue
            _subtract_columns(stock, rr[ok], cc[ok], lo[ok], hi[ok])
        else:
            # Every column the tilted tool could reach below the stock's top:
            # its radius, plus how far the axis leans over on the way up to
            # that height. Generous; the crossing test decides.
            live = stock.count > 0
            z_max = float(np.nanmax(stock.z_top[0][live])) if live.any() else z
            lean = max(0.0, z_max - z) / max(abs(az), 1e-9) * float(np.hypot(ax, ay))
            reach = shape.radius_mm + lean + stock.resolution
            r0, c0 = stock.cells_of(x, y)
            n_px = int(np.ceil(reach / stock.resolution))
            jj, ii = np.mgrid[-n_px:n_px + 1, -n_px:n_px + 1]
            rr = (r0 + jj).ravel()
            cc = (c0 + ii).ravel()
            ok = (cc >= 0) & (cc < cols) & (rr >= 0) & (rr < rows)
            rr, cc = rr[ok], cc[ok]
            xs = stock.origin[0] + cc * stock.resolution
            ys = stock.origin[1] + rr * stock.resolution
            lo, hi = shape.column_intervals((x, y, z), (ax, ay, az), xs, ys)
            hit = lo <= hi
            if hit.any():
                _subtract_columns(stock, rr[hit], cc[hit], lo[hit], hi[hit])
    return stock


# --------------------------------------------------------------- production

def extension_available() -> bool:
    """True when the C++ kernel is importable, without importing it."""
    import importlib.util
    try:
        return importlib.util.find_spec("guildmodel_stock") is not None
    except (ImportError, ValueError):
        return False


def cut(stock: DexelStock, poses, shape: ToolShape, *, threads: int | None = None,
        footprint: Footprint | None = None) -> DexelStock:
    """Cut `stock` in place with the fastest kernel this install has.

    The C++ extension takes the vertical poses band-parallel over rows; the
    tilted ones (none in 1.9.0) go through the reference. Without the
    extension everything does, and the log says so once.
    """
    global _EXT_WARNED
    P = np.asarray(poses, dtype=np.float64).reshape(-1, 6)
    if len(P) == 0:
        return stock
    fp = footprint if footprint is not None else shape.footprint(stock.resolution)
    vertical = (np.abs(P[:, 3]) < 1e-12) & (np.abs(P[:, 4]) < 1e-12) & (P[:, 5] > 0.5)
    if vertical.any() and len(fp):
        if extension_available():
            import guildmodel_stock
            n = threads if threads is not None else 0
            merges = guildmodel_stock.cut_vertical(
                stock.z_top, stock.z_bot, stock.count,
                float(stock.origin[0]), float(stock.origin[1]), float(stock.resolution),
                np.ascontiguousarray(P[vertical, :3]),
                np.ascontiguousarray(fp.di.astype(np.int64)),
                np.ascontiguousarray(fp.dj.astype(np.int64)),
                np.ascontiguousarray(fp.z_lo), np.ascontiguousarray(fp.z_hi), int(n))
            stock.overflow_merges += int(merges)
        else:
            if not _EXT_WARNED:
                _log.info("guildmodel_stock (the C++ stock kernel) is not installed; "
                          "simulating with the NumPy reference")
                _EXT_WARNED = True
            cut_reference(stock, P[vertical], shape, fp)
    if (~vertical).any():
        cut_reference(stock, P[~vertical], shape, fp)
    return stock


# ---------------------------------------------------------------- collisions

def shank_shape(tool: dict) -> ToolShape | None:
    """The part of the tool above its flutes, as a flat cylinder standing
    `flute_length_mm` up from the tip: what must never enter stock. None for
    a tool that declares no flute length or no shank."""
    flute = float(tool.get("flute_length_mm") or 0.0)
    dia = float(tool.get("shank_diameter_mm") or tool.get("diameter_mm") or 0.0)
    if flute <= 0.0 or dia <= 0.0:
        return None
    return ToolShape(kind="flat", radius_mm=dia / 2.0, flute_length_mm=flute)


def collisions(stock: DexelStock, poses, shape: ToolShape, *, lift: float = 0.0,
               footprint: Footprint | None = None) -> np.ndarray:
    """Which poses put the tool's occupancy into material — tested, never
    stamped (§6.5). For a rapid, `shape` is the cutting tool and a True is a
    rapid through stock; for the holder, `shape` is `shank_shape` and `lift`
    its flute length, so the shank's occupancy starts that far above the tip.
    Vertical poses only; returns a bool per pose."""
    P = np.asarray(poses, dtype=np.float64).reshape(-1, 6)
    hit = np.zeros(len(P), dtype=bool)
    if len(P) == 0:
        return hit
    fp = footprint if footprint is not None else shape.footprint(stock.resolution)
    if len(fp) == 0:
        return hit
    rows, cols = stock.shape
    live = np.arange(stock.k)[:, None, None] < stock.count[None]
    tops = np.where(live, stock.z_top, -np.inf)
    bots = np.where(live, stock.z_bot, np.inf)
    for n, (x, y, z, ax, ay, az) in enumerate(P):
        if not _is_vertical((ax, ay, az)):
            continue
        r0, c0 = stock.cells_of(x, y)
        rr, cc = r0 + fp.dj, c0 + fp.di
        ok = (cc >= 0) & (cc < cols) & (rr >= 0) & (rr < rows)
        if not ok.any():
            continue
        rr, cc = rr[ok], cc[ok]
        lo = z + lift + fp.z_lo[ok]
        hi = z + lift + fp.z_hi[ok]
        # an interval [t, b] meets the cutter [lo, hi] when lo < t and hi > b
        meets = (lo[None] < tops[:, rr, cc]) & (hi[None] > bots[:, rr, cc])
        hit[n] = bool(meets.any())
    return hit
