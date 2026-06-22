"""Worktable bed canvas (BUILDPLAN M7.4).

A machine-coordinate sibling of :class:`DxfCanvas`: renders a :class:`Worktable`'s
tagged regions on the bed (origin lower-left, Y up), colours each by its role, and
emits :sig:`region_clicked` when the maker clicks a region so the Worktable tab can
tag it. Zoom/pan mirror the DXF canvas (wheel zoom, middle/right-drag pan).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QWheelEvent, QMouseEvent, QPaintEvent,
    QResizeEvent, QFont, QPainterPath,
)

from guildcam.core.project.schema import BedRole
from guildcam.gui.style import theme

_PLACEHOLDER = "Import a bed DXF, or load the Guild fixture, to set up the worktable"

# Role → (fill RGBA, outline hex). Keep-out is a red hatch; untagged a neutral grey.
_ROLE_COLORS: dict[BedRole, tuple[tuple[int, int, int, int], str]] = {
    BedRole.UNASSIGNED:       ((150, 150, 150, 50),  "#8a8a8a"),
    BedRole.FRAME_FRONT:      ((40, 110, 200, 70),   "#2e6ec8"),
    BedRole.TEMPLE_RIGHT:     ((40, 160, 90, 70),    "#28a05a"),
    BedRole.TEMPLE_LEFT:      ((40, 175, 160, 70),   "#28afa0"),
    BedRole.BASE_CURVE_RIGHT: ((220, 130, 40, 70),   "#dc8228"),
    BedRole.BASE_CURVE_LEFT:  ((215, 175, 50, 70),   "#d7af32"),
    BedRole.KEEP_OUT:         ((200, 60, 50, 90),    "#c83c32"),
}


class BedCanvas(QWidget):
    """Render a worktable's zones with click-to-select tagging, plus the nested
    component footprints (BUILDPLAN M7.6) — drag a footprint to nudge it."""

    region_clicked = Signal(str)    # zone id (left-click hit), or "" on empty space
    component_nudged = Signal(str, float, float)   # zone id, total (dx, dy) mm on release

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self._dark = False
        self._palette = theme.palette(False)

        self._zones: list = []                       # list[WorktableZone] (duck-typed)
        self._work_area: tuple[float, float] = (300.0, 200.0)
        self._selected_id: Optional[str] = None

        # M7.6 nested footprints: each = dict(zone_id, role, label, paths, violated, bbox)
        self._placements: list[dict] = []
        self._nest_drag: Optional[int] = None        # index of the placement being dragged
        self._nest_last: Optional[tuple[float, float]] = None
        self._nest_total: tuple[float, float] = (0.0, 0.0)

        self._scale: float = 3.0
        self._offset: QPointF = QPointF(0.0, 0.0)
        self._pan_active = False
        self._pan_last = QPointF()

        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

    # ------------------------------------------------------------------ public API

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = dark
        self._palette = theme.palette(dark)
        self.update()

    def set_worktable(self, worktable) -> None:
        """Show `worktable` (a core Worktable); refits the view."""
        self._zones = list(worktable.zones) if worktable else []
        self._work_area = (
            worktable.work_area_width_mm if worktable else 300.0,
            worktable.work_area_height_mm if worktable else 200.0,
        )
        if self._selected_id not in {z.id for z in self._zones}:
            self._selected_id = None
        self._placements = []                # a new bed invalidates any prior nest
        self._nest_drag = None
        self.fit_to_view()

    def refresh(self, worktable) -> None:
        """Re-read zones (e.g. after a re-tag) without refitting the view."""
        self._zones = list(worktable.zones) if worktable else []
        self.update()

    def set_selected(self, zone_id: Optional[str]) -> None:
        self._selected_id = zone_id
        self.update()

    def selected_id(self) -> Optional[str]:
        return self._selected_id

    # ---- M7.6 nested footprints ----------------------------------------------

    def set_nest(self, placements: list) -> None:
        """Show the nested component footprints (BUILDPLAN M7.6). `placements` is a
        list of dicts: `zone_id`, `role`, `label`, `paths` (machine-coord polylines),
        `violated` (bool). The footprints draw over the bed; drag one to nudge it."""
        self._placements = []
        for pl in placements:
            paths = [list(p) for p in pl.get("paths", [])]
            self._placements.append({
                "zone_id": pl["zone_id"], "role": pl.get("role"),
                "label": pl.get("label", ""), "paths": paths,
                "violated": bool(pl.get("violated", False)),
                "bbox": self._paths_bbox(paths),
            })
        self._nest_drag = None
        self.update()

    def clear_nest(self) -> None:
        self._placements = []
        self._nest_drag = None
        self.update()

    @staticmethod
    def _paths_bbox(paths: list) -> tuple[float, float, float, float]:
        xs = [pt[0] for p in paths for pt in p]
        ys = [pt[1] for p in paths for pt in p]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def fit_to_view(self) -> None:
        w_mm, h_mm = self._work_area
        xs = [0.0, w_mm]
        ys = [0.0, h_mm]
        for z in self._zones:
            for x, y in z.polygon:
                xs.append(x)
                ys.append(y)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = (max_x - min_x) or 1.0
        span_y = (max_y - min_y) or 1.0

        w, h = self.width(), self.height()
        self._scale = min(w * 0.9 / span_x, h * 0.9 / span_y)
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
        self._offset = QPointF(w / 2.0 - cx * self._scale, h / 2.0 + cy * self._scale)
        self.update()

    # ------------------------------------------------------------------ coords

    def _world_to_screen(self, x: float, y: float) -> QPointF:
        return QPointF(x * self._scale + self._offset.x(),
                       -y * self._scale + self._offset.y())

    def _screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return ((sx - self._offset.x()) / self._scale,
                -(sy - self._offset.y()) / self._scale)

    @staticmethod
    def _point_in_ring(px: float, py: float, ring: list) -> bool:
        """Ray-cast point-in-polygon test."""
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > py) != (yj > py)) and (
                    px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def _hit_test(self, wx: float, wy: float) -> Optional[str]:
        """The smallest-area zone containing (wx, wy) — so a screw inside a big
        zone is still selectable."""
        hits = [z for z in self._zones
                if len(z.polygon) >= 3 and self._point_in_ring(wx, wy, z.polygon)]
        if not hits:
            return None
        return min(hits, key=lambda z: z.area()).id

    def _nest_hit_test(self, wx: float, wy: float) -> Optional[int]:
        """Index of the smallest-bbox nested footprint under (wx, wy) — so dragging a
        footprint nudges it (takes priority over zone tagging while a nest is shown)."""
        hits = []
        for i, pl in enumerate(self._placements):
            x0, y0, x1, y1 = pl["bbox"]
            if x0 <= wx <= x1 and y0 <= wy <= y1:
                hits.append((i, (x1 - x0) * (y1 - y0)))
        if not hits:
            return None
        return min(hits, key=lambda t: t[1])[0]

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._palette.canvas_bg))

        if not self._zones:
            self._draw_placeholder(painter)
            return

        self._draw_work_area(painter)
        self._draw_zones(painter)
        self._draw_nest(painter)
        self._draw_scale_bar(painter)

    def _draw_placeholder(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSize(12)
        painter.setFont(font)
        painter.setPen(QColor(self._palette.placeholder))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _PLACEHOLDER)

    def _draw_work_area(self, painter: QPainter) -> None:
        w_mm, h_mm = self._work_area
        pen = QPen(QColor(self._palette.stock_dash), 1.4, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        tl = self._world_to_screen(0.0, h_mm)
        br = self._world_to_screen(w_mm, 0.0)
        painter.drawRect(QRectF(tl, br))
        # machine origin marker (lower-left)
        o = self._world_to_screen(0.0, 0.0)
        painter.drawLine(QPointF(o.x() - 6, o.y()), QPointF(o.x() + 6, o.y()))
        painter.drawLine(QPointF(o.x(), o.y() - 6), QPointF(o.x(), o.y() + 6))

    def _draw_zones(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSize(9)
        for z in self._zones:
            if len(z.polygon) < 3:
                continue
            rgba, outline = _ROLE_COLORS.get(
                BedRole(z.role), _ROLE_COLORS[BedRole.UNASSIGNED])
            path = QPainterPath()
            pts = [self._world_to_screen(x, y) for x, y in z.polygon]
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            path.closeSubpath()

            selected = z.id == self._selected_id
            if BedRole(z.role) == BedRole.KEEP_OUT:
                painter.fillPath(path, QBrush(QColor(*rgba), Qt.BrushStyle.BDiagPattern))
            else:
                painter.fillPath(path, QColor(*rgba))
            pen = QPen(QColor(outline), 2.4 if selected else 1.2)
            pen.setCosmetic(True)
            if selected:
                pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # label (skip tiny keep-outs to avoid clutter)
            if BedRole(z.role) != BedRole.KEEP_OUT:
                cx = sum(p[0] for p in z.polygon) / len(z.polygon)
                cy = sum(p[1] for p in z.polygon) / len(z.polygon)
                sc = self._world_to_screen(cx, cy)
                painter.setFont(font)
                painter.setPen(QColor(self._palette.annotation))
                painter.drawText(QPointF(sc.x() - 28, sc.y()), z.label or z.id)

    def _draw_nest(self, painter: QPainter) -> None:
        """Draw each nested component's footprint/toolpaths over its zone (M7.6).
        Violating footprints draw in red so collisions read at a glance."""
        if not self._placements:
            return
        font = QFont(self.font())
        font.setPointSize(8)
        for pl in self._placements:
            if pl["violated"]:
                outline = "#d83a3a"
            else:
                _, outline = _ROLE_COLORS.get(
                    BedRole(pl["role"]) if pl["role"] is not None else BedRole.UNASSIGNED,
                    _ROLE_COLORS[BedRole.UNASSIGNED])
            pen = QPen(QColor(outline), 2.0 if pl["violated"] else 1.4)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for path in pl["paths"]:
                if len(path) < 2:
                    # a lone point (a drilled hole) → a small marker
                    if path:
                        c = self._world_to_screen(path[0][0], path[0][1])
                        painter.drawEllipse(c, 2.4, 2.4)
                    continue
                qpath = QPainterPath()
                pts = [self._world_to_screen(x, y) for x, y, *_ in path]
                qpath.moveTo(pts[0])
                for p in pts[1:]:
                    qpath.lineTo(p)
                painter.drawPath(qpath)
            # label at the footprint centre
            x0, y0, x1, y1 = pl["bbox"]
            sc = self._world_to_screen((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            painter.setFont(font)
            painter.setPen(QColor("#d83a3a") if pl["violated"]
                           else QColor(self._palette.annotation))
            painter.drawText(QPointF(sc.x() - 20, sc.y()), pl["label"])

    def _draw_scale_bar(self, painter: QPainter) -> None:
        bar_mm = 50.0
        bar_px = bar_mm * self._scale
        margin = 16
        x2 = self.width() - margin
        x1 = x2 - bar_px
        y = self.height() - margin
        pen = QPen(QColor(self._palette.annotation), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(int(x1), int(y), int(x2), int(y))
        painter.drawLine(int(x1), int(y) - 4, int(x1), int(y) + 4)
        painter.drawLine(int(x2), int(y) - 4, int(x2), int(y) + 4)
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(QRectF(x1, y - 18, bar_px, 14),
                         Qt.AlignmentFlag.AlignCenter, "50 mm")

    # ------------------------------------------------------------------ interaction

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        pos = event.position()
        wx, wy = self._screen_to_world(pos.x(), pos.y())
        self._scale *= factor
        self._offset = QPointF(pos.x() - wx * self._scale, pos.y() + wy * self._scale)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_active = True
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            wx, wy = self._screen_to_world(event.position().x(), event.position().y())
            # A nested footprint under the cursor takes priority — drag to nudge it.
            idx = self._nest_hit_test(wx, wy)
            if idx is not None:
                self._nest_drag = idx
                self._nest_last = (wx, wy)
                self._nest_total = (0.0, 0.0)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                event.accept()
                return
            hit = self._hit_test(wx, wy)
            self._selected_id = hit
            self.update()
            self.region_clicked.emit(hit or "")
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            delta = event.position() - self._pan_last
            self._offset += delta
            self._pan_last = event.position()
            self.update()
            event.accept()
        elif self._nest_drag is not None:
            wx, wy = self._screen_to_world(event.position().x(), event.position().y())
            dwx, dwy = wx - self._nest_last[0], wy - self._nest_last[1]
            self._translate_placement(self._nest_drag, dwx, dwy)
            self._nest_last = (wx, wy)
            self._nest_total = (self._nest_total[0] + dwx, self._nest_total[1] + dwy)
            self.update()
            event.accept()

    def _translate_placement(self, idx: int, dwx: float, dwy: float) -> None:
        pl = self._placements[idx]
        pl["paths"] = [[(x + dwx, y + dwy, *rest) for x, y, *rest in path]
                       for path in pl["paths"]]
        x0, y0, x1, y1 = pl["bbox"]
        pl["bbox"] = (x0 + dwx, y0 + dwy, x1 + dwx, y1 + dwy)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            self._pan_active = False
            self.unsetCursor()
            event.accept()
        elif self._nest_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            pl = self._placements[self._nest_drag]
            dx, dy = self._nest_total
            self._nest_drag = None
            self._nest_total = (0.0, 0.0)
            self.unsetCursor()
            if dx or dy:
                self.component_nudged.emit(pl["zone_id"], dx, dy)
            event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._zones:
            self.fit_to_view()
