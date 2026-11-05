"""The blueprint as a DXF for the factory's CAD (2.3): the same sheet model
`gui.draft_render` paints, written with ezdxf in model space, millimeters,
each sheet's page frame laid side by side and y up. Dimensions are written
as their lines, arrowheads and text (exploded), so any CAD reads them as
drawn; the layers follow the strokes' styles."""
from __future__ import annotations

from .sheet import Sheet

__all__ = ["write_dxf"]

LAYERS = {
    "visible": ("VISIBLE", 7, "CONTINUOUS"),
    "hidden": ("HIDDEN", 8, "DASHED"),
    "center": ("CENTER", 4, "CENTER"),
    "thin": ("THIN", 8, "CONTINUOUS"),
    "dim": ("DIM", 1, "CONTINUOUS"),
    "border": ("BORDER", 7, "CONTINUOUS"),
    "heavy": ("VISIBLE", 7, "CONTINUOUS"),
    "text": ("TEXT", 7, "CONTINUOUS"),
    "ink": ("DIM", 1, "CONTINUOUS"),
}
_SHEET_GAP_MM = 20.0


def write_dxf(path, sheets: list, font_family: str = "") -> None:
    """`font_family` names the text style's font for the CAD to map; the
    colors are the layers' own, not the sheet's."""
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4          # millimeters
    text_style = "STANDARD"
    if font_family:
        # the file name is a guess; the family in the style's extended
        # font data is what AutoCAD and BricsCAD resolve a TrueType by
        try:
            style = doc.styles.add("BLUEPRINT", font=f"{font_family}.ttf")
            try:
                style.set_extended_font_data(font_family)
            except Exception:                               # noqa: BLE001
                pass
            text_style = "BLUEPRINT"
        except Exception:                                   # noqa: BLE001
            text_style = "STANDARD"
    for name, color, ltype in sorted(set(LAYERS.values())):
        if ltype not in doc.linetypes:
            try:
                doc.linetypes.add(ltype, pattern=_PATTERNS[ltype], description=ltype)
            except Exception:                                   # noqa: BLE001
                ltype = "CONTINUOUS"
        if name not in doc.layers:
            doc.layers.add(name, color=color, linetype=ltype)
    msp = doc.modelspace()
    offset = 0.0
    for sheet in sheets:
        # page (x right, y down) -> model (x right, y up), the page's bottom-left at (offset, 0)
        def to_model(x, y, _o=offset, _h=sheet.height):
            return (_o + x, _h - y)

        _write_page(msp, sheet, to_model, text_style)
        offset += sheet.width + _SHEET_GAP_MM
    doc.saveas(str(path))


_PATTERNS = {
    "CONTINUOUS": [0.0],
    "DASHED": [3.0, 2.0, -1.0],
    "CENTER": [6.0, 4.0, -1.0, 0.5, -0.5],
}


def _layer(style: str) -> str:
    return LAYERS.get(style, LAYERS["visible"])[0]


def _write_page(msp, sheet: Sheet, to_model, text_style: str = "STANDARD") -> None:
    for s in sheet.strokes:
        pts = [to_model(x, y) for x, y in s.pts]
        msp.add_lwpolyline(pts, close=s.closed, dxfattribs={"layer": _layer(s.style)})
    for f in sheet.fills:
        pts = [to_model(x, y) for x, y in f.pts]
        if len(pts) >= 3:
            msp.add_solid(pts[:4], dxfattribs={"layer": _layer(f.style)})
    for t in sheet.texts:
        _text(msp, to_model(t.x, t.y), t, 0.0, 1.0, text_style)
    for p in sheet.placed:
        v = p.view
        for s in v.strokes:
            pts = [to_model(*p.to_page(x, y)) for x, y in s.pts]
            msp.add_lwpolyline(pts, close=s.closed, dxfattribs={"layer": _layer(s.style)})
        for f in v.fills:
            pts = [to_model(*p.to_page(x, y)) for x, y in f.pts]
            if len(pts) >= 3:
                msp.add_solid(pts[:4], dxfattribs={"layer": _layer(f.style)})
        for t in v.texts:
            _text(msp, to_model(*p.to_page(t.x, t.y)), t, t.angle, p.scale, text_style)


def _text(msp, at, t, angle: float, scale: float = 1.0, text_style: str = "STANDARD") -> None:
    height = 0.72 * t.size * scale
    align = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(t.align, "LEFT")
    # the page's own texts hang from their anchor; a view's sit on their baseline
    valign = {"top": "TOP", "middle": "MIDDLE", "baseline": "BASELINE"}.get(t.valign, "BASELINE")
    try:
        from ezdxf.enums import TextEntityAlignment
        key = f"{valign}_{align}" if valign != "BASELINE" else align
        alignment = getattr(TextEntityAlignment, key, TextEntityAlignment.LEFT)
    except Exception:                                           # noqa: BLE001
        alignment = None
    e = msp.add_text(t.text, dxfattribs={"layer": LAYERS["text"][0], "height": height,
                                         "rotation": angle, "style": text_style})
    if alignment is not None:
        e.set_placement(at, align=alignment)
    else:
        e.dxf.insert = at
