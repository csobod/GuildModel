"""Render GuildDraw engraving *text objects* to ENGRAVING polylines (GUI-side).

A GuildDraw ``.gdraw`` stores engraving as a TEXT OBJECT — a string plus font,
cap-height ``size_mm``, anchor and rotation — in ``state["texts"]``, NOT as outlined
curves. The Qt-free core reader (:mod:`guildmodel.core.io_import.gdraw`) therefore can't
produce geometry for it, so engraving was invisible/unmachined on import. Font outlining
needs a font engine (Qt), so it lives here.

This reproduces GuildDraw's own ``framedraft/textpath.text_outline_path`` exactly
(``QPainterPath.addText`` at a fixed pixel size, then scaled by the measured cap height,
with the y-down rotation convention) — the same outlining GuildDraw's DXF export uses,
so a ``.gdraw`` engraving and the equivalent DXF import yield the same glyphs. It then
applies the reader's scene→posterior flip ``(x, y) → (-x, -y)`` so the glyphs share the
temple's coordinate frame — landing on the interior (hinge-pocket) face, aligned with
the outline and hinge, exactly where the temple relief/G-code already cut engraving.

Needs a running ``QGuiApplication`` (always true inside the app).
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTransform

Point = tuple[float, float]

# Build glyphs at this pixel size, then scale to mm — matches GuildDraw's textpath so
# flattening stays fine (Qt's default flatness is ~0.25 px here ⇒ ~0.004 mm at 3.8 mm).
_BASE_PX = 256.0


def _text_polylines(t: dict) -> list[list[Point]]:
    """Flattened glyph-outline polylines (scene mm) for one GuildDraw text object.

    Mirrors ``framedraft.textpath.text_outline_path``: ``size_mm`` is the CAP HEIGHT,
    so the path is built at a fixed pixel size and rescaled by the font's measured cap
    height; rotation is CCW-as-displayed (negative Qt angle in the y-down scene)."""
    text = str(t.get("text", ""))
    if not text.strip():
        return []
    size_mm = float(t.get("size_mm", 0.0) or 0.0)
    if size_mm <= 0.0:
        return []

    font = QFont(str(t.get("family", "") or ""))
    font.setPixelSize(int(_BASE_PX))
    cap = QFontMetricsF(font).capHeight()
    if cap <= 0:
        cap = QFontMetricsF(font).ascent() or _BASE_PX

    path = QPainterPath()
    path.addText(0.0, 0.0, font, text)          # baseline-left at the origin

    xf = QTransform()
    xf.translate(float(t.get("anchor_x", 0.0) or 0.0),
                 float(t.get("anchor_y", 0.0) or 0.0))
    rot = float(t.get("rotation", 0.0) or 0.0)
    if rot:
        xf.rotate(-rot)                          # scene is y-down: CCW display = -Qt angle
    xf.scale(size_mm / cap, size_mm / cap)

    out: list[list[Point]] = []
    for poly in path.toSubpathPolygons():        # flatten at 256 px (fine), then map to mm
        pts = [(p.x(), p.y()) for p in (xf.map(v) for v in poly)]
        if len(pts) >= 2:
            out.append(pts)
    return out


def engraving_polylines_from_texts(
    texts, *, layer: str = "ENGRAVING", posterior: bool = True,
) -> list[list[Point]]:
    """ENGRAVING-layer polylines for a workspace's GuildDraw text objects.

    Outlines each text object on ``layer`` (GuildDraw's engraving convention) and, when
    ``posterior``, applies the reader's scene→posterior flip so the glyphs align with the
    temple's other (already-flipped) layers. Raises if no ``QGuiApplication`` exists."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        raise RuntimeError("engraving text outlining needs a running QGuiApplication")

    out: list[list[Point]] = []
    for t in texts or ():
        if not isinstance(t, dict) or t.get("layer") != layer:
            continue
        for poly in _text_polylines(t):
            out.append([(-x, -y) for x, y in poly] if posterior else poly)
    return out
