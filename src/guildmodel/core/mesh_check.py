"""Is this mesh actually a solid object? (BUILDPLAN-NEW UI-0)

**Why this module exists.** The screenshot that opened the UI-0 work showed a
visibly corrupt model — a spike of material off the nosepad — under a status bar
reading "3D model ready" and an Inspector reading "Nothing flagged". Every gate
the app had was green, because every gate it had asked the *kernel* whether the
kernel was happy. OCCT's `BRepCheck_Analyzer` returns True for shapes with zero
volume, for shapes whose booleans left the topology in pieces, and for the
order-dependent corruption catalogued in BUILDPLAN-NEW §3.1.

The tessellation is the only oracle that has ever caught any of it, so it is the
one the interface reports from. A closed, consistently-wound mesh of positive
volume is the property a maker actually needs: it is what STL export requires,
what the CAM's stock model assumes, and what "this is a real object" means.

Kernel-neutral on purpose — it takes triangles. It works unchanged for the OCCT
path today and for the Manifold path M-N1 introduces, which is exactly the point:
the check must not be able to inherit the bias of whatever produced the mesh.

**It judges the welded surface, not the index table.** That distinction is the
whole of `welded_surface` below, and getting it wrong made this module blind to
an entire class of defect for the length of the M-N1 work — see there.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: A part smaller than this is not a frame, it is debris from a failed boolean.
#: The demo frame is ~7,800 mm3 and the smallest real component (a base-curve
#: template) is a couple of hundred; 1 mm3 sits far below anything legitimate
#: while still being comfortably above float noise.
MIN_VOLUME_MM3 = 1.0

#: Area at or below which a triangle carries no surface, mm2. The ones Manifold
#: emits are exactly zero; the bound is here so a collinear-but-not-identical
#: triangle is caught too. Far below any real feature: the narrowest thing this
#: app cuts is a lens groove around 0.6 mm wide.
_NO_AREA_MM2 = 1e-12


def welded_surface(mesh):
    """The mesh as an exporter sees it: coincident vertices are one vertex, and
    the faces carrying no surface are gone. `None` if it cannot be read.

    **Why welding is not optional.** A mesh kernel's invariant is that its
    output is a closed 2-manifold *by vertex index*, and Manifold's holds —
    every index edge has exactly two faces. It keeps that invariant across a
    place where the surface touches itself by giving the contact two coincident
    vertices with *different indices*. An STL has no index table: a slicer welds
    by position and sees the contact.

    So a check that counts index edges reports "Model verified" on a model that
    will not slice. That is UI-0's own complaint one layer down — a green gate
    that asked the producer whether the producer was happy — and it held for the
    length of the M-N1 work. The demo frame's bare base had 157 self-touching
    edges, the aviator 247, the gabriel 232, and this module said nothing about
    any of them (BUILDPLAN-NEW risk 0).

    **Dropping the dead faces is not optional either.** Welding is what exposes
    the zero-area stitches, and each one hands its long edge to the count a
    second time. Skipping the drop reported 194 on the demo base where the
    honest figure was 157 — and reported the *B-Rep* as defective too, which is
    how a measurement error nearly became a bug report against the shipped path.

    The weld tolerance is trimesh's own, about 1e-8 mm — six orders of magnitude
    tighter than the float32 grid (~4e-6 mm at a 50 mm coordinate) that produced
    false readings in both directions earlier in this investigation. It is a
    geometric weld, not a quantisation.

    It runs on every build the GUI does, so it was timed: **5.2 ms** on the fully
    featured demo frame (22,632 triangles), against 35 ms for the whole verdict
    and a 1.5 s build. Not a reason to make the check optional or lazy.
    """
    try:
        import trimesh

        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        if verts.ndim != 2 or faces.ndim != 2 or faces.shape[1] != 3:
            return None

        welded = trimesh.Trimesh(vertices=verts.copy(), faces=faces.copy(),
                                 process=False)
        welded.merge_vertices()

        faces = welded.faces
        if not len(faces):
            return welded
        repeated = ((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2])
                    | (faces[:, 0] == faces[:, 2]))
        corners = welded.vertices[faces]
        area = 0.5 * np.linalg.norm(
            np.cross(corners[:, 1] - corners[:, 0],
                     corners[:, 2] - corners[:, 0]), axis=1)
        dead = repeated | (area <= _NO_AREA_MM2)
        if not dead.any():
            return welded
        return trimesh.Trimesh(vertices=welded.vertices, faces=faces[~dead],
                               process=False)
    except Exception:                                        # noqa: BLE001
        return None


@dataclass(frozen=True)
class MeshVerdict:
    """What the tessellation says about a build, in the app's own words."""

    ok: bool
    #: Short, user-facing. "Model verified" or the first thing that is wrong.
    summary: str
    #: One line per problem, phrased for someone who is not a kernel engineer.
    problems: list[str] = field(default_factory=list)
    volume_mm3: float = 0.0
    watertight: bool = True

    @property
    def severity(self) -> str:
        return "info" if self.ok else "error"


def _surface_problems(holes: int, overlaps: int) -> list[str]:
    """Say *how* a surface fails to close, because the two ways differ.

    A closed surface uses every edge exactly twice. Used once is a hole. Used
    three or more times is the opposite failure — surfaces overlapping along a
    shared edge — and it points at a different cause: a cutter grazing a face it
    should have crossed cleanly, rather than a boolean losing material.

    Worth separating because the bridge relief on the aviator fixture produces
    the second kind with **zero** edges of the first, and reporting it as "gaps"
    sent this investigation looking for missing material that was never missing.
    """
    out = []
    if holes:
        out.append(
            f"The surface has gaps along {holes:,} edges, so this is not a "
            "closed solid. It will not export as a valid STL and any volume "
            "shown is unreliable.")
    if overlaps:
        out.append(
            f"The model overlaps itself along {overlaps:,} edges, where more "
            "than two surfaces meet. It will not export as a valid STL. This "
            "usually means a feature grazes a face instead of crossing it — "
            "try changing that feature's depth slightly.")
    if not out:                       # unwatertight for a reason we can't name
        out.append("This is not a closed solid. It will not export as a valid "
                   "STL.")
    return out


def verify_mesh(mesh) -> MeshVerdict:
    """Check a `trimesh.Trimesh` is a closed solid, and say so in plain terms.

    Closure is judged on the **welded** surface — see `welded_surface` for why
    the index table is the wrong thing to ask. Winding, volume and body count
    still come from the mesh as given: winding is an index property and means
    nothing once an edge carries more than two faces, and welding two genuinely
    severed pieces back together is a way to *lose* a real fault, not find one.

    Never raises: a verification that can itself fail the build would be one
    more way for the app to go dark. An unreadable mesh is reported as a
    problem, not thrown.
    """
    if mesh is None:
        return MeshVerdict(False, "No model was produced.",
                           ["The build finished without returning geometry."])

    problems: list[str] = []
    try:
        n_faces = len(mesh.faces)
    except Exception:                                        # noqa: BLE001
        return MeshVerdict(False, "The model could not be read.",
                           ["The build returned something that is not a mesh."])

    if n_faces == 0:
        return MeshVerdict(
            False, "The model came out empty.",
            ["A cut removed the whole part. This usually means a feature is "
             "far larger than the frame — check the most recently changed "
             "depth or width."])

    volume = float(getattr(mesh, "volume", 0.0) or 0.0)

    welded = welded_surface(mesh)
    if welded is None:            # unreadable as triangles; fall back to trimesh
        watertight = bool(getattr(mesh, "is_watertight", False))
        if not watertight:
            problems.extend(_surface_problems(0, 0))
    elif not len(welded.faces):   # every face was degenerate: no surface at all
        watertight = False
        problems.extend(_surface_problems(0, 0))
    else:
        counts = np.unique(welded.edges_sorted, axis=0, return_counts=True)[1]
        holes = int((counts == 1).sum())
        overlaps = int((counts > 2).sum())
        watertight = not holes and not overlaps
        if not watertight:
            problems.extend(_surface_problems(holes, overlaps))

    if not bool(getattr(mesh, "is_winding_consistent", True)):
        problems.append(
            "Parts of the surface face inward, so inside and outside are "
            "ambiguous.")
    if volume <= 0.0:
        problems.append(
            "The model encloses no space — its volume computes as "
            f"{volume:.1f} mm3.")
    elif volume < MIN_VOLUME_MM3:
        problems.append(
            f"Only {volume:.3f} mm3 of material is left; the part has very "
            "likely been cut away by a feature.")

    bodies = int(getattr(mesh, "body_count", 1) or 1)
    if bodies > 1:
        problems.append(
            f"The model is in {bodies} separate pieces. A frame component "
            "should be one connected body.")

    if problems:
        return MeshVerdict(False, problems[0], problems, volume, watertight)
    return MeshVerdict(True, "Model verified", [], volume, watertight)
