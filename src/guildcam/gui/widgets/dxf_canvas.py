"""2D DXF preview canvas with zoom, pan, and per-layer visibility."""
from __future__ import annotations
import math
from typing import Optional

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QPen, QColor, QWheelEvent, QMouseEvent,
    QPaintEvent, QResizeEvent, QFont, QPainterPath,
)

from guildcam.core.layers import LAYER_STYLES
from guildcam.gui.style import theme

_PLACEHOLDER_TEXT = "Open a DXF file to begin"


class DxfCanvas(QWidget):
    """Render DXF layer data as 2D polylines with zoom/pan.

    Feed data via :meth:`set_layers`.  Layer visibility is controlled by
    :meth:`set_layer_visible`.  Call :meth:`fit_to_view` after loading.
    """

    zoom_changed = Signal(float)   # emits current scale (px / mm)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        # theme palette for everything QPainter draws (M4.5: no hardcoded hexes)
        self._dark = False
        self._palette = theme.palette(False)

        # layer-name → list of polylines (each polyline = list of (x, y) in mm)
        self._layers: dict[str, list[list[tuple[float, float]]]] = {}
        self._visible: dict[str, bool] = {k: True for k in LAYER_STYLES}

        # stock outline rectangles (x0, y0, x1, y1 in mm), drawn dashed
        self._stock_rects: list[tuple[float, float, float, float]] = []
        # zone-inspector hover highlight: polygon rings in mm
        self._zone_rings: list[list[tuple[float, float]]] = []
        # program-zero / G54 datum marker (world mm), or None (BUILDPLAN M6.2)
        self._program_zero_xy: Optional[tuple[float, float]] = None
        self._program_zero_label: str = ""

        # toolpath overlay (BUILDPLAN M7.11): per-op cutting paths drawn over the
        # design, colour-coded, with per-op visibility + a highlighted op.
        self._toolpaths: list[dict] = []          # [{name, paths:[[(x,y)..]..], color}]
        self._tp_visible: dict[str, bool] = {}
        self._tp_highlight: Optional[str] = None

        # view transform: world_to_screen = point * scale + offset
        self._scale: float = 5.0       # px / mm
        self._offset: QPointF = QPointF(0.0, 0.0)

        # pan state
        self._pan_active = False
        self._pan_last: QPointF = QPointF()

        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

    # ------------------------------------------------------------------ public API

    def set_dark_mode(self, dark: bool) -> None:
        """Swap the painter palette (mirrors GuildDraw's scene.set_dark_mode)."""
        self._dark = dark
        self._palette = theme.palette(dark)
        self.update()

    def set_layers(self, layers: dict[str, list[list[tuple[float, float]]]]) -> None:
        """Replace layer data and refresh."""
        self._layers = layers
        self._visible = {k: True for k in LAYER_STYLES}
        self.fit_to_view()

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        self._visible[layer] = visible
        self.update()

    def set_stock(self, rects: list[tuple[float, float, float, float]]) -> None:
        """Stock outline rectangles (x0, y0, x1, y1 in mm); empty hides them."""
        refit = rects != self._stock_rects
        self._stock_rects = list(rects)
        if refit and self._layers:
            self.fit_to_view()
        else:
            self.update()

    def set_program_zero(self, xy: tuple[float, float] | None, label: str = "") -> None:
        """Mark where the program's G54 work zero lands (world mm); None hides
        it. The toolpaths stay in the design frame — this is just a datum hint."""
        self._program_zero_xy = xy
        self._program_zero_label = label
        self.update()

    def set_toolpaths(self, ops: list[dict]) -> None:
        """Show a generated program's cutting paths over the design (M7.11).

        `ops`: ``[{"name": str, "paths": [[(x, y), ...], ...], "color": "#hex"}]`` in
        design (canvas) mm. All ops start visible; the highlight clears."""
        self._toolpaths = list(ops)
        self._tp_visible = {op["name"]: True for op in self._toolpaths}
        self._tp_highlight = None
        self.update()

    def set_toolpath_visible(self, name: str, visible: bool) -> None:
        self._tp_visible[name] = visible
        self.update()

    def set_toolpath_highlight(self, name: str | None) -> None:
        self._tp_highlight = name
        self.update()

    def clear_toolpaths(self) -> None:
        self._toolpaths = []
        self._tp_visible = {}
        self._tp_highlight = None
        self.update()

    def set_zone_highlight(
        self, rings: list[list[tuple[float, float]]] | None
    ) -> None:
        """Highlight a zone polygon (exterior + hole rings); None clears."""
        self._zone_rings = rings or []
        self.update()

    def fit_to_view(self) -> None:
        """Scale and centre so all geometry fills 90% of the widget."""
        if not self._layers:
            return
        xs: list[float] = []
        ys: list[float] = []
        for curves in self._layers.values():
            for curve in curves:
                for x, y in curve:
                    xs.append(x)
                    ys.append(y)
        for x0, y0, x1, y1 in self._stock_rects:
            xs += [x0, x1]
            ys += [y0, y1]
        if not xs:
            return

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0

        w, h = self.width(), self.height()
        scale_x = w * 0.9 / span_x
        scale_y = h * 0.9 / span_y
        self._scale = min(scale_x, scale_y)

        # centre the content — DXF Y increases upward; screen Y increases downward
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        self._offset = QPointF(
            w / 2.0 - cx * self._scale,
            h / 2.0 + cy * self._scale,   # flip Y
        )
        self.zoom_changed.emit(self._scale)
        self.update()

    # ------------------------------------------------------------------ coordinate helpers

    def _world_to_screen(self, x: float, y: float) -> QPointF:
        return QPointF(
            x * self._scale + self._offset.x(),
            -y * self._scale + self._offset.y(),
        )

    def _screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        x = (sx - self._offset.x()) / self._scale
        y = -(sy - self._offset.y()) / self._scale
        return x, y

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(self._palette.canvas_bg))

        if not self._layers:
            self._draw_placeholder(painter)
            return

        self._draw_grid(painter)
        self._draw_stock(painter)
        self._draw_layers(painter)
        self._draw_toolpaths(painter)
        self._draw_zone_highlight(painter)
        self._draw_program_zero(painter)
        self._draw_scale_bar(painter)

    def _draw_placeholder(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSize(13)
        painter.setFont(font)
        painter.setPen(QColor(self._palette.placeholder))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _PLACEHOLDER_TEXT)

    def _draw_grid(self, painter: QPainter) -> None:
        """Light 10-mm grid."""
        grid_mm = 10.0
        pen = QPen(QColor(self._palette.grid), 0.5, Qt.PenStyle.DotLine)
        painter.setPen(pen)

        # find world bounds of the widget
        x0, y0 = self._screen_to_world(0, 0)
        x1, y1 = self._screen_to_world(self.width(), self.height())
        xmin, xmax = sorted([x0, x1])
        ymin, ymax = sorted([y0, y1])

        # vertical lines
        gx = math.floor(xmin / grid_mm) * grid_mm
        while gx <= xmax:
            sp = self._world_to_screen(gx, 0)
            painter.drawLine(int(sp.x()), 0, int(sp.x()), self.height())
            gx += grid_mm

        # horizontal lines
        gy = math.floor(ymin / grid_mm) * grid_mm
        while gy <= ymax:
            sp = self._world_to_screen(0, gy)
            painter.drawLine(0, int(sp.y()), self.width(), int(sp.y()))
            gy += grid_mm

    def _draw_stock(self, painter: QPainter) -> None:
        """Dashed outlines of the stock blank and pad block."""
        if not self._stock_rects:
            return
        pen = QPen(QColor(self._palette.stock_dash), 1.2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for x0, y0, x1, y1 in self._stock_rects:
            top_left = self._world_to_screen(min(x0, x1), max(y0, y1))
            bottom_right = self._world_to_screen(max(x0, x1), min(y0, y1))
            painter.drawRect(QRectF(top_left, bottom_right))

    def _draw_program_zero(self, painter: QPainter) -> None:
        """A small crosshair-in-circle at the G54 work-zero datum (M6.2)."""
        if self._program_zero_xy is None:
            return
        c = self._world_to_screen(*self._program_zero_xy)
        color = QColor(self._palette.zone_outline)
        pen = QPen(color, 1.4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = 7.0
        painter.drawEllipse(c, r, r)
        painter.drawLine(QPointF(c.x() - r - 3, c.y()), QPointF(c.x() + r + 3, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - r - 3), QPointF(c.x(), c.y() + r + 3))
        if self._program_zero_label:
            font = QFont(self.font())
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(QPointF(c.x() + r + 5, c.y() - r), self._program_zero_label)

    def _draw_zone_highlight(self, painter: QPainter) -> None:
        if not self._zone_rings:
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for ring in self._zone_rings:
            if len(ring) < 3:
                continue
            pts = [self._world_to_screen(x, y) for x, y in ring]
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            path.closeSubpath()
        painter.fillPath(path, QColor(*self._palette.zone_fill_rgba))
        pen = QPen(QColor(self._palette.zone_outline), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_layers(self, painter: QPainter) -> None:
        for layer, curves in self._layers.items():
            if not self._visible.get(layer, True):
                continue
            color_hex, width = LAYER_STYLES.get(
                layer, (self._palette.annotation, 1.0)
            )
            color_hex = theme.layer_color(color_hex, self._dark)
            pen = QPen(QColor(color_hex), width)
            pen.setCosmetic(True)   # width in screen px regardless of zoom
            painter.setPen(pen)

            for curve in curves:
                if len(curve) < 2:
                    continue
                pts = [self._world_to_screen(x, y) for x, y in curve]
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])
                # close if first ≈ last
                if len(curve) > 2:
                    first = pts[0]
                    last = pts[-1]
                    if abs(first.x() - last.x()) > 1 or abs(first.y() - last.y()) > 1:
                        painter.drawLine(pts[-1], pts[0])

            # draw HINGE markers as small crosses
            if layer == "HINGE":
                cross_pen = QPen(QColor(color_hex), 1.5)
                cross_pen.setCosmetic(True)
                painter.setPen(cross_pen)
                for curve in curves:
                    if curve:
                        cx_mm = sum(p[0] for p in curve) / len(curve)
                        cy_mm = sum(p[1] for p in curve) / len(curve)
                        sc = self._world_to_screen(cx_mm, cy_mm)
                        r = 5
                        painter.drawLine(
                            int(sc.x()) - r, int(sc.y()),
                            int(sc.x()) + r, int(sc.y()),
                        )
                        painter.drawLine(
                            int(sc.x()), int(sc.y()) - r,
                            int(sc.x()), int(sc.y()) + r,
                        )

    def _draw_toolpaths(self, painter: QPainter) -> None:
        """Per-op cutting paths over the design, colour-coded; the rapids between
        successive paths are faint dashed connectors (BUILDPLAN M7.11)."""
        if not self._toolpaths:
            return
        for op in self._toolpaths:
            name = op.get("name", "")
            if not self._tp_visible.get(name, True):
                continue
            color = QColor(op.get("color") or self._palette.annotation)
            hi = (name == self._tp_highlight)
            pen = QPen(color, 2.6 if hi else 1.3)
            pen.setCosmetic(True)
            rapid = QPen(QColor(color.red(), color.green(), color.blue(), 80),
                         0.8, Qt.PenStyle.DashLine)
            rapid.setCosmetic(True)
            prev_end: Optional[QPointF] = None
            for path in op.get("paths", []):
                if len(path) < 1:
                    continue
                pts = [self._world_to_screen(x, y) for x, y in path]
                if prev_end is not None:
                    painter.setPen(rapid)
                    painter.drawLine(prev_end, pts[0])
                painter.setPen(pen)
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])
                prev_end = pts[-1]

    def _draw_scale_bar(self, painter: QPainter) -> None:
        """10 mm scale bar in the bottom-right corner."""
        bar_mm = 10.0
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
        painter.setPen(QColor(self._palette.annotation))
        label_rect = QRectF(x1, y - 18, bar_px, 14)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "10 mm")

    # ------------------------------------------------------------------ interaction

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1.0 / 1.15

        mouse_pos = event.position()
        wx, wy = self._screen_to_world(mouse_pos.x(), mouse_pos.y())

        self._scale *= factor
        # keep the point under the cursor fixed
        self._offset = QPointF(
            mouse_pos.x() - wx * self._scale,
            mouse_pos.y() + wy * self._scale,
        )
        self.zoom_changed.emit(self._scale)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_active = True
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            delta = event.position() - self._pan_last
            self._offset += delta
            self._pan_last = event.position()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            self._pan_active = False
            self.unsetCursor()
            event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._layers:
            self.fit_to_view()
