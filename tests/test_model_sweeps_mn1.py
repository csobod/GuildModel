"""Sweeping a profile that is not convex (BUILDPLAN-NEW M-N1).

`hull_chain` is the fast route and it requires convex sections. Three of this
project's four surface features have one; the edge feature's round-over does
not — it is the upper half of a circle, so the region above it is concave, and
a convex hull spans the dent. The failure is silent and it is not subtle: every
fillet becomes a chamfer.

These pin `swept_profile`, the slab decomposition that handles it, against a
case where the two constructions must visibly disagree.
"""
import numpy as np
import pytest

from guildmodel.core.model.kernel import (ManifoldError, hull_chain,
                                          swept_profile, to_trimesh)

#: A square path, so the swept solid's volume is easy to reason about by hand.
_SIDE = 40.0
_STATIONS = 4


def _square_ring():
    """Corners of a square, with outward normals — a closed 4-station path."""
    half = _SIDE / 2.0
    points = np.array([[-half, -half], [half, -half], [half, half], [-half, half]])
    normals = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    normals = normals / np.linalg.norm(normals, axis=1)[:, None]
    return points, normals


def _round_over(width: float, drop: float, n: int = 9):
    """The edge-feature fillet, matching `_edge_section`'s "fillet" branch:

        v = -drop + drop * sqrt(1 - ((r - u) / r)^2)

    from `(0, -drop)` up to `(width, 0)`. The square root is the **upper** half
    of a circle, so `v` is a *concave* function and the region above it is not a
    convex set — which is the case `hull_chain` gets wrong.

    Worth stating because the first version of this fixture used the lower half
    (`-drop * sqrt(1 - (u/r)^2)`), which is *convex*, so both constructions
    agreed to the last digit and the test proved nothing. The curve looks
    similar and behaves oppositely.
    """
    us = np.linspace(0.0, width, n)
    r = width
    vs = -drop + drop * np.sqrt(np.maximum(1.0 - ((r - us) / r) ** 2, 0.0))
    return np.column_stack([us, vs])


def test_a_concave_profile_sweeps_to_less_material_than_its_hull():
    """The whole point. Hulling the round-over fills the dent, so the hulled
    cutter is strictly larger — and a cutter that is too large removes material
    the maker asked to keep."""
    points, normals = _square_ring()
    profile = _round_over(4.0, 2.0)
    far = 10.0

    slabbed = swept_profile(points, normals, [profile] * _STATIONS, far)

    def as_3d(k):
        p, d = points[k], normals[k]
        return np.array([[p[0] + d[0] * u, p[1] + d[1] * u, v] for u, v in profile]
                        + [[p[0] + d[0] * profile[-1][0],
                            p[1] + d[1] * profile[-1][0], far],
                           [p[0] + d[0] * profile[0][0],
                            p[1] + d[1] * profile[0][0], far]])

    hulled = hull_chain([as_3d(k) for k in range(_STATIONS)])

    assert slabbed.volume() < hulled.volume(), (
        "the hull did not fill the concavity, so this fixture proves nothing")
    # The dent is a real fraction of the section, not float noise.
    assert (hulled.volume() - slabbed.volume()) / hulled.volume() > 0.02


def test_the_swept_profile_is_a_closed_solid():
    points, normals = _square_ring()
    mesh = to_trimesh(swept_profile(points, normals,
                                    [_round_over(4.0, 2.0)] * _STATIONS, 10.0))
    assert mesh.is_watertight
    assert mesh.volume > 0.0


def test_a_straight_profile_agrees_with_the_hull_route():
    """Where the section *is* convex the two constructions describe the same
    solid, which is what makes `hull_chain` a safe shortcut rather than a
    different answer."""
    points, normals = _square_ring()
    straight = np.array([[0.0, -2.0], [4.0, 0.0]])       # a chamfer: convex
    far = 10.0

    slabbed = swept_profile(points, normals, [straight] * _STATIONS, far)

    def as_3d(k):
        p, d = points[k], normals[k]
        return np.array([[p[0] + d[0] * u, p[1] + d[1] * u, v]
                         for u, v in straight]
                        + [[p[0] + d[0] * 4.0, p[1] + d[1] * 4.0, far],
                           [p[0], p[1], far]])

    hulled = hull_chain([as_3d(k) for k in range(_STATIONS)])
    assert slabbed.volume() == pytest.approx(hulled.volume(), rel=1e-9)


def test_a_malformed_sweep_is_refused_not_guessed():
    points, normals = _square_ring()
    with pytest.raises(ManifoldError):
        swept_profile(points, normals, [_round_over(4.0, 2.0)] * 2, 10.0)
    with pytest.raises(ManifoldError):
        swept_profile(points, normals, [np.array([[0.0, 0.0]])] * _STATIONS, 10.0)
