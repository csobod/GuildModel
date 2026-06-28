"""Save and load .guildmodel project files (JSON, pydantic-validated)."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import ProjectSchema


def save_project(schema: ProjectSchema, path: Path) -> None:
    path.write_text(schema.model_dump_json(indent=2), encoding="utf-8")


def load_project(path: Path) -> ProjectSchema:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProjectSchema.model_validate(data)
