"""`min_thickness_mm` has to mean the same thing in all three paths.

`EdgeFeature.min_thickness_mm` says "never leave the frame thinner than this
where the feature cuts". Only the raster obeyed it: `relief.edges.carve_edge_feature`
clamps each cell against the opposite face, and neither solid kernel had any
clamp at all.

That was survivable while the raster *was* the production CAM path. M-N4 made
the CAM post from a solid, so the number started reaching metal — and it was
not close. Demo frame, posterior brow chamfer, thinnest wall where the feature
cut, raster against mesh **before** the fix:

    4 mm wide, min 1.0 mm    1.000    0.789
    6 mm wide, min 1.0 mm    1.000    0.000
    6 mm wide, min 2.5 mm    2.500    0.000

Zero is a hole clean through a frame the maker asked to keep 2.5 mm of.

The clamp is `rings.thickness_limit`, read by ray at each station in both
kernels rather than per cell as the raster does. That is exactly as good
wherever the opposite face is flat under the run — every frame with nothing
cutting its front, which is the default — and the same reading every other
surface-riding feature in these kernels already trusts.
"""
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

#: A chamfer this wide takes more off the demo's brow than the wall can give.
BREACHING_WIDTH_MM = 6.0


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


def _castle(width_mm, min_thickness_mm):
    from guildmodel.core.project.schema import CastleParams, EdgeFeature

    castle = CastleParams()
    castle.edge_features = [EdgeFeature(
        id="brow", label="Brow chamfer", face="posterior", edge="outline",
        zones=["eyewire_superior_od"], profile="chamfer",
        width_mm=width_mm, angle_deg=45.0, blend_mm=2.0,
        min_thickness_mm=min_thickness_mm, mirror=True)]
    return castle


def _sampled(relief):
    """Cells whose neighbourhood the kernel's surface actually covers.

    A cell touching a hole in the sampled surface is not a thickness reading.
    The B-Rep leaves isolated pits near the body edge — its tessellation misses
    a cell centre and the rasteriser fills the background — and a cell beside
    one comes back part-height. That is the 0.3%-of-cells disagreement M-N4
    measured between the two solid kernels, and it has nothing to do with the
    feature: all four cells this excludes on the demo read 4.8 mm with no
    feature enabled, agree with the mesh and the raster to 0.1 mm, and each sits
    next to a cell the B-Rep reports as exactly 0.

    Named rather than budgeted, because "four cells are allowed to be wrong" is
    a number that rots and "a cell beside a gap is not a measurement" is a rule.
    It removes essentially nothing from the raster or the mesh.
    """
    from scipy.ndimage import binary_dilation

    return ~binary_dilation(relief.field.z <= 1e-9, iterations=1)


def _reliefs(front, castle):
    """The same castle down all three paths, on the CAM's own grid."""
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, clear_base_cache,
                                       solid_to_relief)

    part, hinges = front.partition, front.hinge_polys
    out = {"raster": build_castle_relief(part, castle, hinges,
                                         resolution=CUT_RES_MM),
           "mesh": mesh_cam_relief(part, castle, hinges,
                                   resolution=CUT_RES_MM)}
    clear_base_cache()
    out["brep"] = solid_to_relief(build_castle_solid(part, castle, hinges),
                                  part, castle, resolution=CUT_RES_MM)
    return out


@pytest.fixture(scope="module")
def bare(demo_front):
    """The frame with no edge feature, per kernel — the wall the feature is
    allowed to eat into.

    Needed because a kernel cannot be asked to *preserve* material it never
    had. The B-Rep reads 0.000 mm on five cells inside the band with no feature
    enabled at all: its tessellation does not cover those cell centres, which
    is the same 0.3%-of-cells disagreement M-N4 measured between it and the
    mesh. Taking a plain `min()` over the band scores that artifact as a
    breach, which is what the first version of this test did.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams

    return _reliefs(demo_front, CastleParams())


@pytest.mark.parametrize("min_thickness", [1.0, 2.5])
def test_no_kernel_cuts_through_a_wall_the_maker_reserved(demo_front, bare,
                                                          min_thickness):
    """The gate. A chamfer wider than the wall can give, on all three paths.

    Judged only where that kernel had at least `min_thickness` of material
    before the feature was switched on — anywhere thinner, the feature is not
    what made it thin and has nothing to preserve.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")

    castle = _castle(BREACHING_WIDTH_MM, min_thickness)
    cut = _reliefs(demo_front, castle)

    band = cut["raster"].feature_band
    assert band is not None and band.any(), "the feature carved nothing"

    for label in ("raster", "mesh", "brep"):
        had = bare[label].thickness()
        now = cut[label].thickness()
        judged = band & (had >= min_thickness) & _sampled(cut[label])
        assert judged.sum() > 100, (
            f"{label}: only {int(judged.sum())} cells had material to keep")
        got = float(now[judged].min())
        assert got >= min_thickness - 0.05, (
            f"{label} left {got:.3f} mm where the feature asked for "
            f"{min_thickness:.2f} mm, on {int((now[judged] < min_thickness - 0.05).sum())} "
            f"of {int(judged.sum())} cells")


def test_the_clamp_only_fires_where_it_is_needed(demo_front):
    """A feature that never reaches the limit must be untouched by it.

    The clamp truncates a section; applied when it should not be, it would
    flatten the bottom of every chamfer on the frame. So: a narrow chamfer,
    which clears the minimum easily, has to come out the same whether the
    minimum is 1 mm or zero.
    """
    from guildmodel.core.model import mesh_cam_relief
    from guildmodel.core.relief.castle import CUT_RES_MM

    part, hinges = demo_front.partition, demo_front.hinge_polys
    with_min = mesh_cam_relief(part, _castle(2.0, 1.0), hinges,
                               resolution=CUT_RES_MM)
    without = mesh_cam_relief(part, _castle(2.0, 0.0), hinges,
                              resolution=CUT_RES_MM)

    worst = float(np.abs(with_min.field.z - without.field.z).max())
    assert worst < 1e-9, (
        f"the clamp moved a cut that never reached it, by {worst:.3e} mm")


def test_the_shared_rule_is_the_one_both_kernels_read():
    """`thickness_limit` is a floor for a posterior cut and a ceiling for an
    anterior one. Both kernels import this rather than each spelling out the
    sign, which is the mistake the codebase keeps making with conventions."""
    from guildmodel.core.geometry.rings import thickness_limit

    opposite = np.array([0.0, 1.0, -2.0])
    np.testing.assert_allclose(thickness_limit(opposite, 1.5, True),
                               [1.5, 2.5, -0.5])
    np.testing.assert_allclose(thickness_limit(opposite, 1.5, False),
                               [-1.5, -0.5, -3.5])


def test_both_kernels_read_the_rule_from_one_place():
    """Structural, because two copies of a sign convention is how this project
    has repeatedly ended up with two answers — most recently the offset
    direction in `curves.OffsetCurve`, which was backwards until it was
    measured against OCCT."""
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "guildmodel" / "core"
    for path in (src / "model" / "features.py", src / "solid" / "features.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {alias.asname or alias.name
                 for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom)
                 for alias in node.names}
        assert "thickness_limit" in {n.replace("_thickness_limit",
                                               "thickness_limit")
                                     for n in names}, (
            f"{path.name} does not import the shared rule")
