"""The mesh kernel must build the same part as the B-Rep one.

BUILDPLAN-NEW M-N1. Parity comes before improvement: the two kernels have to
agree on the part before either can be trusted to replace the other. Every
feature ported gets a gate here, and the gates run against *both* kernels from
the same partition and the same parameters, so a disagreement names itself.

The tolerances are stated rather than tuned to whatever the run produced.
Volume agreement is the referee (BUILDPLAN's GProp table established that the
tessellation is the only self-consistent measurement), and the two paths mesh
curves differently — OCCT tessellates trimmed surfaces at a chordal deviation,
Manifold extrudes the already-flattened partition polygon — so they are allowed
to differ by the chord deficit and nothing more.
"""
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

#: Volume agreement between the two kernels on **polygonal** terraces, as a
#: fraction. Deliberately tight: both paths extrude the same flattened partition
#: polygons to the same heights, so they do not merely agree closely, they agree
#: exactly — measured 8004.952 mm3 from each on the demo frame, delta 0.0000%.
#:
#: A loose bound here would be worthless. 0.5% would still pass with a whole
#: hinge pocket missing (~1.5% of the part), and the only reason to allow any
#: slack at all is float accumulation in two different summations.
VOLUME_TOL = 1e-6


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


def _gdraw_front(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    """The maker's own drawing, and the only fixture that catches the pad splay
    severing the frame. Two real drawings were not enough: M-N0's tangency
    existed on exactly one of them, and this one adds a failure neither of the
    others shows."""
    return _gdraw_front(tmp_path_factory, "gabriel")


def _bare_params():
    """Defaults, which carry no finishing features — the stage the mesh kernel
    has ported so far. The footing blends are excluded on the B-Rep side by
    going through `build_terraces` directly (see `_terraces_only`) rather than
    by switching them off, because the schedule has no such switch."""
    from guildmodel.core.project.schema import CastleParams

    return CastleParams()


def _terraces_only(partition, castle):
    """The B-Rep terraces without footing blends, for a like-for-like compare.

    `castle_base` also applies the blends, which the mesh path has not ported
    yet; asking it for the whole base would compare a featured part against an
    unfeatured one and report the difference as a parity failure.
    """
    from guildmodel.core.solid.build import build_terraces, zone_heights

    return build_terraces(partition, zone_heights(partition, castle, None),
                          curved=False)


# ------------------------------------------------------------------ the kernel

def test_the_mesh_kernel_is_closed_by_construction(demo_front):
    """The property the whole migration is for. Not asserted of the B-Rep path
    anywhere, because there it is an outcome rather than an invariant."""
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import build_castle_model, to_trimesh

    model = build_castle_model(demo_front.partition, _bare_params(),
                               demo_front.hinge_polys)
    verdict = verify_mesh(to_trimesh(model))
    assert verdict.ok, verdict.problems


def test_the_weld_uses_the_merge_map(demo_front):
    """MeshGL splits vertices by design, so the raw soup looks open. Welding
    positionally is guesswork; the library's own merge map is the answer. The
    spike measured 33,036 spurious boundary edges from getting this wrong."""
    from guildmodel.core.model import build_castle_model, to_trimesh

    mesh = to_trimesh(build_castle_model(demo_front.partition, _bare_params(),
                                         demo_front.hinge_polys))
    assert mesh.is_watertight
    assert mesh.euler_number % 2 == 0, "a closed surface has even Euler number"


# ------------------------------------------------------------------- parity

@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_terraces_agree_with_the_brep_kernel(fixture, request):
    """Same zones, same heights, two kernels, one part."""
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model import to_trimesh
    from guildmodel.core.solid.build import zone_heights
    from guildmodel.core.solid.occ import mesh_volume

    front = request.getfixturevalue(fixture)
    castle = _bare_params()
    heights = zone_heights(front.partition, castle, None)

    brep = mesh_volume(_terraces_only(front.partition, castle))
    mesh = to_trimesh(mesh_terraces(front.partition, heights)).volume

    assert mesh == pytest.approx(brep, rel=VOLUME_TOL), (
        f"terrace volumes disagree: B-Rep {brep:.3f}, mesh {mesh:.3f}")


def test_hinge_pockets_remove_the_same_material(demo_front):
    """A pocket is the simplest cut there is, so a disagreement here would be
    about the *floor* — where the pocket starts — not about the boolean."""
    from guildmodel.core.model import (build_terraces, hinge_pockets,
                                       subtract_all, to_trimesh)
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights

    castle = _bare_params()
    heights = zone_heights(demo_front.partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    bare = build_terraces(demo_front.partition, heights)
    pockets = hinge_pockets(demo_front.hinge_polys, castle, top)
    assert pockets, "the demo frame has hinge pockets; the fixture is wrong"

    pocketed = subtract_all(bare, pockets)
    removed = to_trimesh(bare).volume - to_trimesh(pocketed).volume

    depth = castle.hinge_pocket_depth_mm
    expected = sum(p.area for p in demo_front.hinge_polys) * depth
    assert removed == pytest.approx(expected, rel=0.02), (
        "a pocket is a prism: area x depth, whatever the kernel")


# -------------------------------------------------------------- lens groove

def _groove_params():
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.lens_groove.enabled = True
    return castle


def _lip(front, castle):
    from guildmodel.core.geometry.rings import lip_partition
    from guildmodel.core.solid.build import zone_heights

    lip = lip_partition(front.partition, castle.lens_groove.depth_mm)
    return lip, zone_heights(lip, castle, None)


@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_groove_v_agrees_with_the_brep_kernel(fixture, request):
    """Terraces plus the groove, both kernels, same lip partition.

    Compared without the footing blends on either side — the mesh path has not
    ported them yet, and comparing a featured part against an unfeatured one
    would report the difference as a groove disagreement.
    """
    from guildmodel.core.model import subtract_all, to_trimesh
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model.features import groove_cutters as mesh_grooves
    from guildmodel.core.solid.build import build_terraces as occ_terraces
    from guildmodel.core.solid.features import groove_cutters as occ_grooves
    from guildmodel.core.solid.occ import cut_many, mesh_volume

    front = request.getfixturevalue(fixture)
    castle = _groove_params()
    lip, heights = _lip(front, castle)

    occ_tools = occ_grooves(lip, castle)
    assert occ_tools, "the fixture has no lens apertures to groove"
    occ_bare = occ_terraces(lip, heights, curved=False)
    brep_removed = mesh_volume(occ_bare) - mesh_volume(cut_many(occ_bare,
                                                                occ_tools))

    mesh_tools = mesh_grooves(lip, castle)
    assert len(mesh_tools) == len(occ_tools), "different number of V cutters"
    mesh_bare = mesh_terraces(lip, heights)
    grooved = to_trimesh(subtract_all(mesh_bare, mesh_tools))
    mesh_removed = to_trimesh(mesh_bare).volume - grooved.volume

    assert grooved.is_watertight

    # **Compared on the material REMOVED, not on the finished part.** The groove
    # is ~187 mm3 of an ~9,000 mm3 castle, so a 1% gate on the part tolerates a
    # 48% error in the feature — and did: it passed a V built backwards, mouth
    # buried in the wall and apex out in the hole, with no undercut whatever.
    # Only the ray test below caught that.
    #
    # 4% of the removed volume is the honest bound. Both cutters inscribe the
    # same polygon in the same ring at the same station count, but the B-Rep one
    # is a ruled loft between planar sections and the mesh one a chain of convex
    # hulls, so they differ by the sagitta of the V's flanks.
    assert mesh_removed == pytest.approx(brep_removed, rel=0.04), (
        f"the groove removes {mesh_removed:.3f} mm3 in the mesh kernel against "
        f"{brep_removed:.3f} in the B-Rep one")


def test_the_groove_actually_undercuts(demo_front):
    """The whole reason this project left the heightfield behind.

    A vertical ray through the eyewire wall must cross the surface at least
    four times — in, into the groove, out of the groove, out — because a V cut
    sideways into the wall is exactly what a Z-map cannot represent.
    """
    import numpy as np
    from shapely.geometry import LineString

    from guildmodel.core.geometry.rings import inward_normals, ring_stations
    from guildmodel.core.model import build_castle_model, to_trimesh

    castle = _groove_params()
    lip, _heights = _lip(demo_front, castle)
    mesh = to_trimesh(build_castle_model(demo_front.partition, castle,
                                         demo_front.hinge_polys))

    ring = next(r for r in lip.body.interiors if not lip.is_hole(r))
    pts, tans = ring_stations(LineString(ring), 40)
    into_wall = inward_normals(lip.body, pts, tans)

    deep = 0
    for point, normal in zip(pts, into_wall):
        probe = point + normal * (castle.lens_groove.depth_mm / 2.0)
        hits = mesh.ray.intersects_location(
            [[probe[0], probe[1], -100.0]], [[0.0, 0.0, 1.0]])[0]
        if len({round(float(h[2]), 6) for h in hits}) >= 4:
            deep += 1
    assert deep >= 36, f"the undercut is present at only {deep}/40 stations"


def test_subtraction_does_not_depend_on_tool_order(demo_front):
    """`(X \\ A) \\ B == X \\ (A u B)` — true of the algebra, and on the B-Rep
    path *not* true in practice: reordering tools flipped results between
    watertight and corrupt. Pinned here so the property is guarded, not assumed.
    """
    from guildmodel.core.model import (build_terraces, hinge_pockets,
                                       subtract_all, to_trimesh)
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights

    castle = _bare_params()
    heights = zone_heights(demo_front.partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM
    bare = build_terraces(demo_front.partition, heights)
    tools = hinge_pockets(demo_front.hinge_polys, castle, top)
    if len(tools) < 2:
        pytest.skip("needs at least two tools to reorder")

    forward = to_trimesh(subtract_all(bare, tools)).volume
    reverse = to_trimesh(subtract_all(bare, list(reversed(tools)))).volume
    assert forward == pytest.approx(reverse, rel=1e-9)
