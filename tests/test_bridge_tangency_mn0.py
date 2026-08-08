"""A cutter must CROSS every surface it exits, never graze it.

BUILDPLAN-NEW M-N0. The bridge relief's loft ended exactly on `y_base` — the
highest point of the body on the centreline — so its end cap was the plane
y = y_base, tangent to the bridge wall along one vertical line at x = 0. The cut
left that line carrying four faces: a non-manifold model with **no holes at
all**, which `BRepCheck_Analyzer` called valid and which the app reported as
"3D model ready".

One edge of 33,683, on the maker's own drawing, deterministic — cold cache, warm
cache, and deep-copied cache alike. It is the defect behind the screenshot that
opened this whole line of work, and it was never the history-dependence the plan
first blamed.

Guarded on the aviator because the demo frame does not reproduce it: y_base has
to be a *tangent* extremum of the wall for the degeneracy to appear, and only
one of our two fixtures is shaped that way. That asymmetry is the lesson — the
clean fixture proved nothing.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / "aviator.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "aviator").iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def scooped(aviator_front):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.bridge_relief.enabled = True
    clear_base_cache()
    solid = build_castle_solid(aviator_front.partition, castle,
                               aviator_front.hinge_polys)
    return tessellate(solid).to_trimesh()


def _edge_use(mesh):
    return np.unique(mesh.edges_sorted, axis=0, return_counts=True)[1]


def test_the_scoop_leaves_no_edge_with_more_than_two_faces(scooped):
    counts = _edge_use(scooped)
    bad = int((counts > 2).sum())
    assert bad == 0, f"{bad} non-manifold edges — the cutter is grazing again"


def test_and_still_none_missing(scooped):
    """The other way to fail: the fix must not open a hole while closing an
    overlap."""
    assert int((_edge_use(scooped) == 1).sum()) == 0


def test_the_model_verifies_end_to_end(scooped):
    """What the maker sees. This is the assertion the status bar makes."""
    from guildmodel.core.mesh_check import verify_mesh

    verdict = verify_mesh(scooped)
    assert verdict.ok, verdict.problems
    assert scooped.is_watertight


def test_the_extension_removes_no_extra_material(scooped):
    """The station added past `y_base` runs through empty space, so it fixes the
    topology without changing the part. Pinned against the pre-fix figure
    (8209.238 mm3), which came off a corrupt mesh and so is itself only good to
    about this tolerance — hence a bound, not an equality."""
    assert scooped.volume == pytest.approx(8209.28, abs=0.5)
