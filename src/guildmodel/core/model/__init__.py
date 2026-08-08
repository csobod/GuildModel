"""Mesh-domain model kernel (BUILDPLAN-NEW M-N1).

The replacement for `core/solid`'s construction layer. Same inputs, same part,
built out of triangles instead of trimmed surfaces — see `kernel.py` for why
that swap is the structural fix rather than another bandaid.

Cheap to import: `manifold3d` is a few MB against OCP's ~70, so unlike
`core.solid` this package does not have to be kept off the startup path.
"""
from .build import build_castle_model, build_terraces, hinge_pockets
from .kernel import (ManifoldError, cross_section, extrude, hull_chain,
                     subtract_all, to_trimesh, union_all, volume)

__all__ = [
    "ManifoldError",
    "build_castle_model",
    "build_terraces",
    "cross_section",
    "extrude",
    "hinge_pockets",
    "hull_chain",
    "subtract_all",
    "to_trimesh",
    "union_all",
    "volume",
]
