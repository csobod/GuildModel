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


def build_component_mesh(spec: dict, *, resolution: float, solid: bool = False,
                         progress: ProgressFn = None):
    """Build one component's preview mesh from a plain build description.

    `spec` is what `MainWindow._build_spec` produces — geometry and parameters
    only, no live widget state — so any worker can build any component off the
    GUI thread without touching the active working set.

    Returns `(mesh, edges, core_guide)`:

    * `edges` is the solid's real topological edge polylines, or None on the
      raster path. The four Fusion-parity display modes are drawings *of the
      edges*, so a None here is what makes the viewer disable the combo.
    * `core_guide` is the temple injected-core bar bounds, or None for anything
      else.
    """
    mode = spec["mode"]
    if mode == "castle":
        return _build_castle(spec, resolution, solid, progress)
    if mode == "temple":
        return _build_temple(spec, resolution, progress)
    return _build_block(spec, resolution, progress)


def _build_castle(spec, resolution, solid, progress):
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_stage

    stage = spec.get("stage", "pockets")
    if solid and stage == "pockets":
        # The solid path only models the FULL posterior. The teaching stepper's
        # partial stages stay on the raster builder — they are a pedagogical
        # decomposition of the raster construction, not states the solid passes
        # through.
        return _build_castle_solid(spec, progress)

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
