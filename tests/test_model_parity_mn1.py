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


# ------------------------------------------------------------ eyewire bezel

@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_bezel_band_agrees_with_the_brep_kernel(fixture, request):
    """Terraces plus the rim chamfer, both kernels, same anchors.

    Compared on the material removed for the same reason as the groove: the
    band is a small fraction of the part, and a gate on the finished volume
    would tolerate the band being in the wrong place entirely.
    """
    from guildmodel.core.model import subtract_all, to_trimesh
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model.features import bezel_cutters as mesh_bezels
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights
    from guildmodel.core.solid.build import build_terraces as occ_terraces
    from guildmodel.core.solid.features import bezel_cutters as occ_bezels
    from guildmodel.core.solid.occ import cut_many, mesh_volume

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    heights = zone_heights(front.partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    occ_bare = occ_terraces(front.partition, heights, curved=False)
    occ_tools = occ_bezels(occ_bare, front.partition, castle, top)
    assert occ_tools, "the fixture has no rims to bezel"
    brep_removed = mesh_volume(occ_bare) - mesh_volume(cut_many(occ_bare,
                                                                occ_tools))

    mesh_bare = mesh_terraces(front.partition, heights)
    mesh_tools = mesh_bezels(to_trimesh(mesh_bare), front.partition, castle, top)
    assert len(mesh_tools) == len(occ_tools)
    banded = to_trimesh(subtract_all(mesh_bare, mesh_tools))
    mesh_removed = to_trimesh(mesh_bare).volume - banded.volume

    assert banded.is_watertight
    assert mesh_removed == pytest.approx(brep_removed, rel=0.04), (
        f"the bezel removes {mesh_removed:.3f} mm3 in the mesh kernel against "
        f"{brep_removed:.3f} in the B-Rep one")


# ------------------------------------------------------- splay and the scoop

#: The one combination where the kernels legitimately disagree, and why.
#:
#: The aviator's bridge keyhole is a decorative OUTLINE hole sitting on the
#: scoop's centreline, so several anchor rays pass straight through it. OCCT's
#: `surface_z_at` reports a miss as **0.0**, indistinguishable from "the surface
#: is at the anterior face", and the scoop then plunges the full thickness
#: across the opening. That is the identical defect that cut Gabriel's frame in
#: half through the pad splay (M-N0) — a miss read as solid material at z=0.
#:
#: The mesh path carries the neighbouring anchors across the gap instead, so the
#: scoop follows the surrounding surface over the opening rather than diving to
#: the floor. That is the behaviour we believe is correct, which is why this is
#: recorded as a divergence to resolve rather than papered over with a wider
#: tolerance. See `test_the_scoop_does_not_dive_through_a_decorative_opening`.
_KNOWN_DIVERGENCE = {("aviator_front", "bridge_relief")}


@pytest.mark.parametrize("feature", ["pad_splay", "bridge_relief"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_surface_features_agree_with_the_brep_kernel(fixture, feature, request):
    """The two features that read the surface beneath them, one at a time."""
    if (fixture, feature) in _KNOWN_DIVERGENCE:
        pytest.skip("known divergence — see _KNOWN_DIVERGENCE")
    from guildmodel.core.model import subtract_all, to_trimesh
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model.features import scoop_cutter, splay_cutter
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import build_terraces as occ_terraces
    from guildmodel.core.solid.build import zone_heights
    from guildmodel.core.solid.features import (scoop_cutter as occ_scoop,
                                                splay_cutter as occ_splay)
    from guildmodel.core.solid.occ import cut_many, mesh_volume

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    getattr(castle, feature).enabled = True
    params = getattr(castle, feature)
    heights = zone_heights(front.partition, castle, None)

    occ_bare = occ_terraces(front.partition, heights, curved=False)
    occ_build = occ_splay if feature == "pad_splay" else occ_scoop
    occ_tool = occ_build(occ_bare, front.partition.body, params)
    brep_removed = mesh_volume(occ_bare) - mesh_volume(cut_many(occ_bare,
                                                                [occ_tool]))

    mesh_bare = mesh_terraces(front.partition, heights)
    build = splay_cutter if feature == "pad_splay" else scoop_cutter
    tool = build(to_trimesh(mesh_bare), front.partition.body, params)
    cut = to_trimesh(subtract_all(mesh_bare, [tool]))
    mesh_removed = to_trimesh(mesh_bare).volume - cut.volume

    assert cut.is_watertight
    assert cut.body_count == 1, "a surface feature severed the frame"
    assert mesh_removed == pytest.approx(brep_removed, rel=0.06), (
        f"{feature}: mesh removes {mesh_removed:.3f} mm3 against the B-Rep "
        f"path's {brep_removed:.3f}")


def test_the_scoop_does_not_dive_through_a_decorative_opening(aviator_front):
    """Pins the divergence above, and which side of it we are on.

    Anchor rays that cross the aviator's bridge keyhole find nothing. Read as
    0.0 they mean "the surface is at the anterior face" and the scoop cuts the
    full thickness; carried from the neighbouring stations they mean "the
    surface continues", which is what a scoop running over an opening actually
    does.

    Asserted as a *floor on the cutter*, not as a volume, because the volume is
    the symptom and the cutter reaching z=0 is the defect.
    """
    from guildmodel.core.model import build_terraces, to_trimesh
    from guildmodel.core.model.features import scoop_cutter
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import zone_heights

    partition = aviator_front.partition
    assert any(partition.is_hole(r) for r in partition.body.interiors), (
        "this fixture is chosen for its decorative opening")

    castle = CastleParams()
    castle.bridge_relief.enabled = True
    heights = zone_heights(partition, castle, None)
    bare = build_terraces(partition, heights)
    cutter = to_trimesh(scoop_cutter(to_trimesh(bare), partition.body,
                                     castle.bridge_relief))

    floor = float(castle.bridge_relief.anterior_clamp_mm)
    assert cutter.bounds[0][2] >= floor - 0.05, (
        f"the scoop reaches z={cutter.bounds[0][2]:.3f}, below its own "
        f"anterior clamp of {floor} — it is diving through the opening")


@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_every_feature_at_once_is_one_verified_body(fixture, request):
    """What the maker actually clicks, on every drawing we own."""
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.project.schema import CastleParams

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.bridge_relief.enabled = True
    castle.lens_groove.enabled = True
    castle.eyewire_bezel.enabled = True

    mesh = to_trimesh(build_castle_model(front.partition, castle,
                                         front.hinge_polys))
    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict.problems


# ------------------------------------------------------------ edge features

def _brow(profile="chamfer"):
    """The M17 brow chamfer: over each eyewire, not across the bridge."""
    from guildmodel.core.project.schema import CastleParams, EdgeFeature

    castle = CastleParams()
    castle.edge_features = [EdgeFeature(
        id="brow", label="Brow", face="anterior", edge="outline",
        zones=["eyewire_superior_od"], profile=profile,
        width_mm=2.0, angle_deg=45.0, radius_mm=2.0)]
    return castle


@pytest.mark.parametrize("profile", ["chamfer", "fillet"])
def test_edge_features_agree_with_the_brep_kernel(demo_front, profile):
    """Both profiles, because they take different routes through the kernel:
    the chamfer's section is convex and the fillet's is not, so the fillet is
    the one that exercises `swept_profile`'s slab decomposition end to end."""
    from guildmodel.core.model import subtract_all, to_trimesh
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model.features import (resolved_edge_cutters as
                                                mesh_edges)
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights
    from guildmodel.core.solid.build import build_terraces as occ_terraces
    from guildmodel.core.solid.features import resolved_edge_cutters as occ_edges
    from guildmodel.core.solid.occ import cut_many, mesh_volume

    castle = _brow(profile)
    partition = demo_front.partition
    heights = zone_heights(partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    occ_bare = occ_terraces(partition, heights, curved=False)
    occ_tools = occ_edges(occ_bare, partition, castle, top)
    assert occ_tools, "the brow feature produced no spans; the fixture is wrong"
    brep_removed = mesh_volume(occ_bare) - mesh_volume(cut_many(occ_bare,
                                                                occ_tools))

    mesh_bare = mesh_terraces(partition, heights)
    mesh_tools = mesh_edges(to_trimesh(mesh_bare), partition, castle, top)
    assert len(mesh_tools) == len(occ_tools), "different number of spans"
    cut = to_trimesh(subtract_all(mesh_bare, mesh_tools))
    mesh_removed = to_trimesh(mesh_bare).volume - cut.volume

    assert cut.is_watertight
    assert mesh_removed == pytest.approx(brep_removed, rel=0.05), (
        f"{profile}: mesh removes {mesh_removed:.3f} mm3 against the B-Rep "
        f"path's {brep_removed:.3f}")


def test_the_fillet_removes_less_than_the_chamfer_it_would_collapse_to(demo_front):
    """A round-over is strictly shallower than the chamfer spanning the same
    corner, so if the slab decomposition ever regresses to a plain hull this
    goes the other way. The direct guard on the failure `swept_profile` exists
    to prevent."""
    from guildmodel.core.model import subtract_all, to_trimesh
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model.features import resolved_edge_cutters
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights

    partition = demo_front.partition
    removed = {}
    for profile in ("chamfer", "fillet"):
        castle = _brow(profile)
        heights = zone_heights(partition, castle, None)
        top = max(heights.values()) + SWEEP_MARGIN_MM
        bare = mesh_terraces(partition, heights)
        tools = resolved_edge_cutters(to_trimesh(bare), partition, castle, top)
        removed[profile] = (to_trimesh(bare).volume
                            - to_trimesh(subtract_all(bare, tools)).volume)

    assert removed["fillet"] < removed["chamfer"], (
        "the fillet removed at least as much as the chamfer — the concave "
        "profile is being hulled flat")


def test_neither_kernel_bezels_a_decorative_opening(aviator_front):
    """A decorative OUTLINE hole is a through-cut, not an eyewire.

    The aviator's bridge keyhole seats no lens, so there is no bevel for a rim
    band to make room for, and chamfering it thins a deliberately slender part
    of the frame. The lens groove has always skipped these (`lip_body`); the
    B-Rep bezel did not, which M-N1 parity exposed as 2 cutters against 3.

    Pinned on both kernels, because the whole value of the second one is that a
    disagreement like this becomes visible.
    """
    from guildmodel.core.model.features import bezel_cutters as mesh_bezels
    from guildmodel.core.model import build_terraces as mesh_terraces
    from guildmodel.core.model import to_trimesh
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights
    from guildmodel.core.solid.build import build_terraces as occ_terraces
    from guildmodel.core.solid.features import bezel_cutters as occ_bezels

    partition = aviator_front.partition
    holes = [r for r in partition.body.interiors if partition.is_hole(r)]
    lenses = [r for r in partition.body.interiors if not partition.is_hole(r)]
    assert holes and lenses, "the aviator must have both, or this proves nothing"

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    heights = zone_heights(partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    occ = occ_bezels(occ_terraces(partition, heights, curved=False), partition,
                     castle, top)
    mesh = mesh_bezels(to_trimesh(mesh_terraces(partition, heights)), partition,
                       castle, top)
    assert len(occ) == len(lenses), "the B-Rep path bezelled a decorative hole"
    assert len(mesh) == len(lenses), "the mesh path bezelled a decorative hole"


def test_the_mesh_anchor_ray_reports_a_miss_as_nan(demo_front):
    """Not 0.0. The B-Rep default of 0.0 is indistinguishable from "the surface
    sits on the anterior face", and that is precisely how the pad splay came to
    treat Gabriel's empty nose notch as solid material and cut the frame in
    half. A miss has to be loud."""
    import numpy as np

    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.model.kernel import surface_z_at
    from guildmodel.core.project.schema import CastleParams

    mesh = to_trimesh(build_castle_model(demo_front.partition, CastleParams(),
                                         demo_front.hinge_polys))
    far_away = [(10_000.0, 10_000.0)]
    assert np.isnan(surface_z_at(mesh, far_away)[0])

    inside = demo_front.partition.body.representative_point()
    hit = surface_z_at(mesh, [(inside.x, inside.y)])[0]
    assert not np.isnan(hit) and hit > 0.0


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
