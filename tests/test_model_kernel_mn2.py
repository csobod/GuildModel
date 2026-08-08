"""The mesh kernel reaches the app, and brings edges with it (M-N2).

Three things have to hold before a maker can pick this kernel in Preferences
and get what they expect: the flag reaches every build path, the viewer's edge
display modes keep working, and someone who had already switched the B-Rep path
on is not quietly moved back to the raster by the upgrade.
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


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / "aviator.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "aviator").iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


# ----------------------------------------------------------------- the edges

def test_the_mesh_path_reports_no_edges_rather_than_guessing(demo_front):
    """A deliberate gap, pinned so it stays deliberate.

    The viewer's four Fusion-parity display modes are drawings *of the edges*,
    and the B-Rep path supplies its real topological ones. A mesh has no
    topology to ask, so deriving them from dihedral angle was built — and then
    backed out on its own measurements.

    Against the demo frame with the bezel on: the detector found 89% of what
    the B-Rep's own tessellation calls a crease, so it was missing little. But
    only 44% of the length it would have *drawn* had any counterpart there, and
    the surplus was real, manifold, watertight geometry of this mesh that could
    not be accounted for — 90-degree creases running 14 mm across a terrace top.
    Unexplained lines on the maker's part are worse than no lines.

    So the mesh kernel costs three display modes for now, the viewer says so,
    and this test fails the moment someone supplies edges without also updating
    the reasoning. BUILDPLAN-NEW §8.2 carries the figures.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import build_component_mesh

    spec = {"mode": "castle", "partition": demo_front.partition,
            "castle": CastleParams(), "hinge": list(demo_front.hinge_polys),
            "stage": "pockets"}
    mesh, edges, _guide = build_component_mesh(spec, resolution=0.8,
                                               kernel="mesh")
    assert len(mesh.faces) > 0
    assert edges is None, (
        "the mesh path now supplies edges — good, but §8.2 and "
        "`_build_castle_mesh` still say it does not")


# ----------------------------------------------------------------- the flag

def test_every_kernel_name_builds(demo_front):
    """`KERNELS` is what Preferences offers; each entry has to actually work."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import KERNELS, build_component_mesh

    spec = {"mode": "castle", "partition": demo_front.partition,
            "castle": CastleParams(), "hinge": list(demo_front.hinge_polys),
            "stage": "pockets"}
    for kernel in KERNELS:
        mesh, edges, _guide = build_component_mesh(spec, resolution=0.8,
                                                   kernel=kernel)
        assert len(mesh.faces) > 0, f"{kernel} built nothing"
        # Only the B-Rep path carries edges today — see
        # `test_the_mesh_path_reports_no_edges_rather_than_guessing`.
        assert (edges is not None) == (kernel == "brep")


def test_a_teaching_stage_stays_on_the_raster(demo_front):
    """The stepper's partial stages are a decomposition of the *raster*
    construction, not states a solid passes through. Asking for one on a
    modelled kernel must fall back rather than silently return the finished
    part, which would make the stepper look broken."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import build_component_mesh

    spec = {"mode": "castle", "partition": demo_front.partition,
            "castle": CastleParams(), "hinge": list(demo_front.hinge_polys),
            "stage": "towers"}
    _mesh, edges, _guide = build_component_mesh(spec, resolution=0.8,
                                                kernel="mesh")
    assert edges is None, "a partial stage is a raster build and has no edges"


def test_an_unknown_kernel_name_falls_back_to_the_raster(monkeypatch):
    """A prefs file hand-edited to a name we do not have must not crash the
    build; it must land on the path that always works."""
    pytest.importorskip("PySide6.QtWidgets")
    from guildmodel.gui.app import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._prefs = {"model_kernel": "nurbs-from-the-future"}
    assert MainWindow._model_kernel(window) == "raster"

    window._prefs = {"model_kernel": "mesh"}
    assert MainWindow._model_kernel(window) == "mesh"


# ------------------------------------------------------------- the migration

def test_an_existing_solid_user_is_not_moved_back_to_the_raster(tmp_path,
                                                                monkeypatch):
    """Prefs are restored over the schema defaults on every launch, so a new
    key with a new default silently undoes a maker's choice. `use_solid_model`
    was that choice until M-N2."""
    import json

    from guildmodel.gui import prefs as P

    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"use_solid_model": True}), encoding="utf-8")
    monkeypatch.setattr(P, "_FILE", path)
    assert P.load()["model_kernel"] == "brep"

    # ...and a choice made since wins over the old key.
    path.write_text(json.dumps({"use_solid_model": True,
                                "model_kernel": "mesh"}), encoding="utf-8")
    assert P.load()["model_kernel"] == "mesh"

    # ...and someone who never turned it on stays where they are.
    path.write_text(json.dumps({"use_solid_model": False}), encoding="utf-8")
    assert P.load()["model_kernel"] == "raster"


# --------------------------------------------------------------- the A/B tool

def test_the_kernel_comparison_reports_both_sides(demo_front):
    """`--diag-kernels`. The migration's claim is that the two kernels build the
    same part; this is how that gets re-checked on a drawing nobody wrote a
    fixture for."""
    from guildmodel.core.model.compare import compare_kernels, format_report
    from guildmodel.core.project.schema import CastleParams

    result = compare_kernels(demo_front.partition, CastleParams(),
                             demo_front.hinge_polys)
    assert result["mesh"]["ok"]
    assert result["mesh"]["bodies"] == 1
    assert "error" not in result["brep"], result["brep"]["error"]

    # Volume and silhouette both, because one number can hide a feature in the
    # wrong place — see the module docstring.
    for key in ("volume", "silhouette"):
        mesh, brep = result["mesh"][key], result["brep"][key]
        assert abs(mesh - brep) / brep < 0.01, (
            f"{key}: mesh {mesh:.4f} against B-Rep {brep:.4f}")

    report = format_report(result)
    assert "silhouette" in report and "verified" in report
