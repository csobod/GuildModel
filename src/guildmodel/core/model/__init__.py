"""Mesh-domain model kernel (BUILDPLAN-NEW M-N1).

The replacement for `core/solid`'s construction layer. Same inputs, same part,
built out of triangles instead of trimmed surfaces — see `kernel.py` for why
that swap is the structural fix rather than another bandaid.

Cheap to import: `manifold3d` is a few MB against OCP's ~70, so unlike
`core.solid` this package does not have to be kept off the startup path.
"""
from .build import (build_base, build_castle_model, build_terraces,
                    footing_tools, hinge_pockets)
from .edges import CREASE_ANGLE_DEG, feature_edges
from .kernel import (ManifoldError, cross_section, drop_degenerate, extrude,
                     hull_chain, intersect_all, subtract_all, to_trimesh,
                     union_all, volume)
from .zmap import mesh_cam_relief, mesh_to_relief, mesh_to_zmap

__all__ = [
    "CREASE_ANGLE_DEG",
    "ManifoldError",
    "build_base",
    "build_castle_model",
    "build_terraces",
    "cross_section",
    "extrude",
    "feature_edges",
    "footing_tools",
    "hinge_pockets",
    "drop_degenerate",
    "hull_chain",
    "intersect_all",
    "mesh_cam_relief",
    "mesh_to_relief",
    "mesh_to_zmap",
    "subtract_all",
    "to_trimesh",
    "union_all",
    "volume",
]
