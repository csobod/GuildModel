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
    """Defaults, which carry no finishing features."""
    from guildmodel.core.project.schema import CastleParams

    return CastleParams()


def _terraces_only(partition, castle):
    """The B-Rep terraces without footing blends, for a like-for-like compare.

    `castle_base` also applies the blends, so asking it for the whole base would
    compare a blended part against a plain one. The footing schedule has no
    enable switch, so the way to get terraces alone is to call `build_terraces`
    directly. `test_the_base_agrees_with_the_brep_kernel` covers the blends.
    """
    from guildmodel.core.solid.build import build_terraces, zone_heights

    return build_terraces(partition, zone_heights(partition, castle, None),
                          curved=False)


def _brep_base(partition, castle):
    """B-Rep terraces **plus** footing blends, polygonal.

    Not `castle_base`, which builds curved terraces off the authored splines —
    that is a real difference of about 0.017% and nothing to do with the blends.
    This assembles the same stage the mesh `build_base` does, from the same
    flattened polygons, so the comparison is about the sweep alone.
    """
    from guildmodel.core.solid.build import (SWEEP_MARGIN_MM, build_terraces,
                                             footing_bodies, zone_heights)
    from guildmodel.core.solid.occ import BooleanError, cut_many, fuse_all

    heights = zone_heights(partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM
    solid = build_terraces(partition, heights, curved=False)

    carves, fills, prisms = [], [], {}
    for edge in partition.edges:
        if not edge.canonical:
            continue
        try:
            fillet = castle.footing.for_edge(edge.canonical)
        except AttributeError:
            continue
        try:
            carve, fill = footing_bodies(partition, edge, heights, fillet, top,
                                         prisms)
        except BooleanError:
            continue
        if carve is not None:
            carves.append(carve)
        if fill is not None:
            fills.append(fill)

    if fills:
        solid = fuse_all([solid, *fills])
    return cut_many(solid, carves) if carves else solid


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


#: Volume agreement on the **footing blends**, as a fraction. Ten S-profile
#: bands swept along ten SCULPT cuts, and the two kernels sweep them
#: differently: the B-Rep path fits a spline through the 30 stations and
#: pipe-sweeps it, the mesh path treats the stations as a polyline. That is a
#: real chord difference, so this cannot be pinned at `VOLUME_TOL`.
#:
#: Measured at 0.00000% on all three fixtures — the cuts are gentle enough that
#: 30 stations inscribe the same curve either way. 1e-5 leaves three orders of
#: magnitude over what was observed and is still far tighter than losing any
#: single blend (the smallest is 47 mm3, 0.6% of the part).
BLEND_TOL = 1e-5


@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_base_agrees_with_the_brep_kernel(fixture, request):
    """Terraces with the ten footing blends in them — M-N1's named schedule
    risk, and the last feature to port.

    Checked on the finished base rather than on the bands, unlike the bezel and
    the groove, because a blend is not a small correction: the ten of them move
    97 mm3 onto the frame and take 174 mm3 off it, ~3% of the part. A gate on
    the total is sensitive enough here.
    """
    from guildmodel.core.model import build_base, to_trimesh
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights
    from guildmodel.core.solid.occ import mesh_volume

    front = request.getfixturevalue(fixture)
    castle = _bare_params()
    heights = zone_heights(front.partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    brep = mesh_volume(_brep_base(front.partition, castle))
    base = build_base(front.partition, castle, heights, top)
    mesh = to_trimesh(base)

    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(brep, rel=BLEND_TOL), (
        f"base volumes disagree: B-Rep {brep:.4f}, mesh {mesh.volume:.4f}")


@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_blends_actually_change_the_part(fixture, request):
    """The gate above would pass with every blend missing if the terraces
    happened to match, so pin that the blends do something.

    This is the lesson from the groove's backwards V and the bezel's
    part-volume tolerance: a parity gate has to be checked against a
    known-*wrong* input, and "no blends at all" is the wrong input closest to
    hand.

    **Measured in each direction, not as a net.** A blend fills the low side of
    a seam and carves the high side, so the two nearly cancel: on Gabriel the
    net is 33 mm3 while 116 goes on and 150 comes off. A gate on the net would
    have been a gate on the cancellation.
    """
    from guildmodel.core.model import (build_base, build_terraces,
                                       subtract_all, to_trimesh)
    from guildmodel.core.solid.build import SWEEP_MARGIN_MM, zone_heights

    front = request.getfixturevalue(fixture)
    castle = _bare_params()
    heights = zone_heights(front.partition, castle, None)
    top = max(heights.values()) + SWEEP_MARGIN_MM

    plain = build_terraces(front.partition, heights)
    blended = build_base(front.partition, castle, heights, top)

    part = to_trimesh(plain).volume
    added = to_trimesh(subtract_all(blended, [plain])).volume
    removed = to_trimesh(subtract_all(plain, [blended])).volume

    assert added > 0.005 * part, (
        f"the blends raise only {added:.3f} mm3 of {part:.3f}")
    assert removed > 0.005 * part, (
        f"the blends carve only {removed:.3f} mm3 of {part:.3f}")


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

@pytest.mark.parametrize("feature", ["pad_splay", "bridge_relief"])
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_surface_features_agree_with_the_brep_kernel(fixture, feature, request):
    """The two features that read the surface beneath them, one at a time.

    `(aviator_front, bridge_relief)` was skipped here as a known divergence
    until the B-Rep path stopped reading a missed anchor ray as 0.0. It was the
    mesh kernel that was right; the gate is now live on all six combinations.
    """
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


@pytest.mark.parametrize("kernel", ["mesh", "brep"])
@pytest.mark.parametrize("fixture", ["aviator_front", "gabriel_front"])
def test_the_scoop_does_not_dive_where_its_rays_find_nothing(fixture, kernel,
                                                             request):
    """The scoop marches up the centreline, which is where a frame is not solid.

    Both real drawings break the ray, for different reasons: seven of the
    aviator's thirteen stations sit inside its decorative keyhole, and two of
    Gabriel's run off the bottom of the bridge into the nose gap. Read as 0.0
    those misses mean "the surface is at the anterior face" and the section —
    which closes upward to `top` — takes the full thickness. Carried from the
    neighbouring stations they mean "the surface continues", which is what a
    scoop passing over an opening actually does.

    Asserted as a *floor on the cutter*, not as a volume, because the volume is
    the symptom and the cutter reaching z=0 is the defect. The volume gate above
    ran green on Gabriel throughout: its two missed stations are over air, so
    diving there removed almost nothing while still being wrong.

    Run against both kernels, since the whole point is that they now answer this
    the same way.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import zone_heights

    front = request.getfixturevalue(fixture)
    partition = front.partition
    castle = CastleParams()
    castle.bridge_relief.enabled = True
    heights = zone_heights(partition, castle, None)

    if kernel == "mesh":
        from guildmodel.core.model import build_terraces, to_trimesh
        from guildmodel.core.model.features import scoop_cutter

        bare = build_terraces(partition, heights)
        cutter = to_trimesh(scoop_cutter(to_trimesh(bare), partition.body,
                                         castle.bridge_relief))
        z_min = float(cutter.bounds[0][2])
    else:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib

        from guildmodel.core.solid.build import build_terraces as occ_terraces
        from guildmodel.core.solid.features import scoop_cutter as occ_scoop

        bare = occ_terraces(partition, heights, curved=False)
        box = Bnd_Box()
        BRepBndLib.Add_s(occ_scoop(bare, partition.body,
                                   castle.bridge_relief), box)
        z_min = float(box.CornerMin().Z())

    floor = float(castle.bridge_relief.anterior_clamp_mm)
    assert z_min >= floor - 0.05, (
        f"the {kernel} scoop reaches z={z_min:.3f}, below its own anterior "
        f"clamp of {floor} — it is diving where its rays found nothing")


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


@pytest.mark.parametrize("kernel", ["mesh", "brep"])
def test_an_anchor_ray_reports_a_miss_as_nan(kernel, demo_front):
    """Not 0.0, on either kernel.

    0.0 is indistinguishable from "the surface sits on the anterior face", and
    that is precisely how the pad splay came to treat Gabriel's empty nose notch
    as solid material and cut the frame in half, and how the bridge scoop came
    to plunge through the aviator's keyhole. A miss has to be loud.

    The B-Rep path defaulted to 0.0 until the scoop fix; the two kernels now
    disagree about nothing here, which is why this is one parametrized test
    rather than a mesh-side rule the other side is free to ignore.
    """
    import numpy as np

    from guildmodel.core.project.schema import CastleParams

    if kernel == "mesh":
        from guildmodel.core.model import build_castle_model, to_trimesh
        from guildmodel.core.model.kernel import surface_z_at

        part = to_trimesh(build_castle_model(demo_front.partition,
                                             CastleParams(),
                                             demo_front.hinge_polys))
    else:
        from guildmodel.core.solid.build import zone_heights
        from guildmodel.core.solid.build import build_terraces as occ_terraces
        from guildmodel.core.solid.occ import surface_z_at

        part = occ_terraces(demo_front.partition,
                            zone_heights(demo_front.partition, CastleParams(),
                                         None), curved=False)

    assert np.isnan(surface_z_at(part, [(10_000.0, 10_000.0)])[0])

    inside = demo_front.partition.body.representative_point()
    hit = surface_z_at(part, [(inside.x, inside.y)])[0]
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
