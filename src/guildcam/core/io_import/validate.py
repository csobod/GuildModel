"""Validate normalized geometry before proceeding to parametric editing."""
from __future__ import annotations
from dataclasses import dataclass, field
from shapely.geometry import Polygon


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(layers: dict[str, list[Polygon]]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if "OUTLINE" not in layers or not layers["OUTLINE"]:
        errors.append("Missing required layer: OUTLINE")
    elif len(layers["OUTLINE"]) > 1:
        warnings.append("Multiple curves on OUTLINE layer; using the largest.")

    lens_curves = layers.get("LENS", [])
    if not lens_curves:
        errors.append("Missing required layer: LENS (need two lens openings).")
    elif len(lens_curves) == 1:
        warnings.append("Only one lens curve found on LENS layer; expected two for a pair.")
    elif len(lens_curves) > 2:
        warnings.append(f"{len(lens_curves)} curves on LENS layer; expected two.")

    for layer_name, curves in layers.items():
        for i, poly in enumerate(curves):
            if not poly.is_valid:
                warnings.append(f"Layer {layer_name!r} curve {i} is not a valid polygon (self-intersecting?).")
            if poly.area <= 0:
                errors.append(f"Layer {layer_name!r} curve {i} has zero or negative area.")

    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)
