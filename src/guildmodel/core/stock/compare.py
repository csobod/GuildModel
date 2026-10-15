"""The cut report from two stocks (BUILDPLAN M21 §6.5): what the program
left standing that the model does not have, and what it took that the model
keeps.

The target is the model mesh cast through the same columns as the stock
(`DexelStock.from_mesh`), so each column holds the material the maker wants
as an interval list, and the stock the material the program leaves. Column by
column: the uncut volume is the stock less the target, the gouge volume the
target less the stock, each a set difference of intervals summed over cells
and multiplied by a cell's area — deterministic, and carrying the grid's
resolution rather than a tolerance of their own.

The report keeps `sim.report.CutReport`'s meaning for the GUI and the gates:
the cell counts and fractions, the worst excess and gouge, the masks, the
per-zone breakdown, the rim-band exclusion of the gouge check and the
ok / warn / fail thresholds, measured on the tops as `verify` measures them,
so the numbers reproduce today's within one cell on every fixture; and it
adds the volumes, which the heightfield could not give.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dexel import DexelStock

__all__ = ["StockReport", "compare", "interval_difference"]


def interval_difference(a: DexelStock, b: DexelStock) -> np.ndarray:
    """Per column, how much of `a`'s material lies outside `b`'s, mm: the
    length of ``A \\ B`` summed over each column's intervals. The intervals
    within one stock are disjoint, so the pairwise overlaps add up exactly."""
    if a.shape != b.shape:
        raise ValueError("the two stocks must share a grid")
    live_a = np.arange(a.k)[:, None, None] < a.count[None]
    live_b = np.arange(b.k)[:, None, None] < b.count[None]
    at = np.where(live_a, a.z_top, 0.0)
    ab = np.where(live_a, a.z_bot, 0.0)
    bt = np.where(live_b, b.z_top, 0.0)
    bb = np.where(live_b, b.z_bot, 0.0)
    total = (at - ab).sum(axis=0)
    overlap = np.zeros(a.shape)
    for i in range(a.k):
        for j in range(b.k):
            both = live_a[i] & live_b[j]
            o = np.minimum(at[i], bt[j]) - np.maximum(ab[i], bb[j])
            overlap += np.where(both, np.maximum(o, 0.0), 0.0)
    return total - overlap


@dataclass
class StockReport:
    """The verdict on a simulated stock against its target."""
    uncut_fraction: float
    uncut_cells: int
    body_cells: int
    max_excess_mm: float
    mean_excess_mm: float
    gouge_fraction: float
    gouge_cells: int
    max_gouge_mm: float
    uncut_volume_mm3: float
    gouge_volume_mm3: float
    uncut_mask: np.ndarray = field(repr=False)
    gouge_mask: np.ndarray = field(repr=False)
    excess: np.ndarray = field(repr=False)        # stock top less target top, per cell
    per_zone: dict = field(default_factory=dict)
    complete_tol_mm: float = 0.5
    origin: tuple[float, float] = (0.0, 0.0)
    resolution: float = 0.15

    def status(self) -> str:
        """`CutReport.status`'s thresholds, unchanged: they become project
        settings in a later task with these as the defaults."""
        if self.uncut_fraction > 0.10 or self.max_gouge_mm > 0.5:
            return "fail"
        if self.uncut_fraction > 0.04 or self.gouge_cells > 0:
            return "warn"
        return "ok"

    def summary_lines(self) -> list[str]:
        lines = [
            f"Cut completeness: {100 * (1 - self.uncut_fraction):.1f}% reached "
            f"({self.uncut_cells} of {self.body_cells} cells short, "
            f"worst {self.max_excess_mm:.2f} mm proud, "
            f"{self.uncut_volume_mm3:.1f} mm³ left standing)",
        ]
        if self.gouge_cells:
            lines.append(f"Gouge: {self.gouge_cells} cells below target "
                         f"(worst {self.max_gouge_mm:.2f} mm, {self.gouge_volume_mm3:.2f} mm³)")
        for kind, d in sorted(self.per_zone.items(), key=lambda kv: -kv[1]["cells"]):
            if d["cells"]:
                lines.append(f"  {kind}: {d['cells']} uncut, worst {d['max_excess_mm']:.2f} mm")
        return lines

    def to_cut_report(self, target_top: np.ndarray, stock_top: np.ndarray, faults=()):
        """The same verdict as a `sim.report.CutReport`, for the views and the
        gates that read one — the facade of task 7. Its lines are this
        report's, volumes included; `faults` are what the program would do
        beyond the cut (a rapid through stock, a shank in it), each of which
        fails it."""
        from ..sim.report import Completeness, CutReport, Gouge
        comp = Completeness(self.uncut_fraction, self.uncut_cells, self.body_cells,
                            self.max_excess_mm, self.mean_excess_mm, self.uncut_mask,
                            dict(self.per_zone))
        gouge = Gouge(self.gouge_fraction, self.gouge_cells, self.max_gouge_mm, self.gouge_mask)
        return CutReport(comp, gouge, stock_top, target_top, self.origin, self.resolution,
                         self.complete_tol_mm, lines=tuple(self.summary_lines()),
                         faults=tuple(faults))


def compare(stock: DexelStock, target: DexelStock, inside: np.ndarray, *,
            complete_tol_mm: float = 0.5, gouge_tol_mm: float = 0.2,
            gouge_rim_margin_mm: float = 1.7, partition=None) -> StockReport:
    """The report. `inside` marks the body's cells; the gouge check keeps off
    a tool-radius band around every step in the target and the body rim, as
    `sim.report.verify` does, for the same reason: a flat tool cannot finish
    a concave corner sharper than its radius, and the through-cut kerf at the
    rim is not a gouge."""
    from scipy.ndimage import binary_dilation, binary_erosion

    if stock.shape != target.shape:
        raise ValueError("the stock and the target must share a grid")
    inside = np.asarray(inside, dtype=bool)
    res = stock.resolution
    area = res * res

    stock_top = stock.top(empty=np.nan).z
    target_top = target.top(empty=np.nan).z
    valid = inside & np.isfinite(target_top)
    # a body column with no stock left is cut through: as deep as the target goes
    stock_z = np.where(np.isfinite(stock_top), stock_top, target.bottom(empty=np.nan).z)
    excess = np.where(valid, stock_z - target_top, 0.0)

    uncut_mask = valid & (excess > complete_tol_mm)
    body_cells = int(valid.sum())
    uncut_cells = int(uncut_mask.sum())
    ex = excess[uncut_mask]

    tfill = np.where(valid, target_top, 0.0)
    d0 = np.abs(np.diff(tfill, axis=0, prepend=tfill[:1, :]))
    d1 = np.abs(np.diff(tfill, axis=1, prepend=tfill[:, :1]))
    step = (d0 > 0.4) | (d1 > 0.4)
    step |= ~binary_erosion(inside, iterations=1)
    m_px = max(1, int(round(gouge_rim_margin_mm / res)))
    step_band = binary_dilation(step, iterations=m_px)
    gouge_depth = np.where(valid, target_top - stock_z, 0.0)
    gouge_mask = valid & ~step_band & (gouge_depth > gouge_tol_mm)
    gd = gouge_depth[gouge_mask]

    uncut_len = interval_difference(stock, target)
    gouge_len = interval_difference(target, stock)
    uncut_volume = float(uncut_len[inside].sum() * area)
    gouge_volume = float(gouge_len[inside & ~step_band].sum() * area)

    per_zone: dict = {}
    if partition is not None and uncut_cells:
        from ..sim.report import _per_zone
        ox, oy = stock.origin
        rr, cc = np.nonzero(uncut_mask)
        per_zone = _per_zone(partition, cc * res + ox, rr * res + oy, excess[uncut_mask])

    return StockReport(
        uncut_fraction=(uncut_cells / body_cells) if body_cells else 0.0,
        uncut_cells=uncut_cells, body_cells=body_cells,
        max_excess_mm=float(ex.max()) if ex.size else 0.0,
        mean_excess_mm=float(ex.mean()) if ex.size else 0.0,
        gouge_fraction=(int(gouge_mask.sum()) / body_cells) if body_cells else 0.0,
        gouge_cells=int(gouge_mask.sum()),
        max_gouge_mm=float(gd.max()) if gd.size else 0.0,
        uncut_volume_mm3=uncut_volume, gouge_volume_mm3=gouge_volume,
        uncut_mask=uncut_mask, gouge_mask=gouge_mask, excess=excess,
        per_zone=per_zone, complete_tol_mm=complete_tol_mm,
        origin=stock.origin, resolution=res,
    )
