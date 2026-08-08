"""Does the surface touch itself? No longer — anywhere. Degenerate faces remain.

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

**And measure at full precision.** `to_trimesh` used to extract through
`Manifold.to_mesh()`, which is float32 while Manifold itself keeps float64. At a
50 mm coordinate that spacing is about 4e-6 mm, and it distorted these counts in
*both* directions — the bezel read 308 zero-area triangles where there are 2,
because quantisation merges vertices and turns faces degenerate, while the
aviator read 2 contacts where there are 6, because a face that goes degenerate
carries its edges out of the count. For a while it also meant the control was
comparing the B-Rep at float64 against the mesh at float32.

**Where this stands.** Contacts and open edges are **zero everywhere** — base
and every feature, matching the B-Rep on all three drawings. Four changes, and
three of them are one rule: *a tool must cross every surface it meets, and no
vertex of it may lie in a face of its target.*

* `FOOTING_CROSS_MM` — the blend halves ended at `u = 0`, the zone wall at the
  seam. The base was 157 / 247 / 232 contacts.
* `features.EDGE_CROSS_MM` — the pad splay's sections start on the ring it
  sweeps, and that ring *is* the body outline. 105 / 97 / 93 degenerate faces
  and 34 / 47 / 15 open edges, none of which moved for four hypotheses about the
  far end of the profile before a staged target named the near end: the same
  tool cuts a plain box clean and the real outline at 102.
* `kernel.sweep_sections` — a swept tube built as an explicit strip rather than
  a union of abutting convex hulls, whose shared sections the union did not
  reliably cancel. The lens groove was 76 / 94 / 82.
* `ZONE_WELD_MM` — the odd one out: grow each zone so neighbours overlap, rather
  than asking two independently computed copies of a wall to cancel.

What remains is a handful of **zero-area triangles** — at most 12, against the
B-Rep's none. `mesh_check` does not report them and slicers generally discard
them, so they are a gap rather than a defect. `_KNOWN_DEGENERATE` holds them.
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

#: Zero-area triangles left per fixture and feature. Pinned as an upper bound:
#: the B-Rep emits none, so this is a ratchet on a known gap rather than an
#: expectation that it is fine.
#:
#: These are what survived three rounds of one rule — a tool must cross every
#: surface it meets, and no *vertex* of it may lie in a face of its target.
#: `model.build.FOOTING_CROSS_MM` for the zone wall at a blend seam,
#: `features.EDGE_CROSS_MM` for the body outline under the pad splay, and
#: `kernel.sweep_sections` for the sections a hull chain left abutting inside
#: its own tube. The splay alone went 105 / 97 / 93 to 6 / 4 / 2.
_KNOWN_DEGENERATE = {
    "demo_front":    {"eyewire_bezel": 2, "lens_groove": 8,
                      "pad_splay": 6, "bridge_relief": 0},
    "aviator_front": {"eyewire_bezel": 12, "lens_groove": 0,
                      "pad_splay": 4, "bridge_relief": 0},
    "gabriel_front": {"eyewire_bezel": 12, "lens_groove": 8,
                      "pad_splay": 2, "bridge_relief": 0},
}


@pytest.mark.parametrize("feature", ["eyewire_bezel", "lens_groove",
                                     "pad_splay", "bridge_relief"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_no_feature_makes_the_surface_touch_itself(fixture, feature, request):
    """Zero contacts, per feature, matching the B-Rep on all three drawings.

    This is the M-N0 condition — what `mesh_check` words as "the model overlaps
    itself along N edges ... will not export as a valid STL" — and it is the one
    that has to be zero rather than merely small. The lens groove was 76 / 94 /
    82 of them until `kernel.sweep_sections` replaced the hull chain.
    """
    mesh = _model(request.getfixturevalue(fixture), **{feature: True})
    found = self_touching_edges(mesh)
    assert found["touching"] == 0, found
    assert mesh.is_watertight
    assert mesh.body_count == 1


@pytest.mark.parametrize("feature", ["eyewire_bezel", "lens_groove",
                                     "pad_splay", "bridge_relief"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_degenerate_faces_do_not_grow(fixture, feature, request):
    """A ratchet on what is left, not an expectation that it is fine.

    Open edges are asserted at **zero** rather than ratcheted. An edge that
    opens when the degenerate faces are dropped means those faces were holding
    the surface together, which is a real pinch; the splay had 34 / 47 / 15 of
    them until `EDGE_CROSS_MM` moved its first sample off the outline.
    """
    mesh = _model(request.getfixturevalue(fixture), **{feature: True})
    found = self_touching_edges(mesh)
    budget = _KNOWN_DEGENERATE[fixture][feature]
    assert found["zero_area"] <= budget, (
        f"zero-area triangles rose to {found['zero_area']} from a known "
        f"{budget} — see the module docstring")
    assert found["open"] == 0, found


def test_the_sweep_never_falls_back_to_the_hull_chain(demo_front):
    """`sweep_sections` keeps `hull_chain` for paths that turn tighter than the
    section is deep, where a strip would build the self-intersection faithfully.

    A fallback nobody notices is the failure mode this project keeps being
    bitten by, so pin that it is not silently carrying the build: on a fully
    featured frame every sweep must take the strip.
    """
    from guildmodel.core.model import kernel
    from guildmodel.core.model import build_castle_model
    from guildmodel.core.project.schema import CastleParams

    real, taken = kernel._strip_mesh, {"strip": 0, "fallback": 0}

    def counting(profiles, closed):
        out = real(profiles, closed)
        taken["strip" if out is not None else "fallback"] += 1
        return out

    castle = CastleParams()
    for name in ("eyewire_bezel", "lens_groove", "pad_splay", "bridge_relief"):
        getattr(castle, name).enabled = True

    kernel._strip_mesh = counting
    try:
        build_castle_model(demo_front.partition, castle, demo_front.hinge_polys)
    finally:
        kernel._strip_mesh = real

    assert taken["strip"] > 0, "no sweep ran at all; this test proves nothing"
    assert taken["fallback"] == 0, (
        f"{taken['fallback']} of {sum(taken.values())} sweeps fell back to the "
        "hull chain, which leaves membranes — find out which and why")


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
