"""Cut verification report (BUILDPLAN M5).

Compare the simulated achieved floor to the intended relief surface inside the
body: cells left well above target are **uncut**; cells taken below target are
**gouged**. The result is a pass/warn/fail report with per-zone breakdown that
the GUI badges and the completeness test gates on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Completeness:
    uncut_fraction: float
    uncut_cells: int
    body_cells: int
    max_excess_mm: float
    mean_excess_mm: float
    uncut_mask: np.ndarray = field(repr=False)
    per_zone: dict = field(default_factory=dict)


@dataclass
class Gouge:
    gouge_fraction: float
    gouge_cells: int
    max_depth_mm: float
    gouge_mask: np.ndarray = field(repr=False)


@dataclass
class CutReport:
    completeness: Completeness
    gouge: Gouge
    floor: np.ndarray = field(repr=False)
    target: np.ndarray = field(repr=False)
    origin: tuple[float, float] = (0.0, 0.0)
    resolution: float = 0.3
    complete_tol_mm: float = 0.5

    def status(self) -> str:
        c, g = self.completeness, self.gouge
        if c.uncut_fraction > 0.10 or g.max_depth_mm > 0.5:
            return "fail"
        if c.uncut_fraction > 0.04 or g.gouge_cells > 0:
            return "warn"
        return "ok"

    def summary_lines(self) -> list[str]:
        c, g = self.completeness, self.gouge
        lines = [
            f"Cut completeness: {100 * (1 - c.uncut_fraction):.1f}% reached "
            f"({c.uncut_cells} of {c.body_cells} cells short, "
            f"worst {c.max_excess_mm:.2f} mm proud)",
        ]
        if g.gouge_cells:
            lines.append(
                f"Gouge: {g.gouge_cells} cells below target "
                f"(worst {g.max_depth_mm:.2f} mm)")
        for kind, d in sorted(c.per_zone.items(), key=lambda kv: -kv[1]["cells"]):
            if d["cells"]:
                lines.append(f"  {kind}: {d['cells']} uncut, "
                             f"worst {d['max_excess_mm']:.2f} mm")
        return lines


def _per_zone(partition, xs, ys, excess) -> dict:
    """Group uncut cells by the zone polygon they fall in (best-effort)."""
    out: dict = {}
    try:
        import shapely
        contains_xy = shapely.contains_xy
    except Exception:
        return out
    for zone in getattr(partition, "zones", []):
        try:
            inside = contains_xy(zone.polygon, xs, ys)
        except Exception:
            continue
        n = int(inside.sum())
        if not n:
            continue
        agg = out.setdefault(zone.kind, {"cells": 0, "max_excess_mm": 0.0})
        agg["cells"] += n
        agg["max_excess_mm"] = max(agg["max_excess_mm"], float(excess[inside].max()))
    return out


def verify(
    floor: np.ndarray,
    target: np.ndarray,
    inside: np.ndarray,
    origin: tuple[float, float],
    resolution: float,
    partition=None,
    complete_tol_mm: float = 0.5,
    gouge_tol_mm: float = 0.2,
    gouge_rim_margin_mm: float = 1.7,
) -> CutReport:
    """Build a CutReport from a simulated floor vs the target relief surface.

    `target` is the intended posterior surface (NaN outside the body / openings);
    `inside` marks body cells. Uncut = inside & floor − target > complete_tol.
    Gouge = target − floor > gouge_tol, but only well inside the body
    (`gouge_rim_margin_mm` eroded from the boundary), so the legitimate through-
    cut kerf at the rim and half-cell raster fuzz at the edge don't count.
    """
    valid = inside & np.isfinite(target)
    excess = np.where(valid, floor - target, 0.0)

    uncut_mask = valid & (excess > complete_tol_mm)
    body_cells = int(valid.sum())
    uncut_cells = int(uncut_mask.sum())
    ex = excess[uncut_mask]
    comp = Completeness(
        uncut_fraction=(uncut_cells / body_cells) if body_cells else 0.0,
        uncut_cells=uncut_cells,
        body_cells=body_cells,
        max_excess_mm=float(ex.max()) if ex.size else 0.0,
        mean_excess_mm=float(ex.mean()) if ex.size else 0.0,
        uncut_mask=uncut_mask,
    )

    # A flat tool cannot machine a sharp concave step corner cleaner than its
    # radius, so the tool-radius band around any vertical step in the target
    # (terrace / pocket / hinge walls and the body rim) holds unavoidable
    # half-cell artifacts — exclude it from the gouge check. The uncut check
    # stays on the full body (the rim is exactly where real incompleteness hid).
    from scipy.ndimage import binary_dilation, binary_erosion
    m_px = max(1, int(round(gouge_rim_margin_mm / resolution)))
    tfill = np.where(valid, target, 0.0)
    d0 = np.abs(np.diff(tfill, axis=0, prepend=tfill[:1, :]))
    d1 = np.abs(np.diff(tfill, axis=1, prepend=tfill[:, :1]))
    step = (d0 > 0.4) | (d1 > 0.4)                       # terrace / pocket walls
    step |= ~binary_erosion(inside, iterations=1)        # the body rim is a step
    step_band = binary_dilation(step, iterations=m_px)
    gouge_mask = valid & ~step_band & ((target - floor) > gouge_tol_mm)
    gd = (target - floor)[gouge_mask]
    gouge = Gouge(
        gouge_fraction=(int(gouge_mask.sum()) / body_cells) if body_cells else 0.0,
        gouge_cells=int(gouge_mask.sum()),
        max_depth_mm=float(gd.max()) if gd.size else 0.0,
        gouge_mask=gouge_mask,
    )

    if partition is not None and uncut_cells:
        ox, oy = origin
        rr, cc = np.nonzero(uncut_mask)
        comp.per_zone = _per_zone(
            partition, cc * resolution + ox, rr * resolution + oy, excess[uncut_mask])

    return CutReport(comp, gouge, floor, target, origin, resolution, complete_tol_mm)
