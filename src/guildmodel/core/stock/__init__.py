"""The stock engine (BUILDPLAN M21): a multi-interval Z-dexel grid, the tool
shapes that cut it, one cutter with a NumPy reference and a C++ fast path, the
posted program as poses, and the report against a target cast from the model.

Qt-free and kernel-free. `core.sim` becomes a facade over this package for one
release, so the GUI moves in steps.
"""
from .compare import StockReport, compare, interval_difference
from .cutting import (collisions, cut, cut_reference, extension_available, poses_from_path,
                      shank_shape, vertical_poses)
from .dexel import DEFAULT_K, DexelSnapshot, DexelStock
from .program import (Run, cutting_paths, machine_seconds, parse_program, poses_for_run,
                      spacing_for)
from .tools import Footprint, ToolShape

__all__ = [
    "DEFAULT_K", "DexelSnapshot", "DexelStock", "Footprint", "Run", "StockReport",
    "ToolShape", "collisions", "compare", "cut", "cut_reference", "cutting_paths",
    "extension_available", "interval_difference", "machine_seconds", "parse_program",
    "poses_for_run", "poses_from_path", "shank_shape", "spacing_for", "vertical_poses",
]
