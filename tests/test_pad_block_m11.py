"""Stock pad-block toggle (BUILDPLAN M11): off ⇒ a single flat blank."""
import numpy as np

from guildmodel.core.project.schema import StockDefinition
from guildmodel.core.relief.castle import stock_top_heightfield


def test_total_pad_height_drops_the_pad_when_off():
    on = StockDefinition(blank_thickness_mm=6.0, pad_block_thickness_mm=4.0)
    off = StockDefinition(blank_thickness_mm=6.0, pad_block_thickness_mm=4.0,
                          use_pad_block=False)
    assert on.total_pad_height_mm == 10.0          # blank + pad
    assert off.total_pad_height_mm == 6.0           # blank only


def test_stock_top_is_flat_when_pad_block_off():
    on = stock_top_heightfield(StockDefinition())
    off = stock_top_heightfield(StockDefinition(use_pad_block=False))
    assert on.z.std() > 0.0                          # two-level (raised pad region)
    assert off.z.std() == 0.0                        # single flat blank surface
    assert np.allclose(off.z, StockDefinition().blank_thickness_mm)


def test_default_is_pad_block_on():
    assert StockDefinition().use_pad_block is True   # back-compat: existing projects
