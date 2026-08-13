"""The relief the CAM posts from, built by a kernel instead of rasterized.

`relief_from_zmap` filled `field` and the groove fields and left everything
else at its default. That was enough for the parity gates, which only ever
compared surfaces, and it is not enough to post from: the CAM also reads
`surface_field`, `pocket_polys`, `feature_band`, `feature_max_slope_deg` and
`anterior`. A relief with those defaulted posts a program that machines the
pockets twice, skips the feature finish and cannot see the front — and a
surface comparison shows none of it. So each one is pinned here by what it is
*for*, not by whether it is populated.

The last test is the one the milestone rests on. Changing the CAM's surface
changes what a machine cuts, and the argument for doing it is that the two
independent solid kernels agree with each other where they both disagree with
the raster. That is a measurement, and it belongs in the suite rather than in a
paragraph.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

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
def gabriel_front(tmp_path_factory):
    return _front_from_gdraw(tmp_path_factory, "gabriel")


def _featured():
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.eyewire_bezel.enabled = True
    castle.bridge_relief.enabled = True
    return castle


@pytest.fixture(scope="module")
def gabriel_pair(gabriel_front):
    """(raster, mesh) reliefs of the fully featured gabriel, built once."""
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    part, hinges = gabriel_front.partition, gabriel_front.hinge_polys
    castle = _featured()
    return (build_castle_relief(part, castle, hinges, resolution=CUT_RES_MM),
            mesh_cam_relief(part, castle, hinges, resolution=CUT_RES_MM))


def test_the_pre_pocket_surface_is_a_second_build_not_the_same_array(gabriel_pair):
    """`surface_field` exists so the relief passes sail over an already-cut
    hinge pocket instead of diving back to its floor (M8). Handing back `field`
    would satisfy every type check and re-machine both pockets.

    Both kernels take exactly 2235 cells down 1.000 mm — the pocket depth — and
    they agree on which cells, which is the check that the second build
    happened *and* landed in the same place.
    """
    raster, mesh = gabriel_pair
    for label, relief in (("raster", raster), ("mesh", mesh)):
        assert relief.surface_field is not None, f"{label} has no pre-pocket surface"
        assert relief.surface_field is not relief.field
        cut = (relief.field.z - relief.surface_field.z) < -1e-6
        assert cut.any(), f"{label} pockets removed nothing"
        assert (relief.surface_field.z - relief.field.z)[cut].max() == \
            pytest.approx(1.0, abs=1e-6), f"{label} pocket is not 1 mm deep"

    r_cut = (raster.field.z - raster.surface_field.z) < -1e-6
    m_cut = (mesh.field.z - mesh.surface_field.z) < -1e-6
    assert int(r_cut.sum()) == int(m_cut.sum()) == 2235
    assert np.array_equal(r_cut, m_cut), "the two kernels pocket different cells"


def test_the_hinge_polygons_come_through(gabriel_pair, gabriel_front):
    """The Hinge Pockets op cuts `pocket_polys`. An empty list is a program
    that mills the pocket floors with the relief pass and never cuts them."""
    raster, mesh = gabriel_pair
    assert len(mesh.pocket_polys) == len(gabriel_front.hinge_polys) == 2
    assert len(mesh.pocket_polys) == len(raster.pocket_polys)


def test_the_feature_band_lands_where_the_raster_carved(gabriel_pair):
    """The band confines the fine-relief rings, so it is a cut-time decision as
    much as a quality one. Derived here by diffing a featured build against an
    unfeatured one, where the raster marks cells as it carves them — different
    routes to the same set, and they agree on 97%.

    Not exact, and the residue is explainable: the bridge scoop feathers to
    nothing at its tip, so the raster stops marking where its carve falls under
    a rounding while the solid is still cutting.
    """
    raster, mesh = gabriel_pair
    assert raster.feature_band is not None and mesh.feature_band is not None
    inter = int((raster.feature_band & mesh.feature_band).sum())
    union = int((raster.feature_band | mesh.feature_band).sum())
    assert inter / union > 0.95, f"IoU {inter / union:.3f}"
    assert mesh.feature_max_slope_deg == pytest.approx(
        raster.feature_max_slope_deg), "the fine pass would pick a different stepover"


def test_a_bare_frame_asks_for_no_band_and_no_anterior(gabriel_front):
    """The defaults have to stay the defaults: `None` for both is what keeps
    every project that predates M13/M17 on its original CAM path."""
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM

    relief = mesh_cam_relief(gabriel_front.partition, CastleParams(),
                             gabriel_front.hinge_polys, resolution=CUT_RES_MM)
    assert relief.feature_band is None
    assert relief.feature_max_slope_deg == 0.0
    assert relief.anterior is None
    assert relief.surface_field is not None       # there are still pockets


def test_the_front_face_appears_only_when_something_cuts_it(gabriel_front):
    """`anterior` is the lower envelope, so the mesh path gets it from the same
    pass as the surface rather than from a separate carve. Zero means the
    blank's untouched front, which is why it is reported as `None`."""
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.relief.castle import CUT_RES_MM

    castle = _featured()
    castle.eyewire_bezel.face = "anterior"
    relief = mesh_cam_relief(gabriel_front.partition, castle,
                             gabriel_front.hinge_polys, resolution=CUT_RES_MM)

    assert relief.anterior is not None, "an anterior bezel cut nothing off the front"
    assert relief.anterior.min() >= -1e-9, "the front face went below its datum"
    assert relief.anterior.max() > 0.1, "the anterior cut is implausibly shallow"
    assert (relief.thickness()[relief.inside] > 0).all(), "zero-thickness body"


def test_the_two_solid_kernels_agree_where_they_both_leave_the_raster(demo_front):
    """The measurement M-N4 step 1 rests on.

    Posting from a solid surface changes what a machine cuts, and the reason to
    do it is that the raster approximates chamfers both solid kernels cut
    exactly. That is only an argument if the two solid kernels — written
    independently, on unrelated geometry libraries — agree with each other
    *precisely where* they both diverge from the raster.

    On the featured demo they do, by two orders of magnitude. The same
    measurement on the gabriel: on the 8392 cells where the raster and the mesh
    differ by more than 0.05 mm, the two solid kernels sit 0.0045 mm apart on
    average while the raster is 0.4525 mm from the B-Rep.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, clear_base_cache,
                                       solid_to_relief)

    part, hinges = demo_front.partition, demo_front.hinge_polys
    castle = _featured()
    raster = build_castle_relief(part, castle, hinges, resolution=CUT_RES_MM)
    mesh = mesh_cam_relief(part, castle, hinges, resolution=CUT_RES_MM)
    clear_base_cache()
    brep = solid_to_relief(build_castle_solid(part, castle, hinges), part,
                           castle, resolution=CUT_RES_MM)

    disputed = raster.inside & (np.abs(raster.field.z - mesh.field.z) > 0.05)
    assert disputed.sum() > 1000, "the two barely disagree; the test proves nothing"

    solids_apart = np.abs(mesh.field.z - brep.field.z)[disputed].mean()
    raster_apart = np.abs(raster.field.z - brep.field.z)[disputed].mean()
    assert solids_apart < raster_apart / 20.0, (
        f"where the raster and the mesh disagree, the two solid kernels are "
        f"{solids_apart:.4f} mm apart and the raster is {raster_apart:.4f} mm "
        "from the B-Rep — not the margin this milestone was justified on")


# ------------------------------------------------- the program a maker gets

def test_the_demo_frame_posts_deterministically_through_the_shipped_path(
        demo_front):
    """Stage 2's last exit criterion, in the form the architecture left it.

    It was written as "the posted G-code for the demo frame is equivalent to
    today's within the agreed tolerance", against a Stage 2 that would have
    swapped a polygonal kernel for a curved one under an unchanged CAM. M-N3
    settled that half — byte-equal, and structurally so, because the CAM could
    not reach a kernel at all — and then **M-N4 deliberately changed what a
    machine cuts**, posting from the model kernel instead of the raster because
    the two solid kernels agree with each other where they both leave the
    raster. Equivalence to the old program is no longer the property to want.

    What is still worth gating is what replaced it: the demo frame posts, and
    posts the same way twice, through `zmap.castle_relief` — the one entry point
    every G-code path goes through — at the shipped default kernel.
    `test_kernel_flip_mn3`'s determinism gate predates that routing and still
    calls `build_castle_relief` directly, so it pins the raster's program and
    nobody's program pins this one.
    """
    import yaml

    from guildmodel.core.cam.castle_ops import (generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.zmap import castle_relief

    config = Path(__file__).parents[1] / "src" / "guildmodel" / "config"
    tools_cfg = yaml.safe_load((config / "tools.yaml").read_text(encoding="utf-8"))
    tools = tools_cfg.get("tools", tools_cfg)
    tool = tools.get("flat_3175", next(iter(tools.values())))

    part, hinges = demo_front.partition, demo_front.hinge_polys
    castle = _featured()

    def posted(kernel):
        relief = castle_relief(part, castle, hinges, kernel=kernel,
                               resolution=CUT_RES_MM)
        ops = generate_castle_program(relief, castle, hinges, tool,
                                      tools_cfg=tools)
        post = GRBLPost(job_name="mn4", material="acetate",
                        tool_diameter_mm=3.175, spindle_rpm=10000,
                        feed_rate_mmpm=750, plunge_rate_mmpm=333,
                        safe_z_mm=castle.stock.total_pad_height_mm + 5.0)
        write_castle_program(ops, post)
        return post.to_string()

    first, second = posted("mesh"), posted("mesh")
    assert first == second, "the posted program is not deterministic"
    assert "M30" in first and "nan" not in first.lower()

    # And it is genuinely the mesh's surface being cut. A silent fall back to
    # the raster is the exact failure M-N4 exists to prevent, and it would leave
    # every assertion above true — the raster posts a clean, deterministic
    # program too. The reliefs differ on ~60% of cells, so the programs must
    # differ; identical output here means the routing stopped working.
    assert posted("raster") != first, (
        "the mesh and raster kernels posted the same program — the model "
        "kernel is not reaching the CAM")
