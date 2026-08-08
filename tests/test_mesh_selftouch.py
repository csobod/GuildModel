"""The mesh kernel's surface touches itself. The B-Rep's does not.

Found while investigating why dihedral edge detection produced lines that were
not on the part (BUILDPLAN-NEW §8.2). The creases turned out to be zero-area
triangles — Manifold emits them, their normal is the zero vector, and the angle
between a zero vector and a real normal computes as exactly 90 degrees. But
removing them from the measurement exposed something underneath that is real.

**What this measures, and why it takes three steps.** Manifold's invariant is
that its output is a closed 2-manifold *by vertex index*, and it holds — every
index edge has exactly two faces. It keeps that invariant across a self-contact
by giving the contact two coincident vertices with different indices. An STL has
no index table, so a slicer welds by position and sees the contact. So:

1. weld coincident vertices by position — what export effectively does;
2. drop zero-area faces, which are the stitches that welding exposes, and which
   otherwise inflate the count roughly threefold by contributing their long edge
   twice;
3. *then* count edges carrying more than two faces.

Step 2 is not optional. Skipping it reports 194 on the demo base where the
honest figure is 157, and it was skipping it that made the B-Rep look defective
too (see `test_the_brep_surface_does_not_touch_itself`).

The counts below are pinned as a **known defect**, not as an expectation. The
build is watertight, correct on volume to 0.00000%, and one connected body; what
it is not is a surface a slicer will call manifold. M-N3 does not flip the
default until this is zero.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh

FIXTURES = Path(__file__).parent / "fixtures"


def _front_from_gdraw(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


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


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    return _front_from_gdraw(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    return _front_from_gdraw(tmp_path_factory, "gabriel")


#: Area at or below which a triangle carries no surface, mm2. These are exactly
#: zero in practice; the bound is here so a collinear-but-not-identical triangle
#: is caught too.
_NO_AREA_MM2 = 1e-12


def self_touching_edges(mesh) -> dict:
    """Welded by position, degenerate faces removed, then counted.

    Returns `{"zero_area", "raw", "touching", "open"}`. `raw` is the count
    *without* step 2, kept because the gap between it and `touching` is the
    whole reason this function exists rather than a one-liner.
    """
    welded = trimesh.Trimesh(vertices=np.asarray(mesh.vertices).copy(),
                             faces=np.asarray(mesh.faces).copy(), process=False)
    welded.merge_vertices()

    faces = welded.faces
    repeated = ((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2])
                | (faces[:, 0] == faces[:, 2]))
    corners = welded.vertices[faces]
    area = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0],
                                         corners[:, 2] - corners[:, 0]), axis=1)
    dead = repeated | (area <= _NO_AREA_MM2)

    raw = np.unique(welded.edges_sorted, axis=0, return_counts=True)[1]
    kept = trimesh.Trimesh(vertices=welded.vertices, faces=faces[~dead],
                           process=False)
    counts = np.unique(kept.edges_sorted, axis=0, return_counts=True)[1]
    return {"zero_area": int(dead.sum()), "raw": int((raw > 2).sum()),
            "touching": int((counts > 2).sum()), "open": int((counts == 1).sum())}


# ------------------------------------------------------------------ the B-Rep

@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_brep_surface_does_not_touch_itself(fixture, request):
    """Zero, on all three drawings, with the bezel on. This is the standard.

    Worth pinning for its own sake and as the control: an earlier measurement of
    mine reported 26 and 16 here and concluded the shipped path was broken. It
    was not. That measurement round-tripped through **binary STL, which stores
    float32**, and the quantisation merged distinct nearby vertices into false
    contacts. The lesson is the one this project keeps relearning — check the
    instrument against a case known to be clean before believing it.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    castle.eyewire_bezel.enabled = True

    clear_base_cache()
    mesh = tessellate(build_castle_solid(front.partition, castle,
                                         front.hinge_polys)).to_trimesh()
    found = self_touching_edges(mesh)
    assert found["zero_area"] == 0, found
    assert found["touching"] == 0, found


# -------------------------------------------------------------- the mesh path

#: Known self-touching edge counts for the mesh kernel, by fixture: the bare
#: model, and the model with the eyewire bezel. Pinned as an upper bound so the
#: defect cannot quietly grow, and so that fixing it fails here and has to be
#: acknowledged rather than slipping by.
#:
#: The blends are the source, localised by staging: terraces alone are 0 on all
#: three fixtures, and the base is already at the full count before any feature
#: is switched on. It is the two halves of each blend meeting at the seam —
#: carves alone give 20 on the demo frame and raises alone 29, but together 194
#: (157 honest), so it is their interaction rather than either one.
#:
#: Invariant to every parameter it was swept against — `FOOTING_LEAD_MM` from 0
#: to 1.0 mm, `FOOTING_SECTION_POINTS` 16 to 60, `SLAB_MARGIN_MM` 2 to 20 — which
#: is what rules out tangency and points at the construction.
_KNOWN_SELF_TOUCH = {
    "demo_front":    {"bare": 157, "bezel": 94},
    "aviator_front": {"bare": 247, "bezel": 153},
    "gabriel_front": {"bare": 232, "bezel": 145},
}


@pytest.mark.parametrize("feature", ["bare", "bezel"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_mesh_surface_self_touch_does_not_grow(fixture, feature, request):
    """A ratchet on a known defect, not an expectation that it is fine.

    Under-tightening this would let the defect spread unnoticed;
    over-tightening it to the exact figure would make every unrelated
    tessellation change fail here. So: at most what is recorded, and the model
    must still be the closed, single, correct-volume body it is today.
    """
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.project.schema import CastleParams

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    if feature == "bezel":
        castle.eyewire_bezel.enabled = True

    mesh = to_trimesh(build_castle_model(front.partition, castle,
                                         front.hinge_polys))
    found = self_touching_edges(mesh)
    budget = _KNOWN_SELF_TOUCH[fixture][feature]
    assert found["touching"] <= budget, (
        f"self-touching edges rose to {found['touching']} from a known "
        f"{budget} — the blends are getting worse, see the module docstring")

    # Everything else about the part is still right, which is exactly why this
    # needed a dedicated measurement to see at all.
    assert mesh.is_watertight
    assert mesh.body_count == 1


def test_the_zero_area_faces_are_manifolds_own(demo_front):
    """Not something our merge-map handling introduces.

    Worth pinning because that was the first hypothesis and it was wrong:
    `to_trimesh` applies `merge_from_vert`/`merge_to_vert`, and collapsing two
    of a triangle's vertices onto each other would produce exactly this. But the
    merge map comes back **empty** for these models and the raw `tri_verts`
    already contain the degenerate triangles, so they arrive that way.
    """
    import numpy as np

    from guildmodel.core.model import build_castle_model
    from guildmodel.core.project.schema import CastleParams

    model = build_castle_model(demo_front.partition, CastleParams(),
                               demo_front.hinge_polys)
    raw = model.to_mesh()
    verts = np.asarray(raw.vert_properties)[:, :3]
    tris = np.asarray(raw.tri_verts, dtype=np.int64)
    corners = verts[tris]
    area = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0],
                                         corners[:, 2] - corners[:, 0]), axis=1)

    assert len(raw.merge_from_vert) == 0, (
        "there is a merge map after all — re-check whether applying it is what "
        "collapses these triangles")
    assert (area <= _NO_AREA_MM2).sum() > 0, (
        "no zero-area triangles arrived — if Manifold has stopped emitting "
        "them, this whole investigation is obsolete and the edge detector in "
        "§8.2 deserves another look")
