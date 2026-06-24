"""M7.13 — mesh cross-section: a plane through a known solid yields a valid polyline."""
import numpy as np
import pytest

from guildcam.core.mesh.section import mesh_section


def _unit_cube():
    """A 1x1x1 cube at the origin as (points, triangle-faces)."""
    pts = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3),   # bottom (z=0)
        (4, 6, 5), (4, 7, 6),   # top (z=1)
        (0, 4, 5), (0, 5, 1),   # y=0
        (1, 5, 6), (1, 6, 2),   # x=1
        (2, 6, 7), (2, 7, 3),   # y=1
        (3, 7, 4), (3, 4, 0),   # x=0
    ]
    return pts, faces


def test_section_through_cube_is_a_closed_square():
    pts, faces = _unit_cube()
    polylines = mesh_section(pts, faces, origin=(0.5, 0.5, 0.5), normal=(0.0, 0.0, 1.0))
    assert polylines, "a plane through the cube must produce a cross-section"
    # every section point lies on the cut plane z = 0.5
    all_pts = [p for line in polylines for p in line]
    assert all(abs(p[2] - 0.5) < 1e-6 for p in all_pts)
    # the cross-section traces the unit-square perimeter (the triangulated cube adds
    # collinear edge-midpoints, so allow >=4 unique points, all on the boundary)
    unique = {(round(p[0], 3), round(p[1], 3)) for p in all_pts}
    assert len(unique) >= 4
    for (x, y) in unique:
        on_perimeter = (abs(x) < 1e-6 or abs(x - 1.0) < 1e-6
                        or abs(y) < 1e-6 or abs(y - 1.0) < 1e-6)
        assert on_perimeter, f"section point {(x, y)} is off the square perimeter"
    # bounds match the cube footprint
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(1.0)


def test_section_each_polyline_valid():
    pts, faces = _unit_cube()
    polylines = mesh_section(pts, faces, origin=(0.5, 0.5, 0.5), normal=(1.0, 0.0, 0.0))
    assert polylines
    for line in polylines:
        assert len(line) >= 2          # a polyline needs at least two points
        assert all(len(p) == 3 for p in line)


def test_section_miss_returns_empty():
    pts, faces = _unit_cube()
    # plane well above the cube — no intersection
    polylines = mesh_section(pts, faces, origin=(0.5, 0.5, 5.0), normal=(0.0, 0.0, 1.0))
    assert polylines == []
