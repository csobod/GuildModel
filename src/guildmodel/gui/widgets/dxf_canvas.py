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

from guildmodel.core.layers import LAYER_STYLES
from guildmodel.gui.style import theme

_PLACEHOLDER_TEXT = "Open a DXF file to begin"


class DxfCanvas(QWidget):
    """Render DXF layer data as 2D polylines with zoom/pan.

    Feed data via :meth:`set_layers`.  Layer visibility is controlled by
    :meth:`set_layer_visible`.  Call :meth:`fit_to_view` after loading.
    """

    zoom_changed = Signal(float)   # emits current scale (px / mm)
    measure_changed = Signal(str)  # measure read-out text ("" when cleared) — M7.13

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

        # measure tool (BUILDPLAN M7.13): left-click drops snapped points; 2 points
        # read a distance, 3 read a corner angle. A flat vertex cache feeds snapping.
        self._measure_mode = False
        self._measure_pts: list[tuple[float, float]] = []
        self._measure_hover: Optional[tuple[float, float]] = None
        self._measure_hover_snapped = False
        self._measure_vertices: list[tuple[float, float]] = []

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
        self._rebuild_measure_vertices()
        self._clear_measure()
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

    def recolor_toolpaths(self, colors: list[str]) -> dict[str, str]:
        """Re-cycle the overlay op colors (Preferences ▸ Appearance palette
        change). Returns op-name → color so the inspector table can follow."""
        out: dict[str, str] = {}
        for i, op in enumerate(self._toolpaths):
            op["color"] = colors[i % len(colors)] if colors else None
            out[op.get("name", "")] = op["color"] or ""
        if self._toolpaths:
            self.update()
        return out

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

    # ----------------------------------------------------------- measure (M7.13)
    def set_measure_mode(self, on: bool) -> None:
        """Enter/leave the measure tool. In measure mode a left-click drops a point
        (snapped to the nearest curve vertex); 2 points read a distance, 3 a corner
        angle. Leaving clears the picks and the read-out."""
        self._measure_mode = bool(on)
        self._clear_measure()
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        if not on:
            self.unsetCursor()
        self.update()

    def measure_active(self) -> bool:
        return self._measure_mode

    def has_layers(self) -> bool:
        return bool(self._layers)

    def _rebuild_measure_vertices(self) -> None:
        verts: list[tuple[float, float]] = []
        for curves in self._layers.values():
            for curve in curves:
                verts.extend((float(x), float(y)) for x, y in curve)
        self._measure_vertices = verts

    def _clear_measure(self) -> None:
        self._measure_pts = []
        self._measure_hover = None
        self._measure_hover_snapped = False
        if self._measure_mode:
            self.measure_changed.emit("")

    def _snap(self, sx: float, sy: float) -> tuple[tuple[float, float], bool]:
        """World point for a screen click, snapped to the nearest vertex within ~10 px
        if one is in range. Returns (point, snapped?)."""
        from guildmodel.core.geometry.measure import snap_to_vertices
        wx, wy = self._screen_to_world(sx, sy)
        tol_mm = 10.0 / self._scale if self._scale else 0.0
        hit = snap_to_vertices((wx, wy), self._measure_vertices, tol_mm)
        if hit is not None:
            return hit, True
        return (wx, wy), False

    def _measure_readout(self, hover: tuple[float, float] | None) -> str:
        """Build the status text for the current picks (+ optional live hover)."""
        from guildmodel.core.geometry.measure import angle_at, distance
        pts = self._measure_pts
        if not pts:
            return "Measure: click a point (snaps to curve vertices)"
        if len(pts) == 1:
            if hover is None:
                return "Measure: click the second point"
            return f"{distance(pts[0], hover):.2f} mm"
        if len(pts) == 2:
            return f"Distance: {distance(pts[0], pts[1]):.2f} mm"
        a, b, c = pts[0], pts[1], pts[2]
        return (f"A–B {distance(a, b):.2f} mm   ·   B–C {distance(b, c):.2f} mm"
                f"   ·   ∠B {angle_at(a, b, c):.1f}°")

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
        self._draw_measure(painter)
        self._draw_scale_bar(painter)

    def _draw_placeholder(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSize(13)
        painter.setFont(font)
        painter.setPen(QColor(self._palette.placeholder))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _PLACEHOLDER_TEXT)

    def _draw_grid(self, painter: QPainter) -> None:
        """Grid from the theme's config (Preferences ▸ Appearance ▸ Grid):
        spacing, a heavier major line every Nth, optional color overrides.
        Shipped config = the historical light 10-mm dotted grid."""
        cfg = theme.grid_config()
        if not cfg["visible"]:
            return
        grid_mm = float(cfg["spacing_mm"])
        major_every = int(cfg["major_every"])
        minor = QColor(cfg["minor_color"] or self._palette.grid)
        major = QColor(cfg["major_color"] or cfg["minor_color"]
                       or self._palette.grid)
        minor_pen = QPen(minor, 0.5, Qt.PenStyle.DotLine)
        major_pen = QPen(major, float(cfg["major_width_px"]),
                         Qt.PenStyle.DotLine)

        # find world bounds of the widget
        x0, y0 = self._screen_to_world(0, 0)
        x1, y1 = self._screen_to_world(self.width(), self.height())
        xmin, xmax = sorted([x0, x1])
        ymin, ymax = sorted([y0, y1])

        def _is_major(coord_mm: float) -> bool:
            return major_every > 1 and round(coord_mm / grid_mm) % major_every == 0

        # vertical lines
        gx = math.floor(xmin / grid_mm) * grid_mm
        while gx <= xmax:
            sp = self._world_to_screen(gx, 0)
            painter.setPen(major_pen if _is_major(gx) else minor_pen)
            painter.drawLine(int(sp.x()), 0, int(sp.x()), self.height())
            gx += grid_mm

        # horizontal lines
        gy = math.floor(ymin / grid_mm) * grid_mm
        while gy <= ymax:
            sp = self._world_to_screen(0, gy)
            painter.setPen(major_pen if _is_major(gy) else minor_pen)
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
            _, width = LAYER_STYLES.get(layer, (self._palette.annotation, 1.0))
            # By NAME, so the maker's Preferences ▸ Layers override wins.
            color_hex = theme.layer_color_for(layer, self._dark)
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

    def _draw_measure(self, painter: QPainter) -> None:
        """Measure-tool overlay (M7.13): the picked points, the dimension lines with
        their lengths, the corner angle (3 points), the live rubber-band to the cursor,
        and a snap box when the cursor has latched onto a vertex."""
        if not self._measure_mode:
            return
        from guildmodel.core.geometry.measure import angle_at, distance
        color = QColor(self._palette.measure)
        screen = [self._world_to_screen(x, y) for (x, y) in self._measure_pts]

        # rubber-band from the last point to the live (snapped) cursor
        if screen and self._measure_hover is not None and len(self._measure_pts) < 3:
            hs = self._world_to_screen(*self._measure_hover)
            pen = QPen(color, 1.2)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(screen[-1], hs)

        # solid dimension segments + length labels
        pen = QPen(color, 1.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(1, len(screen)):
            painter.drawLine(screen[i - 1], screen[i])
            mid = QPointF((screen[i - 1].x() + screen[i].x()) / 2.0,
                          (screen[i - 1].y() + screen[i].y()) / 2.0)
            d = distance(self._measure_pts[i - 1], self._measure_pts[i])
            self._draw_measure_label(painter, mid, f"{d:.2f} mm", color)

        # point markers
        painter.setBrush(color)
        painter.setPen(QPen(color, 1.0))
        for p in screen:
            painter.drawEllipse(p, 3.2, 3.2)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # corner angle at the middle vertex when three points are placed
        if len(self._measure_pts) == 3:
            ang = angle_at(*self._measure_pts)
            self._draw_measure_label(
                painter, screen[1] + QPointF(2, -2), f"∠ {ang:.1f}°", color)

        # snap box at the cursor when latched onto a vertex
        if self._measure_hover is not None and self._measure_hover_snapped:
            hs = self._world_to_screen(*self._measure_hover)
            pen = QPen(color, 1.4)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(hs.x() - 4.0, hs.y() - 4.0, 8.0, 8.0))

    def _draw_measure_label(self, painter: QPainter, anchor: QPointF,
                            text: str, color: QColor) -> None:
        font = QFont(self.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text)
        h = fm.height()
        pad = 3.0
        x = anchor.x() + 6.0
        top = anchor.y() - h / 2.0
        bg = QRectF(x - pad, top - pad, w + 2 * pad, h + 2 * pad)
        bgc = QColor(self._palette.canvas_bg)
        bgc.setAlpha(220)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bgc)
        painter.drawRoundedRect(bg, 3.0, 3.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(color)
        painter.drawText(QPointF(x, anchor.y() + fm.ascent() / 2.0 - fm.descent() / 2.0),
                         text)

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
            return
        if self._measure_mode and event.button() == Qt.MouseButton.LeftButton:
            pt, _ = self._snap(event.position().x(), event.position().y())
            if len(self._measure_pts) >= 3:      # a 4th click starts a fresh chain
                self._measure_pts = [pt]
            else:
                self._measure_pts.append(pt)
            self.measure_changed.emit(self._measure_readout(None))
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            delta = event.position() - self._pan_last
            self._offset += delta
            self._pan_last = event.position()
            self.update()
            event.accept()
            return
        if self._measure_mode:
            hover, snapped = self._snap(event.position().x(), event.position().y())
            self._measure_hover = hover
            self._measure_hover_snapped = snapped
            if 0 < len(self._measure_pts) < 3:   # live read-out while extending
                self.measure_changed.emit(self._measure_readout(hover))
            self.update()
            event.accept()

    def keyPressEvent(self, event) -> None:
        if self._measure_mode and event.key() == Qt.Key.Key_Escape:
            self._clear_measure()
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_active:
            self._pan_active = False
            self.unsetCursor()
            event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._layers:
            self.fit_to_view()
