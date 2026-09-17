"""Every component the app can build, it can export — and the oracle agrees.

The base-curve template could not be exported at all, and the reason came in two
halves that had to be found separately.

**The oracle was wrong.** `_snap_to_rings` conforms the rim to a *polyline*, so
three corners of one grid quad landing on a single straight segment come out
exactly collinear: a real grid triangle, 0.3-0.4 mm on a side, of zero area.
`welded_surface` dropped those as degenerate stitches, and dropping a face out of
a valid tiling unpairs its three edges — 86 of them on the gabriel block reported
as 258 gaps, on a solid trimesh, an STL round-trip and the genus all agreed was
closed. Flat parts got it on every build (their top and bottom are planes, so
collinear in XY is collinear in 3D); the frame front got it too, and could be
talked out of it by switching kernel, which is why it read as intermittent.

**There was no export path.** `_on_export_stl` gated on `_castle_ready()` and
hard-coded `castle_relief`, so it offered a base-curve template the one piece of
advice it could never take: go and draw five SCULPT section cuts.

These pin both halves against the shipped fixtures, at preview *and* export
resolution, because the count of collinear faces scales with the grid.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh

from guildmodel.core.mesh_check import verify_mesh, welded_surfaces
from guildmodel.core.project.schema import (BaseCurveBlockParams, CastleParams,
                                            TempleParams)
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
from guildmodel.gui.mesh_build import build_component_mesh

FIXTURES = Path(__file__).parent / "fixtures"

#: Preview, and the `export_resolution_mm` default. Both, because the collapse
#: is created by the conform and so gets denser as the grid refines: the gabriel
#: block carried 86 collinear faces at 0.30 mm and 254 at 0.15 mm.
RESOLUTIONS = (0.30, 0.15)


@pytest.fixture(scope="module")
def components(tmp_path_factory):
    """Every buildable component of the maker's own drawing, by kind.

    The gabriel fixture rather than a synthetic outline, because the collapse
    needs a real spline: it happens where the rim conform projects several grid
    vertices onto one straight segment of the chordal approximation, and a
    circle or a rectangle does not produce enough of them to be worth trusting.
    """
    path = tmp_path_factory.mktemp("gdraw") / "gabriel.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    out = {}
    for ws in build_workspaces_from_gdraw(path)[0]:
        if ws.enabled and (ws.castle_ready or ws.is_temple
                           or (ws.outline_poly is None
                               and ws.lens_od is not None)):
            out[ws.kind.value] = ws
    return out


def _spec(ws):
    """The build description `MainWindow._build_spec` produces, for a workspace."""
    if ws.castle_ready:
        return {"mode": "castle", "kind": ws.kind.value, "label": ws.label,
                "partition": ws.partition,
                "castle": ws.castle_params or CastleParams(),
                "hinge": list(ws.hinge_polys), "stage": "pockets"}
    if ws.is_temple:
        return {"mode": "temple", "kind": ws.kind.value, "label": ws.label,
                "outline": ws.outline_poly,
                "temple": ws.temple_params or TempleParams(),
                "hinge": list(ws.hinge_polys),
                "engraving": list(ws.engraving_curves)}
    return {"mode": "block", "kind": ws.kind.value, "label": ws.label,
            "lens": ws.lens_od,
            "block": ws.block_params or BaseCurveBlockParams()}


@pytest.mark.parametrize("resolution", RESOLUTIONS)
@pytest.mark.parametrize("fragment", ["frame_front", "temple_right",
                                      "base_curve_right"])
def test_every_buildable_component_verifies_on_the_raster(components, fragment,
                                                          resolution):
    """The gate that never existed.

    The suite's one end-to-end calibration ran `tessellate(build_castle_solid(…))`
    — the B-Rep path. Nothing asserted the *raster* mesher's output verifies, and
    the raster is the only path a flat part has and the one every export went
    through. So every base-curve template in the repo reported "will not export
    as a valid STL" and no test disagreed.
    """
    mesh, _, _ = build_component_mesh(_spec(components[fragment]),
                                      resolution=resolution, kernel="raster")
    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict.problems
    assert verdict.volume_mm3 > 1000.0


@pytest.mark.parametrize("resolution", RESOLUTIONS)
def test_the_mesher_emits_no_zero_area_faces(components, resolution):
    """Not merely "the verdict is green" — nothing degenerate is *produced*.

    The oracle fix alone would have turned the verdict green while the mesher
    kept emitting collinear triangles, so this measures the mesher directly:
    `_split_quads` flips a quad's diagonal where the default collapses.
    """
    mesh, _, _ = build_component_mesh(_spec(components["base_curve_right"]),
                                      resolution=resolution, kernel="raster")
    full, live = welded_surfaces(mesh)
    dead = len(full.faces) - len(live.faces)
    assert dead == 0, f"{dead} zero-area faces survived the diagonal choice"


def test_flipping_the_diagonal_does_not_move_the_surface(components):
    """`_split_quads` must be a re-triangulation, never a re-shaping.

    It is safe to flip only because the default collapses exactly when three
    corners are collinear, and three collinear points plus a fourth are always
    coplanar — so the quad is flat there and both splits cover the same region.
    If that ever stops holding, the frame front is being quietly re-cut and the
    demo-STL parity gate is measuring a different part. Volume and triangle
    count are the two things a pure re-triangulation cannot change.
    """
    from guildmodel.core.relief import castle as C

    spec = _spec(components["base_curve_right"])
    mesh, _, _ = build_component_mesh(spec, resolution=0.30, kernel="raster")

    flat = C._split_quads
    try:                              # the triangulation this replaced
        C._split_quads = lambda v, a, b, c, d: np.vstack([
            np.column_stack([a, b, c]), np.column_stack([c, b, d])])
        before, _, _ = build_component_mesh(spec, resolution=0.30,
                                            kernel="raster")
    finally:
        C._split_quads = flat

    assert len(mesh.faces) == len(before.faces)
    assert mesh.volume == pytest.approx(before.volume, abs=1e-6)
    # ...and the fix is doing something: the old split really was degenerate.
    assert len(welded_surfaces(before)[1].faces) < len(before.faces)


def test_a_base_curve_template_exports_a_loadable_solid(components, tmp_path):
    """The whole point, end to end: a file on disk that reloads as a solid.

    Genus is checked rather than only watertightness because it is the property
    that says the three M4 mounting holes came through as real through-holes:
    a sphere is 2, and each through-hole costs 2.
    """
    mesh, _, _ = build_component_mesh(_spec(components["base_curve_right"]),
                                      resolution=0.15, kernel="raster")
    path = tmp_path / "bc_template_right.stl"
    mesh.export(str(path))

    reloaded = trimesh.load(path)
    assert reloaded.is_watertight
    assert reloaded.body_count == 1
    assert reloaded.volume == pytest.approx(mesh.volume, rel=1e-6)
    assert reloaded.euler_number == 2 - 2 * BaseCurveBlockParams().hole_count


def test_the_export_worker_writes_every_component_kind(components, tmp_path):
    """`ExportWorker` itself, over a frame front, a temple and a base-curve
    template in one run.

    It used to take `(partition, castle, hinge_polys, …)` and call
    `castle_relief` directly, which is why the app's only `mesh.export` sat
    behind a castle-only gate. It now takes build specs and goes through
    `build_component_mesh`, so a component the viewer can draw is a component
    the maker can get a file for.
    """
    pytest.importorskip("PySide6.QtWidgets")

    from guildmodel.gui.app import ExportWorker

    chosen = [components[k] for k in ("frame_front", "temple_right",
                                     "base_curve_right") if k in components]
    specs = [_spec(ws) for ws in chosen]
    paths = [tmp_path / f"{ws.kind.value}.stl" for ws in chosen]

    worker = ExportWorker(specs, resolution=0.30, paths=paths)
    written, errors = [], []
    worker.finished.connect(written.extend)
    worker.error.connect(errors.append)
    worker.run()

    assert not errors, errors[:1]
    assert [Path(p) for p in written] == paths
    for path, ws in zip(paths, chosen):
        reloaded = trimesh.load(path)
        assert reloaded.is_watertight, f"{ws.kind.value} exported open"
        assert reloaded.volume > 1000.0


def test_the_kernel_reaches_the_exported_file(components):
    """A `mesh`/`brep` export must be the model's own triangles.

    `castle_relief` takes a kernel, builds a solid with it, and then rasterizes
    that solid back into a heightfield — so routing export through it meant the
    exact kernels were re-meshed through the grid on the way to disk, and the
    Inspector could read "Model verified" off a Manifold build while the maker
    received something else. Triangle count is the tell: the raster remesh of
    this frame runs to hundreds of thousands, the model's own to tens.
    """
    pytest.importorskip("manifold3d")

    spec = _spec(components["frame_front"])
    raster, _, _ = build_component_mesh(spec, resolution=0.15, kernel="raster")
    exact, _, _ = build_component_mesh(spec, resolution=0.15, kernel="mesh")

    assert len(exact.faces) * 4 < len(raster.faces), (
        "the mesh kernel is still being re-meshed through the raster grid")
    assert exact.volume == pytest.approx(raster.volume, rel=2e-3)
    assert verify_mesh(exact).ok


@pytest.mark.gui
def test_export_stl_is_offered_on_a_base_curve_tab(tmp_path, monkeypatch):
    """The action the maker actually reaches for, on the tab they reach for it.

    `_on_export_stl` gated on `_castle_ready()` and `_activate_workspace` set
    `_act_export.setEnabled(ws.castle_ready)`, so on a base-curve tab the menu
    item was greyed out and the shortcut did nothing — while Build 3D on the
    same tab worked. Both now ask `_workspace_buildable`, the one question.
    """
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    path = tmp_path / "gabriel.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    win._load_model(path)

    kinds = [ws.kind.value for ws in win._workspaces]
    for kind in ("frame_front", "temple_right", "base_curve_right"):
        assert kind in kinds, f"fixture has no {kind}"
        win._activate_workspace(kinds.index(kind))
        assert win._act_export.isEnabled(), f"Export STL greyed out on {kind}"
        assert win._act_export_all.isEnabled()

    # ...and the default filename follows the component, not the frame front.
    # Asked of the window rather than recomputed here: the point is what the
    # Save dialog is seeded with, and a test that rebuilds the name itself
    # agrees with any naming rule at all, including a broken one.
    win._activate_workspace(kinds.index("base_curve_right"))
    assert win._export_filenames()[win._active_ws] == "base_curve_right.stl"


def test_export_all_gives_every_component_its_own_file():
    """Components of the same kind must not share a filename.

    `build_project_from_gdraw` makes one base-curve template per LENS curve in
    the front, split right/left by centroid — so a drawing carrying decorative
    lens shapes has several of a kind. One such drawing builds ten components,
    four of them Base Curve R. Naming by `kind.value` alone gave those four one
    path: Export All built all ten, wrote four files, and logged a "Wrote …"
    line for each of the six it had just overwritten.

    Reproduced here on synthetic workspaces rather than that drawing, since the
    naming is what is under test and it needs no geometry. Seven components with
    four of one kind is the shape of the failure.
    """
    pytest.importorskip("PySide6.QtWidgets")

    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.app import MainWindow

    kinds = [ComponentKind.FRAME_FRONT, ComponentKind.TEMPLE_RIGHT,
             ComponentKind.TEMPLE_LEFT] + [ComponentKind.BASE_CURVE_RIGHT] * 4

    class _Project:
        _workspaces = [type("W", (), {"kind": k})() for k in kinds]
        _export_filenames = MainWindow._export_filenames

    names = _Project()._export_filenames()
    assert len(set(names)) == len(names), f"two components share a file: {names}"
    # The kinds that appear once keep their plain names, so the canonical
    # five-component project exports exactly what it always has.
    assert names[:3] == ["frame_front.stl", "temple_right.stl",
                         "temple_left.stl"]
    assert names[3:] == [f"base_curve_right_{n}.stl" for n in (1, 2, 3, 4)]


def _workspace(kind, **layers):
    """A bare ComponentWorkspace with the given layers, derived."""
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)
    base = {k: [] for k in ("OUTLINE", "LENS", "SCULPT", "HINGE", "ENGRAVING")}
    base.update(layers)
    ws = ComponentWorkspace(kind=getattr(ComponentKind, kind), label="", layers=base)
    derive_workspace(ws)
    return ws


_LENS = [(20, -12), (45, -12), (45, 12), (20, 12)]
_LENS2 = [(-45, -12), (-20, -12), (-20, 12), (-45, 12)]
_OUTLINE = [(-60, -20), (60, -20), (60, 20), (-60, 20)]
_SCULPT = [[(0, -20), (0, 20)], [(30, -20), (30, 20)]]


def test_a_half_drawn_front_is_not_silently_a_base_curve_block():
    """A half-drawn front from a maker's corpus: five SCULPT cuts, one LENS, no
    OUTLINE at all.

    It is not castle-ready, and `is_temple` wants an outline so it does not match
    either — so `_build_spec`'s final branch took it and built the **frame front**
    as a base-curve template. The frame-front tab rendered a lens block, and once
    Export STL started following buildability it would have written one out under
    that name. A component that cannot be built must say so, not become a
    different component.
    """
    from guildmodel.gui.app import MainWindow

    jude = _workspace("FRAME_FRONT", LENS=[_LENS], SCULPT=_SCULPT)
    assert jude.outline_poly is None and jude.lens_od is not None
    assert not jude.castle_ready and not jude.is_temple
    assert not MainWindow._is_block_workspace(jude)
    assert not MainWindow._workspace_buildable(jude)


def test_a_real_base_curve_template_still_builds():
    """The other side of that gate: a lone LENS and nothing else is exactly what
    `build_project_from_gdraw` hands a base-curve component, and all 96 templates
    in the frame library must keep building."""
    from guildmodel.gui.app import MainWindow

    block = _workspace("BASE_CURVE_RIGHT", LENS=[_LENS])
    assert MainWindow._is_block_workspace(block)
    assert MainWindow._workspace_buildable(block)


def test_a_matched_front_and_a_temple_are_not_blocks():
    from guildmodel.gui.app import MainWindow

    front = _workspace("FRAME_FRONT", OUTLINE=[_OUTLINE], LENS=[_LENS, _LENS2],
                       SCULPT=_SCULPT)
    temple = _workspace("TEMPLE_RIGHT", OUTLINE=[_OUTLINE])
    for ws in (front, temple):
        assert not MainWindow._is_block_workspace(ws)
        assert MainWindow._workspace_buildable(ws)


def test_the_blocked_reason_names_what_is_actually_missing():
    """"Draw the SCULPT zones" is the usual answer and the wrong one here,
    whose five section cuts are the one part of that drawing that is fine."""
    from guildmodel.gui.app import MainWindow

    jude = _workspace("FRAME_FRONT", LENS=[_LENS], SCULPT=_SCULPT)
    why = MainWindow._export_blocked_reason(jude)
    assert "OUTLINE" in why and "two LENS curves" in why
    assert "SCULPT" not in why

    no_zones = _workspace("FRAME_FRONT", OUTLINE=[_OUTLINE], LENS=[_LENS, _LENS2])
    assert "SCULPT" in MainWindow._export_blocked_reason(no_zones)
