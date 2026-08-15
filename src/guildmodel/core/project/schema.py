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
    (vendored under tests/fixtures/demo/).
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

    Defaults are the Demo Project reference values, including
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

    The heightfield analog of the complex Fusion stock model — CAM and
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
    # Start the cut away from bottom-center, leaving the middle uncut (2026-08-11).
    # A **keyhole** bridge carries its own shape across the centerline and a splay
    # run through it planes that shape off; the maker wants the two halves of the
    # splay and nothing between them. `gap_mm` is the total uncut width, measured
    # as arc length along the outline and split evenly either side of bottom-center,
    # so each side now runs from `gap_mm / 2` out to `run_mm`.
    #
    # Not a separate feature: it is the same crest, the same angles and the same
    # feather, with the middle of the station table taken out. That keeps the two
    # halves guaranteed symmetric and keeps one set of controls to learn — and it
    # is why `feather_mm` applies at the inner ends too, so the cut runs out to
    # nothing at the keyhole instead of stopping in a wall.
    non_contiguous: bool = False
    gap_mm: float = Field(8.0, gt=0)

    def spans(self) -> list[tuple[float, float]]:
        """The signed station intervals the splay covers, in mm from bottom-center.

        One interval `(-run, run)` normally; two, mirror-image, when the cut is
        non-contiguous. Empty when the gap has swallowed the whole run, which is a
        splay the maker has switched off by the back door rather than an error.
        """
        run = float(self.run_mm)
        if not self.non_contiguous:
            return [(-run, run)]
        half = float(self.gap_mm) / 2.0
        if half >= run:
            return []
        return [(-run, -half), (half, run)]


class EyewireBezelParams(BaseModel):
    """Constant-width chamfer band around each lens opening's rim — the "bezeled
    eyewire" (M13.2). Depth below the local surface at the rim is
    width_mm * tan(angle_deg); the anterior clamp floors the cut.

    `face` (M17) picks which side of the frame the band is cut into. The
    posterior band is the historical one and stays the default; `anterior` moves
    it to the front face and `both` cuts a matching band on each side — the
    "instead of or in addition to" the maker asked for. An anterior band is
    modeled and previewed now; machining it needs the flip setup (M9/V2).
    """
    enabled: bool = False
    width_mm: float = 2.5
    angle_deg: float = 30.0
    anterior_clamp_mm: float = 1.5
    face: Literal["posterior", "anterior", "both"] = "posterior"
    # Anterior band geometry, used when `face` is anterior/both. Separate from the
    # posterior numbers because the two sides are different jobs: the posterior
    # bezel seats the lens, the anterior one is cosmetic and usually shallower.
    anterior_width_mm: float = 1.5
    anterior_angle_deg: float = 45.0
    # The anterior cut may never leave the frame thinner than this at any point.
    min_thickness_mm: float = 1.0

    def cuts_posterior(self) -> bool:
        return self.enabled and self.face in ("posterior", "both")

    def cuts_anterior(self) -> bool:
        return self.enabled and self.face in ("anterior", "both")

    def as_edge_features(self) -> list["EdgeFeature"]:
        """The anterior band, expressed as whole-ring `EdgeFeature`s.

        The anterior band *is* a chamfer round a whole ring, so describing it as
        one leaves a single chamfer implementation to trust instead of a copy of
        the same maths per kernel. It lives on the params rather than in any one
        kernel because all three paths need the identical list: the raster
        (`relief.edges.carve_anterior_bezel`), the B-Rep
        (`solid.features.bezel_cutters`) and the mesh
        (`model.features.bezel_cutters`). Two of them had their own copy and the
        third had none, which is how `face="anterior"` came to model on one
        kernel and silently not on the other.

        Empty `zones` is the whole ring — see `relief.edges.spans_whole_ring`,
        which the solid kernels need because of it. `blend_mm=0` because the
        band does not feather out; it closes on itself.

        The posterior band is *not* here. It is a purpose-built loft anchored on
        the surface it seats the lens against, and it is only cut around lens
        apertures — a decorative OUTLINE opening seats no lens.
        """
        if not self.cuts_anterior() or self.anterior_width_mm <= 0:
            return []
        return [
            EdgeFeature(
                id=f"anterior-bezel-{edge}", label="Anterior eyewire bezel",
                face="anterior", edge=edge, profile="chamfer",
                width_mm=self.anterior_width_mm,
                angle_deg=self.anterior_angle_deg,
                min_thickness_mm=self.min_thickness_mm,
                zones=[], blend_mm=0.0, mirror=False,
            )
            for edge in ("lens_od", "lens_os")
        ]


class EdgeFeature(BaseModel):
    """One chamfer or fillet run along part of an edge (BUILDPLAN M17).

    The feature the thick modern frames need: a chamfer on the **anterior brow**,
    over each eyewire, *not* carried across the bridge. That shape is impossible
    to describe with the M13 bezel, which is a constant band all the way round a
    ring — hence a feature with a span, a profile, and a taper.

    **The span is named by zones, not by numbers along the ring.** `zones` lists
    the castle zones the run covers (empty = the whole ring); the run is the part
    of the ring those zones own. That survives re-importing a tweaked drawing —
    an arc-length fraction would silently point somewhere else — it reads as the
    maker already thinks ("over the brow, not the bridge"), and it mirrors by
    swapping `_od` for `_os`. `trim_start_mm` / `trim_end_mm` then nudge each end
    along the ring for the last few millimeters of control, and `blend_mm` tapers
    the cut to nothing at each end so it feathers out instead of stopping dead.

    `width_end_mm` makes the run **variable**: the chamfer widens or narrows
    along its length. Left None it is constant at `width_mm`.
    """
    id: str = ""
    label: str = ""
    enabled: bool = True

    # Which face and which edge ring.
    face: Literal["anterior", "posterior"] = "anterior"
    edge: Literal["outline", "lens_od", "lens_os"] = "outline"

    # The span, in castle-zone vocabulary. Empty `zones` = the whole ring.
    zones: list[str] = Field(default_factory=list)
    trim_start_mm: float = 0.0     # + pulls the start in, - pushes it out
    trim_end_mm: float = 0.0
    blend_mm: float = Field(4.0, ge=0)   # taper to nothing over this run-in

    # Profile.
    profile: Literal["chamfer", "fillet"] = "chamfer"
    width_mm: float = Field(2.0, gt=0)          # chamfer's radial run at the start
    width_end_mm: float | None = Field(None, gt=0)   # None = constant width
    angle_deg: float = Field(45.0, gt=0, lt=90)
    radius_mm: float = Field(2.0, gt=0)         # fillet radius
    depth_limit_mm: float | None = Field(None, gt=0)  # cap the axial cut

    # Never leave the frame thinner than this where the feature cuts.
    min_thickness_mm: float = Field(1.0, ge=0)

    # Emit the x-mirrored twin automatically (OD ↔ OS). The brow chamfer is
    # always a pair, and keeping it one feature means one edit, not two.
    mirror: bool = True

    def width_at(self, t: float) -> float:
        """Chamfer width at normalized station `t` (0 at the run's start)."""
        if self.width_end_mm is None:
            return self.width_mm
        return self.width_mm + (self.width_end_mm - self.width_mm) * min(max(t, 0.0), 1.0)

    def max_width_mm(self) -> float:
        """The widest the feature ever reaches — the search radius the carver needs."""
        if self.profile == "fillet":
            return self.radius_mm
        return max(self.width_mm, self.width_end_mm or self.width_mm)

    def mirrored(self) -> "EdgeFeature":
        """The x-mirrored twin: OD zones become OS (and vice versa), and a lens
        edge swaps sides. A center zone (`bridge`) is its own mirror, so a run
        that legitimately spans the center mirrors onto itself."""
        def swap(name: str) -> str:
            if name.endswith("_od"):
                return name[:-3] + "_os"
            if name.endswith("_os"):
                return name[:-3] + "_od"
            return name
        edge = {"lens_od": "lens_os", "lens_os": "lens_od"}.get(self.edge, self.edge)
        return self.model_copy(update={
            "id": f"{self.id}_mirror" if self.id else "",
            "label": f"{self.label} (mirrored)" if self.label else "",
            "zones": [swap(z) for z in self.zones],
            "edge": edge,
            "mirror": False,          # the twin never mirrors again
        })


class BridgeReliefParams(BaseModel):
    """Bridge projection relief (M13.3, reworked 2026-07-02): a CONIC scoop on
    the posterior bridge, running on Y — the base (widest, deepest cut of the
    cone section) opens through the top edge of the frame over the bridge, and
    the sides taper at `taper_angle_deg` per side to a rounded tip down the
    lower bridge. The depth scales with the local width (a true cone imprint
    feathering to nothing at the tip), so the cut flows with the smooth footing.

    **The cross-section is a footing-style U** *(2026-08-11, field report)*. It
    was a tangent cosine bell, which is smooth but has no numbers in it: a maker
    who wanted the trough tighter, or the rim to blend further out into the
    bridge, had nothing to turn. `exterior_radius_mm` and `interior_radius_mm`
    are the same pair `FootingFillet` already uses and mean the same things — a
    convex round-over where the cut leaves the surrounding face, a concave
    fillet where it lands on the floor — with a straight ramp between them.
    `geometry.blends.scoop_drop` builds it and all three kernels call that one
    function.

    Both radii at 0 is a straight V, which is a legitimate thing to ask for. The
    defaults are the pair that most nearly reproduces the cosine bell this
    replaced (23.6 degrees of ramp against its 25.2), so an existing project
    opens looking like itself.
    """
    enabled: bool = False
    width_mm: float = 8.0                    # scoop width at its base (the top edge)
    depth_mm: float = 1.2                    # cut depth at the base centerline
    taper_angle_deg: float = 30.0            # per-side taper of the cone toward the tip
    # Convex round-over at the rim, where the scoop leaves the bridge surface.
    exterior_radius_mm: float = Field(3.0, ge=0)
    # Concave fillet at the trough, where the scoop lands on its floor.
    interior_radius_mm: float = Field(3.0, ge=0)
    anterior_clamp_mm: float = 1.5

    def max_slope_deg(self) -> float:
        """The steepest slope on the scoop — the ramp between the two arcs."""
        from ..geometry.blends import scoop_max_slope_deg
        return scoop_max_slope_deg(self.width_mm, self.depth_mm,
                                   self.exterior_radius_mm,
                                   self.interior_radius_mm)

    def trough_radius_mm(self) -> float:
        """Concave radius at the bottom of the U at its widest station — the
        largest ball that can reach the root, and 0 for a sharp V, which no ball
        can finish. The radii shrink toward the tip along with the section, so
        this is the base figure; the CAM warns against it because that is where
        the maker's tool choice is decided."""
        from ..geometry.blends import scoop_ramp_angle
        _theta, _re, ri = scoop_ramp_angle(
            max(self.width_mm / 2.0, 1e-9), max(self.depth_mm, 1e-9),
            self.exterior_radius_mm, self.interior_radius_mm)
        return float(ri)


class HoldingParams(BaseModel):
    """How a released part is held in the blank until the cut finishes (M16).

    Two strategies, and they are **alternatives, not additions** — the reason the
    tab machinery in `cam/tabs.py` sat unused since it was written:

    * ``skin`` (default, the historical behavior) — the through-cut stops
      ``onion_skin_mm`` above the anterior face and the part is snapped/sanded off
      that wafer by hand. Nothing to program around; the whole part edge is cut at
      full depth.
    * ``tabs`` — the through-cut goes to the anterior face (z = 0, never below: the
      Guild fixture's hold-down screws and blank zone live under the stock) and the
      **last depth pass** rises over `tab_count` uncut bridges. The part is free
      except at the tabs, which are cut off and filed. Choose this when the onion
      skin is fighting you — a thin or brittle blank that cracks when the wafer is
      broken, or a part small enough that the skin distorts it.

    Tabs apply only to the op that **releases the part** (the outside profile).
    Inside through-cuts — eyewires, decorative holes — always keep the onion skin:
    their waste slug is dropping into the fixture either way, and a tabbed slug is
    a loose piece for the cutter to catch rather than a part worth saving.
    """
    strategy: Literal["skin", "tabs"] = "skin"
    tab_count: int = Field(4, ge=0, le=16)
    tab_width_mm: float = Field(3.0, gt=0)
    # Uncut bridge height, measured up from the anterior face. Must stay under the
    # blank thickness or the "tab" is the whole part.
    tab_height_mm: float = Field(1.0, gt=0)

    def tabs_on(self) -> bool:
        return self.strategy == "tabs" and self.tab_count > 0


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
    onion_skin_mm: float = 0.4               # axial stock left under through-cuts (skin holding)
    hand_finishing_allowance_mm: float = 0.1  # radial leave-behind stock on contour operations
    holding: HoldingParams = Field(default_factory=HoldingParams)   # skin | tabs (M16)
    # Posterior finishing features (M13, all default-off — the M2/M3/M4 gates
    # machine the bare castle; each is a min-carve into the footed surface).
    pad_splay: PadSplayParams = Field(default_factory=PadSplayParams)
    eyewire_bezel: EyewireBezelParams = Field(default_factory=EyewireBezelParams)
    bridge_relief: BridgeReliefParams = Field(default_factory=BridgeReliefParams)
    lens_groove: LensGrooveParams = Field(default_factory=lambda: LensGrooveParams())
    # Partial-span chamfers / fillets on either face (M17). Empty = none, so every
    # existing project models exactly as before.
    edge_features: list[EdgeFeature] = Field(default_factory=list)

    def resolved_edge_features(self) -> list[EdgeFeature]:
        """Every enabled edge feature, each followed by its mirrored twin where
        `mirror` is set — the list the carver actually walks."""
        out: list[EdgeFeature] = []
        for f in self.edge_features:
            if not f.enabled:
                continue
            out.append(f)
            if f.mirror:
                out.append(f.mirrored())
        return out

    def cuts_anterior(self) -> bool:
        """True when anything in this castle removes material from the front face
        — the flag the relief build uses to decide whether an anterior surface is
        needed at all (M17). False keeps the historical single-surface fast path."""
        return (self.eyewire_bezel.cuts_anterior()
                or any(f.face == "anterior" for f in self.resolved_edge_features()))

    def cuts_posterior_features(self) -> bool:
        """True when any posterior finishing feature is on — the condition for
        there being a feature band at all (M13/M17)."""
        return (self.pad_splay.enabled or self.eyewire_bezel.cuts_posterior()
                or self.bridge_relief.enabled
                or any(f.face == "posterior"
                       for f in self.resolved_edge_features()))

    def posterior_feature_slope(self) -> float:
        """The steepest enabled posterior finishing feature, in degrees.

        The CAM turns this into a stepover: on a chamfer the contour rings are
        its level curves, so a flat tool leaves facet ridges of
        `stepover * tan(slope)` between them, and the feature-finish pass picks
        a stepover from a cusp height instead (`cam.castle_ops`).

        Here on the params, in the pattern `EyewireBezelParams.as_edge_features`
        set, because more than one path needs the identical number and a second
        copy of a derivation is how this project has repeatedly ended up with
        two answers. The raster accumulates the same figures as it carves, so it
        drops a feature that turned out to carve nothing; this cannot know that
        and reports the enabled one. The difference is a finer stepover in the
        one case where a feature is on and removes nothing, never a coarser one.
        """
        import math

        slope = 0.0
        splay = self.pad_splay
        if splay.enabled:
            slope = max(slope, splay.angle_center_deg,
                        *((splay.angle_middle_deg, splay.angle_end_deg)
                          if splay.toric else ()))
        if self.eyewire_bezel.cuts_posterior():
            slope = max(slope, self.eyewire_bezel.angle_deg)
        scoop = self.bridge_relief
        if scoop.enabled:
            # The U's straight ramp: both arcs are tangent to it at one end and
            # to a horizontal at the other, so nothing on the scoop is steeper.
            slope = max(slope, scoop.max_slope_deg())
        for f in self.resolved_edge_features():
            if f.face != "posterior":
                continue
            # A round-over's steepest tangent is vertical at the edge; the
            # useful number for a finishing stepover is its 45 degree mid-slope.
            slope = max(slope, 45.0 if f.profile == "fillet" else f.angle_deg)
        return float(slope)


# Canonical posterior op names, in machining order. These are the keys for the
# per-operation tool assignment (BUILDPLAN M6.1) and the labels the post / sim /
# cut-time model already canonicalize on.
#
# The **optional** ops — "Features" (only present when a posterior feature is
# on), "Holes" (only when the drawing has decorative openings) and "Lens Groove"
# (V1) — are deliberately NOT listed. Each of them has a sensible per-op default
# that is another op's tool rather than the global one, and listing them here
# would make every job read as multi-tool even with the feature off. They are
# still first-class where it counts: `tools_in_use` scans pinned `op_tools`
# alongside this tuple, and the GUI offers a selector for each.
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

    `fixture` keeps the design frame (current behavior — zero at the blank
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
    # tools.yaml. Empty = every op uses tool_name (single-tool, M1–M5 behavior).
    # The everyday multi-tool case: a small tool clears the hinge pockets, the
    # bulk tool does relief / eyewires / perimeter.
    op_tools: dict[str, str] = Field(default_factory=dict)

    # Per-operation enable/skip (M16): op name -> False to leave it out of the
    # program. Absent = enabled, so an empty dict is the historical "cut everything"
    # and old projects load unchanged. The everyday use is cutting a job in stages —
    # pocket and engrave today, release the part after the inserts go in — or
    # re-posting one operation after a tool change without re-cutting the rest.
    # Disabling the releasing profile deliberately leaves the part in the blank.
    op_enabled: dict[str, bool] = Field(default_factory=dict)

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
        """Distinct tool names across the program's ops, in machining order.

        The canonical five, **plus every op the maker has explicitly pinned**.
        The optional ops — "Features", "Holes", "Lens Groove" — are deliberately
        not in `POSTERIOR_OPS` (see the note there), and scanning only that tuple
        meant a pinned tool on one of them was invisible to `is_multi_tool`,
        which is what decides whether the post emits tool-change blocks and
        per-tool feeds at all. A ball pinned to "Features" would then have been
        run at the end mill's feeds with no change block: the lens groove's
        `or relief.groove is not None` at each call site is a workaround for the
        same gap, and this closes it for every optional op at once.

        An op pinned to the tool it would have used anyway does not count — the
        comparison is on resolved names, not on whether an entry exists.
        """
        seen: list[str] = []
        for op in (*POSTERIOR_OPS, *self.op_tools):
            name = self.tool_for_op(op)
            if name not in seen:
                seen.append(name)
        return seen

    def is_multi_tool(self) -> bool:
        return len(self.tools_in_use()) > 1

    def is_op_enabled(self, op_name: str) -> bool:
        """Whether `op_name` should be emitted (M16). Unknown/absent = enabled."""
        return bool(self.op_enabled.get(op_name, True))

    def enabled_ops(self, ops: list) -> list:
        """`ops` minus the operations the maker has switched off."""
        return [op for op in ops if self.is_op_enabled(op.name)]

    # strategy / geometry. The step / stepover fields drive `while`-loops that only
    # advance by their value, so 0 or negative would spin forever — reject them at
    # load with a clear error (the generators also floor them defensively). `gt=0`
    # is deliberately NOT on rough_axial_stock_mm (0 = leave no extra roughing stock).
    pocket_stepover_mm: float = Field(1.2, gt=0)
    relief_stepover_mm: float = Field(0.9, gt=0)   # matches Fusion Scallop coverage
    rough_axial_stock_mm: float = 2.0
    # Requested through-cut depth per pass, clamped down per material+machine by
    # `max_doc`. M12.4 set this to 4.0 ("cut as deep as the material allows") on the
    # strength of an unvalidated acetate DOC ceiling; the field verdict is that a
    # full-depth pass is far too much bite. 1.5 is the conservative baseline — a 4 mm
    # temple blank cuts in three passes rather than one — and the maker raises it per
    # job from the Cut tab, which now shows the resulting pass count.
    contour_stepdown_mm: float = Field(1.5, gt=0)
    # Axial depth per pocket level (hinge recesses). The outer ring ramps in at
    # `ramp_step_mm` per lap; the floor cascade that follows used to clear the whole
    # remaining depth in ONE full-depth pass, so a deep pocket buried the cutter. Now
    # the pocket is cut in levels this deep, each with its own cascade.
    pocket_stepdown_mm: float = Field(1.0, gt=0)
    ramp_step_mm: float = Field(0.6, gt=0)  # pocket ramp descent per lap
    contour_ramp_angle_deg: float = 8.0    # through-cut lead-in ramp (partial lap)
    # How a through-cut pass enters the material (M16). `ramp` is the historical
    # partial-lap ramped lead-in — no slot-plunge, at the cost of the lead-in
    # distance every pass. `plunge` drops straight to depth at the pass start and
    # cuts one clean lap: shorter and perfectly serviceable for a small tool in
    # acetate, and the only option that makes sense with a slow plunge rate and a
    # center-cutting endmill. NOTE this is not a duplicate of a zero ramp angle —
    # `_emit_ramped_loop` treats a non-positive angle as "ramp the WHOLE lap", so
    # before this field there was no way to ask for a straight entry at all.
    contour_lead_in: Literal["ramp", "plunge"] = "ramp"
    # Milling direction for the through-cut contours (M16). `climb` (default, the
    # M12.5 behavior) runs the cutter so the chip thins to zero — the cleaner wall
    # on acetate, and what the Fusion reference program does. `conventional`
    # reverses every ring: the choice for a machine with backlash it cannot take
    # out, where climb milling pulls the cutter into the work.
    cut_direction: Literal["climb", "conventional"] = "climb"
    skim_epsilon_mm: float = 0.05          # "nothing to cut" threshold for roughing
    # Contour-relief linking (M11): bridge a contour ring's masked gaps up to this
    # width by riding the cutter over the thin cap instead of retract+plunging across
    # it — turns a ring shattered into tiny stub paths ("drill holes" over caps/bands)
    # into one long sweep, like a Fusion contour. A run still shorter than
    # `relief_min_run_mm` after linking is dropped (negligible material, hand-finished).
    relief_link_gap_mm: float = 4.0
    # How far ABOVE its two cut ends the tool may be carried when it rides the
    # drop-cutter surface between them (M-Z2, M-Z3). Two places do that: the gap
    # linking above, and the M12.2 stitch that joins adjacent paths into one sweep.
    # Both were written for "a thin cap" and neither asked how tall it was — wrong
    # wherever the ground between two cut points is masked *precisely because it
    # stands at stock height*, which is what the rim band does next to uncut stock.
    # Corner Optical's frame climbed 5.8 mm out of the eyewire terrace that way.
    # 0.5 mm still rides a thin cap; over it, the link or the stitch is refused and
    # the paths keep their own entries — a retract and a plunge, removing exactly the
    # same material, which is what the cut mask intended in the first place.
    relief_link_max_rise_mm: float = Field(0.5, ge=0)
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
    # at each stock-blank corner + one at each lens center, `screw_head_diameter_mm`
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
    box (assumed centerd on the design origin, like the frame blank) feeds the
    program-zero offset and the safe-Z; defaults match the `temple_right` fixture
    zone (170 × 30 × 4 mm).
    """
    blank_length_mm: float = 170.0
    blank_width_mm: float = 30.0
    blank_thickness_mm: float = 4.0
    hinge_pocket_depth_mm: float = 1.0     # HINGE pocket floor below the top face
    engrave_depth_mm: float = 0.3          # groove depth below the top face
    # Axial depth per engraving pass. A groove deeper than this is cut in several
    # passes instead of one plunge to full depth — a 1.5 mm channel with a slender
    # V-bit or 1 mm endmill snaps the tool otherwise. The 0.3 mm default groove is
    # one pass either way, so shallow engraving is unchanged.
    engrave_stepdown_mm: float = Field(0.5, gt=0)
    engrave_tool: str = "engrave_vbit"     # small tool for the ENGRAVING passes
    hinge_tool: str = "flat_2mm"           # endmill that clears the HINGE pockets
    # M11 #7: engrave a single fixed-depth line down each stroke's CENTER (medial
    # axis of the closed glyph outlines) instead of tracing the outlines — one pass
    # per stroke, no double-cut ridge. Off = trace the raw ENGRAVING outlines.
    engrave_centerline: bool = True
    profile_tool: str = "flat_3175"        # outline through-cut tool
    onion_skin_mm: float = 0.4             # axial stock left under the profile
    hand_finishing_allowance_mm: float = 0.1
    holding: HoldingParams = Field(default_factory=HoldingParams)   # skin | tabs (M16)
    fixture_zone: str = "temple_right"     # fixture blank zone (clearance check)

    # Snap the temple to one end of the blank so the injected metal core (a wire
    # set into the blank along its length) runs through the whole temple — the
    # HINGE/butt end registers to a short edge of the 170 mm blank (BUILDPLAN M7).
    # ON by default (workflow decision 2026-07-09): blanks are slid into the fixture
    # with their core ends against one stop, so the cut is always plotted from the
    # snapped position — the 2D view back-projects the blank/datum/toolpath so it
    # still matches the drawing. OFF leaves the part at its DESIGN alignment (legacy;
    # the program-zero datum then assumes the drawing is centerd on the blank).
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
    holding: HoldingParams = Field(default_factory=HoldingParams)   # skin | tabs (M16)

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
        """Mounting-hole centers in the block frame (centerd on the origin)."""
        n = self.hole_count
        s = self.hole_spacing_mm
        if self.hole_arrangement == "triangle" and n == 3:
            # equilateral triangle, side = spacing, centroid at the origin
            h = s * (3 ** 0.5) / 2.0
            cy = h / 3.0
            return [(-s / 2.0, -cy), (s / 2.0, -cy), (0.0, h - cy)]
        # in-line, centerd: pitch = spacing along x
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
    (and optionally rotated) onto the bed — by default the center of its
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
        """Vertex mean — the exact center of a regular ring (a screw) and a
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


class ComponentCamOverrides(BaseModel):
    """Per-component departures from the project-global `CastleCamParams` (M16).

    `cam_params` is one model for the whole project — sensible while every part is
    the same acetate on the same machine, and wrong the moment a project mixes
    stock. The standard job already does: the frame front and both temples are
    acetate, the base-curve forming blocks are **acetal**, whose depth-of-cut
    ceiling is half acetate's. Before this, only the block's *feeds* re-read its own
    material; its depth per pass came from whatever the frame was set to.

    Every field is optional and ``None`` means "inherit". `material` is the
    important one — it re-clamps the depth per pass through that material's own
    `max_doc_mm` at post time — and the rest are escape hatches for a part that
    needs a lighter cut than its material's defaults imply (a fragile small piece,
    a worn tool kept in service for one component).
    """
    material: str | None = None
    contour_stepdown_mm: float | None = Field(None, gt=0)
    pocket_stepdown_mm: float | None = Field(None, gt=0)
    feed_rate_mmpm: float | None = Field(None, gt=0)
    spindle_rpm: int | None = Field(None, gt=0)
    cut_direction: Literal["climb", "conventional"] | None = None

    def is_empty(self) -> bool:
        """True when nothing is overridden — the component inherits everything."""
        return not self.model_dump(exclude_none=True)

    def apply(self, cam: "CastleCamParams") -> "CastleCamParams":
        """`cam` with this component's overrides layered on (material excluded —
        that one selects the preset the caller clamps against, it is not a CAM
        field). Returns `cam` unchanged when nothing is set."""
        update = self.model_dump(exclude_none=True)
        update.pop("material", None)
        return cam.model_copy(update=update) if update else cam


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
    # Per-component departures from the project-global cam_params (M16) — most
    # usefully the material, since a base-curve block is acetal among acetate parts.
    cam_overrides: ComponentCamOverrides = Field(default_factory=ComponentCamOverrides)

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
