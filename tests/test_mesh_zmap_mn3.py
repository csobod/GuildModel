"""Mesh -> Heightfield, the bridge that lets the mesh kernel post (M-N3).

**What was missing.** The `model_kernel` preference drove the 3D viewer and
nothing else: every G-code path calls `relief.castle.build_castle_relief`
regardless, because a Manifold model had no way to become the `Heightfield` the
CAM consumes. Stage 2 built that bridge for OCCT (`solid/zmap.py`) and never
wired it in, and only its first two lines were kernel-specific — the rest takes
vertices and faces. `core/zmap.py` is now the kernel-neutral half.

**What the numbers say.** Sampled on the CAM's own 0.15 mm grid, three drawings,
four configurations:

| within 5 um | mesh vs B-Rep | mesh vs raster | B-Rep vs raster |
|---|---|---|---|
| bare | 99.94-99.96% | 99.06-99.86% | 99.01-99.81% |
| eyewire bezel | 97.1-97.8% | 77.9-85.0% | 77.9-85.0% |
| all four features | 97.1-98.1% | 34.4-41.2% | 34.4-41.2% |

The last two columns track each other to two decimal places in every row. That
is the signature of the *raster* being the one that differs: both solid kernels
model a chamfer exactly and the raster approximates it, so they disagree with it
identically and agree with each other. Worst case against the raster is also
much smaller on the mesh — 0.33 mm against the B-Rep's 9.42 mm on the demo bare.

So these gate the mesh against the **B-Rep**, which models the same thing, and
against the B-Rep's own agreement with the raster, which is the incumbent bar.
Gating it directly against the raster would be gating it against a known
approximation.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


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


def _reliefs(front, castle):
    from guildmodel.core.model import build_castle_model, mesh_to_relief
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, clear_base_cache,
                                       solid_to_relief)

    part, hinges = front.partition, front.hinge_polys
    raster = build_castle_relief(part, castle, hinges, resolution=CUT_RES_MM)
    mesh = mesh_to_relief(build_castle_model(part, castle, hinges), part,
                          castle, resolution=CUT_RES_MM)
    clear_base_cache()
    brep = solid_to_relief(build_castle_solid(part, castle, hinges), part,
                           castle, resolution=CUT_RES_MM)
    return raster, mesh, brep


def _agreement(a, b, mask):
    d = (a.field.z - b.field.z)[mask]
    return float((np.abs(d) <= 0.005).mean()), float(np.sqrt((d ** 2).mean()))


def test_the_mesh_zmap_agrees_with_the_brep_one(demo_front):
    """The like-for-like gate: both sample the same solid on the same grid.

    99.95% of in-body cells within 5 um on a bare frame. Not 100% because the
    two arrive at the surface differently — OCCT meshes trimmed surfaces at a
    5 um chord, Manifold *is* the triangles — so they differ where a facet edge
    falls relative to a cell center.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams

    raster, mesh, brep = _reliefs(demo_front, CastleParams())
    within, rms = _agreement(mesh, brep, raster.inside)
    assert within > 0.99, f"only {within:.2%} of cells within 5 um, RMS {rms:.4f}"


def test_the_mesh_zmap_is_no_further_from_the_raster_than_the_brep_is(demo_front):
    """The incumbent bar, and the one that says the remaining gap is not ours.

    Whatever the mesh disagrees with the raster about, the B-Rep disagrees about
    too — the two columns match to two decimal places on every configuration
    measured. Asserted as "no worse", because being *closer* to an approximation
    is not the goal; tracking the other exact kernel is.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True
    raster, mesh, brep = _reliefs(demo_front, castle)

    mesh_within, _ = _agreement(mesh, raster, raster.inside)
    brep_within, _ = _agreement(brep, raster, raster.inside)
    assert mesh_within >= brep_within - 0.01, (
        f"mesh agrees with the raster on {mesh_within:.2%} of cells against "
        f"the B-Rep's {brep_within:.2%} — it should track the other kernel")


def test_the_masks_and_grid_do_not_depend_on_the_kernel(demo_front):
    """`inside`, `zone_index` and the grid come from the partition, so all three
    reliefs have to land cell-for-cell on top of each other. An off-by-one grid
    would make every comparison above meaningless rather than merely wrong."""
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams

    raster, mesh, brep = _reliefs(demo_front, CastleParams())
    for other in (mesh, brep):
        assert other.field.z.shape == raster.field.z.shape
        assert other.field.origin == pytest.approx(raster.field.origin)
        assert other.field.resolution == raster.field.resolution
        np.testing.assert_array_equal(other.inside, raster.inside)
        np.testing.assert_array_equal(other.zone_index, raster.zone_index)


def test_the_groove_lip_reaches_the_mask_on_the_mesh_path(demo_front):
    """With the lens groove on, the visible aperture is the rim lip rather than
    the drawn ring, and both paths have to mask against that same undersized
    body or they disagree over the whole annulus. Shared through
    `core.zmap.groove_body` so there is one answer, but pinned because it is the
    kind of thing a second implementation gets wrong silently."""
    from guildmodel.core.model import build_castle_model, mesh_to_relief
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    castle = CastleParams()
    castle.lens_groove.enabled = True
    part, hinges = demo_front.partition, demo_front.hinge_polys

    raster = build_castle_relief(part, castle, hinges, resolution=CUT_RES_MM)
    mesh = mesh_to_relief(build_castle_model(part, castle, hinges), part,
                          castle, resolution=CUT_RES_MM)

    assert mesh.groove is not None
    assert mesh.mask_body_override is not None
    np.testing.assert_array_equal(mesh.inside, raster.inside)


def test_the_rasterizer_is_kernel_neutral():
    """It takes vertices and faces. Pinned because it lived inside `core/solid`
    for a milestone, and that is the whole reason the mesh kernel could not
    reach the CAM: importing the bridge meant importing the kernel it replaces.

    **Module level only, as of M-N4.** `castle_relief` gained a branch that
    reaches the B-Rep when a maker asks for it, and it imports `solid.zmap`
    inside the function. This used to walk the whole tree and so read that as
    the coupling it exists to forbid. The coupling was never "the file mentions
    OCCT" — it was "importing this drags in 264 MB of kernel", and a lazy import
    in a branch nobody takes does not. `test_importing_the_bridge_does_not_load_occt`
    below checks the thing itself, so this half only has to hold the structure.
    """
    import ast
    import inspect

    from guildmodel.core import zmap

    imported = set()
    for node in ast.parse(inspect.getsource(zmap)).body:   # top level only
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("OCP" in m or "solid" in m for m in imported), (
        f"core.zmap imports the B-Rep kernel at module level: {sorted(imported)}")

    # A flat quad at z=2 over x 0..4, y 0..3, on a grid reaching x 6, y 5.
    quad = np.array([[0.0, 0.0, 2.0], [4.0, 0.0, 2.0], [4.0, 3.0, 2.0],
                     [0.0, 3.0, 2.0]])
    z = zmap.triangles_to_zmap(quad, np.array([[0, 1, 2], [0, 2, 3]]),
                               (0.0, 0.0), 10, 12, 0.5)
    assert z.shape == (10, 12)
    assert z[0, 0] == pytest.approx(2.0)      # under the quad
    assert z[6, 0] == pytest.approx(2.0)      # y = 3.0, its far edge
    assert z[-1, -1] == 0.0                   # clear of it: background
    assert z.max() == pytest.approx(2.0)


def test_importing_the_bridge_does_not_load_occt():
    """The rule the AST check above is a proxy for, measured directly.

    `core.zmap.castle_relief` can reach OpenCASCADE, because a maker may ask it
    to. What must stay true is that *importing* the module does not — otherwise
    every G-code build pays 264 MB for a branch it never takes, which is the
    coupling this module was split out of `core/solid` to break.

    A subprocess, because `sys.modules` is cumulative and by this point in a
    suite run OCP is long since loaded by something else.
    """
    import subprocess
    import sys
    import textwrap

    root = Path(__file__).parents[1]
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(root / "src")!r})
        import guildmodel.core.zmap                      # noqa: F401
        print(len([m for m in sys.modules if m.startswith("OCP")]))
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "0", (
        "importing core.zmap loaded OpenCASCADE")


@pytest.mark.parametrize("feature", ["eyewire_bezel", "pad_splay",
                                     "bridge_relief", "lens_groove"])
def test_these_features_post_without_loading_occt(feature):
    """The point of the bridge: a mesh can reach the CAM without the kernel it
    replaces. Run in a subprocess because `sys.modules` is cumulative — the
    first version of this measurement ran four features in one interpreter and
    reported three false positives.

    **The lens groove joined the list in M-N4.** It used to load 349 OCP
    modules through `geometry.rings.offset_aperture`, which samples the rim lip
    as an exact parallel of the authored curve and had no sampler but OCCT's.
    `curves.sample_curve` is that sampler now — de Boor and adaptive bisection,
    held to `Geom_OffsetCurve` at 1e-9 by `test_curve_eval_mn4`. The list is
    every posterior feature, and the answer is zero for all of them.
    """
    import subprocess
    import sys
    import textwrap

    root = Path(__file__).parents[1]
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(root / "src")!r})
        from pathlib import Path
        from guildmodel.core.io_import.dxf import import_curves
        from guildmodel.core.project.schema import ComponentKind, CastleParams
        from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                        derive_workspace)
        from guildmodel.core.model import build_castle_model, mesh_to_relief
        layers, curves = import_curves(Path({str(
            root / "tests/fixtures/demo/GuildDraw DXF Export.dxf")!r}))
        ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                                layers=layers, curves=curves)
        derive_workspace(ws)
        castle = CastleParams()
        getattr(castle, {feature!r}).enabled = True
        mesh_to_relief(build_castle_model(ws.partition, castle, ws.hinge_polys),
                       ws.partition, castle)
        print(len([m for m in sys.modules if m.startswith("OCP")]))
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "0", (
        f"{feature} pulled OCCT into a mesh-kernel G-code build")
