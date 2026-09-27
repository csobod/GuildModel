"""Forming preview and formed STL (BUILDPLAN M18).

Qt-free and kernel-free: nothing here builds geometry. It takes the flat
model any kernel produced and moves its vertices through one smooth map —
the base curve, face form and bridge projection the maker applies after
cutting — so the front can be seen and printed as it will be worn. The CAM
cannot reach this package (`test_forming_m18` pins it by AST), the readiness
dot never reads a forming value, and the posted program is byte-identical
with forming on and off.
"""
from .presses import CUSTOM_LABEL, FLAT_LABEL, Press
from .presses import effective as press_rows
from .presses import find as find_press
from .presses import matching as matching_press
from .tessellate import FormingMesh, weld_for_file
from .thermoform import (DEFAULT_BAND_HALF_MM, DEFAULT_CREASE_ANGLE_DEG,
                         DEFAULT_CREASE_GAP_MM, EXPORT_FINE_MM,
                         EXPORT_REFINE_MM, PREVIEW_FINE_MM, PREVIEW_REFINE_MM,
                         SIMPLIFY_TOL_MM, BridgeGeometry, ThermoformMap,
                         bridge_band, bridge_geometry, diopters, form_trimesh,
                         formed_model, manifold_from_trimesh, radius_for,
                         refine, rim_apex, warp)

__all__ = [
    "CUSTOM_LABEL",
    "DEFAULT_BAND_HALF_MM",
    "DEFAULT_CREASE_ANGLE_DEG",
    "DEFAULT_CREASE_GAP_MM",
    "EXPORT_FINE_MM",
    "EXPORT_REFINE_MM",
    "FLAT_LABEL",
    "PREVIEW_FINE_MM",
    "PREVIEW_REFINE_MM",
    "SIMPLIFY_TOL_MM",
    "BridgeGeometry",
    "FormingMesh",
    "weld_for_file",
    "Press",
    "ThermoformMap",
    "bridge_band",
    "bridge_geometry",
    "diopters",
    "find_press",
    "form_trimesh",
    "formed_model",
    "manifold_from_trimesh",
    "matching_press",
    "press_rows",
    "radius_for",
    "refine",
    "rim_apex",
    "warp",
]
