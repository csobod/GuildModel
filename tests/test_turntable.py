"""The 3D viewer's turntable (2026-08-12).

Requested as "a turntable rotation of the frame in its current view around its
center point as the axis of motion", with a speed slider beside it and a hotkey.

What is worth pinning here is not that a timer exists but the things that make it
behave like a control rather than a toy:

* **the step moves the camera.** Added after the first version shipped without
  it: `pyvista.Camera.azimuth` is a *property*, not a method, so `azimuth(1.2)`
  raised `TypeError` on every tick, `_turn_step`'s guard swallowed it, and the
  symptom was a button that toggled while nothing moved. Everything else in this
  file passed throughout — those tests never reached the camera, because
  `_plotter` was None and the step returned at its first line. A stub plotter
  carrying a **real** `pyvista.Camera` closes that gap headlessly;
* **it spins in the maker's current view.** `Azimuth` turns the camera about its
  own view-up vector through the focal point, so tipping the part first changes
  the axis — a spin about world Z would ignore the view it was started from;
* **the spin is relative.** `Camera.azimuth`'s setter rewinds its own previous
  value before applying the new one, so driving a continuous spin through the
  property would undo whatever the maker had just done with the mouse;
* **it parks itself off screen.** An animating hidden viewport renders into a
  zero-size buffer, which is the same incomplete-framebuffer noise the playback
  timer is stopped for. The *choice* survives the trip, though: a look at the 2D
  outline and back must not cost a click;
* **one state, two ways in.** The viewer's own button and the Alt+T action have
  to agree without echoing each other into a loop;
* **the hotkey reaches the action.** Added after the *second* thing that shipped
  broken: a `QAction` fires its shortcut only while it belongs to a widget in the
  active window, and parenting it to the window is not that. Every other action
  in the app got it by sitting in a menu; this one lives on the viewer's own
  strip, so it was in no widget at all and Alt+T did nothing — nor did rebinding
  it in Preferences, which is how the maker found it. Asserting the shortcut
  *string*, which is all this file did, cannot see that: the binding was correct
  and unreachable. `_build_action_registry` now claims every registered action on
  the window, so being rebindable and being reachable are one fact.

No VTK render window is created anywhere here, so it all runs headless.
"""
import numpy as np
import pytest


def _viewer():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.viewer_3d import Viewer3D
    return Viewer3D()


def test_the_button_arms_the_timer_and_releasing_it_stops():
    v = _viewer()
    v.show()
    assert v.turntable_active() is False
    assert v._turn_timer.isActive() is False

    v.set_turntable(True)
    assert v.turntable_active() is True
    assert v._turn_btn.isChecked() is True
    assert v._turn_timer.isActive() is True

    v.toggle_turntable()
    assert v.turntable_active() is False
    assert v._turn_timer.isActive() is False


def test_clicking_the_button_and_calling_the_api_are_the_same_state():
    """`set_turntable` re-enters through the toggle rather than shadowing it, so
    the button is the single source of truth and cannot drift from the action."""
    v = _viewer()
    v.show()
    v._turn_btn.setChecked(True)                 # as a click would
    assert v.turntable_active() is True
    assert v._turn_timer.isActive() is True

    v.set_turntable(True)                        # idempotent
    assert v._turn_timer.isActive() is True

    v.set_turntable(False)
    assert v._turn_btn.isChecked() is False


def test_it_parks_off_screen_and_picks_itself_up_again():
    """Hidden means stopped, not cancelled."""
    v = _viewer()
    v.show()
    v.set_turntable(True)
    assert v._turn_timer.isActive() is True

    v.hide()
    assert v._turn_timer.isActive() is False, "spinning into a hidden buffer"
    assert v.turntable_active() is True, "the maker's choice was thrown away"

    v.show()
    assert v._turn_timer.isActive() is True


def test_a_step_with_no_plotter_is_a_no_op():
    """The timer can outlive the render window by a beat; a spinning camera must
    never be a way for the app to go down."""
    v = _viewer()
    v.set_turntable(True)
    assert v._plotter is None
    v._turn_step()                                # must not raise


# ------------------------------------------------------------- the step itself

class _StubPlotter:
    """Just enough plotter for `_turn_step`: a real camera and a render count.

    A real `pyvista.Camera` and no render window, so this runs headless — which
    matters, because the whole of the rest of this file passed while the step
    was raising `TypeError` on every tick. Those tests never reached the camera:
    `_plotter` was None and `_turn_step` returned at the first line.
    """

    def __init__(self):
        import pyvista as pv
        self.camera = pv.Camera()
        self.renders = 0

    def render(self):
        self.renders += 1


def _spun(v, steps, position, focal, up):
    """Drive `_turn_step` `steps` times from a known camera pose."""
    stub = _StubPlotter()
    stub.camera.position = position
    stub.camera.focal_point = focal
    stub.camera.up = up
    v._plotter = stub
    for _ in range(steps):
        v._turn_step()
    return stub


def test_a_step_actually_moves_the_camera():
    """The regression this file did not have. `pyvista.Camera.azimuth` is a
    *property*, not a method — calling it raised on every tick, `_turn_step`
    swallowed the error and stopped the timer, and the symptom was a button that
    toggled while nothing moved."""
    v = _viewer()
    v.show()
    v.set_turntable_speed(30)                     # 1.2 deg per 40 ms step
    v.set_turntable(True)

    stub = _spun(v, 1, (0.0, -10.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    pos = np.asarray(stub.camera.position)

    assert not np.allclose(pos, (0.0, -10.0, 0.0)), "the camera never moved"
    assert v._turn_timer.isActive(), "the step stopped its own timer — it raised"
    # A rotation: same distance from the focal point, and about the up axis, so
    # the height above the focal plane is untouched.
    assert np.linalg.norm(pos) == pytest.approx(10.0, abs=1e-6)
    assert pos[2] == pytest.approx(0.0, abs=1e-9)
    # And by the angle the slider asked for.
    assert np.degrees(np.arctan2(pos[0], -pos[1])) == pytest.approx(1.2, abs=1e-6)


def test_a_tipped_camera_orbits_instead_of_tumbling():
    """The second bug the stub alone could not see, and the reason this test
    tips the camera.

    `OrthogonalizeViewUp` per step reads like cheap insurance against a drifting
    up vector. `Azimuth` preserves the angle between the view direction and the
    up vector, so there is nothing to guard — and squaring the up vector to the
    view direction *first* re-aims the axis every step, so the camera walks off
    its own elevation. From (0, -120, 90) over a 90-degree sweep it ended at
    height **4.8** having swept 90.2 degrees. The distance to the focal point was
    exact throughout, which is why a square-on camera shows nothing.
    """
    v = _viewer()
    v.show()
    v.set_turntable_speed(30)
    v.set_turntable(True)

    stub = _spun(v, 75, (0.0, -120.0, 90.0), (0.0, 0.0, 3.0), (0.0, 0.0, 1.0))
    pos = np.asarray(stub.camera.position)
    focal = np.asarray(stub.camera.focal_point)

    assert np.allclose(focal, (0.0, 0.0, 3.0)), "the turntable moved its own centre"
    assert pos[2] == pytest.approx(90.0, abs=1e-6), "the camera left its elevation"
    assert np.linalg.norm(pos - focal) == pytest.approx(
        np.linalg.norm(np.array([0.0, -120.0, 90.0]) - focal), abs=1e-6)
    # A quarter turn in plan, to the degree the slider asked for.
    assert np.degrees(np.arctan2(pos[0], -pos[1])) == pytest.approx(90.0, abs=1e-4)


def test_it_turns_about_the_view_up_axis_not_world_z():
    """The behavioural claim: "around its center point as the axis of motion",
    in the view the maker set up. Tip the camera and the axis tips with it."""
    v = _viewer()
    v.show()
    v.set_turntable_speed(30)
    v.set_turntable(True)

    # Up = world Y instead of Z: the spin now happens in the XZ plane, so it is
    # the Y coordinate that stays put rather than the Z one.
    stub = _spun(v, 5, (0.0, 0.0, -10.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    pos = np.asarray(stub.camera.position)
    assert pos[1] == pytest.approx(0.0, abs=1e-9)
    assert abs(pos[0]) > 1e-3, "nothing turned about the tipped axis"
    assert np.linalg.norm(pos) == pytest.approx(10.0, abs=1e-6)


def test_the_spin_is_relative_so_it_composes_with_a_drag():
    """`Camera.azimuth`'s setter rewinds its own previous value before applying
    the new one, so a continuous spin driven through the property would undo
    whatever the maker had just done with the mouse. `Azimuth(delta)` does not.
    Checked by moving the camera mid-spin and confirming the next step carries on
    from where it was put."""
    v = _viewer()
    v.show()
    v.set_turntable_speed(30)
    v.set_turntable(True)

    stub = _spun(v, 3, (0.0, -10.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    stub.camera.position = (10.0, 0.0, 0.0)       # as a drag would
    v._turn_step()
    pos = np.asarray(stub.camera.position)

    # One more step *from the dragged pose*: 1.2 deg on from +x, not 4.8 on from
    # -y, and certainly not back to where the spin had got to.
    assert np.linalg.norm(pos) == pytest.approx(10.0, abs=1e-6)
    assert np.degrees(np.arctan2(pos[1], pos[0])) == pytest.approx(1.2, abs=1e-6)


def test_a_step_that_raises_stops_and_says_so(capsys):
    """The guard has to stay — the plotter can go away between the timer firing
    and the step running — but it must not hide a broken step again."""
    class _Broken:
        @property
        def camera(self):
            raise RuntimeError("render window is gone")

    v = _viewer()
    v.show()
    v.set_turntable(True)
    v._plotter = _Broken()
    v._turn_step()                                 # must not raise

    assert v._turn_timer.isActive() is False
    assert v.turntable_active() is False, "a dead turntable must not look armed"
    assert "turntable stopped" in capsys.readouterr().out


def test_the_speed_slider_is_bounded_and_reads_in_degrees_per_second():
    from guildmodel.gui.widgets.viewer_3d import (TURNTABLE_DEFAULT_DEG_S,
                                                  TURNTABLE_MAX_DEG_S,
                                                  TURNTABLE_MIN_DEG_S)
    v = _viewer()
    assert v.turntable_speed() == TURNTABLE_DEFAULT_DEG_S

    v.set_turntable_speed(1000)
    assert v.turntable_speed() == TURNTABLE_MAX_DEG_S
    v.set_turntable_speed(-5)
    assert v.turntable_speed() == TURNTABLE_MIN_DEG_S
    v.set_turntable_speed(45)
    assert v.turntable_speed() == 45

    # A record deck is 200 deg/s; this is for looking at a blend, not dancing.
    assert TURNTABLE_MAX_DEG_S < 200
    assert "°/s" in v._turn_btn.toolTip()


def test_the_step_angle_follows_the_slider():
    """Angle per step is derived from the rate and the interval, so a dropped
    frame slows the spin instead of skipping part of it."""
    from guildmodel.gui.widgets.viewer_3d import TURNTABLE_INTERVAL_MS

    v = _viewer()
    v.set_turntable_speed(30)
    step = v.turntable_speed() * TURNTABLE_INTERVAL_MS / 1000.0
    assert step == pytest.approx(1.2)
    assert v._turn_timer.interval() == TURNTABLE_INTERVAL_MS
    # One full turn in a round number of seconds at the shipped default.
    assert 360.0 / v.turntable_speed() == pytest.approx(12.0)


def test_the_icon_is_present_and_conforms_to_the_style_guide():
    """A missing SVG leaves the button text-only rather than blank, which is the
    icon runtime's contract — but the icon is meant to ship, so check it does."""
    from guildmodel.gui import icons as icons_mod

    svg = icons_mod._ICONS_DIR / "view-turntable.svg"
    assert svg.exists(), "the LP icon is missing"
    src = svg.read_text(encoding="utf-8")
    assert 'viewBox="0 0 20 20"' in src
    assert 'stroke="currentColor"' in src        # recoloured per theme at runtime
    assert 'stroke-width="1.6"' in src
    assert icons_mod.themed_icon("view-turntable", False) is not None
    assert icons_mod.themed_icon("view-turntable", True) is not None


def test_the_speed_default_is_in_prefs():
    from guildmodel.gui import prefs as prefs_mod

    assert "turntable_speed" in prefs_mod.DEFAULTS
    assert prefs_mod.DEFAULTS["turntable_speed"] == 30


# --------------------------------------------------------- the main window

def _window(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import MainWindow
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


def test_alt_t_and_the_button_are_one_state(tmp_path, monkeypatch):
    """The action is created with the toolbar, which is built *before* the
    central stack — so the wiring cannot simply reference `self.view3d` at
    construction time, and neither can the saved speed. Both are checked here
    because getting either wrong is an AttributeError at startup.
    """
    win = _window(tmp_path, monkeypatch)
    assert win._act_turntable.shortcut().toString() == "Alt+T"

    win._act_turntable.setChecked(True)
    assert win.view3d.turntable_active() is True
    win.view3d._turn_btn.setChecked(False)             # as a click on the strip
    assert win._act_turntable.isChecked() is False

    # Registered for rebinding like every other hotkey (M7.15).
    assert "turntable" in win._actions_by_key
    assert any(s.key == "turntable" for s in win._action_specs)


def test_pressing_alt_t_actually_starts_it(tmp_path, monkeypatch):
    """The gate the assertion above cannot be: *press the key*.

    `shortcut().toString() == "Alt+T"` was true the whole time the feature was
    broken. What was missing is the other half — that the keystroke has an
    action to find — and the only way to see it is to send one.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    win = _window(tmp_path, monkeypatch)
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    if QApplication.activeWindow() is not win:            # pragma: no cover
        pytest.skip("this Qt platform will not activate a window")

    win._act_turntable.setEnabled(True)                   # 3D view, normally
    QTest.keyClick(win, Qt.Key_T, Qt.KeyboardModifier.AltModifier)
    QApplication.processEvents()
    assert win.view3d.turntable_active() is True, "Alt+T did not reach the action"

    QTest.keyClick(win, Qt.Key_T, Qt.KeyboardModifier.AltModifier)
    QApplication.processEvents()
    assert win.view3d.turntable_active() is False, "Alt+T does not toggle back"


def test_every_rebindable_action_can_actually_be_reached(tmp_path, monkeypatch):
    """The general form, so the next action added does not repeat this.

    An action offered in Preferences ▸ Hotkeys promises the maker that binding a
    key to it does something. That promise is only kept while the action belongs
    to a widget — so a registered action with a shortcut and no widget is a
    silently dead binding, which is exactly what shipped.
    """
    win = _window(tmp_path, monkeypatch)
    dead = [key for key, act in win._actions_by_key.items()
            if act.shortcut().toString() and not act.associatedObjects()]
    assert dead == [], f"registered but in no widget, so the hotkey cannot fire: {dead}"


def test_the_saved_speed_is_restored_and_written_back(tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    win.view3d.set_turntable_speed(17)
    win._save_window_state()
    assert win._prefs["turntable_speed"] == 17

    from guildmodel.gui import prefs as prefs_mod
    assert prefs_mod.load()["turntable_speed"] == 17
    again = _window(tmp_path, monkeypatch)
    assert again.view3d.turntable_speed() == 17
