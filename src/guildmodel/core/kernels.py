"""Which model kernels this install can actually offer (BUILDPLAN-NEW M-N4).

Three kernels build the frame front — the M17 raster heightfield, Manifold, and
OpenCASCADE — and only two of them ship. OCCT is **264 MB** installed (163 MB of
`OCP` plus 101 MB of `cadquery_ocp.libs`, measured; the buildplan's long-standing
"70 MB" was wrong and too kind), for a kernel that is no longer the default,
no longer posts G-code, and is no longer needed by any feature: every posterior
feature now loads zero OCP modules on the mesh path.

**It is demoted, not deleted.** The B-Rep is still the third opinion every
parity gate measures the mesh against, and building the same part two ways is
what has caught the silent defects this season — the nosepad spike, the whole-
ring bezel, the swept groove. So `cadquery-ocp` moved to an optional extra
(`pip install guildmodel[brep]`) and the option leaves Preferences unless it is
both installed and asked for.

**Asked for, not merely installed.** A developer has it installed permanently,
because the gates need it; that must not put a kernel in front of a maker that
the maker has no reason to choose. `GUILDMODEL_BREP=1` is the flag.

Nothing here imports OCP, or `core.solid`, which would import it — that is the
whole point. `find_spec` answers without loading.
"""
from __future__ import annotations

import importlib.util
import os

__all__ = ["BREP_ENV", "available_kernels", "brep_installed", "brep_offered",
           "resolve_kernel"]

#: Set to anything truthy to put the B-Rep back in Preferences, where it is
#: installed. The gates do not read this — they `importorskip("OCP")` — so a
#: developer only needs it to drive the kernel by hand from the GUI.
BREP_ENV = "GUILDMODEL_BREP"

#: The default when a stored preference names a kernel this install cannot
#: build. Not the raster: a maker who chose the B-Rep asked for an exact solid,
#: and the mesh is one — the two agree to a mean of 0.0025 mm across a fully
#: featured frame. Falling back to the raster would answer a request for
#: exactness with the approximation it was chosen over.
_SOLID_FALLBACK = "mesh"


def brep_installed() -> bool:
    """True when `cadquery-ocp` is importable, without importing it.

    `find_spec` is allowed to raise as well as return None — a half-removed
    package, a finder that objects, an `OCP` whose parent cannot be resolved.
    Any of those means "this install cannot build a B-Rep", which is the
    question being asked, so they answer it rather than propagating into
    whatever was merely trying to draw a Preferences dialog.
    """
    try:
        return importlib.util.find_spec("OCP") is not None
    except (ImportError, ValueError):
        return False


def brep_offered() -> bool:
    """True when the B-Rep should appear as a choice: installed *and* asked for."""
    return bool(os.environ.get(BREP_ENV)) and brep_installed()


def available_kernels() -> tuple[str, ...]:
    """The kernels this install can offer, in Preferences order."""
    return ("raster", "brep", "mesh") if brep_offered() else ("raster", "mesh")


def resolve_kernel(name: str, default: str = _SOLID_FALLBACK) -> str:
    """`name` if this install can build it, else something it can.

    A prefs file is not a contract and neither is an environment variable: a
    maker who set the B-Rep once, on a machine that had it, must not be unable
    to open their project on one that does not.
    """
    if name in ("raster", "mesh"):
        return name
    if name == "brep":
        # Installed is enough to *honor* an explicit choice; the flag only
        # governs whether it is offered in the first place.
        return "brep" if brep_installed() else default
    return default
