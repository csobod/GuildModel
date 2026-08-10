"""Dragging a handle has to reach the 3D view (BUILDPLAN-NEW M-N4).

Two things stood between a slider and a live preview, and only one of them was
about sliders.

**The window threw rebuild requests away.** `_start_mesh_build` returned early
whenever a build was already running, and nothing ever looked again — the
finished handler has no notion of a pending request. So a parameter changed
during a build was lost from the preview until something *else* happened to
trigger one. With a spin box and a 350 ms debounce that was rare enough to go
unnoticed for a season. With a handle emitting on every pixel it is the normal
case, and the view would sit on whatever shape happened to win the race.

**And the debounce is the wrong instrument for a drag.** 350 ms of stillness
before starting means a drag shows nothing until it stops. The pacing a drag
wants is the build itself: start one, and when it lands, start another if the
handle has moved since. That paces exactly at the kernel's rate, cannot
livelock, and needs no interval to tune.

Measured on the demo, one full mesh rebuild: 221 ms bare, 603 ms with every
posterior feature on, 674 ms with the lens groove too — essentially all of it
`build_castle_model` (`to_trimesh` is 1 ms, edge detection 12-18 ms). So a drag
redraws two to five times a second, not sixty. BUILDPLAN-NEW's "39 ms full
build" predates most of those features and is not the number any more.
"""
import pytest

pytest.importorskip("PySide6.QtWidgets")


class _Thread:
    def __init__(self, running):
        self._running = running

    def isRunning(self):        # noqa: N802  (Qt spelling)
        return self._running


def _window(*, busy=False, page=1, ready=True):
    """A `MainWindow` with only the attributes the rebuild bookkeeping reads.

    `MainWindow.__new__` rather than a real one, following
    `test_model_kernel_mn2`: none of this touches a widget, and constructing the
    whole window to check a boolean would make the gate slow enough to skip.
    """
    from guildmodel.gui.app import MainWindow

    w = MainWindow.__new__(MainWindow)
    w._mesh_thread = _Thread(busy)
    w._rebuild_pending = False
    w._live_preview = False
    w._stage_cache = {}
    w._edge_cache = {}
    w._castle_ready = lambda: ready

    class _Stack:
        def currentIndex(self):     # noqa: N802
            return page
    w.stack = _Stack()
    return w


# ------------------------------------------------------- coalescing the work

def test_a_request_during_a_build_is_remembered_not_dropped():
    """The defect. Before this, the change simply never reached the view."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=True)
    MainWindow._start_mesh_build(w)
    assert w._rebuild_pending is True


def test_the_remembered_request_runs_when_the_build_lands():
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._rebuild_pending = True
    started = []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)

    MainWindow._drain_pending_rebuild(w)

    assert started == [False], "the pending rebuild never ran"
    assert w._rebuild_pending is False, "and it must not run twice"


def test_only_one_rebuild_is_owed_however_many_were_asked_for():
    """Latest-wins. A hundred pixels of drag is one more build, not a hundred —
    the worker snapshots the live parameters when it starts, so the queue never
    needs to be longer than one."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=True)
    for _ in range(100):
        MainWindow._start_mesh_build(w)
    assert w._rebuild_pending is True

    w._mesh_thread = _Thread(False)
    started = []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)
    MainWindow._drain_pending_rebuild(w)
    MainWindow._drain_pending_rebuild(w)
    assert started == [False]


def test_nothing_is_rebuilt_for_a_view_the_maker_is_not_looking_at():
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False, page=0)
    w._rebuild_pending = True
    started = []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)

    MainWindow._drain_pending_rebuild(w)

    assert started == []
    assert w._rebuild_pending is False


def test_a_cancelled_build_drops_what_was_owed():
    """Cancel is the one case where the maker has said they do not want this.
    Draining there would start the next build immediately and make the button
    look broken."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._rebuild_pending = True
    started = []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)
    w._close_progress = lambda: None
    w.append_log = lambda _t: None
    w.status_lbl = type("L", (), {"setText": lambda self, t: None})()
    w._act_build = type("A", (), {"setEnabled": lambda self, on: None})()

    MainWindow._on_mesh_cancelled(w)

    assert started == []
    assert w._rebuild_pending is False


def test_a_failed_build_still_lets_the_next_one_run():
    """The parameters have moved on since the build that failed, and the state
    they moved to may well build. Leaving the flag set would also wedge every
    later rebuild behind one bad one."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._rebuild_pending = True
    started = []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)
    w._close_progress = lambda: None
    w.append_log = lambda _t: None
    w.status_lbl = type("L", (), {"setText": lambda self, t: None})()
    w._act_build = type("A", (), {"setEnabled": lambda self, on: None})()

    MainWindow._on_mesh_error(w, "boom")

    assert started == [False]


# ------------------------------------------------------------ the drag path

def test_a_moving_handle_does_not_wait_for_the_debounce():
    """`_rebuild_timer` exists so a spin box being typed into does not queue a
    build per digit. A handle is the opposite case: it is already continuous,
    and the in-flight guard paces it."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    started, timed = [], []
    w._start_mesh_build = lambda show_progress=False: started.append(show_progress)

    class _Timer:
        def start(self):
            timed.append(True)
    w._rebuild_timer = _Timer()

    MainWindow._on_castle_sliding(w)

    assert started == [False], "a drag must start the build itself"
    assert timed == [], "and must not go through the debounce"


def test_a_drag_does_not_touch_the_program_or_the_readiness_dot():
    """Those belong to the settled value. Invalidating a stored program on every
    pixel would drop the readiness light to yellow over and over while the maker
    is still deciding what the number should be."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._start_mesh_build = lambda show_progress=False: None
    touched = []
    w._invalidate_program = lambda: touched.append("program")
    w._refresh_readiness = lambda: touched.append("readiness")

    MainWindow._on_castle_sliding(w)

    assert touched == []


def test_the_settled_value_still_does_everything_it_did():
    """The commit path is unchanged: caches dropped, program invalidated, and
    the rebuild debounced as before."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._stage_cache = {"pockets": object()}
    w._edge_cache = {"pockets": object()}
    touched, timed = [], []
    w._invalidate_program = lambda: touched.append("program")

    class _Timer:
        def start(self):
            timed.append(True)
    w._rebuild_timer = _Timer()

    MainWindow._on_castle_params_changed(w)

    assert w._stage_cache == {} and w._edge_cache == {}
    assert touched == ["program"]
    assert timed == [True]


def test_the_log_records_builds_again_once_the_handle_is_let_go():
    """A drag silences the per-build log lines — one to five a second would bury
    everything else. The settled value that ends the drag turns them back on,
    so the next real build is recorded."""
    from guildmodel.gui.app import MainWindow

    w = _window(busy=False)
    w._invalidate_program = lambda: None
    w._rebuild_timer = type("T", (), {"start": lambda self: None})()
    w._start_mesh_build = lambda show_progress=False: None

    MainWindow._on_castle_sliding(w)
    assert w._live_preview is True

    MainWindow._on_castle_params_changed(w)
    assert w._live_preview is False


# ------------------------------------------------------------- the panel end

#: One control from each group on the Model tab. Named rather than discovered,
#: so this says what has to be live instead of restating how the connection is
#: made — a walk compared against a walk would pass with nothing connected.
_LIVE_CONTROLS = ("zone_endpiece", "zone_bridge", "zone_nosepad",
                  "zone_eyewire_superior", "zone_eyewire_inferior",
                  "hinge_pocket_depth", "splay_run", "splay_angle_center",
                  "bezel_width", "bezel_angle", "bridge_relief_width",
                  "bridge_relief_depth", "groove_offset", "groove_depth",
                  "groove_width", "ef_width", "ef_angle", "ef_radius")


def test_every_model_handle_reports_while_it_moves():
    """`ParamsPanel.castle_sliding` is the one signal the window connects; a
    handle that does not feed it drags dead."""
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    QApplication.instance() or QApplication([])
    panel = ParamsPanel()
    seen = []
    panel.castle_sliding.connect(lambda: seen.append(True))

    for name in _LIVE_CONTROLS:
        handle = getattr(panel, name)
        seen.clear()
        handle.sliding.emit(handle.value())
        assert seen, f"{name} does not report while dragging"


def test_a_control_added_to_the_model_tab_later_is_live_too():
    """The connection walks the tab rather than a list, so this holds without
    anyone remembering to update it. Pinned because the alternative failure —
    one slider that drags dead — reads as a broken widget, not a missed wire."""
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.widgets.param_slider import ParamSlider
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    QApplication.instance() or QApplication([])
    panel = ParamsPanel()
    live = 0
    for handle in panel.widget(panel._tab_castle).findChildren(ParamSlider):
        seen = []
        panel.castle_sliding.connect(lambda: seen.append(True))
        handle.sliding.emit(handle.value())
        panel.castle_sliding.disconnect()
        live += bool(seen)

    total = len(panel.widget(panel._tab_castle).findChildren(ParamSlider))
    assert live == total > 0


def test_the_real_window_is_actually_listening(tmp_path, monkeypatch):
    """Everything above tests the two ends. This tests the wire.

    A signal the panel emits and the window never connects would pass every
    other gate in this file and drag dead in the application, which is the exact
    shape of the defect being fixed here.
    """
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    try:
        started = []
        win._start_mesh_build = lambda show_progress=False: started.append(True)
        win._castle_ready = lambda: True

        win.params.zone_nosepad.sliding.emit(8.0)

        assert win._live_preview is True, "the window did not see the drag"
        # It only builds when the 3D page is showing; either way the handler ran.
        assert started or win.stack.currentIndex() != 1
    finally:
        win.close()


def test_the_stock_tab_does_not_rebuild_the_model_while_dragging():
    """Stock changes the ghost box around the part, not the part. Feeding it
    into the model rebuild would make dragging a blank dimension the most
    expensive thing in the panel."""
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    QApplication.instance() or QApplication([])
    panel = ParamsPanel()
    seen = []
    panel.castle_sliding.connect(lambda: seen.append(True))

    panel.blank_length.sliding.emit(120.0)
    assert seen == []
