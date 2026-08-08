"""One builder for every component's 3D preview.

There used to be three. `MeshWorker` built a frame front and knew about the
B-Rep solid path; `FlatMeshWorker` built a temple or a base-curve block;
`MultiMeshWorker` built *all* components for the Build 3D toolbar button and
carried its own second copy of both — a copy that had never been given the solid
branch.

That gap was the whole of the 2026-08-07 review's finding 2. Build 3D went
through `MultiMeshWorker`, so it always returned raster meshes with no edges;
the viewer correctly saw no edges, disabled the display-mode combo and pinned it
to Shaded. Changing a *parameter* went through `MeshWorker` instead and did
build a solid, which is why the dropdown looked broken only sometimes.

So the fix is not "add the solid branch to the third worker" — that leaves three
copies and the next feature lands in one or two of them. The workers keep their
own signals and threading, and all of them call `build_component_mesh` here.

Deliberately Qt-free: this module is importable and testable without a display,
and it defers the heavy imports (OCP is ~70 MB) to call time.
"""
from __future__ import annotations

from typing import Callable, Optional

ProgressFn = Optional[Callable[[str, float], None]]

#: The three ways to build a frame front, newest last.
#:
#: * `raster` — the M17 heightfield. No edges, and the resolution settings apply.
#: * `brep` — OpenCASCADE (BUILDPLAN Stage 2). Exact, and the reason
#:   BUILDPLAN-NEW exists: see its §3 for what it costs.
#: * `mesh` — Manifold (BUILDPLAN-NEW M-N1). Agrees with `brep` on every parity
#:   gate and builds the base in 2.4 s against 12.7 s.
#:
#: All three are kept while the migration runs, because being able to build the
#: same part three ways is what has caught every silent defect this season.
KERNELS = ("raster", "brep", "mesh")

#: Preview grid step for an engraved temple. The engraving v-groove is ~0.5 mm
#: wide, so at the frame-front preview resolution (0.3 mm) it spans <2 cells and
#: the 3D groove looks blocky. A temple is a small part (a ~135 mm strip), so
#: refining the WHOLE temple to this step still builds in ~0.5 s while the big
#: frame front stays coarse.
ENGRAVE_PREVIEW_RES_MM = 0.1


def temple_preview_res(base_res: float, engraving) -> float:
    """The preview grid step for a temple: refined to `ENGRAVE_PREVIEW_RES_MM`
    when it carries engraving (so the grooves aren't pixellated), else the coarse
    `base_res`. Never coarsens a user resolution that is already finer."""
    return min(base_res, ENGRAVE_PREVIEW_RES_MM) if engraving else base_res


def build_component_mesh(spec: dict, *, resolution: float,
                         kernel: str = "raster", progress: ProgressFn = None):
    """Build one component's preview mesh from a plain build description.

    `spec` is what `MainWindow._build_spec` produces — geometry and parameters
    only, no live widget state — so any worker can build any component off the
    GUI thread without touching the active working set.

    `kernel` is one of `KERNELS` and applies to the frame front only; a temple
    and a base-curve block are flat parts the raster builds exactly.

    Returns `(mesh, edges, core_guide)`:

    * `edges` is the part's feature edge polylines, or None on the raster path.
      The four Fusion-parity display modes are drawings *of the edges*, so a
      None here is what makes the viewer disable the combo.
    * `core_guide` is the temple injected-core bar bounds, or None for anything
      else.
    """
    mode = spec["mode"]
    if mode == "castle":
        return _build_castle(spec, resolution, kernel, progress)
    if mode == "temple":
        return _build_temple(spec, resolution, progress)
    return _build_block(spec, resolution, progress)


def _build_castle(spec, resolution, kernel, progress):
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_stage

    stage = spec.get("stage", "pockets")
    if kernel != "raster" and stage == "pockets":
        # The modelled paths only build the FULL posterior. The teaching
        # stepper's partial stages stay on the raster builder — they are a
        # pedagogical decomposition of the raster construction, not states a
        # solid passes through.
        builder = _build_castle_mesh if kernel == "mesh" else _build_castle_solid
        return builder(spec, progress)

    relief = build_castle_stage(
        spec["partition"], spec["castle"], spec["hinge"],
        stage=stage, resolution=resolution, progress=progress)
    return build_castle_mesh(relief, progress=progress), None, None


def _build_castle_solid(spec, progress):
    """The B-Rep path: a solid, tessellated with its real edges."""
    from guildmodel.core.solid import build_castle_solid
    from guildmodel.core.solid.tessellate import tessellate

    solid = build_castle_solid(
        spec["partition"], spec["castle"], spec["hinge"], progress=progress)
    if progress is not None:
        progress("Tessellating", 0.95)
    tess = tessellate(solid)
    return tess.to_trimesh(), tess.edges, None


def _build_castle_mesh(spec, progress):
    """The Manifold path: closed by construction, and **no edges yet**.

    No tessellation step, because there is nothing to tessellate — the model is
    already triangles, and `to_trimesh` only re-indexes them through the
    library's own merge map.

    `edges=None` costs the maker three of the four display modes when this
    kernel is selected, so it is a deliberate choice rather than an oversight.
    Deriving them from dihedral angle was built and then backed out on its own
    measurements: it finds 89% of what the B-Rep's tessellation calls a crease,
    so it misses little, but only 44% of what it would *draw* has a counterpart
    there — and the surplus is real, manifold geometry of this mesh that could
    not be accounted for. Drawing unexplained lines on the part is worse than
    drawing none. BUILDPLAN-NEW §8.2 carries the figures.
    """
    from guildmodel.core.model import build_castle_model, to_trimesh

    model = build_castle_model(
        spec["partition"], spec["castle"], spec["hinge"], progress=progress)
    return to_trimesh(model), None, None


def _build_temple(spec, resolution, progress):
    from guildmodel.core.relief.castle import build_castle_mesh
    from guildmodel.core.relief.flat import (
        build_temple_relief, place_temple_on_blank, temple_core_guide)

    temple = spec["temple"]
    outline, hinge, eng = place_temple_on_blank(
        spec["outline"], spec["hinge"], spec["engraving"],
        temple.blank_length_mm, stock_side=temple.stock_side,
        snap=temple.snap_to_blank_end)
    relief = build_temple_relief(
        outline, temple, hinge, eng,
        resolution=temple_preview_res(resolution, eng), progress=progress)
    guide = temple_core_guide(outline, hinge, temple).bounds
    return build_castle_mesh(relief, progress=progress), None, guide


def _build_block(spec, resolution, progress):
    from guildmodel.core.relief.castle import build_castle_mesh
    from guildmodel.core.relief.flat import build_block_relief

    relief = build_block_relief(
        spec["lens"], spec["block"], resolution=resolution, progress=progress)
    return build_castle_mesh(relief, progress=progress), None, None
