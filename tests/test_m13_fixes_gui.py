"""M13 fixes: the 3D camera must survive a same-part rebuild.

Every Castle-tab spinbox tick rebuilds the mesh; `show_mesh` used to reset the
camera each time, zooming the maker out mid-fine-tune. `Viewer3D._keep_camera`
now preserves the camera when the new scene covers roughly the last footprint
(param edit / stage step / re-sim) and still resets on the first show or a
different part (component-tab switch).
"""


def _viewer():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.viewer_3d import Viewer3D
    return Viewer3D()


def test_camera_kept_across_same_part_rebuilds():
    v = _viewer()
    frame = (-70.0, 70.0, -30.0, 30.0)
    assert v._keep_camera(frame) is False          # first show -> reset
    assert v._keep_camera(frame) is True           # identical rebuild -> keep
    nudged = (-70.0, 70.0, -30.0, 31.5)            # a zone-height tweak
    assert v._keep_camera(nudged) is True


def test_camera_resets_on_a_different_part_or_fresh_context():
    v = _viewer()
    frame = (-70.0, 70.0, -30.0, 30.0)
    temple = (0.0, 170.0, -15.0, 15.0)             # temple blank footprint
    v._keep_camera(frame)
    assert v._keep_camera(temple) is False         # different part -> reset
    assert v._keep_camera(temple) is True          # then stable again
    v._scene_bounds = None                         # fresh GL context
    assert v._keep_camera(temple) is False
