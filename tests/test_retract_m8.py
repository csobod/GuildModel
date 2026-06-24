"""M8 prep — single-part rapids retract above the work-holding, not just the stock.

A frame-front-only program must clear the hold-down screws/clamps during travels,
the same way the bed program does. `CastleCamParams.safe_z_for` raises the retract to
the taller of the stock and the work-holding height; the post emits it on every rapid.
"""
from guildcam.core.project.schema import CastleCamParams
from guildcam.core.post.grbl import GRBLPost


def test_safe_z_default_is_back_compatible():
    cam = CastleCamParams()                      # hold_down 0, clearance 5
    assert cam.hold_down_height_mm == 0.0
    assert cam.safe_z_for(6.0) == 6.0 + cam.safe_z_clearance_mm   # stock + clearance


def test_safe_z_clears_a_taller_holddown():
    cam = CastleCamParams(hold_down_height_mm=12.0)               # screws 12 mm proud
    assert cam.safe_z_for(6.0) == 17.0                            # max(6, 12) + 5


def test_safe_z_uses_stock_when_it_is_taller():
    cam = CastleCamParams(hold_down_height_mm=4.0)
    assert cam.safe_z_for(8.0) == 13.0                           # max(8, 4) + 5


def test_safe_z_respects_clearance_margin():
    cam = CastleCamParams(hold_down_height_mm=10.0, safe_z_clearance_mm=8.0)
    assert cam.safe_z_for(6.0) == 18.0                           # 10 + 8


def test_posted_rapids_clear_the_holddown_end_to_end():
    cam = CastleCamParams(hold_down_height_mm=12.0)
    post = GRBLPost(
        job_name="t", material="acetate", tool_diameter_mm=3.0,
        spindle_rpm=10000, feed_rate_mmpm=1000, plunge_rate_mmpm=300,
        safe_z_mm=cam.safe_z_for(6.0))
    post.safe_retract()
    text = post.to_string()
    # every retract rides above the 12 mm screws (12 + 5 clearance)
    assert "G0 Z17.000" in text
    # and the old stock-only height (6 + 5 = 11) would NOT have cleared them
    assert "G0 Z11.000" not in text
