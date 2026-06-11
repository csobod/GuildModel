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


class ZoneThicknesses(BaseModel):
    """Posterior height of each castle zone (mm from the flat anterior face).

    Keys match Zone.kind from geometry.regions. Towers: endpiece, bridge,
    nosepad. Walls: eyewire_superior, eyewire_inferior. Defaults are the
    Demo Project reference values (DEMO_PROJECT_TEARDOWN.md §3).
    """
    endpiece_mm: float = 5.5
    bridge_mm: float = 5.3
    nosepad_mm: float = 10.0
    eyewire_superior_mm: float = 4.8
    eyewire_inferior_mm: float = 4.2

    def for_kind(self, kind: str) -> float:
        return getattr(self, f"{kind}_mm")


class FootingFillet(BaseModel):
    """Rolling-ball blend pair for one step edge: exterior = convex round-over
    at the top of the step, interior = concave fillet at its base.

    `first` records which fillet is applied first — it changes the blend
    geometry whenever the radii are larger than the step (the first fillet
    rolls through the step corner, the second lands tangent to it). Verified
    against the Demo Project STL: profiles match the Fusion timeline order to
    < 0.01 mm rms (interior-first on endpiece/bridge edges, exterior-first on
    nosepad edges).
    """
    exterior_mm: float
    interior_mm: float
    first: Literal["interior", "exterior"] = "interior"


class FootingSchedule(BaseModel):
    """Per-edge footing fillets, keyed by ZoneEdge.canonical (OD/OS share).

    Defaults are the Demo Project reference values (teardown §4) including
    the Fusion application order (timeline features 7-16).
    """
    endpiece_superior: FootingFillet = Field(default_factory=lambda: FootingFillet(exterior_mm=32.0, interior_mm=48.0, first="interior"))
    endpiece_inferior: FootingFillet = Field(default_factory=lambda: FootingFillet(exterior_mm=16.0, interior_mm=32.0, first="interior"))
    bridge_superior: FootingFillet = Field(default_factory=lambda: FootingFillet(exterior_mm=24.0, interior_mm=32.0, first="interior"))
    nosepad_superior: FootingFillet = Field(default_factory=lambda: FootingFillet(exterior_mm=6.0, interior_mm=4.0, first="exterior"))
    nosepad_inferior: FootingFillet = Field(default_factory=lambda: FootingFillet(exterior_mm=9.0, interior_mm=10.0, first="exterior"))

    def for_edge(self, canonical: str) -> FootingFillet:
        return getattr(self, canonical)


class StockDefinition(BaseModel):
    """Two-level stock: blank sheet + pad block stacked centrally on top.

    The heightfield analogue of the complex Fusion stock model — CAM and
    preview both read it so toolpaths never cut air at the wrong height.
    Defaults match the GuildDraw stock/pad guides and guild_cnc.yaml.
    """
    blank_length_mm: float = 170.0
    blank_width_mm: float = 85.0
    blank_thickness_mm: float = 6.0
    pad_block_length_mm: float = 45.0
    pad_block_width_mm: float = 45.0
    pad_block_thickness_mm: float = 4.0
    # Pad block center offset from the blank center (0,0 = centrally located).
    pad_block_dx_mm: float = 0.0
    pad_block_dy_mm: float = 0.0

    @property
    def total_pad_height_mm(self) -> float:
        return self.blank_thickness_mm + self.pad_block_thickness_mm


class CastleParams(BaseModel):
    """The parametric castle (BUILDPLAN §2): towers, walls, footing, stock.

    UI presents these staged Towers -> Walls -> Footing; this schema is the
    API surface and keeps anatomical vocabulary.
    """
    zones: ZoneThicknesses = Field(default_factory=ZoneThicknesses)
    footing: FootingSchedule = Field(default_factory=FootingSchedule)
    hinge_pocket_depth_mm: float = 1.0       # below the endpiece zone height
    stock: StockDefinition = Field(default_factory=StockDefinition)
    onion_skin_mm: float = 0.4               # axial stock left under through-cuts (no tabs)
    hand_finishing_allowance_mm: float = 0.1  # radial leave-behind stock on contour operations


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
    castle: CastleParams = Field(default_factory=CastleParams)
    relief: ReliefRecipe = Field(default_factory=ReliefRecipe)  # legacy spike recipe; superseded by castle in M2/M4
    forming: FormingMetadata = Field(default_factory=FormingMetadata)
    cam: CAMSettings = Field(default_factory=CAMSettings)
