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

def test_the_mesh_path_supplies_edges(demo_front):
    """It did not until 2026-08-08, and the gap was pinned here as deliberate.

    The viewer's four display modes are drawings *of the edges*. A mesh has no
    topology to ask, so deriving them from dihedral angle was built and then
    backed out: against the demo frame with the bezel on it found 89% of what
    the B-Rep's tessellation calls a crease, but only **44%** of what it would
    have drawn had any counterpart there, the surplus being 90-degree creases
    running 14 mm across a terrace top that could not be accounted for.
    Unexplained lines on a maker's part are worse than no lines.

    They were **zero-area triangles**. Their normal is the zero vector and its
    angle to a unit one is exactly 90 degrees, so each read as a right-angle
    crease; they were also the stitches over the surface's self-contacts, and
    risk 0 took both away together. Re-measured with them gone, the detector
    draws 98.6% real against the B-Rep tessellation's own 98.2% and finds 100%
    of what that finds — `test_mesh_edges_mn2` holds the table.

    The predecessor of this test was written to fail the moment someone supplied
    edges without updating the reasoning, and that is exactly how it went.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import build_component_mesh

    spec = {"mode": "castle", "partition": demo_front.partition,
            "castle": CastleParams(), "hinge": list(demo_front.hinge_polys),
            "stage": "pockets"}
    mesh, edges, _guide = build_component_mesh(spec, resolution=0.8,
                                               kernel="mesh")
    assert len(mesh.faces) > 0
    assert edges, "no edges: the viewer disables three of its four modes"


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
        # Both solid kernels carry edges; the raster preview has none, because
        # at the export grid its triangle borders are grid seams rather than
        # edges of the frame.
        assert bool(edges) == (kernel in ("brep", "mesh")), kernel


def test_a_teaching_stage_stays_on_the_raster(demo_front):
    """The stepper's partial stages are a decomposition of the *raster*
    construction, not states a solid passes through. Asking for one on a
    modeled kernel must fall back rather than silently return the finished
    part, which would make the stepper look broken."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.gui.mesh_build import build_component_mesh

    spec = {"mode": "castle", "partition": demo_front.partition,
            "castle": CastleParams(), "hinge": list(demo_front.hinge_polys),
            "stage": "towers"}
    _mesh, edges, _guide = build_component_mesh(spec, resolution=0.8,
                                                kernel="mesh")
    assert edges is None, "a partial stage is a raster build and has no edges"


def test_an_unknown_kernel_name_falls_back_to_the_shipped_default(monkeypatch):
    """A prefs file hand-edited to a name we do not have must not crash the
    build; it must land on the path that always works.

    That path was the raster when this was written and is the mesh now
    (M-N4): `manifold3d` is a required dependency, the mesh is the default, and
    it is what the CAM posts from — while `cadquery-ocp` is an optional extra
    and the raster is the one kernel that approximates. The assertion is
    against `prefs.DEFAULTS` rather than a literal, so it pins the intent
    instead of the constant.
    """
    pytest.importorskip("PySide6.QtWidgets")
    from guildmodel.gui import prefs as P
    from guildmodel.gui.app import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._prefs = {"model_kernel": "nurbs-from-the-future"}
    assert MainWindow._model_kernel(window) == P.DEFAULTS["model_kernel"] == "mesh"

    window._prefs = {"model_kernel": "mesh"}
    assert MainWindow._model_kernel(window) == "mesh"
    window._prefs = {"model_kernel": "raster"}
    assert MainWindow._model_kernel(window) == "raster"


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

    # ...and someone who never turned it on is not carried anywhere: they get
    # whatever the shipped default is, which M-N3 moved from "raster" to "mesh".
    # Asserted against DEFAULTS rather than a literal, because the thing being
    # pinned is "the migration does not fire", not what the default happens to
    # be this milestone.
    path.write_text(json.dumps({"use_solid_model": False}), encoding="utf-8")
    assert P.load()["model_kernel"] == P.DEFAULTS["model_kernel"] != "brep"


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
