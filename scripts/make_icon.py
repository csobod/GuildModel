"""Regenerate src/guildcam/assets/icon.ico from icon.svg (multi-resolution).

Run by the release script before freezing so the bundled .ico always matches the
source SVG. Renders the SVG with Qt (QSvgRenderer) at every Windows icon size and
packs them into one .ico with Pillow.
"""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "src" / "guildcam" / "assets"
SVG = ASSETS / "icon.svg"
ICO = ASSETS / "icon.ico"
SIZES = [256, 128, 64, 48, 32, 24, 16]


def _render(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    return img


def main() -> None:
    # A QGuiApplication is needed for QImage/QPainter off-screen.
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SVG))
    tmp = ASSETS / "_iconcache"
    tmp.mkdir(exist_ok=True)
    frames = []
    for sz in SIZES:
        fp = tmp / f"{sz}.png"
        _render(renderer, sz).save(str(fp))
        frames.append(Image.open(fp).convert("RGBA"))
    frames[0].save(str(ICO), format="ICO", sizes=[(s, s) for s in SIZES],
                   append_images=frames[1:])
    for fp in tmp.glob("*.png"):
        fp.unlink()
    tmp.rmdir()
    print(f"wrote {ICO} ({ICO.stat().st_size} bytes; sizes {SIZES})")
    del app


if __name__ == "__main__":
    main()
