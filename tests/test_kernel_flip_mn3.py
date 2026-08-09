"""M-N3: parity over feature *combinations*, and the posted program's insulation.

Two claims, and they are different in kind.

**Parity.** Volume and silhouette, mesh against B-Rep, over the combination
matrix rather than one feature at a time. `compare_kernels` pairs those two for
the reason its docstring gives — volume is one number and two very different
parts can share it; the silhouette is what the part looks like from the front —
and combinations rather than singles because the whole-ring defect in risk 0 sat
behind four individually clean features for a milestone.

**The posted program.** M-N3 asks for "posted G-code byte-equivalence (it posts
from curves, so this should be exactly equal)". It is exactly equal, and tracing
*why* was worth more than the gate: the CAM never sees a kernel at all. Every
G-code path builds a `CastleRelief` from the partition and posts from that, so
the `model_kernel` preference has only ever changed the 3D viewer. The gate that
means something is therefore structural — `core.cam` must not be able to reach
either kernel — plus determinism of the posting itself.

*What is deliberately not here.* Now that `core.model.zmap` exists, the CAM
could post from a mesh-derived relief, and that comparison is **not**
byte-equal: on a fully featured frame the raster and both solid kernels differ
on ~60% of cells. That is the raster approximating chamfers the solids cut
exactly, so the solid answer is the better one — but it is a change to what a
machine cuts, and it belongs to M-N4 with its own measurements rather than
sliding in under a parity gate.
"""
import ast
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = Path(__file__).parents[1] / "src" / "guildmodel" / "config"

#: Volume agreement between the kernels, as a fraction. The two mesh curves
#: differently — OCCT tessellates trimmed surfaces at a chordal deviation,
#: Manifold extrudes the already-flattened partition polygon — so they are
#: allowed to differ by that chord deficit and nothing more.
#:
#: Worst measured over 12 configurations x 3 drawings: **0.0413%** (gabriel,
#: bezel+groove). This is 2.4x that — enough headroom for a drawing with tighter
#: curves, and still well inside a whole missing hinge pocket, which
#: `test_model_parity_mn1` measured at ~1.5% of the part.
VOLUME_TOL = 0.001

#: Silhouette agreement, same units. An order looser than volume, on purpose and
#: for a known reason: the mesh path extrudes the partition's *flattened*
#: polygons, which are inscribed in the splines the B-Rep extrudes, so its
#: shadow is the smaller of the two everywhere. The deficit is a property of the
#: drawing rather than of the features — it sits between 0.22% and 0.36% across
#: all 36 pairs and barely moves as features are switched on.
#:
#: Worst measured: **0.3609%** (gabriel, bridge relief). This is 2.1x that.
SILHOUETTE_TOL = 0.0075


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
    return _gdraw_front(tmp_path_factory, "gabriel")


#: The combinations M-N3 gates. Singles are already covered per feature in
#: `test_model_parity_mn1`; these are the pairs a real frame uses and the
#: three-of-four sets, which is where a feature that reads a surface another
#: feature already cut can go wrong.
COMBOS = [
    ("bezel+groove", ("eyewire_bezel", "lens_groove")),
    ("splay+bridge", ("pad_splay", "bridge_relief")),
    ("bezel+splay", ("eyewire_bezel", "pad_splay")),
    ("groove+bridge", ("lens_groove", "bridge_relief")),
    ("all but bezel", ("lens_groove", "pad_splay", "bridge_relief")),
    ("all but groove", ("eyewire_bezel", "pad_splay", "bridge_relief")),
    ("all four", ("eyewire_bezel", "lens_groove", "pad_splay",
                  "bridge_relief")),
]


@pytest.mark.parametrize("combo,features", COMBOS)
@pytest.mark.parametrize("fixture",
                         ["demo_front", "aviator_front", "gabriel_front"])
def test_the_kernels_agree_on_every_combination(fixture, combo, features,
                                                request):
    """The M-N3 parity gate. Both kernels must build the same part.

    Also asserts both verdicts are clean, which is now a real assertion rather
    than a formality: `verify_mesh` welds by position before judging, so it can
    see the class of defect that was invisible through M-N1.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model.compare import compare_kernels
    from guildmodel.core.project.schema import CastleParams

    front = request.getfixturevalue(fixture)
    castle = CastleParams()
    for name in features:
        getattr(castle, name).enabled = True

    result = compare_kernels(front.partition, castle, front.hinge_polys)
    mesh, brep = result["mesh"], result["brep"]
    assert "error" not in brep, brep.get("error")

    dv = abs(mesh["volume"] - brep["volume"]) / brep["volume"]
    ds = abs(mesh["silhouette"] - brep["silhouette"]) / brep["silhouette"]
    assert dv < VOLUME_TOL, f"{combo}: volume differs by {dv:.4%}"
    assert ds < SILHOUETTE_TOL, f"{combo}: silhouette differs by {ds:.4%}"

    assert mesh["ok"], mesh["problems"]
    assert brep["ok"], brep["problems"]
    assert mesh["bodies"] == 1 and brep["bodies"] == 1


def test_the_mesh_silhouette_is_the_inscribed_one(demo_front):
    """The sign of the silhouette difference, pinned as expected rather than
    tolerated.

    The mesh path extrudes the partition's *flattened* polygons; the B-Rep
    extrudes the splines those polygons are inscribed in. So the mesh shadow is
    the smaller one, always, and a run where it came out larger would mean
    something other than the chord deficit is at work.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model.compare import compare_kernels
    from guildmodel.core.project.schema import CastleParams

    result = compare_kernels(demo_front.partition, CastleParams(),
                             demo_front.hinge_polys)
    assert result["mesh"]["silhouette"] < result["brep"]["silhouette"]


# ------------------------------------------------------------- the posting

def test_the_cam_cannot_reach_either_model_kernel():
    """Why the posted program is byte-equal across the flip: it never sees one.

    Every G-code path builds a `CastleRelief` from the partition and posts from
    that. Pinned structurally because "the kernel does not affect the program"
    is only true while nothing in `core.cam` imports a kernel, and that is one
    convenience import away from being false — at which point the flip would
    silently change what a machine cuts.

    `core.model.zmap` deliberately points the other way: the CAM stays ignorant
    and a *caller* chooses which relief to hand it.
    """
    import guildmodel.core.cam as cam_pkg

    offenders = {}
    for path in sorted(Path(cam_pkg.__file__).parent.glob("*.py")):
        imported = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        bad = [m for m in imported
               if "solid" in m or m.endswith("model") or ".model." in m
               or "OCP" in m or "manifold" in m]
        if bad:
            offenders[path.name] = sorted(bad)
    assert not offenders, f"core.cam reaches a model kernel: {offenders}"


def test_the_shipped_default_is_the_mesh_kernel():
    """The flip itself (M-N3).

    Safe to make because the setting governs the 3D model and the edges drawn
    on it, and nothing a machine cuts — see the test above. What a new install
    gets is: the same part to within 0.0413% on volume and 0.3609% on
    silhouette, 20-55x faster, and with the feature edges the raster has none of.

    Existing files come too, via `prefs._migrate_kernel_flip`. `save()` writes
    every key, so a maker who has ever opened Preferences has `"raster"` frozen
    into their file whether they chose it or inherited it — without a migration
    the flip would reach new installs only.
    """
    from guildmodel.gui.mesh_build import KERNELS
    from guildmodel.gui.prefs import DEFAULTS

    assert DEFAULTS["model_kernel"] == "mesh"
    assert DEFAULTS["model_kernel"] in KERNELS


def test_an_unversioned_raster_file_is_carried_onto_the_mesh_kernel(
        tmp_path, monkeypatch):
    """The flip reaching people who already have a prefs file.

    A pre-M-N3 file cannot distinguish a chosen "raster" from an inherited one,
    so an unversioned one is treated as inherited and moved. `"brep"` is left
    alone — that can only have got there deliberately, and moving it would be
    the silent reassignment `_migrate_model_kernel` exists to prevent.

    Once only: the version is stamped on load and written back on save.
    """
    import json

    from guildmodel.gui import prefs as P

    path = tmp_path / "prefs.json"
    monkeypatch.setattr(P, "_FILE", path)

    path.write_text(json.dumps({"model_kernel": "raster"}), encoding="utf-8")
    loaded = P.load()
    assert loaded["model_kernel"] == "mesh"
    assert loaded["prefs_version"] == P.PREFS_VERSION

    # A deliberate B-Rep choice is not touched.
    path.write_text(json.dumps({"model_kernel": "brep"}), encoding="utf-8")
    assert P.load()["model_kernel"] == "brep"

    # And once the file is versioned, raster is a choice and stays.
    path.write_text(json.dumps({"model_kernel": "raster",
                                "prefs_version": P.PREFS_VERSION}),
                    encoding="utf-8")
    assert P.load()["model_kernel"] == "raster"


def test_posting_the_same_inputs_twice_is_byte_identical(demo_front):
    """Determinism, which is the other half of byte-equivalence being meaningful.

    A program that varies run to run would make any diff between two builds
    unreadable — and set iteration or dict ordering leaking into a toolpath is
    exactly the kind of thing that stays hidden until someone diffs two runs.
    """
    import yaml

    from guildmodel.core.cam.castle_ops import (generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief

    tools_cfg = yaml.safe_load(
        (CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    tools = tools_cfg.get("tools", tools_cfg)
    tool = tools.get("flat_3175", next(iter(tools.values())))

    castle = CastleParams()
    castle.eyewire_bezel.enabled = True

    def posted():
        relief = build_castle_relief(demo_front.partition, castle,
                                     demo_front.hinge_polys,
                                     resolution=CUT_RES_MM)
        ops = generate_castle_program(relief, castle, demo_front.hinge_polys,
                                      tool, tools_cfg=tools)
        post = GRBLPost(job_name="parity", material="acetate",
                        tool_diameter_mm=3.175, spindle_rpm=10000,
                        feed_rate_mmpm=750, plunge_rate_mmpm=333,
                        safe_z_mm=castle.stock.total_pad_height_mm + 5.0)
        write_castle_program(ops, post)
        return post.to_string()

    first, second = posted(), posted()
    assert first == second, "the posted program is not deterministic"
    assert "M30" in first and "nan" not in first.lower()
