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


# Canonical posterior op names, in machining order. These are the keys for the
# per-operation tool assignment (BUILDPLAN M6.1) and the labels the post / sim /
# cut-time model already canonicalize on.
POSTERIOR_OPS: tuple[str, ...] = (
    "Hinge Pockets", "Rough Relief", "Fine Relief", "Eyewires", "Perimeter",
)


class ProgramZero(BaseModel):
    """Where the program's G54 work zero lands (BUILDPLAN M6.2).

    `fixture` keeps the design frame (current behaviour — zero at the blank
    center, anterior face; needed for the two-sided flip axis in M8). `stock_box`
    zeroes to a datum on the stock blank box — a corner or center in X/Y and the
    top or bottom (anterior) face in Z — what a maker touches off on the blank.
    Applied as a rigid post-time offset only; geometry / CLS / sim stay in the
    design frame, so the M2/M3 envelopes and the cut simulator are unaffected.

    Design-frame convention (relief.castle.stock_top_heightfield): the blank is
    centered on the world origin and the anterior face is Z = 0, so the blank box
    spans x ∈ [-L/2, L/2], y ∈ [-W/2, W/2], z ∈ [0, blank_thickness].
    """
    mode: Literal["fixture", "stock_box"] = "stock_box"
    x_ref: Literal["left", "center", "right"] = "left"
    y_ref: Literal["bottom", "center", "top"] = "bottom"
    z_ref: Literal["top", "bottom"] = "top"

    def datum_world(self, stock: "StockDefinition") -> tuple[float, float, float]:
        """The datum point in design-frame (world) coordinates."""
        hl = stock.blank_length_mm / 2.0
        hw = stock.blank_width_mm / 2.0
        x = {"left": -hl, "center": 0.0, "right": hl}[self.x_ref]
        y = {"bottom": -hw, "center": 0.0, "top": hw}[self.y_ref]
        z = {"bottom": 0.0, "top": stock.blank_thickness_mm}[self.z_ref]
        return (x, y, z)

    def work_offset(self, stock: "StockDefinition") -> tuple[float, float, float]:
        """Rigid offset added to every posted coordinate so the datum maps to 0.
        Fixture mode is the identity (the design frame is unchanged)."""
        if self.mode == "fixture":
            return (0.0, 0.0, 0.0)
        dx, dy, dz = self.datum_world(stock)
        return (-dx + 0.0, -dy + 0.0, -dz + 0.0)   # +0.0 normalizes -0.0

    def label(self) -> str:
        if self.mode == "fixture":
            return "Fixture (design frame: blank center, anterior face)"
        corner = {
            ("left", "bottom"): "lower-left", ("right", "bottom"): "lower-right",
            ("left", "top"): "upper-left", ("right", "top"): "upper-right",
            ("center", "center"): "center",
        }.get((self.x_ref, self.y_ref), f"{self.y_ref}/{self.x_ref}")
        return f"Stock blank {corner}, {self.z_ref} face"


class CastleCamParams(BaseModel):
    """Operation parameters for the five-op posterior program (BUILDPLAN M4.8).

    The knobs that drive cut time and finish, persisted with the project and
    editable from the CAM tab. Defaults are the Demo Project reference values
    (proven on the Guild CNC); the relief stepover (0.9) matches the Fusion
    Scallop's effective coverage. Feed/plunge/spindle overrides are optional —
    when None the active material preset supplies them — and are clamped to the
    active machine profile at post time.
    """
    tool_name: str = "flat_3175"          # default / fallback tool for any op
    machine_name: str = "guild_cnc"

    # Per-operation tool override (BUILDPLAN M6.1): op name -> tool name from
    # tools.yaml. Empty = every op uses tool_name (single-tool, M1–M5 behaviour).
    # The everyday multi-tool case: a small tool clears the hinge pockets, the
    # bulk tool does relief / eyewires / perimeter.
    op_tools: dict[str, str] = Field(default_factory=dict)

    # Program zero / G54 work datum (BUILDPLAN M6.2). Default = stock-box
    # lower-left, top face — what a maker touches off on the blank.
    program_zero: ProgramZero = Field(default_factory=ProgramZero)

    def tool_for_op(self, op_name: str) -> str:
        """The tool assigned to `op_name`, falling back to the global tool."""
        return self.op_tools.get(op_name, self.tool_name)

    def tools_in_use(self) -> list[str]:
        """Distinct tool names across all five ops, in machining order."""
        seen: list[str] = []
        for op in POSTERIOR_OPS:
            name = self.tool_for_op(op)
            if name not in seen:
                seen.append(name)
        return seen

    def is_multi_tool(self) -> bool:
        return len(self.tools_in_use()) > 1

    # strategy / geometry
    pocket_stepover_mm: float = 1.2
    relief_stepover_mm: float = 0.9        # matches Fusion Scallop coverage
    rough_axial_stock_mm: float = 2.0
    contour_stepdown_mm: float = 2.5
    ramp_step_mm: float = 0.6              # pocket ramp descent per lap
    contour_ramp_angle_deg: float = 8.0    # through-cut lead-in ramp (partial lap)
    skim_epsilon_mm: float = 0.05          # "nothing to cut" threshold for roughing
    simplify_tol_mm: float = 0.01
    arc_tolerance_mm: float = 0.01         # 0 disables arc fitting (linearized G1)

    # output / feeds (None -> use the material preset)
    feed_rate_mmpm: float | None = None
    plunge_rate_mmpm: float | None = None
    spindle_rpm: int | None = None
    safe_z_clearance_mm: float = 5.0       # rapid clearance above the stock top


class MachineProfile(BaseModel):
    """A GRBL-family machine's capabilities (BUILDPLAN M4.8 task 3).

    The post validates against and adapts to this: feeds, plunge, spindle and
    depth-of-cut are clamped to the machine's limits; arcs are linearized for
    controllers without reliable G2/G3; the work envelope bounds soft-limit
    checks; and the motion dynamics drive the cut-time estimate. Shipped as
    user-editable YAML under config/machines/; the default is the Guild CNC.
    """
    name: str = "guild_cnc"
    display_name: str = "Guild CNC"

    # work envelope (mm), origin lower-left, Z+ above stock
    work_area_x_mm: float = 300.0
    work_area_y_mm: float = 200.0
    work_area_z_mm: float = 80.0

    # feed / speed limits
    max_feed_mmpm: float = 2000.0
    max_plunge_mmpm: float = 1000.0
    max_spindle_rpm: float = 24000.0
    min_spindle_rpm: float = 0.0

    # depth of cut
    max_doc_mm: float = 2.5

    # motion dynamics (GRBL $110/$111, $120/$121, $11) — feed the cut-time model
    rapid_rate_mmpm: float = 3000.0
    max_accel_mmps2: float = 500.0
    junction_deviation_mm: float = 0.01

    # output dialect
    supports_arcs: bool = True             # G2/G3; linearize when False
    units: Literal["mm", "inch"] = "mm"
    enforce_soft_limits: bool = True

    # tool-change policy (BUILDPLAN M6.1): "m6" = automatic ATC (M6 Tn),
    # "m0" = manual change behind an M0 pause with an operator prompt. The
    # Guild CNC has no ATC, so manual is the default.
    tool_change_mode: Literal["m6", "m0"] = "m0"
    tool_change_seconds: float = 20.0      # nominal dwell per change, cut-time model
    notes: str = ""


class MachineRef(BaseModel):
    name: str = "guild_cnc"
    preset_file: str = "machines/guild_cnc.yaml"


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
    forming: FormingMetadata = Field(default_factory=FormingMetadata)
    cam: CAMSettings = Field(default_factory=CAMSettings)
    cam_params: CastleCamParams = Field(default_factory=CastleCamParams)
    machine: MachineRef = Field(default_factory=MachineRef)
