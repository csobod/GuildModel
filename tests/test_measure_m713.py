"""M7.13 — 2D measure math: distance, angle, vertex snapping."""
import math

import pytest

from guildcam.core.geometry.measure import angle_at, distance, snap_to_vertices


def test_distance_basic():
    assert distance((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)
    assert distance((1.0, 1.0), (1.0, 1.0)) == pytest.approx(0.0)


def test_distance_symmetric():
    a, b = (2.5, -1.0), (-3.0, 4.25)
    assert distance(a, b) == pytest.approx(distance(b, a))


def test_angle_right():
    # corner at the origin between the +x and +y arms = 90 degrees
    assert angle_at((1.0, 0.0), (0.0, 0.0), (0.0, 1.0)) == pytest.approx(90.0)


def test_angle_straight_and_zero():
    # collinear, vertex in the middle = 180 degrees
    assert angle_at((-1.0, 0.0), (0.0, 0.0), (1.0, 0.0)) == pytest.approx(180.0)
    # same direction = 0 degrees
    assert angle_at((1.0, 0.0), (0.0, 0.0), (2.0, 0.0)) == pytest.approx(0.0)


def test_angle_degenerate_arm():
    # a zero-length arm reads as 0, not a crash
    assert angle_at((0.0, 0.0), (0.0, 0.0), (1.0, 1.0)) == 0.0


def test_angle_in_range():
    ang = angle_at((1.0, 2.0), (0.3, -0.4), (-2.0, 1.5))
    assert 0.0 <= ang <= 180.0


def test_snap_picks_nearest_within_tol():
    verts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    # near the second vertex
    assert snap_to_vertices((10.4, 0.3), verts, tol=1.0) == (10.0, 0.0)


def test_snap_returns_none_outside_tol():
    verts = [(0.0, 0.0), (10.0, 0.0)]
    assert snap_to_vertices((5.0, 5.0), verts, tol=1.0) is None


def test_snap_empty_vertices():
    assert snap_to_vertices((1.0, 1.0), [], tol=5.0) is None


def test_snap_ties_to_closest_of_two():
    verts = [(0.0, 0.0), (2.0, 0.0)]
    assert snap_to_vertices((1.2, 0.0), verts, tol=5.0) == (2.0, 0.0)
    assert snap_to_vertices((0.8, 0.0), verts, tol=5.0) == (0.0, 0.0)
