"""Pydantic schema for .guildcam project files (JSON under the hood)."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class BoxingParams(BaseModel):
    a: float = 50.0
    b: float = 38.0
    dbl: float = 18.0
    ed: float = 54.0
    frame_width: float = 0.0
    frame_height: float = 0.0
    bridge_depth: float = 4.0
    bridge_width: float = 5.0
    endpiece_width: float = 8.0
    temple_length: float = 145.0
    symmetric: bool = True


class ScallopParams(BaseModel):
    enabled: bool = True
    central_zone_mm: float = 10.0     # half-width of full-thickness zone
    slope_extent_mm: float = 8.0      # transition distance from full to min
    min_edge_thickness_mm: float = 1.2


class NosepadParams(BaseModel):
    enabled: bool = True
    height_mm: float = 1.5
    footprint_mm: float = 12.0
    blend_radius_mm: float = 4.0


class GrooveParams(BaseModel):
    enabled: bool = True
    depth_mm: float = 0.8
    width_mm: float = 0.6
    profile: Literal["vee", "radius"] = "radius"


class PocketParams(BaseModel):
    enabled: bool = True
    depth_mm: float = 1.2


class HingeParams(BaseModel):
    """Per-hinge placement and catalog reference.  Two entries expected: OD and OS."""
    enabled: bool = True
    catalog_file: str = "hinges/standard.yaml"
    hinge_name: str = "screw_barrel_14x5p5"
    # Placement in frame local coordinates (mm, degrees).
    # RotationCharniere from CHA vocabulary.
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation_deg: float = 0.0
    face: str = "front"     # "front" | "back"


class ReliefRecipe(BaseModel):
    scallop: ScallopParams = Field(default_factory=ScallopParams)
    nosepad: NosepadParams = Field(default_factory=NosepadParams)
    groove: GrooveParams = Field(default_factory=GrooveParams)
    pocket: PocketParams = Field(default_factory=PocketParams)
    hinge_od: HingeParams = Field(default_factory=HingeParams)
    hinge_os: HingeParams = Field(default_factory=HingeParams)


class FormingMetadata(BaseModel):
    """Recorded for archive; NOT machined in v1. Heat-forming is post-cutting."""
    base_curve: float = 0.0          # diopters
    pantoscopic_tilt_deg: float = 0.0
    face_form_wrap_deg: float = 0.0


class MaterialRef(BaseModel):
    name: str = "acetate"
    preset_file: str = "materials.yaml"


class ToolRef(BaseModel):
    name: str
    preset_file: str = "tools.yaml"


class FixtureRef(BaseModel):
    name: str = "guild_cnc"
    preset_file: str = "fixtures/guild_cnc.yaml"


class CAMSettings(BaseModel):
    two_file_output: bool = True      # False = single file with M0 pause
    relief_stepover_mm: float = 0.4
    relief_stepdown_mm: float = 0.5
    profile_stepdown_mm: float = 1.5
    tab_count: int = 4
    tab_width_mm: float = 3.0
    tab_height_mm: float = 1.0
    material: MaterialRef = Field(default_factory=MaterialRef)
    tool_relief: ToolRef = Field(default_factory=lambda: ToolRef(name="ball_2mm"))
    tool_profile: ToolRef = Field(default_factory=lambda: ToolRef(name="flat_3mm"))
    fixture: FixtureRef = Field(default_factory=FixtureRef)


class ProjectSchema(BaseModel):
    version: str = "0.1"
    created_at: datetime = Field(default_factory=datetime.now)
    modified_at: datetime = Field(default_factory=datetime.now)
    job_name: str = "Untitled Frame"
    source_file: str = ""            # original imported DXF/SVG path
    stock_thickness_mm: float = 6.0
    stock_width_mm: float = 80.0
    stock_height_mm: float = 50.0
    boxing: BoxingParams = Field(default_factory=BoxingParams)
    relief: ReliefRecipe = Field(default_factory=ReliefRecipe)
    forming: FormingMetadata = Field(default_factory=FormingMetadata)
    cam: CAMSettings = Field(default_factory=CAMSettings)
