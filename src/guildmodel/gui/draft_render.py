"""Paint a blueprint sheet on any QPainter (2.3): the PDF writer, the SVG
generator, the printer and a QImage all drive `paint_sheet`, which walks the
sheet model `core.draft.sheet` composes. Pens are sized on paper (the line
weight the settings name for the part's outlines, thinner for the rest),
text is set in the settings' font at the sheet's sizes, the ink and the
paper are the settings' colors (black on white, or a true blueprint), and a
view's strokes are scaled by its placement; its texts were composed at
paper size over the scale, so they come out the size the sheet model meant.

GuildDraw's `export/template_print.py` is the model: one device-agnostic
painter, the drivers thin."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                           QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPen, QPolygonF)

from guildmodel.core.draft.sheet import Sheet

__all__ = ["RenderStyle", "export_pdf", "export_svg", "measure_text_width_em",
           "paint_sheet", "print_sheets", "render_png"]

DEFAULT_FONT = "Helvetica"
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


@dataclass(frozen=True)
class RenderStyle:
    """How a sheet is painted: the outlines' weight on paper, the font, the
    ink and the paper. `from_settings` reads a `BlueprintSettings`."""
    line_weight_mm: float = 0.35
    font_family: str = ""
    line_color: str = "#000000"
    paper_color: str = "#ffffff"

    @classmethod
    def from_settings(cls, settings) -> "RenderStyle":
        return cls(line_weight_mm=float(settings.line_weight_mm),
                   font_family=str(settings.font_family or ""),
                   line_color=str(settings.line_color), paper_color=str(settings.paper_color))

    @property
    def ink(self) -> QColor:
        return QColor(self.line_color)

    @property
    def paper(self) -> QColor:
        return QColor(self.paper_color)

    def text_color(self, style: str) -> QColor:
        """The ink for a text style: muted is the ink faded toward the
        paper; a warning is red on a light paper, amber on a dark one."""
        ink, paper = self.ink, self.paper
        if style == "muted":
            return QColor(int(0.6 * ink.red() + 0.4 * paper.red()),
                          int(0.6 * ink.green() + 0.4 * paper.green()),
                          int(0.6 * ink.blue() + 0.4 * paper.blue()))
        if style == "warning":
            return QColor("#ffb74d") if paper.lightnessF() < 0.5 else QColor("#a03020")
        return ink

    def font(self, size_mm: float, px_per_mm: float, style: str) -> QFont:
        font = QFont(self.font_family or DEFAULT_FONT)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setPixelSize(max(1, round(size_mm * px_per_mm)))
        if style == "bold":
            font.setBold(True)
        return font


def measure_text_width_em(font_family: str = "") -> float:
    """The average glyph advance of a family, as a fraction of its em, over
    the characters a sheet's texts are made of; the sheet model lays its
    texts out by it. Needs a QGuiApplication."""
    font = QFont(font_family or DEFAULT_FONT)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(100)
    sample = "0123456789.,:;-+±×°[]()/ ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    w = QFontMetricsF(font).horizontalAdvance(sample)
    em = w / (100.0 * len(sample))
    return min(max(float(em), 0.3), 0.9) if em > 0 else 0.52


def _pen(style: str, lw_mm: float, px_per_mm: float, ink: QColor) -> QPen:
    frac, dash = _PENS.get(style, _PENS["visible"])
    w = max(lw_mm * frac * px_per_mm, 0.6)
    pen = QPen(ink)
    pen.setWidthF(w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap if dash else Qt.PenCapStyle.RoundCap)
    if dash:
        pen.setDashPattern([d * px_per_mm / w for d in dash])
    return pen


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
               px_per_mm: float, style: RenderStyle, angle_deg: float = 0.0) -> None:
    font = style.font(size_mm, px_per_mm, text.style)
    fm = QFontMetricsF(font)
    painter.setFont(font)
    painter.setPen(QPen(style.text_color(text.style)))
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


def _style_of(line_weight_mm, style) -> RenderStyle:
    """The drivers' older calling form, a line weight alone, still works."""
    if style is None:
        return RenderStyle(line_weight_mm=float(line_weight_mm))
    return style


def paint_sheet(painter: QPainter, px_per_mm: float, sheet: Sheet,
                line_weight_mm: float = 0.35, style: RenderStyle | None = None) -> None:
    """Paint one sheet; the painter's origin is the page's top-left corner,
    one unit a device pixel. The paper is painted first, in its color."""
    style = _style_of(line_weight_mm, style)
    lw = style.line_weight_mm
    ink = style.ink
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    s = px_per_mm
    painter.fillRect(0, 0, int(round(sheet.width * s)) + 1, int(round(sheet.height * s)) + 1,
                     style.paper)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for st in sheet.strokes:
        painter.setPen(_pen(st.style, lw, s, ink))
        painter.drawPath(_path([(x * s, y * s) for x, y in st.pts], st.closed))
    for f in sheet.fills:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(ink))
        painter.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in f.pts]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    for t in sheet.texts:
        _draw_text(painter, t.x * s, t.y * s, t, t.size, s, style)
    for p in sheet.placed:
        v = p.view
        for st in v.strokes:
            painter.setPen(_pen(st.style, lw, s, ink))
            pts = [p.to_page(x, y) for x, y in st.pts]
            painter.drawPath(_path([(x * s, y * s) for x, y in pts], st.closed))
        for f in v.fills:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(ink))
            pts = [p.to_page(x, y) for x, y in f.pts]
            painter.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        for t in v.texts:
            x, y = p.to_page(t.x, t.y)
            _draw_text(painter, x * s, y * s, t, t.size * p.scale, s, style, t.angle)


# ------------------------------------------------------------------ drivers

def render_png(sheet: Sheet, dpi: float = 150.0, line_weight_mm: float = 0.35,
               style: RenderStyle | None = None) -> QImage:
    """The sheet as an image, for tests and for a thumbnail."""
    style = _style_of(line_weight_mm, style)
    s = dpi / 25.4
    img = QImage(int(round(sheet.width * s)), int(round(sheet.height * s)),
                 QImage.Format.Format_RGB32)
    img.fill(style.paper)
    painter = QPainter(img)
    try:
        paint_sheet(painter, s, sheet, style=style)
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


def export_pdf(path, sheets: list, line_weight_mm: float = 0.35, dpi: int = 600,
               style: RenderStyle | None = None) -> None:
    """Every sheet to one PDF, each on its own page at its own size."""
    from PySide6.QtGui import QPdfWriter

    style = _style_of(line_weight_mm, style)
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
            paint_sheet(painter, s, sheet, style=style)
    finally:
        painter.end()


def export_svg(path, sheet: Sheet, line_weight_mm: float = 0.35, dpi: float = 600.0,
               style: RenderStyle | None = None) -> None:
    """One sheet to one SVG, sized in millimeters. Drawn at the PDF's
    resolution, so the pens keep their weights (a 96 dpi device floors
    every pen at 0.6 px, which is 0.16 mm, and the thin pens with it) and
    the text sizes are not rounded to whole pixels. The font family is
    named with a generic fallback, for a viewer without it."""
    from PySide6.QtCore import QRect, QSize
    from PySide6.QtSvg import QSvgGenerator

    style = _style_of(line_weight_mm, style)
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
        paint_sheet(painter, s, sheet, style=style)
    finally:
        painter.end()
    _svg_font_fallback(path)


def _svg_font_fallback(path: Path) -> None:
    """QSvgGenerator names the family alone; a viewer without it falls to
    its own default, usually a serif. Append the generic sans."""
    import re
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    fixed = re.sub(r'font-family="([^",]*)"', r'font-family="\1, sans-serif"', text)
    if fixed != text:
        try:
            path.write_text(fixed, encoding="utf-8")
        except OSError:
            pass


def print_sheets(printer, sheets: list, line_weight_mm: float = 0.35,
                 style: RenderStyle | None = None) -> int:
    """Every sheet to a QPrinter (a printer or a PDF); returns the pages."""
    from PySide6.QtPrintSupport import QPrinter

    style = _style_of(line_weight_mm, style)
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
            paint_sheet(painter, s, sheet, style=style)
            painter.restore()
    finally:
        painter.end()
    return len(sheets)
