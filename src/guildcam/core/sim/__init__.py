"""Geometric cut simulation & verification (BUILDPLAN M5).

A headless material-removal model: sweep the tool's swept volume along every
cutting move of a posted program and record the lowest Z it reaches at each XY
cell (the "achieved floor" = the machined cut-piece top surface). Compare to the
intended relief surface to flag uncut and gouged regions. Geometric only — no
forces/feeds physics. The GUI Cut Simulation workspace renders this; the
completeness check gates the relief strategy against the Fusion control.
"""
from .toolsim import ToolProfile, achieved_floor, achieved_floor_grouped, densify
from .paths import (
    cutting_paths_from_program, cutting_paths_from_program_grouped,
    cutting_paths_from_ops,
)
from .report import Completeness, Gouge, CutReport, verify
from .playback import (
    FloorSnapshot, RemovalPlayback, simulate_removal, simulate_steps, steps_from_ops,
)
from .bed import (
    BedRemovalPart, ComponentSim, composite_bed_report, simulate_bed_removal,
    simulate_component,
)

__all__ = [
    "ToolProfile", "achieved_floor", "achieved_floor_grouped", "densify",
    "cutting_paths_from_program", "cutting_paths_from_program_grouped",
    "cutting_paths_from_ops",
    "Completeness", "Gouge", "CutReport", "verify",
    "ComponentSim", "composite_bed_report", "simulate_component",
    "BedRemovalPart", "simulate_bed_removal",
    "FloorSnapshot", "RemovalPlayback", "simulate_removal", "simulate_steps",
    "steps_from_ops",
]
