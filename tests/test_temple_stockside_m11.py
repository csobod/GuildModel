"""Temple stock-side alignment (BUILDPLAN M11): choose which end of the blank the
hinge registers to. Flipping rotates the temple 180° in-plane (hinge pocket stays
up) so the body always runs inward from the chosen end."""
from shapely.geometry import Polygon

from guildmodel.core.relief.flat import place_temple_on_blank


def _temple():
    outline = Polygon([(-60, -6), (60, -6), (60, 6), (-60, 6)])   # long axis x
    hinge = [Polygon([(50, -5), (58, -5), (58, 5), (50, 5)])]      # hinge at the +x end
    eng = [[(-40.0, 0.0), (40.0, 0.0)]]
    return outline, hinge, eng


def test_right_butts_hinge_to_plus_x_end():
    o, h, _e = place_temple_on_blank(*_temple(), 170.0, stock_side="right")
    assert h[0].centroid.x > 0                 # hinge at the +x (right) end
    assert o.bounds[2] <= 85 + 1e-6            # body stays within the ±85 blank


def test_left_flips_hinge_to_minus_x_end():
    o, h, e = place_temple_on_blank(*_temple(), 170.0, stock_side="left")
    assert h[0].centroid.x < 0                 # hinge flipped to the -x (left) end
    assert o.bounds[0] >= -85 - 1e-6           # body runs inward — no overhang
    assert any(x < 0 for c in e for x, _y in c)   # engraving moved with the part


def test_no_snap_leaves_geometry_unplaced():
    outline, hinge, eng = _temple()
    o, _h, _e = place_temple_on_blank(outline, hinge, eng, 170.0,
                                      stock_side="left", snap=False)
    assert o.bounds == outline.bounds          # untouched when not snapping
