"""Tool cross-section visualizer (BUILDPLAN M7.9).

A small QPainter widget that draws a 2D front section of a `ToolSpec` — the cutting
profile (flat / ball / toroid corner / V-bit cone) plus the shank — scaled to fit.
It redraws live as the Preferences ▸ Tools editor edits a tool, so the maker *sees*
the cutter they're describing. Pure presentation; the geometry mirrors the
`ToolProfile` drop profiles the sim uses.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from guildmodel.core.cam.tooling import ToolSpec
from guildmodel.gui.style import theme


def _half_cutting_profile(spec: ToolSpec, cut_h: float):
    """Right-half outline of the cutting region, tip→top, in tool mm
    (x = radius from the axis, y = height above the tip)."""
    R = max(spec.radius_mm, 0.01)
    pts = [(0.0, 0.0)]
    if spec.type == "ball":
        n = 20
        for i in range(1, n + 1):
            a = (math.pi / 2) * i / n
            pts.append((R * math.sin(a), R * (1.0 - math.cos(a))))
    elif spec.type == "toroid" and spec.corner_radius_mm > 0:
        rc = min(spec.corner_radius_mm, R)
        flat = R - rc
        pts.append((flat, 0.0))
        n = 12
        for i in range(1, n + 1):
            a = (math.pi / 2) * i / n
            pts.append((flat + rc * math.sin(a), rc * (1.0 - math.cos(a))))
    elif spec.type == "vbit" and spec.included_angle_deg > 0:
        t = math.tan(math.radians(spec.included_angle_deg / 2.0))
        cone_h = R / t if t > 1e-6 else cut_h
        if cone_h <= cut_h:
            pts.append((R, cone_h))                 # full cone, then the flute side
        else:
            pts.append((cut_h * t, cut_h))          # cone taller than the view
    elif spec.type == "groove" and spec.groove_width_mm > 0:
        # Side-cutting V-form (the lens-bevel drageoir): flat tip at the form
        # ROOT radius, the V apex at half the form width (R = the apex
        # radius), back to the root, then the relieved neck up to the shank —
        # the supplier's published silhouette (rc2).
        depth = min(max(spec.groove_depth_mm, 0.0), R)
        w = spec.groove_width_mm
        root = max(R - depth, 0.05)
        neck = max((spec.neck_diameter_mm / 2.0) if spec.neck_diameter_mm > 0
                   else root * 0.9, 0.05)
        pts.append((root, 0.0))
        pts.append((R, w / 2.0))                    # the V apex
        pts.append((root, w))
        pts.append((neck, w))                       # step onto the neck
    else:                                            # flat
        pts.append((R, 0.0))
    if pts[-1][1] < cut_h:                            # straight flute up to the top
        pts.append((pts[-1][0], cut_h))
    return pts


class ToolView(QWidget):
    """Live 2D cross-section of a tool (BUILDPLAN M7.9)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spec: ToolSpec | None = None
        self._dark = False
        self.setMinimumSize(150, 170)

    def set_spec(self, spec: ToolSpec | None) -> None:
        self._spec = spec
        self.update()

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = bool(dark)
        self.update()

    def paintEvent(self, _event) -> None:
        pal = theme.palette(self._dark)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, QColor(pal.canvas_bg))

        spec = self._spec
        if spec is None or spec.diameter_mm <= 0:
            p.setPen(QColor(pal.placeholder))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "no tool")
            return

        R = max(spec.radius_mm, 0.01)
        # view heights (mm): a flute region, then a short shank stub above it
        cut_h = spec.flute_length_mm if spec.flute_length_mm > 0 else max(2.5 * R, 6.0)
        if spec.type == "vbit" and spec.included_angle_deg > 0:        # show the full V
            t = math.tan(math.radians(spec.included_angle_deg / 2.0))
            if t > 1e-6:
                cut_h = max(cut_h, R / t)
        elif spec.type == "groove" and spec.groove_width_mm > 0:
            # head + relieved neck before the shank (the drageoir's neck runs
            # ~3× the form width — the supplier's proportions)
            cut_h = 4.0 * spec.groove_width_mm
        shank_r = max(spec.shank_diameter_mm / 2.0, R)
        shank_h = 0.45 * cut_h
        total_h = cut_h + shank_h
        half = _half_cutting_profile(spec, cut_h)

        # fit transform: tool mm → widget px (y up → screen y down)
        margin = 16
        avail_w = max(rect.width() - 2 * margin, 10)
        avail_h = max(rect.height() - 2 * margin, 10)
        span_x = 2.0 * max(shank_r, R)
        scale = min(avail_w / span_x, avail_h / total_h)
        cx = rect.width() / 2.0
        base_y = rect.height() - margin            # the tip sits near the bottom

        def pt(x_mm: float, y_mm: float) -> QPointF:
            return QPointF(cx + x_mm * scale, base_y - y_mm * scale)

        # build the closed silhouette: up the right cutting edge, up the right
        # shank, across the top, down the left shank, down the left cutting edge.
        path = QPainterPath()
        path.moveTo(pt(0.0, 0.0))
        for x, y in half[1:]:
            path.lineTo(pt(x, y))
        path.lineTo(pt(shank_r, cut_h))
        path.lineTo(pt(shank_r, total_h))
        path.lineTo(pt(-shank_r, total_h))
        path.lineTo(pt(-shank_r, cut_h))
        for x, y in reversed(half[1:]):
            path.lineTo(pt(-x, y))
        path.closeSubpath()

        p.setBrush(QBrush(QColor(pal.mesh_surface)))
        p.setPen(QPen(QColor(pal.annotation), 1.4))
        p.drawPath(path)

        # centreline (dashed)
        pen = QPen(QColor(pal.grid), 1.0, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(pt(0.0, 0.0), pt(0.0, total_h))

        # caption: Ø + type (+ angle for a V-bit)
        cap = f"Ø{spec.diameter_mm:.3g} mm · {spec.type}"
        if spec.type == "vbit" and spec.included_angle_deg:
            cap += f" {spec.included_angle_deg:.0f}°"
        elif spec.type == "groove" and spec.groove_width_mm:
            cap += f" {spec.groove_depth_mm:.3g}×{spec.groove_width_mm:.3g} mm"
        p.setPen(QColor(pal.annotation))
        p.drawText(rect.adjusted(4, 4, -4, -4),
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, cap)
