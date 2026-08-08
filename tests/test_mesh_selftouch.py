"""Does the surface touch itself? The base no longer does; three features still.

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

Step 2 is not optional. Skipping it reported 194 on the demo base where the
honest figure was 157, and it was skipping it that made the B-Rep look defective
too (see `test_the_brep_surface_does_not_touch_itself`).

**Where this stands.** The base — terraces plus all ten footing blends, which
was 157 / 247 / 232 across the three fixtures — is now zero, and so is the bare
model with its hinge pockets. Two changes did it, both in `model/build.py` and
both the same rule: carry a tool *across* every surface it meets
(`FOOTING_CROSS_MM`, for the zone wall at the seam), and never ask two
independently computed copies of a face to cancel (`ZONE_WELD_MM`).

What remains is per feature, and is not the same defect:

* **lens groove** — 76 / 94 / 82, and the V arrives with 60 to 72 of them
  before it has met the part. Root-caused to `kernel.hull_chain`, whose cells
  abut on a shared section rather than overlapping; see its docstring, and the
  overlap that was tried and rejected.
* **pad splay** — no contacts, but open edges once the degenerate faces are
  dropped, which means those faces are load-bearing and the surface pinches.
* **eyewire bezel** — 308 / 400 / 428 zero-area triangles and up to 2 contacts.

M-N3 does not flip the default until all of it is zero.
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


def _model(front, **features):
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    for name in features:
        getattr(castle, name).enabled = True
    return to_trimesh(build_castle_model(front.partition, castle,
                                         front.hinge_polys))


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


# --------------------------------------------------------------- what is fixed

@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_mesh_base_does_not_touch_itself(fixture, request):
    """Terraces, ten footing blends, hinge pockets. Was 157 / 247 / 232.

    Asserted at zero rather than ratcheted, because this is the state the
    milestone is for and anything above it is a regression rather than a
    known cost. Zero-area triangles too: those went 56 / 68 / 68 to none, and
    they are the same defect one dimension down — a *vertex* of a tool lying in
    a face of its target rather than a whole face of it.
    """
    found = self_touching_edges(_model(request.getfixturevalue(fixture)))
    assert found["touching"] == 0, found
    assert found["open"] == 0, found
    assert found["zero_area"] == 0, found


def test_no_blend_sample_lands_on_the_seam():
    """The rule the fix rests on, checked directly rather than through a build.

    `u = 0` is the vertical wall between the two zones. A profile *vertex* there
    is the same defect as a profile *face* there, one dimension down, and it is
    worth its own test because it is invisible: the variant that appended the
    crossing sample instead of moving the last one built a part with the same
    volume, the same body count and no self-touching edges at all — and 180 to
    324 zero-area triangles.

    Checked across the whole default schedule at three step heights, since a
    span that happened to divide evenly would put a sample back on the wall.
    """
    from guildmodel.core.model.build import (FOOTING_CROSS_MM, ZONE_WELD_MM,
                                             _blend_profile)
    from guildmodel.core.project.schema import CastleParams

    assert FOOTING_CROSS_MM > ZONE_WELD_MM, (
        "the two grown zones overlap across the seam by ZONE_WELD_MM, and both "
        "have to find the blend curve there rather than the terrace they came "
        "from — so the profile must reach further than the growth")

    footing = CastleParams().footing
    fillets = [getattr(footing, f) for f in vars(footing)
               if hasattr(getattr(footing, f), "exterior_mm")]
    assert fillets, "the default footing schedule is empty; this tests nothing"

    for fillet in fillets:
        for drop in (0.5, 1.3, 5.2):
            for side in ("high", "low"):
                try:
                    uv = _blend_profile(5.5, 5.5 - drop, fillet, side)
                except Exception:            # a degenerate span is not a sample
                    continue
                assert not np.any(uv[:, 0] == 0.0), (
                    f"{side} profile has a vertex exactly on the seam wall")


# ------------------------------------------------------------ what is not, yet

#: Known self-touching edge counts by fixture and feature, as an upper bound so
#: the defect cannot quietly grow and so that fixing it fails here and has to be
#: acknowledged rather than slipping by. See the module docstring for what each
#: one is; none of them is the blend defect the base had.
_KNOWN_SELF_TOUCH = {
    "demo_front":    {"eyewire_bezel": 0, "lens_groove": 76},
    "aviator_front": {"eyewire_bezel": 2, "lens_groove": 94},
    "gabriel_front": {"eyewire_bezel": 0, "lens_groove": 82},
}


@pytest.mark.parametrize("feature", ["eyewire_bezel", "lens_groove"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_remaining_features_do_not_get_worse(fixture, feature, request):
    """A ratchet on known defects, not an expectation that they are fine.

    Under-tightening this would let them spread unnoticed; over-tightening to
    the exact figure would make every unrelated tessellation change fail here.
    So: at most what is recorded, and the model must still be the closed,
    single, correct-volume body it is today.
    """
    mesh = _model(request.getfixturevalue(fixture), **{feature: True})
    found = self_touching_edges(mesh)
    budget = _KNOWN_SELF_TOUCH[fixture][feature]
    assert found["touching"] <= budget, (
        f"self-touching edges rose to {found['touching']} from a known "
        f"{budget} — see the module docstring")

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

    Measured on the **bezel** build. It used to be the bare one, which no longer
    emits any — that is what fixing the base did, and it is asserted as zero
    above. This test needs a build that still produces them, and the bezel does:
    308 on the demo frame.
    """
    import numpy as np

    from guildmodel.core.model import build_castle_model
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    model = build_castle_model(demo_front.partition, castle,
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
        "no zero-area triangles arrived — if the bezel has stopped emitting "
        "them too, this whole investigation is obsolete and the edge detector "
        "in §8.2 deserves another look")
