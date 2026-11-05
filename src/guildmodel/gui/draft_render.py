"""Paint a blueprint sheet on any QPainter (2.3): the PDF writer, the SVG
generator, the printer and a QImage all drive `paint_sheet`, which walks the
sheet model `core.draft.sheet` composes. Pens are sized on paper (the line
weight the settings name for the part's outlines, thinner for the rest),
text is Helvetica at the sheet's sizes, and a view's strokes are scaled by
its placement; its texts were composed at paper size over the scale, so
they come out the size the sheet model meant.

GuildDraw's `export/template_print.py` is the model: one device-agnostic
painter, the drivers thin."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                           QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPen, QPolygonF)

from guildmodel.core.draft.sheet import Sheet

__all__ = ["export_pdf", "export_svg", "paint_sheet", "print_sheets", "render_png"]

_INK = "#000000"
_COLORS = {"normal": "#000000", "bold": "#000000", "muted": "#555555",
           "warning": "#a03020"}
#: style -> (weight as a fraction of the outline weight, dash pattern in mm)
_PENS = {
    "visible": (1.0, None),
    "heavy": (1.4, None),
    "hidden": (0.6, (2.4, 1.2)),
    "center": (0.5, (6.0, 1.5, 1.0, 1.5)),
    "thin": (0.5, None),
    "dim": (0.5, None),
    "border": (1.4, None),
}


def _pen(style: str, lw_mm: float, px_per_mm: float) -> QPen:
    frac, dash = _PENS.get(style, _PENS["visible"])
    w = max(lw_mm * frac * px_per_mm, 0.6)
    pen = QPen(QColor(_INK))
    pen.setWidthF(w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap if dash else Qt.PenCapStyle.RoundCap)
    if dash:
        pen.setDashPattern([d * px_per_mm / w for d in dash])
    return pen


def _font(size_mm: float, px_per_mm: float, style: str) -> QFont:
    font = QFont("Helvetica")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(max(1, round(size_mm * px_per_mm)))
    if style == "bold":
        font.setBold(True)
    return font


def _path(points, closed: bool) -> QPainterPath:
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(QPointF(x, y))
    if closed:
        path.closeSubpath()
    return path


def _draw_text(painter: QPainter, x_px: float, y_px: float, text, size_mm: float,
               px_per_mm: float, angle_deg: float = 0.0) -> None:
    font = _font(size_mm, px_per_mm, text.style)
    fm = QFontMetricsF(font)
    painter.setFont(font)
    painter.setPen(QPen(QColor(_COLORS.get(text.style, _INK))))
    w = fm.horizontalAdvance(text.text)
    dx = {"center": -0.5 * w, "right": -w}.get(text.align, 0.0)
    if text.valign == "top":
        dy = fm.ascent()
    elif text.valign == "middle":
        dy = 0.5 * fm.capHeight()
    else:
        dy = 0.0
    painter.save()
    painter.translate(x_px, y_px)
    if abs(angle_deg) > 1e-9:
        painter.rotate(-angle_deg)
    painter.drawText(QPointF(dx, dy), text.text)
    painter.restore()


def paint_sheet(painter: QPainter, px_per_mm: float, sheet: Sheet,
                line_weight_mm: float = 0.35) -> None:
    """Paint one sheet; the painter's origin is the page's top-left corner,
    one unit a device pixel."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    s = px_per_mm
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for st in sheet.strokes:
        painter.setPen(_pen(st.style, line_weight_mm, s))
        painter.drawPath(_path([(x * s, y * s) for x, y in st.pts], st.closed))
    for f in sheet.fills:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(_INK)))
        painter.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in f.pts]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    for t in sheet.texts:
        _draw_text(painter, t.x * s, t.y * s, t, t.size, s)
    for p in sheet.placed:
        v = p.view
        for st in v.strokes:
            painter.setPen(_pen(st.style, line_weight_mm, s))
            pts = [p.to_page(x, y) for x, y in st.pts]
            painter.drawPath(_path([(x * s, y * s) for x, y in pts], st.closed))
        for f in v.fills:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(_INK)))
            pts = [p.to_page(x, y) for x, y in f.pts]
            painter.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        for t in v.texts:
            x, y = p.to_page(t.x, t.y)
            _draw_text(painter, x * s, y * s, t, t.size * p.scale, s, t.angle)


# ------------------------------------------------------------------ drivers

def render_png(sheet: Sheet, dpi: float = 150.0, line_weight_mm: float = 0.35) -> QImage:
    """The sheet as an image, for a preview and for tests."""
    s = dpi / 25.4
    img = QImage(int(round(sheet.width * s)), int(round(sheet.height * s)),
                 QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    try:
        paint_sheet(painter, s, sheet, line_weight_mm)
    finally:
        painter.end()
    return img


def _page_layout(sheet: Sheet) -> QPageLayout:
    from PySide6.QtCore import QMarginsF
    landscape = sheet.width > sheet.height
    w, h = (sheet.height, sheet.width) if landscape else (sheet.width, sheet.height)
    size = QPageSize(QSizeF(w, h), QPageSize.Unit.Millimeter, "",
                     QPageSize.SizeMatchPolicy.ExactMatch)
    return QPageLayout(size, QPageLayout.Orientation.Landscape if landscape
                       else QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                       QPageLayout.Unit.Millimeter)


def export_pdf(path, sheets: list, line_weight_mm: float = 0.35, dpi: int = 600) -> None:
    """Every sheet to one PDF, each on its own page at its own size."""
    from PySide6.QtGui import QPdfWriter

    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setResolution(int(dpi))
    writer.setTitle(sheets[0].title if sheets else "Blueprint")
    writer.setCreator("GuildModel")
    writer.setPageLayout(_page_layout(sheets[0]))
    s = writer.logicalDpiX() / 25.4
    painter = QPainter()
    if not painter.begin(writer):
        raise OSError(f"could not write {path}")
    try:
        for i, sheet in enumerate(sheets):
            if i:
                writer.setPageLayout(_page_layout(sheet))
                writer.newPage()
            paint_sheet(painter, s, sheet, line_weight_mm)
    finally:
        painter.end()


def export_svg(path, sheet: Sheet, line_weight_mm: float = 0.35, dpi: float = 96.0) -> None:
    """One sheet to one SVG, sized in millimeters."""
    from PySide6.QtCore import QRect, QSize
    from PySide6.QtSvg import QSvgGenerator

    path = Path(path)
    gen = QSvgGenerator()
    gen.setFileName(str(path))
    gen.setTitle(sheet.title or "Blueprint")
    gen.setDescription("GuildModel blueprint")
    gen.setResolution(int(dpi))
    s = dpi / 25.4
    w, h = int(round(sheet.width * s)), int(round(sheet.height * s))
    gen.setSize(QSize(w, h))
    gen.setViewBox(QRect(0, 0, w, h))
    painter = QPainter()
    if not painter.begin(gen):
        raise OSError(f"could not write {path}")
    try:
        paint_sheet(painter, s, sheet, line_weight_mm)
    finally:
        painter.end()


def print_sheets(printer, sheets: list, line_weight_mm: float = 0.35) -> int:
    """Every sheet to a QPrinter (a printer or a PDF); returns the pages."""
    from PySide6.QtPrintSupport import QPrinter

    printer.setPageLayout(_page_layout(sheets[0]))
    painter = QPainter()
    if not painter.begin(printer):
        name = printer.printerName()
        raise OSError(f"could not start the print job on {name}" if name
                      else "could not start the print job")
    try:
        for i, sheet in enumerate(sheets):
            if i:
                printer.setPageLayout(_page_layout(sheet))
                printer.newPage()
            page = printer.pageRect(QPrinter.Unit.Millimeter)
            s = printer.logicalDpiX() / 25.4
            # the painter's origin is the printable area's corner: offset the
            # page so the sheet's own margins land where they were composed
            painter.save()
            painter.translate(-page.x() * s, -page.y() * s)
            paint_sheet(painter, s, sheet, line_weight_mm)
            painter.restore()
    finally:
        painter.end()
    return len(sheets)
