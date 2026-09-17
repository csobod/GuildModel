"""The tessellation oracle, and the interface telling the truth about it.

BUILDPLAN-NEW UI-0. The screenshot that opened this work showed a visibly
corrupt model under a status bar reading "3D model ready" and an Inspector
reading "Nothing flagged". Every gate the app had asked the kernel whether the
kernel was happy, and OCCT's `BRepCheck_Analyzer` says yes to empty results, to
leaking shells, and to the order-dependent corruption in BUILDPLAN-NEW §3.1.

These pin the replacement: the mesh decides, and the answer reaches the user.
"""
import numpy as np
import pytest
import trimesh

from guildmodel.core.mesh_check import (MIN_VOLUME_MM3, verify_mesh,
                                        welded_surface, welded_surfaces)


def _box(size=10.0):
    return trimesh.creation.box(extents=(size, size, size))


def test_a_closed_box_verifies():
    verdict = verify_mesh(_box())
    assert verdict.ok
    assert verdict.watertight
    assert verdict.volume_mm3 == pytest.approx(1000.0)
    assert verdict.problems == []
    assert verdict.severity == "info"


def test_a_hole_in_the_surface_is_caught():
    """The failure the screenshot showed: geometry that renders, and looks
    plausible, but is not a closed solid — so the STL is invalid and any
    measurement taken from it is meaningless."""
    box = _box()
    leaky = trimesh.Trimesh(vertices=box.vertices.copy(),
                            faces=box.faces[:-2].copy(), process=False)
    verdict = verify_mesh(leaky)
    assert not verdict.ok
    assert not verdict.watertight
    assert verdict.severity == "error"
    assert any("gaps" in p for p in verdict.problems)
    # phrased for a maker, not a kernel engineer
    assert "STL" in " ".join(verdict.problems)


def test_a_self_overlapping_model_is_named_correctly_not_called_a_gap():
    """The bridge relief on the aviator failed this way: **zero** holes, one
    edge with four faces on it. Reporting that as "gaps" sends the maker (and
    this investigation, for a while) hunting for missing material that was
    never missing, so the two failures are worded apart.

    Two cubes sharing one edge is the same topology in miniature.
    """
    a = _box(1.0)
    b = _box(1.0)
    b.apply_translation([1.0, 1.0, 0.0])
    joined = trimesh.util.concatenate([a, b])          # process=True merges the
    joined.merge_vertices()                            # two shared corners

    counts = np.unique(joined.edges_sorted, axis=0, return_counts=True)[1]
    assert (counts > 2).sum() > 0, "fixture is not non-manifold"
    assert (counts == 1).sum() == 0, "fixture has holes; it must have none"

    verdict = verify_mesh(joined)
    assert not verdict.ok
    text = " ".join(verdict.problems)
    assert "overlaps itself" in text
    assert "gaps" not in text, "a model with no holes must not be called gappy"
    assert "STL" in text


def test_the_overlap_is_found_without_being_welded_first():
    """The same two cubes, handed over **unwelded** — which is how a kernel
    hands them over.

    This is the gap that made `verify_mesh` blind for the length of the M-N1
    work. Manifold's invariant is index-manifold, and it keeps that invariant
    across a self-contact by giving the contact two coincident vertices with
    different indices. Every index edge then has exactly two faces, trimesh's
    `is_watertight` says True, and the app said "Model verified" over 157
    self-touching edges on the demo frame's base (BUILDPLAN-NEW risk 0). A
    slicer, which has no index table, would have seen all 157.

    The assertion on `is_watertight` is the point of the test as much as the
    verdict is: it pins that the naive reading really does disagree, so nobody
    later simplifies the welding away as redundant.
    """
    a = _box(1.0)
    b = _box(1.0)
    b.apply_translation([1.0, 1.0, 0.0])
    unwelded = trimesh.util.concatenate([a, b])

    assert unwelded.is_watertight, (
        "fixture is not index-manifold, so it does not exercise the gap")

    verdict = verify_mesh(unwelded)
    assert not verdict.ok
    assert not verdict.watertight
    assert any("overlaps itself" in p for p in verdict.problems), verdict.problems


def test_welding_does_not_invent_problems_on_a_clean_solid():
    """A closed box stays closed, and its faces all survive the drop.

    The measurement has two steps that can each go wrong in the safe-looking
    direction: a weld tolerance too loose merges distinct vertices into false
    contacts, and a zero-area threshold too high deletes real surface and opens
    real holes. Both were seen during risk 0 — the first through a float32 STL
    round-trip that reported 26 contacts on a clean B-Rep.
    """
    box = _box()
    welded = welded_surface(box)
    assert welded is not None
    assert len(welded.faces) == len(box.faces)
    assert welded.is_watertight
    assert welded.volume == pytest.approx(box.volume)


def test_an_unreadable_mesh_falls_back_instead_of_failing_the_build():
    """`welded_surface` returns None rather than raising, and the verdict still
    comes back — a check that can itself fail the build is one more way for the
    app to go dark."""
    class NotQuiteAMesh:
        vertices = "no"
        faces = np.zeros((1, 3), int)
        is_watertight = False
        volume = 5.0

    assert welded_surface(NotQuiteAMesh()) is None
    verdict = verify_mesh(NotQuiteAMesh())
    assert not verdict.ok
    assert "STL" in " ".join(verdict.problems)


def test_an_empty_result_is_caught_and_explained():
    """OCCT's signature failure — a boolean that ate the whole part and still
    reported IsValid. It reached the Z-map once; it must never reach the user
    labeled 'ready'."""
    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), int),
                            process=False)
    verdict = verify_mesh(empty)
    assert not verdict.ok
    assert "empty" in verdict.summary.lower()
    assert any("feature" in p for p in verdict.problems)


def test_debris_from_a_failed_boolean_is_caught():
    tiny = trimesh.creation.box(extents=(0.5, 0.5, 0.5))     # 0.125 mm3
    verdict = verify_mesh(tiny)
    assert not verdict.ok
    assert tiny.volume < MIN_VOLUME_MM3


def test_a_part_in_pieces_is_caught():
    """A frame component is one connected body. Two means a cut severed it."""
    a = _box()
    b = _box()
    b.apply_translation([50.0, 0.0, 0.0])
    verdict = verify_mesh(a + b)
    assert not verdict.ok
    assert any("separate pieces" in p for p in verdict.problems)


def test_verification_never_raises():
    """A check that can itself fail the build is one more way for the app to go
    dark, so bad input is reported rather than thrown."""
    assert not verify_mesh(None).ok
    assert not verify_mesh(object()).ok            # not a mesh at all


def test_the_real_castle_verifies(tmp_path):
    """End to end on the demo frame, so the oracle is calibrated against a
    model we know is good rather than only against synthetic boxes."""
    from pathlib import Path

    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import CastleParams, ComponentKind
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    demo = Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf"
    layers, curves = import_curves(demo)
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    clear_base_cache()
    solid = build_castle_solid(ws.partition, CastleParams(), ws.hinge_polys)
    verdict = verify_mesh(tessellate(solid).to_trimesh())
    assert verdict.ok, verdict.problems
    assert verdict.volume_mm3 > 1000.0


def _collinear_tiling(scale=3.0):
    """A closed solid carrying two zero-area faces, tiled validly.

    This is the shape `_conform_rim` actually produced: one grid quad whose
    corner C has been snapped onto the line through A and B, so triangle (A,B,C)
    has three distinct vertices, real 1 mm edges, and no area. Every edge is
    still used exactly twice — the tiling is not broken, the *positions* are
    collinear — which is precisely why dropping the face before counting turned
    a closed solid into a report of six gaps.
    """
    xy = np.array([[0, 0], [1, 0], [2, 0], [1, 1]], float) * scale
    verts = np.vstack([np.column_stack([xy, np.full(4, scale)]),
                       np.column_stack([xy, np.zeros(4)])])
    faces = [(0, 1, 2), (2, 1, 3), (4, 6, 5), (6, 7, 5)]
    for u, v in [(0, 1), (1, 3), (3, 2), (2, 0)]:        # top's boundary loop
        faces += [(v, u, u + 4), (v, u + 4, v + 4)]
    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def test_a_collinear_face_in_a_valid_tiling_is_not_reported_as_a_gap():
    """The base-curve export defect, in miniature.

    A face with no area carries no *surface*, but it does carry *connectivity*:
    its edges are the seam between the faces around it. Drop it before counting
    and each of its three edges loses a face — so a closed solid reads as gaps,
    one per dropped edge. On the gabriel base-curve template that was 86 faces
    reported as 258 gaps, on a mesh trimesh, an STL round-trip and the genus all
    agreed was closed, and it made the part unexportable.
    """
    mesh = _collinear_tiling()
    assert mesh.is_watertight, "the fixture itself must be a closed solid"
    full, live = welded_surfaces(mesh)
    assert len(full.faces) - len(live.faces) == 2, "fixture should carry 2"

    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict.problems
    assert verdict.watertight
    assert verdict.volume_mm3 == pytest.approx(mesh.volume)


def test_a_zero_area_face_cannot_hide_a_real_hole():
    """Counting holes on the surface that keeps the dead faces must not become a
    way to miss one. Open the fixture and it is still caught."""
    mesh = _collinear_tiling()
    leaky = trimesh.Trimesh(vertices=mesh.vertices.copy(),
                            faces=mesh.faces[:-2].copy(), process=False)
    verdict = verify_mesh(leaky)
    assert not verdict.ok
    assert any("gaps" in p for p in verdict.problems)


def test_a_zero_area_face_does_not_invent_an_overlap_either():
    """The other half of the split: overlaps are still counted on the surface
    with the dead faces gone, because a face with no area must not be able to
    put a third surface on an edge. A clean fixture reports neither failure."""
    mesh = _collinear_tiling()
    _, live = welded_surfaces(mesh)
    counts = np.unique(live.edges_sorted, axis=0, return_counts=True)[1]
    assert int((counts > 2).sum()) == 0
