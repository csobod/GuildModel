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
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: A part smaller than this is not a frame, it is debris from a failed boolean.
#: The demo frame is ~7,800 mm3 and the smallest real component (a base-curve
#: template) is a couple of hundred; 1 mm3 sits far below anything legitimate
#: while still being comfortably above float noise.
MIN_VOLUME_MM3 = 1.0


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


def _surface_problems(mesh) -> list[str]:
    """Say *how* a surface fails to close, because the two ways differ.

    A closed surface uses every edge exactly twice. Used once is a hole. Used
    three or more times is the opposite failure — surfaces overlapping along a
    shared edge — and it points at a different cause: a cutter grazing a face it
    should have crossed cleanly, rather than a boolean losing material.

    Worth separating because the bridge relief on the aviator fixture produces
    the second kind with **zero** edges of the first, and reporting it as "gaps"
    sent this investigation looking for missing material that was never missing.
    """
    try:
        counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)[1]
    except Exception:                                        # noqa: BLE001
        return ["This is not a closed solid. It will not export as a valid STL."]

    holes = int((counts == 1).sum())
    overlaps = int((counts > 2).sum())
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

    watertight = bool(getattr(mesh, "is_watertight", False))
    volume = float(getattr(mesh, "volume", 0.0) or 0.0)

    if not watertight:
        problems.extend(_surface_problems(mesh))
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
