"""Render src/guildmodel/assets/icon.svg into a Windows .ico + macOS .icns.

Build-time helper (no Pillow dependency — uses the Qt that GuildModel already
ships with). Renders the SVG at the standard icon sizes and assembles a
PNG-compressed .ico (Vista+ reads PNG entries natively) and a PNG-based
.icns (macOS 10.7+ reads PNG entries natively).

    .venv\\Scripts\\python scripts\\make_icon.py      # Windows
    .venv/bin/python scripts/make_icon.py             # macOS / Linux

Writes src/guildmodel/assets/icon.ico and icon.icns. The release scripts run
this before freezing so the bundled icons always match the source SVG
(guildmodel.spec embeds the .ico on Windows and the .icns in the macOS BUNDLE).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "src" / "guildmodel" / "assets"

SIZES = [512, 256, 128, 64, 48, 32, 24, 16]
ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]      # .ico caps at 256


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    # ICONDIR header: reserved=0, type=1 (icon), count
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = bytearray()
    image_data = bytearray()
    offset = 6 + 16 * len(pngs)  # past header + all dir entries
    for size, png in pngs:
        dim = 0 if size >= 256 else size  # 0 encodes 256
        entries += struct.pack(
            "<BBBBHHII",
            dim,            # width
            dim,            # height
            0,              # palette count
            0,              # reserved
            1,              # color planes
            32,             # bits per pixel
            len(png),       # bytes of image data
            offset,         # offset to image data
        )
        image_data += png
        offset += len(png)
    return bytes(header) + bytes(entries) + bytes(image_data)


# ICNS entry types that carry raw PNG data, by pixel size. The @2x retina
# types (ic11-ic14) are the same pixels served for point-size-at-2x; macOS
# picks per display. All PNG-bearing types work from macOS 10.7.
_ICNS_TYPES = [
    (b"icp4", 16),
    (b"icp5", 32),
    (b"ic11", 32),    # 16pt @2x
    (b"icp6", 64),
    (b"ic12", 64),    # 32pt @2x
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic13", 256),   # 128pt @2x
    (b"ic09", 512),
    (b"ic14", 512),   # 256pt @2x
]


def build_icns(pngs_by_size: dict[int, bytes]) -> bytes:
    body = bytearray()
    for fourcc, size in _ICNS_TYPES:
        png = pngs_by_size.get(size)
        if png is None:
            continue
        body += fourcc + struct.pack(">I", 8 + len(png)) + png
    return b"icns" + struct.pack(">I", 8 + len(body)) + bytes(body)


def main() -> int:
    svg_path = ASSETS / "icon.svg"
    ico_path = ASSETS / "icon.ico"
    icns_path = ASSETS / "icon.icns"
    if not svg_path.exists():
        print(f"missing {svg_path}", file=sys.stderr)
        return 1

    # A QGuiApplication is required before any QImage/QPainter work.
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        print(f"invalid SVG: {svg_path}", file=sys.stderr)
        return 1

    pngs_by_size = {size: render_png(renderer, size) for size in SIZES}

    ico_path.write_bytes(build_ico([(s, pngs_by_size[s]) for s in ICO_SIZES]))
    print(f"wrote {ico_path} ({ico_path.stat().st_size} bytes, "
          f"{len(ICO_SIZES)} sizes)")

    icns_path.write_bytes(build_icns(pngs_by_size))
    print(f"wrote {icns_path} ({icns_path.stat().st_size} bytes, "
          f"{len(_ICNS_TYPES)} entries)")
    del app  # noqa: F841 — keep the app alive until rendering is done
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
