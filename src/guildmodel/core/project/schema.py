"""Pydantic schema for .guildmodel project files (JSON under the hood)."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    nosepad. Walls: eyewire_superior, eyewire_inferior — a wall spanning both
    eyes (an aviator's unified brow, side "ou") is still an eyewire and rides
    the same control. Defaults are the Demo Project reference values
    (DEMO_PROJECT_TEARDOWN.md §3).
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
    # Whether the raised nosepad pad-block sits on the blank (M11). Off ⇒ a single
    # flat blank whose thickness the user sets directly (mill the model to the blank
    # alone). When off, total_pad_height and the stock-top surface are blank-only.
    use_pad_block: bool = True

    @property
    def total_pad_height_mm(self) -> float:
        pad = self.pad_block_thickness_mm if self.use_pad_block else 0.0
        return self.blank_thickness_mm + pad


class LensGrooveParams(BaseModel):
    """Lens bevel groove — the drageoir V-groove in each eyewire wall (V1).

    The groove seats the lens bevel: its BOTTOM lands exactly on the LENS
    contour (the boxed dimension stays honest), so with the groove enabled the
    visible aperture (the rim lip) is cut smaller by ``depth_mm`` and the
    groove is cut outward from it with a side-cutting grooving tool (fraise
    drageoir). The eyewire channel is widened automatically so the tool's head
    can descend into the open channel and feed radially into the wall.
    ``anterior_offset_mm`` positions the groove APEX above the anterior face
    (Z = 0, the design-frame convention). ``width_mm``/``depth_mm`` describe
    the V (included angle = 2·atan((width/2)/depth), shown read-only in the
    GUI); defaults match the shipped ``groove_drageoir`` form cutter. Off by
    default: the bare-castle gates hold, and many makers groove by hand.
    """
    enabled: bool = False
    anterior_offset_mm: float = 1.5   # apex height above the anterior face
    depth_mm: float = 0.75            # radial cut into the rim (= lip undersize)
    width_mm: float = 2.0             # V opening height at the rim face
    tool: str = "groove_drageoir"     # side-cutting form tool


class PadSplayParams(BaseModel):
    """Posterior chamfer under the bridge — the frame's "pad splay" (M13.1).

    A crest line is drawn as an inward offset of the OUTLINE, centered on the
    outline's bottom-center point and running `run_mm` of arc length along the
    outline per side; the chamfer surface falls from the crest (anchored on the
    local relief) toward the outline edge at the splay angle. Toric mode blends
    three angles — center ("start") / half-run ("middle") / run-end ("end") —
    mirror-symmetric about the centerline. Angles are measured from the anterior
    plane (0° = flat). Off by default: many makers cut theirs by hand.
    """
    enabled: bool = False
    run_mm: float = 18.0                     # arc distance per side from bottom-center
    crest_deviation_center_mm: float = 6.0   # inward crest offset at bottom-center
    crest_deviation_end_mm: float = 2.0      # at each run end (interpolated along the run)
    toric: bool = False                      # off = angle_center everywhere
    angle_center_deg: float = 30.0
    angle_middle_deg: float = 30.0
    angle_end_deg: float = 30.0
    anterior_clamp_mm: float = 1.5           # cut floor above the anterior face (no knife edge)
    feather_mm: float = 3.0                  # depth feather over the last mm of each run end
    # Convex round-over at the crest (tangent both sides, footing-style) — the
    # hard chamfer/surface corner shaded as a jagged ridge. 0 = sharp crest.
    crest_blend_mm: float = 2.0


class EyewireBezelParams(BaseModel):
    """Constant-width chamfer band around each lens opening's posterior rim —
    the "bezeled eyewire" (M13.2). Depth below the local surface at the rim is
    width_mm * tan(angle_deg); the anterior clamp floors the cut.
    """
    enabled: bool = False
    width_mm: float = 2.5
    angle_deg: float = 30.0
    anterior_clamp_mm: float = 1.5


class BridgeReliefParams(BaseModel):
    """Bridge projection relief (M13.3, reworked 2026-07-02): a CONIC scoop on
    the posterior bridge, running on Y — the base (widest, deepest cut of the
    cone section) opens through the top edge of the frame over the bridge, and
    the sides taper at `taper_angle_deg` per side to a rounded tip down the
    lower bridge. The cross-section is a tangent cosine bell and the depth
    scales with the local width (a true cone imprint feathering to nothing at
    the tip), so the cut is crease-free and flows with the smooth footing.
    """
    enabled: bool = False
    width_mm: float = 8.0                    # scoop width at its base (the top edge)
    depth_mm: float = 1.2                    # cut depth at the base centerline
    taper_angle_deg: float = 30.0            # per-side taper of the cone toward the tip
    anterior_clamp_mm: float = 1.5


class CastleParams(BaseModel):
    """The parametric castle (BUILDPLAN §2): towers, walls, footing, stock.

    UI presents these staged Towers -> Walls -> Footing; this schema is the
    API surface and keeps anatomical vocabulary.
    """
    zones: ZoneThicknesses = Field(default_factory=ZoneThicknesses)
    # Per-zone height overrides keyed by Zone.name (not kind), for the zones a
    # drawing produces that the per-kind defaults don't suit — a second bridge
    # bar under a decorative opening, an asymmetric wall. Empty = use `zones`.
    zone_height_overrides: dict[str, float] = Field(default_factory=dict)
    footing: FootingSchedule = Field(default_factory=FootingSchedule)
    hinge_pocket_depth_mm: float = 1.0       # below the endpiece zone height
    stock: StockDefinition = Field(default_factory=StockDefinition)
    onion_skin_mm: float = 0.4               # axial stock left under through-cuts (no tabs)
    hand_finishing_allowance_mm: float = 0.1  # radial leave-behind stock on contour operations
    # Posterior finishing features (M13, all default-off — the M2/M3/M4 gates
    # machine the bare castle; each is a min-carve into the footed surface).
    pad_splay: PadSplayParams = Field(default_factory=PadSplayParams)
    eyewire_bezel: EyewireBezelParams = Field(default_factory=EyewireBezelParams)
    bridge_relief: BridgeReliefParams = Field(default_factory=BridgeReliefParams)
    lens_groove: LensGrooveParams = Field(default_factory=lambda: LensGrooveParams())


# Canonical posterior op names, in machining order. These are the keys for the
# per-operation tool assignment (BUILDPLAN M6.1) and the labels the post / sim /
# cut-time model already canonicalize on. The optional "Lens Groove" op (V1) is
# deliberately NOT listed: `tools_in_use()` iterates this tuple, and a groove
# entry would make every job read as multi-tool even with the groove off. Its
# tool comes from `LensGrooveParams.tool` (an explicit `op_tools["Lens Groove"]`
# still overrides).
POSTERIOR_OPS: tuple[str, ...] = (
    "Hinge Pockets", "Rough Relief", "Fine Relief", "Eyewires", "Perimeter",
)

# Per-op tool defaults when a job hasn't pinned one (M11): small precise features
# get a fine tool rather than the bulk global tool. Hinge pockets cut with the
# 3.175 mm default leave ~1.6 mm corners instead of ~1 mm. An explicit op_tools
# entry always overrides this; it only changes the otherwise-global fallback.
DEFAULT_OP_TOOLS: dict[str, str] = {"Hinge Pockets": "flat_2mm"}


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
    x_ref: Literal["left", "center", "right"] = "center"
    y_ref: Literal["bottom", "center", "top"] = "center"
    z_ref: Literal["top", "bottom"] = "bottom"

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
    # center/center, bottom (anterior) face — i.e. the blank center, which is the
    # design-frame origin (a zero offset); pick a corner + top face to touch off
    # there instead.
    program_zero: ProgramZero = Field(default_factory=ProgramZero)

    def tool_for_op(self, op_name: str) -> str:
        """The tool assigned to `op_name`: an explicit op_tools entry, else a per-op
        fine-tool default (M11), else the global tool."""
        return (self.op_tools.get(op_name)
                or DEFAULT_OP_TOOLS.get(op_name)
                or self.tool_name)

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

    # strategy / geometry. The step / stepover fields drive `while`-loops that only
    # advance by their value, so 0 or negative would spin forever — reject them at
    # load with a clear error (the generators also floor them defensively). `gt=0`
    # is deliberately NOT on rough_axial_stock_mm (0 = leave no extra roughing stock).
    pocket_stepover_mm: float = Field(1.2, gt=0)
    relief_stepover_mm: float = Field(0.9, gt=0)   # matches Fusion Scallop coverage
    rough_axial_stock_mm: float = 2.0
    # Requested through-cut depth per pass (M12.4): clamped down per material+machine by
    # `max_doc` (acetate 4.0, acetal 2.0, brittle horn 0.8), so this is "cut as deep as
    # the material allows" by default — fewer perimeter/eyewire passes — and the user can
    # still set it shallower. Was 2.5 (a blanket cap that left acetate at 4 passes).
    contour_stepdown_mm: float = Field(4.0, gt=0)
    ramp_step_mm: float = Field(0.6, gt=0)  # pocket ramp descent per lap
    contour_ramp_angle_deg: float = 8.0    # through-cut lead-in ramp (partial lap)
    skim_epsilon_mm: float = 0.05          # "nothing to cut" threshold for roughing
    # Contour-relief linking (M11): bridge a contour ring's masked gaps up to this
    # width by riding the cutter over the thin cap instead of retract+plunging across
    # it — turns a ring shattered into tiny stub paths ("drill holes" over caps/bands)
    # into one long sweep, like a Fusion contour. A run still shorter than
    # `relief_min_run_mm` after linking is dropped (negligible material, hand-finished).
    relief_link_gap_mm: float = 4.0
    relief_min_run_mm: float = 1.0
    simplify_tol_mm: float = 0.01
    arc_tolerance_mm: float = 0.01         # 0 disables arc fitting (linearized G1)

    # output / feeds (None -> use the material preset)
    feed_rate_mmpm: float | None = None
    plunge_rate_mmpm: float | None = None
    spindle_rpm: int | None = None
    safe_z_clearance_mm: float = 5.0       # rapid clearance above the tallest obstacle
    # Height of the work-holding screws / clamps above the table (z = 0). Single-part
    # rapids retract above the TALLER of the stock and this, so travels clear the
    # hold-downs even when only one part is cut (M8 prep). 0 = flush work-holding.
    hold_down_height_mm: float = 0.0
    # Collision-aware pass linking (M8): between cutting passes, retract only to
    # `link_clearance_mm` above the stock instead of the full safe Z — except where
    # the hop would pass near a work-holding screw (the standard Guild fixture: one
    # at each stock-blank corner + one at each lens centre, `screw_head_diameter_mm`
    # across), which keeps the full safe-Z retract. Cuts the many full retracts of
    # the small relief/rough passes. Set False to always retract to safe Z.
    link_retracts: bool = True
    link_clearance_mm: float = 1.5         # low-retract height above the stock top
    screw_head_diameter_mm: float = 7.0
    screw_keepout_margin_mm: float = 2.0   # extra clearance the tool edge keeps off a head

    def safe_z_for(self, stock_top_mm: float) -> float:
        """Rapid retract height above the table: clears the taller of the stock top
        and the work-holding screws/clamps, plus the clearance margin. The program
        zero offset re-references this to the touch-off datum at post time."""
        return max(float(stock_top_mm), self.hold_down_height_mm) + self.safe_z_clearance_mm


class TempleParams(BaseModel):
    """A temple component: a flat outline cut plus engraving (BUILDPLAN M6.3).

    Unlike the frame front there is no castle relief — a temple is a flat blank
    that gets shallow ENGRAVING grooves on its top face and an OUTLINE through-cut
    (onion skin, like the perimeter). The engraving uses a small tool and the
    profile a larger one, so the program carries one tool change (M6.1). The blank
    box (assumed centred on the design origin, like the frame blank) feeds the
    program-zero offset and the safe-Z; defaults match the `temple_right` fixture
    zone (170 × 30 × 4 mm).
    """
    blank_length_mm: float = 170.0
    blank_width_mm: float = 30.0
    blank_thickness_mm: float = 4.0
    hinge_pocket_depth_mm: float = 1.0     # HINGE pocket floor below the top face
    engrave_depth_mm: float = 0.3          # groove depth below the top face
    engrave_tool: str = "engrave_vbit"     # small tool for the ENGRAVING passes
    hinge_tool: str = "flat_2mm"           # endmill that clears the HINGE pockets
    # M11 #7: engrave a single fixed-depth line down each stroke's CENTRE (medial
    # axis of the closed glyph outlines) instead of tracing the outlines — one pass
    # per stroke, no double-cut ridge. Off = trace the raw ENGRAVING outlines.
    engrave_centerline: bool = True
    profile_tool: str = "flat_3175"        # outline through-cut tool
    onion_skin_mm: float = 0.4             # axial stock left under the profile
    hand_finishing_allowance_mm: float = 0.1
    fixture_zone: str = "temple_right"     # fixture blank zone (clearance check)

    # Snap the temple to one end of the blank so the injected metal core (a wire
    # set into the blank along its length) runs through the whole temple — the
    # HINGE/butt end registers to a short edge of the 170 mm blank (BUILDPLAN M7).
    # ON by default (workflow decision 2026-07-09): blanks are slid into the fixture
    # with their core ends against one stop, so the cut is always plotted from the
    # snapped position — the 2D view back-projects the blank/datum/toolpath so it
    # still matches the drawing. OFF leaves the part at its DESIGN alignment (legacy;
    # the program-zero datum then assumes the drawing is centred on the blank).
    snap_to_blank_end: bool = True
    # Which short end of the blank the HINGE/butt end registers to (M11). Cores are
    # sometimes shot from the left of the stock instead of the right; flipping the
    # side rotates the temple 180° in-plane (hinge pocket stays up) so it butts the
    # chosen end with the body running inward.
    stock_side: Literal["right", "left"] = "right"
    # The injected core is a 3D *visual reference* only (not machined): a bar this
    # wide and long, laid along the temple's long axis from the hinge end.
    core_guide_width_mm: float = 2.0
    core_guide_length_mm: float = 135.0

    def stock(self) -> "StockDefinition":
        """A single-level StockDefinition for the blank (no pad block) — used for
        the program-zero datum and the safe-Z height."""
        return StockDefinition(
            blank_length_mm=self.blank_length_mm,
            blank_width_mm=self.blank_width_mm,
            blank_thickness_mm=self.blank_thickness_mm,
            pad_block_length_mm=0.0, pad_block_width_mm=0.0,
            pad_block_thickness_mm=0.0,
        )


class BaseCurveBlockParams(BaseModel):
    """An auto-generated base-curve holding block (BUILDPLAN M6.4).

    Cut from an acetal blank straight off the frame DXF: the **lens exterior shape**
    is profile-cut free from the blank and three M4 mounting holes bolt it to a jig.
    The block is the lens shape — it sits on the base-curve press and holds the
    eyewire so the frame doesn't distort while thermoforming. There is no other cut:
    just the holes and the lens-shape release (confirmed with the user 2026-06-19).

    Defaults confirmed with the user 2026-06-16: **in-line** holes at **10 mm**
    pitch, **M4 clearance (≈4.5 mm)** — a bolt passes through the block into a
    tapped jig below. Arrangement and drill Ø stay parameters.
    """
    blank_length_mm: float = 70.0
    blank_width_mm: float = 70.0
    blank_thickness_mm: float = 4.7625     # 3/16"
    material: str = "acetal"

    # lens-shape through-cut (the lens exterior, profile-cut free like a frame outline)
    profile_tool: str = "flat_3175"
    onion_skin_mm: float = 0.4
    hand_finishing_allowance_mm: float = 0.1

    # mounting holes
    hole_count: int = 3
    hole_spacing_mm: float = 10.0          # pitch between adjacent holes
    hole_diameter_mm: float = 4.5          # M4 clearance (tapped ≈ 3.3)
    hole_arrangement: Literal["inline", "triangle"] = "inline"
    drill_tool: str = "drill_m4_clear"
    peck_depth_mm: float = 1.5             # per-peck plunge (GRBL has no G83)
    drill_breakthrough_mm: float = 1.0     # drill this far past the bottom face

    fixture_zone: str = "bc_template_right"

    def stock(self) -> "StockDefinition":
        return StockDefinition(
            blank_length_mm=self.blank_length_mm,
            blank_width_mm=self.blank_width_mm,
            blank_thickness_mm=self.blank_thickness_mm,
            pad_block_length_mm=0.0, pad_block_width_mm=0.0,
            pad_block_thickness_mm=0.0,
        )

    def hole_centers(self) -> list[tuple[float, float]]:
        """Mounting-hole centers in the block frame (centred on the origin)."""
        n = self.hole_count
        s = self.hole_spacing_mm
        if self.hole_arrangement == "triangle" and n == 3:
            # equilateral triangle, side = spacing, centroid at the origin
            h = s * (3 ** 0.5) / 2.0
            cy = h / 3.0
            return [(-s / 2.0, -cy), (s / 2.0, -cy), (0.0, h - cy)]
        # in-line, centred: pitch = spacing along x
        x0 = -(n - 1) * s / 2.0
        return [(x0 + i * s, 0.0) for i in range(n)]


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


class ComponentPlacement(BaseModel):
    """One component placed on the worktable bed (BUILDPLAN M6.5).

    `kind` selects the program (frame front / temple / base-curve block); the
    part is generated in its own design frame, then translated by (x_mm, y_mm)
    (and optionally rotated) onto the bed — by default the centre of its
    `fixture_zone`. Positions are in machine/bed coordinates.
    """
    kind: Literal["frame_front", "temple", "base_curve_block"]
    label: str = ""
    fixture_zone: str = "front"
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation_deg: float = 0.0


class BedLayout(BaseModel):
    """A multi-part worktable layout cut in one program (BUILDPLAN M6.5)."""
    fixture: str = "guild_cnc"
    placements: list[ComponentPlacement] = Field(default_factory=list)


class MachineRef(BaseModel):
    name: str = "guild_cnc"
    preset_file: str = "machines/guild_cnc.yaml"


class FormingMetadata(BaseModel):
    """Recorded for archive; NOT machined in v1. Heat-forming is post-cutting.

    `apical_radius_mm` and `bridge_angle_deg` carry the GuildDraw `.gdraw` forming
    values losslessly (BUILDPLAN M7.2). The base-curve template is flat in v1, so
    the apical radius is metadata for now — the 3D forming surface is post-1.0.
    """
    base_curve: float = 0.0          # diopters (optical convention)
    pantoscopic_tilt_deg: float = 0.0
    face_form_wrap_deg: float = 0.0
    apical_radius_mm: float = 0.0    # base-curve forming radius, from the .gdraw
    bridge_angle_deg: float = 0.0    # bridge / face-form angle, from the .gdraw


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


class ComponentKind(str, Enum):
    """The role-typed parts of a complete eyewear model (BUILDPLAN M7.1).

    One shared enum used by the project model (this file), the worktable bed
    roles (M7.4) and the role-matched nesting (M7.5). A canonical project carries
    one of each; a custom-bed run may carry several of a kind.
    """
    FRAME_FRONT = "frame_front"
    TEMPLE_RIGHT = "temple_right"
    TEMPLE_LEFT = "temple_left"
    BASE_CURVE_RIGHT = "base_curve_right"
    BASE_CURVE_LEFT = "base_curve_left"


# Kind → presentation label (the component tab / bed-zone title, M7.3/M7.4).
_COMPONENT_LABELS: dict[ComponentKind, str] = {
    ComponentKind.FRAME_FRONT: "Frame Front",
    ComponentKind.TEMPLE_RIGHT: "Temple R",
    ComponentKind.TEMPLE_LEFT: "Temple L",
    ComponentKind.BASE_CURVE_RIGHT: "Base Curve R",
    ComponentKind.BASE_CURVE_LEFT: "Base Curve L",
}

# Kind → default fixture/bed zone name (config/fixtures/guild_cnc.yaml; M7.4/M7.5).
_COMPONENT_FIXTURE_ZONES: dict[ComponentKind, str] = {
    ComponentKind.FRAME_FRONT: "front",
    ComponentKind.TEMPLE_RIGHT: "temple_right",
    ComponentKind.TEMPLE_LEFT: "temple_left",
    ComponentKind.BASE_CURVE_RIGHT: "bc_template_right",
    ComponentKind.BASE_CURVE_LEFT: "bc_template_left",
}

# Kind → the ProjectSchema/Component param field that drives its CAM.
_COMPONENT_PARAM_FIELD: dict[ComponentKind, str] = {
    ComponentKind.FRAME_FRONT: "castle",
    ComponentKind.TEMPLE_RIGHT: "temple",
    ComponentKind.TEMPLE_LEFT: "temple",
    ComponentKind.BASE_CURVE_RIGHT: "base_curve_block",
    ComponentKind.BASE_CURVE_LEFT: "base_curve_block",
}


def component_label(kind: ComponentKind) -> str:
    """The human label for a kind (the component tab / bed-zone title)."""
    return _COMPONENT_LABELS[ComponentKind(kind)]


def component_fixture_zone(kind: ComponentKind) -> str:
    """The default fixture/bed zone a kind nests onto (the bed *role*, M7.5)."""
    return _COMPONENT_FIXTURE_ZONES[ComponentKind(kind)]


def component_param_field(kind: ComponentKind) -> str:
    """Which of castle / temple / base_curve_block drives this kind's CAM."""
    return _COMPONENT_PARAM_FIELD[ComponentKind(kind)]


def lens_side(kind: ComponentKind) -> Literal["right", "left"] | None:
    """For a base-curve template, which lens it is built from; else None."""
    return {
        ComponentKind.BASE_CURVE_RIGHT: "right",
        ComponentKind.BASE_CURVE_LEFT: "left",
    }.get(ComponentKind(kind))


# ── Worktable (the interactive bed, BUILDPLAN M7.4) ──────────────────────────

class BedRole(str, Enum):
    """The role a tagged worktable zone plays (BUILDPLAN M7.4).

    The five placement roles match `ComponentKind` value-for-value, so
    `BedRole(kind.value)` maps a built component to the zone that holds it.
    `KEEP_OUT` marks a hold-down the cutter must avoid (a screw is a circle, but
    any enclosed region qualifies); `UNASSIGNED` is a freshly polygonized region
    the maker has not tagged yet.
    """
    UNASSIGNED = "unassigned"
    FRAME_FRONT = "frame_front"
    TEMPLE_RIGHT = "temple_right"
    TEMPLE_LEFT = "temple_left"
    BASE_CURVE_RIGHT = "base_curve_right"
    BASE_CURVE_LEFT = "base_curve_left"
    KEEP_OUT = "keep_out"


_BED_ROLE_LABELS: dict[BedRole, str] = {
    BedRole.UNASSIGNED: "Untagged",
    BedRole.FRAME_FRONT: "Frame Front",
    BedRole.TEMPLE_RIGHT: "Temple Right",
    BedRole.TEMPLE_LEFT: "Temple Left",
    BedRole.BASE_CURVE_RIGHT: "Base Curve R",
    BedRole.BASE_CURVE_LEFT: "Base Curve L",
    BedRole.KEEP_OUT: "Keep-out",
}

# Default fixture/bed zone key per role — the inverse of _COMPONENT_FIXTURE_ZONES,
# used to load the YAML fixture into a Worktable and back (M7.4).
_FIXTURE_ZONE_BY_ROLE: dict[BedRole, str] = {
    BedRole.FRAME_FRONT: "front",
    BedRole.TEMPLE_RIGHT: "temple_right",
    BedRole.TEMPLE_LEFT: "temple_left",
    BedRole.BASE_CURVE_RIGHT: "bc_template_right",
    BedRole.BASE_CURVE_LEFT: "bc_template_left",
}
_ROLE_BY_FIXTURE_ZONE: dict[str, BedRole] = {
    v: k for k, v in _FIXTURE_ZONE_BY_ROLE.items()
}


def bed_role_label(role: BedRole) -> str:
    """The human label for a bed role (the tag-menu / zone title)."""
    return _BED_ROLE_LABELS[BedRole(role)]


def role_for_kind(kind: ComponentKind) -> BedRole:
    """The bed role that holds a built component of `kind` (M7.5 nesting)."""
    return BedRole(ComponentKind(kind).value)


def kind_for_role(role: BedRole) -> ComponentKind | None:
    """The component kind a placement role accepts (None for keep-out / untagged)."""
    try:
        return ComponentKind(BedRole(role).value)
    except ValueError:
        return None


class WorktableZone(BaseModel):
    """One tagged region on the worktable (BUILDPLAN M7.4).

    A closed polygon in **machine coordinates** (origin lower-left, mm) plus the
    `role` the maker assigned it. A placement role holds a built component; a
    KEEP_OUT zone is a hold-down the cutter must avoid. `radius_mm` is set when the
    region is a true circle (a screw) so the legacy circular-clearance check
    round-trips exactly; `extra` carries any pass-through fixture keys
    (`flip_axis_x_mm`, `nosepad_sub_zone`) so the default Guild bed is lossless.
    """
    id: str
    role: BedRole = BedRole.UNASSIGNED
    label: str = ""
    polygon: list[tuple[float, float]] = Field(default_factory=list)
    stock_thickness_mm: float | None = None
    radius_mm: float | None = None
    source: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)

    def is_placement(self) -> bool:
        """True for a role that holds a component (not untagged / keep-out)."""
        return self.role not in (BedRole.UNASSIGNED, BedRole.KEEP_OUT)

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def width(self) -> float:
        x0, _, x1, _ = self.bbox()
        return x1 - x0

    def height(self) -> float:
        _, y0, _, y1 = self.bbox()
        return y1 - y0

    def center(self) -> tuple[float, float]:
        """Vertex mean — the exact centre of a regular ring (a screw) and a
        reasonable handle for any region."""
        pts = self.polygon
        if not pts:
            return (0.0, 0.0)
        n = len(pts)
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)

    def bbox_center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox()
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    def area(self) -> float:
        """Shoelace area of the ring (mm²); 0 for a degenerate region."""
        pts = self.polygon
        if len(pts) < 3:
            return 0.0
        s = 0.0
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2.0


class Worktable(BaseModel):
    """A user-defined cutting bed (BUILDPLAN M7.4).

    Supersedes the fixture-name coupling in `BedLayout`: rather than naming a YAML
    fixture, the bed *is* a set of role-tagged zone polygons + keep-out polygons in
    machine coordinates — drawn in CAD and imported from a DXF, or the built-in
    Guild fixture via `from_fixture_dict`. The M6.5 layout machinery still consumes
    a fixture dict, so `to_fixture_dict()` bridges this model onto it until M7.5
    nests directly on the tagged zones.
    """
    name: str = "guild_cnc"
    display_name: str = "Guild CNC (standard fixture)"
    work_area_width_mm: float = 300.0
    work_area_height_mm: float = 200.0
    safe_z_mm: float = 5.0
    max_z_mm: float = 80.0
    # Height of the hold-downs (screw heads / clamps) above the bed (z = 0). Drives
    # the bed-sim collision check (the tool only fouls a hold-down it's low enough to
    # reach) and the rapid safe-Z (rapids must clear the tallest hold-down) — M7.12.3.
    hold_down_height_mm: float = 8.0
    zones: list[WorktableZone] = Field(default_factory=list)
    source_dxf: str = ""
    # Where the whole-bed program's G54 work zero touches off (M11). Reuses the
    # ProgramZero datum picker over the work-area box; default = bed lower-left (the
    # historical bed origin, offset 0). Independent of each component's own zero so a
    # combined bed program and a separately exported part can touch off differently.
    program_zero: ProgramZero = Field(
        default_factory=lambda: ProgramZero(x_ref="left", y_ref="bottom"))

    # ── accessors ────────────────────────────────────────────────────────────
    def bed_work_offset(self) -> tuple[float, float, float]:
        """G54 offset (mm) for the whole-bed program (M11): the negative of the datum
        the maker touches off, over the work-area box [0,W]×[0,H] (machine coords,
        lower-left origin — unlike a stock box, which is centered). `fixture` mode
        keeps raw bed coordinates; Z is left unshifted (touched off on the stock)."""
        pz = self.program_zero
        if pz.mode != "stock_box":
            return (0.0, 0.0, 0.0)
        w, h = self.work_area_width_mm, self.work_area_height_mm
        dx = {"left": 0.0, "center": w / 2.0, "right": w}[pz.x_ref]
        dy = {"bottom": 0.0, "center": h / 2.0, "top": h}[pz.y_ref]
        return (-dx + 0.0, -dy + 0.0, 0.0)

    def zone(self, zone_id: str) -> WorktableZone:
        for z in self.zones:
            if z.id == zone_id:
                return z
        raise KeyError(zone_id)

    def zones_with_role(self, role: BedRole) -> list[WorktableZone]:
        role = BedRole(role)
        return [z for z in self.zones if z.role == role]

    def placement_zones(self) -> list[WorktableZone]:
        """Every tagged component-holding zone (not untagged / keep-out)."""
        return [z for z in self.zones if z.is_placement()]

    def keep_outs(self) -> list[WorktableZone]:
        return self.zones_with_role(BedRole.KEEP_OUT)

    def untagged(self) -> list[WorktableZone]:
        return self.zones_with_role(BedRole.UNASSIGNED)

    def zone_for_role(self, role: BedRole) -> WorktableZone | None:
        zs = self.zones_with_role(role)
        return zs[0] if zs else None

    # ── tagging ──────────────────────────────────────────────────────────────
    def set_role(self, zone_id: str, role: BedRole) -> WorktableZone:
        """Tag (or re-tag) a zone; refresh its label if it was a role default."""
        z = self.zone(zone_id)
        role = BedRole(role)
        if not z.label or z.label in _BED_ROLE_LABELS.values():
            z.label = bed_role_label(role)
        z.role = role
        return z

    # ── the M6.5 bridge ──────────────────────────────────────────────────────
    def to_fixture_dict(self) -> dict:
        """A fixture dict in the shape the M6.5 layout code consumes
        (`blank_zones` + `hold_down_screws` + radius), so the existing nesting /
        clearance machinery runs on this bed unchanged (BUILDPLAN M7.4)."""
        blank_zones: dict[str, dict] = {}
        for z in self.placement_zones():
            x0, y0, x1, y1 = z.bbox()
            entry: dict = {
                "label": z.label or bed_role_label(z.role),
                "role": z.role.value,
                "x_mm": x0, "y_mm": y0,
                "width_mm": x1 - x0, "height_mm": y1 - y0,
            }
            if z.stock_thickness_mm is not None:
                entry["stock_thickness_mm"] = z.stock_thickness_mm
            entry.update(z.extra)
            blank_zones[z.id] = entry

        keep = self.keep_outs()
        screws = [{"x": z.center()[0], "y": z.center()[1]} for z in keep]
        radii = [z.radius_mm for z in keep if z.radius_mm is not None]
        radius = max(radii) if radii else (keep[0].width() / 2.0 if keep else 0.0)

        return {
            "display_name": self.display_name,
            "work_area_width_mm": self.work_area_width_mm,
            "work_area_height_mm": self.work_area_height_mm,
            "safe_z_mm": self.safe_z_mm,
            "max_z_mm": self.max_z_mm,
            "blank_zones": blank_zones,
            "hold_down_screws": screws,
            "hold_down_screw_radius_mm": radius,
        }

    @classmethod
    def from_fixture_dict(cls, fixture: dict, *, name: str = "guild_cnc",
                          circle_segments: int = 48) -> "Worktable":
        """Load a YAML fixture dict (config/fixtures/*.yaml) into a Worktable: each
        blank zone becomes a role-tagged rectangle, each hold-down screw a KEEP_OUT
        circle ring — the built-in default Guild bed (BUILDPLAN M7.4)."""
        import math

        zones: list[WorktableZone] = []
        _passthrough = {"label", "x_mm", "y_mm", "width_mm", "height_mm",
                        "stock_thickness_mm"}
        for key, z in (fixture.get("blank_zones") or {}).items():
            x, y = float(z["x_mm"]), float(z["y_mm"])
            w, h = float(z["width_mm"]), float(z["height_mm"])
            ring = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            role = _ROLE_BY_FIXTURE_ZONE.get(key, BedRole.UNASSIGNED)
            extra = {k: v for k, v in z.items() if k not in _passthrough}
            zones.append(WorktableZone(
                id=key, role=role, label=z.get("label", bed_role_label(role)),
                polygon=ring, stock_thickness_mm=z.get("stock_thickness_mm"),
                source=f"fixture:{key}", extra=extra))

        r = float(fixture.get("hold_down_screw_radius_mm", 5.0))
        for i, s in enumerate(fixture.get("hold_down_screws") or []):
            cx, cy = float(s["x"]), float(s["y"])
            ring = [(cx + r * math.cos(2 * math.pi * k / circle_segments),
                     cy + r * math.sin(2 * math.pi * k / circle_segments))
                    for k in range(circle_segments)]
            zones.append(WorktableZone(
                id=f"screw_{i + 1}", role=BedRole.KEEP_OUT, label="Hold-down screw",
                polygon=ring, radius_mm=r, source="fixture:screw"))

        return cls(
            name=name,
            display_name=fixture.get("display_name", name),
            work_area_width_mm=float(fixture.get("work_area_width_mm", 300.0)),
            work_area_height_mm=float(fixture.get("work_area_height_mm", 200.0)),
            safe_z_mm=float(fixture.get("safe_z_mm", 5.0)),
            max_z_mm=float(fixture.get("max_z_mm", 80.0)),
            zones=zones,
        )


class Component(BaseModel):
    """One role-typed part of a project (BUILDPLAN M7.1).

    Ties a `kind` to its per-kind parameters and provenance. Geometry is *not*
    stored here — it is derived from the project's embedded source file(s) (the
    DXF / `.gdraw`), matching the M1–M6 single-component pattern — so a Component
    is the params + identity + generated-output record for one part. Exactly one
    of `castle` / `temple` / `base_curve_block` is populated, selected by `kind`
    (the param matching the kind is default-constructed if absent).
    """
    id: str
    kind: ComponentKind
    label: str = ""
    enabled: bool = True

    # per-kind parameters — exactly one populated, per `kind` (see params())
    castle: CastleParams | None = None
    temple: TempleParams | None = None
    base_curve_block: BaseCurveBlockParams | None = None
    # Per-component G54 work zero (M11): each part keeps its own datum so separately
    # exported NC files (front, each temple) don't all share one zero.
    program_zero: ProgramZero = Field(default_factory=ProgramZero)

    forming: FormingMetadata = Field(default_factory=FormingMetadata)

    # provenance
    source_file: str = ""        # the DXF / .gdraw this component came from
    source_workspace: str = ""   # .gdraw workspace (front/temple_r/temple_l/hinge), if any

    # generated-output record (files under the .gmodel components/<id>/ tree, M7.1)
    program_files: list[str] = Field(default_factory=list)
    has_program: bool = False

    @model_validator(mode="after")
    def _populate_kind_defaults(self) -> "Component":
        """Make the model total for its kind: default-construct the matching
        param if absent (with the kind's fixture zone), and fill the label."""
        field = component_param_field(self.kind)
        if getattr(self, field) is None:
            if field == "castle":
                setattr(self, field, CastleParams())
            elif field == "temple":
                setattr(self, field, TempleParams(
                    fixture_zone=component_fixture_zone(self.kind)))
            else:
                setattr(self, field, BaseCurveBlockParams(
                    fixture_zone=component_fixture_zone(self.kind)))
        if not self.label:
            self.label = component_label(self.kind)
        return self

    def params(self) -> CastleParams | TempleParams | BaseCurveBlockParams:
        """The param model that drives this component's CAM (per `kind`)."""
        return getattr(self, component_param_field(self.kind))

    def fixture_zone(self) -> str:
        """The component's own fixture zone, falling back to the kind default."""
        p = self.params()
        return getattr(p, "fixture_zone", None) or component_fixture_zone(self.kind)

    @classmethod
    def for_kind(cls, kind: ComponentKind, *, id: str | None = None,
                 label: str | None = None, **kw) -> "Component":
        """A default Component for `kind` (its matching param default-built)."""
        kind = ComponentKind(kind)
        return cls(id=id or kind.value, kind=kind,
                   label=label or component_label(kind), **kw)


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
    temple: TempleParams = Field(default_factory=TempleParams)   # BUILDPLAN M6.3
    base_curve_block: BaseCurveBlockParams = Field(default_factory=BaseCurveBlockParams)  # M6.4
    bed_layout: BedLayout = Field(default_factory=BedLayout)      # BUILDPLAN M6.5
    worktable: Worktable | None = None                           # BUILDPLAN M7.4
    machine: MachineRef = Field(default_factory=MachineRef)

    # The multi-component model (BUILDPLAN M7.1). A project is an ordered list of
    # role-typed components (frame front + temples + per-lens base-curve
    # templates). Empty = a legacy single-component project; call
    # `ensure_components()` to migrate it to a one-component (frame_front) project.
    # The flat `castle` / `temple` / `base_curve_block` fields above remain for the
    # M1–M6 single-component paths until they are migrated to read a component.
    components: list[Component] = Field(default_factory=list)

    def components_of_kind(self, kind: ComponentKind) -> list[Component]:
        """Every component of `kind`, in project order."""
        kind = ComponentKind(kind)
        return [c for c in self.components if c.kind == kind]

    def component(self, kind: ComponentKind) -> Component | None:
        """The first component of `kind`, or None."""
        comps = self.components_of_kind(kind)
        return comps[0] if comps else None

    def frame_front(self) -> Component | None:
        return self.component(ComponentKind.FRAME_FRONT)

    def add_component(self, comp: Component) -> Component:
        """Append `comp`, making its id unique within the project."""
        existing = {c.id for c in self.components}
        if comp.id in existing:
            base, n = comp.id, 2
            while f"{base}_{n}" in existing:
                n += 1
            comp.id = f"{base}_{n}"
        self.components.append(comp)
        return comp

    def ensure_components(self) -> "ProjectSchema":
        """Migrate a legacy single-component project (BUILDPLAN M7.1).

        If `components` is empty, synthesize one `frame_front` Component from the
        flat `castle` / `forming` / `source_file` fields — so an M1–M6 `.gmodel` or
        project loads as a one-component project. Idempotent; returns self.
        """
        if not self.components:
            self.components.append(Component(
                id=ComponentKind.FRAME_FRONT.value,
                kind=ComponentKind.FRAME_FRONT,
                castle=self.castle,
                forming=self.forming,
                source_file=self.source_file,
            ))
        return self
