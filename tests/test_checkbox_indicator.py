"""Checkboxes are drawn by the stylesheet in both modes (2026-09-29): the
platform's box took its outline from the chrome background, and on the dark
chrome an unchecked box all but vanished. GuildDraw carries the same rules."""
import re

from guildmodel.gui.style import theme


def test_both_modes_draw_their_own_box_and_tick():
    for dark in (False, True):
        qss = theme.stylesheet(dark)
        assert "QCheckBox::indicator" in qss and "QAbstractItemView::indicator" in qss
        [tick] = re.findall(r'image: url\("([^"]+)"\)', qss)
        assert tick.endswith("check-dark.svg" if dark else "check-light.svg")
        assert theme.Path(tick).is_file()


def test_the_unchecked_box_stands_out_on_the_dark_chrome():
    border = theme._INDICATOR_COLORS[True]["border"]

    def lum(hex_):
        def ch(v):
            v = int(v, 16) / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(hex_[i:i + 2]) for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    ratio = (lum(border) + 0.05) / (lum("#1a1a1a") + 0.05)
    assert ratio > 4.5


def test_the_box_scales_with_the_ui():
    assert "width: 21px" in theme.stylesheet(False, 1.5)
