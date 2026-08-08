"""The mesh kernel's edges, and the three display modes they unlock.

BUILDPLAN-NEW §8.2 / M-N2. Deriving edges from dihedral angle was built and
backed out once on a measurement saying only 43.7% of what it drew was a real
edge of the part. The surplus was **zero-area triangles** — their normal is the
zero vector, and the angle between a zero vector and a unit one is exactly 90
degrees, so each arrived as a right-angle crease. They were also the stitches
over the surface's self-contacts, and risk 0 removed both at once.

These pin the re-measurement rather than the implementation, because the
implementation is four lines and the measurement is the whole argument.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

#: How close a sample must lie to the other edge set to count as accounted for,
#: mm. The two kernels tessellate the same solid differently, so this absorbs
#: the chord deficit between them rather than float noise.
NEAR_MM = 0.15


@pytest.fixture(scope="module")
def demo_front():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws


def _segments(polylines):
    """(s, 2, 3) segments from a list of polylines."""
    segs = [np.stack([np.asarray(p)[:-1], np.asarray(p)[1:]], axis=1)
            for p in polylines if len(p) >= 2]
    return (np.concatenate(segs, axis=0) if segs
            else np.zeros((0, 2, 3), dtype=float))


def _sample(segs, per_mm=4.0):
    """Points along each segment, and the length each stands for."""
    pts, weights = [], []
    for p, q in zip(segs[:, 0], segs[:, 1]):
        length = float(np.linalg.norm(q - p))
        n = max(2, int(np.ceil(length * per_mm)))
        t = np.linspace(0.0, 1.0, n)
        pts.append(p[None, :] + (q - p)[None, :] * t[:, None])
        weights.append(np.full(n, length / n))
    if not pts:
        return np.zeros((0, 3)), np.zeros(0)
    return np.vstack(pts), np.concatenate(weights)


def _covered(a_segs, b_segs) -> float:
    """Fraction of `a_segs`' length lying within NEAR_MM of `b_segs`."""
    from scipy.spatial import cKDTree

    pts, weights = _sample(a_segs)
    assert len(pts), "the first edge set is empty; this compares nothing"
    other, _ = _sample(b_segs, 8.0)
    assert len(other), "the second edge set is empty; this compares nothing"
    distance, _ = cKDTree(other).query(pts)
    return float(weights[distance <= NEAR_MM].sum() / weights.sum())


def _mesh_and_brep(front, castle):
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    mesh = to_trimesh(build_castle_model(front.partition, castle,
                                         front.hinge_polys))
    clear_base_cache()
    tess = tessellate(build_castle_solid(front.partition, castle,
                                         front.hinge_polys))
    return mesh, tess


def test_every_line_it_draws_is_a_real_edge_of_the_part(demo_front):
    """The measurement the first attempt failed: 43.7%, now 98.6%.

    Compared against the B-Rep's **topological** edges, which are the ground
    truth for "is there an edge here" — they come from the solid's own topology,
    not from any crease heuristic. The control in the same units is the same
    detector run over the B-Rep's own tessellation: it scores 98.2%, so this is
    not merely good, it is as good as the mesh being replaced.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import feature_edges
    from guildmodel.core.project.schema import CastleParams

    mesh, tess = _mesh_and_brep(demo_front, CastleParams())
    drawn = _segments(feature_edges(mesh))
    topological = tess.edge_segments

    accounted = _covered(drawn, topological)
    control = _covered(_segments(feature_edges(tess.to_trimesh())), topological)

    assert accounted > 0.95, (
        f"{accounted:.1%} of the drawn length is a real edge; the first "
        "attempt was backed out at 43.7% and the bar is the B-Rep's own "
        f"tessellation, which scores {control:.1%}")
    assert accounted >= control - 0.02, (
        f"{accounted:.1%} against the same detector's {control:.1%} on the "
        "B-Rep mesh — this path should not be the worse of the two")


def test_it_misses_nothing_the_brep_tessellation_finds(demo_front):
    """100.0%, measured. The recall half of the argument.

    Against creases on the B-Rep's *mesh* rather than its topology, because that
    is the like-for-like question: given the same detector, does this surface
    hide anything? It does not. (Against topology the figure is ~32%, and that
    is the topology's problem — see the next test.)
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import feature_edges
    from guildmodel.core.project.schema import CastleParams

    mesh, tess = _mesh_and_brep(demo_front, CastleParams())
    found = _covered(_segments(feature_edges(tess.to_trimesh())),
                     _segments(feature_edges(mesh)))
    assert found > 0.98, f"only {found:.1%} of the B-Rep's creases are here"


def test_the_topological_set_is_mostly_not_edges_of_the_part(demo_front):
    """Why the missing two thirds are not a shortfall.

    The B-Rep viewer draws every `TopAbs_EDGE`, which on this frame is ~6,200 mm
    against ~1,400 mm of actual crease: a 180-section loft contributes thousands
    of tangent patch seams between surfaces that meet smoothly. Those are not
    edges of the part. Pinned so that "the mesh finds only a third of the B-Rep's
    edges" is never again read as a defect in the detector.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import feature_edges
    from guildmodel.core.project.schema import CastleParams

    mesh, tess = _mesh_and_brep(demo_front, CastleParams())

    def mm(segs):
        return float(np.linalg.norm(segs[:, 1] - segs[:, 0], axis=1).sum())

    creases = mm(_segments(feature_edges(mesh)))
    topological = mm(tess.edge_segments)
    assert creases < 0.4 * topological, (
        f"{creases:.0f} mm of crease against {topological:.0f} mm of topology "
        "— if these have converged, re-examine what the extra was")


def test_the_threshold_sits_in_the_gap_between_blend_facets_and_features():
    """20 degrees is the middle of a measured flat band, not a taste.

    Below it are the facets of the curved footing blends — drawing those lays a
    contour map over every blend. Above it are the features, the shallowest
    being the 30 degree eyewire bezel. If either moves, this fails rather than
    quietly drawing the wrong thing.
    """
    from guildmodel.core.model import CREASE_ANGLE_DEG
    from guildmodel.core.project.schema import EyewireBezelParams

    assert 12.0 <= CREASE_ANGLE_DEG <= 28.0, (
        "the flat band measured on all three drawings is 12-28 degrees")
    assert CREASE_ANGLE_DEG < EyewireBezelParams().angle_deg, (
        "the default eyewire bezel would not be drawn as an edge")


def test_the_viewer_gets_edges_from_the_mesh_kernel(demo_front):
    """End to end through the builder the GUI actually calls, because the gap
    this closes was a *wiring* one: the detector's absence cost three of the
    four display modes, and the viewer enables them on `edges` being non-empty.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import _build_castle_mesh

    mesh, edges, guide = _build_castle_mesh(
        {"partition": demo_front.partition, "castle": CastleParams(),
         "hinge": demo_front.hinge_polys}, None)

    assert guide is None
    assert edges, "the mesh path still returns no edges; the modes stay disabled"
    assert all(len(np.asarray(e)) >= 2 for e in edges)
    assert len(mesh.faces) > 0
