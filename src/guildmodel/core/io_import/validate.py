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

    outline_curves = layers.get("OUTLINE", [])
    lens_curves = layers.get("LENS", [])
    if not outline_curves:
        errors.append("Missing required layer: OUTLINE")
    elif len(outline_curves) > 1:
        # Extra closed OUTLINE curves inside a body are decorative openings
        # (Hole1..HoleN); one that holds a lens is a separated rim, a body of
        # its own; the rest are an authoring mistake. The intake's own rule.
        from .normalize import assemble_outline
        assembly = assemble_outline(
            [list(p.exterior.coords) for p in outline_curves if not p.is_empty],
            lenses=lens_curves)
        holes, stray = len(assembly.holes), len(assembly.stray)
        if holes:
            warnings.append(
                f"{holes} closed curve(s) inside the OUTLINE profile — cutting them "
                "as openings (Hole1…).")
        if stray:
            warnings.append(
                f"{stray} OUTLINE curve(s) fall outside the profile and hold no lens, "
                "so they are ignored; the largest curve is the profile.")

    if not lens_curves:
        errors.append("Missing required layer: LENS (need two lens openings).")
    elif len(lens_curves) == 1:
        # A monocle since 2026-10-16, when its outline is one rim; one lens in
        # an outline drawn for two is refused at intake (`half_drawn_front`).
        warnings.append("One lens curve on the LENS layer: a monocle, if the outline is "
                        "one rim; draw the second lens for a pair.")
    elif len(lens_curves) > 2:
        warnings.append(f"{len(lens_curves)} curves on LENS layer; a front holds two, "
                        "and nothing is cut until the extra ones are deleted.")

    for layer_name, curves in layers.items():
        for i, poly in enumerate(curves):
            if not poly.is_valid:
                warnings.append(f"Layer {layer_name!r} curve {i} is not a valid polygon (self-intersecting?).")
            if poly.area <= 0:
                errors.append(f"Layer {layer_name!r} curve {i} has zero or negative area.")

    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)
