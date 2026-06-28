"""STL export."""
from __future__ import annotations
from pathlib import Path


def export_stl(mesh: "trimesh.Trimesh", path: Path) -> None:  # noqa: F821
    """Export a trimesh.Trimesh to binary STL."""
    path.write_bytes(mesh.export(file_type="stl"))
