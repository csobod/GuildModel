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


def test_the_scoop_stays_above_its_anterior_clamp(scooped, aviator_front):
    """The cutter must not reach the anterior face, and on this fixture that is
    not a formality: the aviator's decorative keyhole sits on the scoop's
    centreline, so seven of its thirteen anchor rays hit nothing.

    While `surface_z_at` reported a miss as 0.0 the sections at those stations
    were anchored on the anterior face and — closing upward to `top` — took the
    full thickness, cutter floor z=-0.020. The three topology tests above all
    passed throughout: a clean cut in the wrong place, exactly like the pad splay
    that halved Gabriel. See `geometry.rings.carry_anchors`.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import build_terraces, zone_heights
    from guildmodel.core.solid.features import scoop_cutter

    castle = CastleParams()
    castle.bridge_relief.enabled = True
    partition = aviator_front.partition
    bare = build_terraces(partition,
                          zone_heights(partition, castle, None), curved=False)

    box = Bnd_Box()
    BRepBndLib.Add_s(scoop_cutter(bare, partition.body, castle.bridge_relief),
                     box)
    floor = float(castle.bridge_relief.anterior_clamp_mm)
    assert box.CornerMin().Z() >= floor - 0.05


def test_the_extension_removes_no_extra_material(scooped):
    """The station added past `y_base` runs through empty space, so it fixes the
    topology without changing the part.

    A tripwire on the finished part, not the argument itself — the three
    assertions above carry that. The tolerance is for tessellation portability
    across platforms, not because the figure is soft.

    Pinned at 8209.238 mm3 when M-N0 landed and now 8214.220, because the scoop
    stopped diving through the keyhole and 4.98 mm3 of bridge stayed on the
    frame. That is the fix in the test above, measured from the other end.
    """
    assert scooped.volume == pytest.approx(8214.22, abs=0.5)
