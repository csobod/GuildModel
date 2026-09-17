"""Base-curve holding-block CAM (BUILDPLAN M6.4).

Auto-generate the base-curve holding block straight from the frame DXF. The block
is the **lens shape** cut from a flat acetal blank — it sits on the base-curve press
and holds the eyewire so the frame doesn't distort while thermoforming. Two cuts,
nothing else (confirmed with the user 2026-06-19):

  1. **Drill Holes** — three M4 mounting holes (peck-drilled) that bolt it to the
     jig; cut first while the blank is rigid.
  2. **Block Profile** — the **lens exterior shape** through-cut with an onion skin,
     freeing the block last — exactly the way a frame outline is cut.

The drill uses its own tool, so the program carries one tool change (M6.1). The
lens shape is centerd on the blank; everything rides the shared GRBL post and
program-zero offset (M6.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.affinity import translate
from shapely.geometry import Point, Polygon

from ..project.schema import BaseCurveBlockParams, CastleCamParams
from .castle_ops import CamOp, contour_op, resolve_tool

Point3 = tuple[float, float, float]

# Op-name sets for write_castle_program (drill peck-cycle, ramped through-cut).
BLOCK_DRILL_OPS = {"Drill Holes"}
BLOCK_CONTOUR_OPS = {"Block Profile"}


def center_on_origin(poly: Polygon) -> Polygon:
    """Translate a polygon so its bounding-box center sits at the origin — the
    lens footprint then sits symmetrically in the square block."""
    x0, y0, x1, y1 = poly.bounds
    return translate(poly, xoff=-(x0 + x1) / 2.0, yoff=-(y0 + y1) / 2.0)


@dataclass(frozen=True)
class HoleFit:
    """Where one mounting hole lands relative to the block it is drilled into."""

    center: tuple[float, float]
    #: Material between the hole and the block rim, mm. Zero or less means the
    #: hole is not a hole — it is a notch bitten out of the edge.
    wall_mm: float
    #: Is the hole's *center* even on the block? False is the worse failure:
    #: the drill plunges into blank scrap and the part gets no hole at all.
    inside: bool

    @property
    def breaches(self) -> bool:
        return self.wall_mm <= 0.0


def hole_fits(lens_outline: Polygon,
              block: BaseCurveBlockParams) -> list[HoleFit]:
    """Measure each mounting hole against the block it is drilled into.

    `hole_centers()` is a fixed pattern — three holes on a 10 mm pitch by
    default — and nothing has ever checked it against the lens actually being
    cut. It does not fit every lens: on a 43 mm eye — the smallest in the
    maker's corpus — two of the three break through the rim and the template
    comes out with **one** usable mounting point.

    Both failures are silent today. The mesh is watertight either way — a
    breached hole just merges into the outline and leaves a clean notch — so
    `verify_mesh` passes it, the viewer draws it, and the program drills it.
    Genus is what gives it away: a good template is Euler −4 (three through
    holes), and those two come out at 0.
    """
    centered = center_on_origin(lens_outline)
    r = block.hole_diameter_mm / 2.0
    out: list[HoleFit] = []
    for hx, hy in block.hole_centers():
        p = Point(hx, hy)
        d = centered.exterior.distance(p)
        inside = bool(centered.contains(p))
        # Outside the rim, the signed wall keeps running negative rather than
        # bottoming out at zero, so "how far off" stays readable in the message.
        out.append(HoleFit((float(hx), float(hy)),
                           float(d - r if inside else -(d + r)), inside))
    return out


def hole_fit_warnings(lens_outline: Polygon,
                      block: BaseCurveBlockParams) -> list[str]:
    """Say, in a maker's terms, which mounting holes will not come out right.

    **The thin-wall bound is the blank's own thickness, and it was measured.**
    Across all 96 base-curve templates in the frame library the walls fall into
    two populations with nothing in between: 86 sit at 6.84 mm or more (median
    11.04, max 14.80), and the other 10 at 1.14 mm or less (8 of them negative,
    down to −6.13 mm). Every value in 1.14 … 6.84 mm is empty, so any bound in
    that band separates them; `blank_thickness_mm` (4.76 mm by default) sits in
    the middle of it, means something physical — a mounting tab thinner than the
    plate is thick — and moves with the blank instead of being a magic number.
    """
    thin = block.blank_thickness_mm
    out: list[str] = []
    for fit in hole_fits(lens_outline, block):
        x, y = fit.center
        where = f"at ({x:+.1f}, {y:+.1f}) mm"
        if not fit.inside:
            out.append(
                f"The mounting hole {where} is off the block entirely — it "
                f"misses the edge by {abs(fit.wall_mm):.2f} mm, so the drill "
                "cuts blank scrap and the template gets no hole there. This "
                "lens is too small for a "
                f"{block.hole_spacing_mm:.0f} mm hole pitch.")
        elif fit.breaches:
            out.append(
                f"The mounting hole {where} breaks through the block rim by "
                f"{abs(fit.wall_mm):.2f} mm — it comes out as a notch in the "
                "edge, not a hole, and cannot be bolted. Reduce the hole pitch "
                "or diameter.")
        elif fit.wall_mm < thin:
            out.append(
                f"The mounting hole {where} leaves only {fit.wall_mm:.2f} mm of "
                f"material to the rim, thinner than the {thin:.2f} mm blank. "
                "That tab is likely to break when the bolt is tightened.")
    return out


def drill_holes_op(
    centers: list[tuple[float, float]], z_top: float, z_bottom: float, tool: dict,
) -> CamOp:
    """A peck-drill op: each hole is stored as ``[(x, y, z_top), (x, y, z_bottom)]``
    — the post reads the top/bottom and emits the G83 cycle."""
    op = CamOp("Drill Holes", tool=tool)
    for x, y in centers:
        op.paths.append([(float(x), float(y), float(z_top)),
                         (float(x), float(y), float(z_bottom))])
    return op


def block_profile_op(
    lens_shape: Polygon, profile_tool: dict, allowance_mm: float,
    top_z: float, skin_z: float, params: CastleCamParams,
    holding=None,
) -> CamOp:
    """The lens-shape through-cut — frees the block last, exactly the way a frame
    outline is cut, and carries the hold-down strategy for the same reason."""
    op = contour_op("Block Profile", [lens_shape], "outside",
                    profile_tool["radius_mm"], allowance_mm, top_z, skin_z, params,
                    holding=holding)
    op.tool = profile_tool
    return op


def generate_block_program(
    lens_outline: Polygon,
    block: BaseCurveBlockParams,
    tools_cfg: dict,
    params: CastleCamParams | None = None,
) -> list[CamOp]:
    """Drill the mounting holes, then cut the lens shape free — in that order
    (drill while rigid, release last). Nothing else is cut: the block *is* the lens
    shape, holding the eyewire on the base-curve press.

    `lens_outline` is a LENS interior from the frame DXF; it is centerd on the
    blank. The drill / profile tools come from `block` (resolved from `tools_cfg`);
    the drill differs from the bulk tool, so the post emits one tool change.
    """
    params = params or CastleCamParams()
    drill_tool = resolve_tool(block.drill_tool, tools_cfg)
    profile_tool = resolve_tool(block.profile_tool, tools_cfg)

    top_z = block.blank_thickness_mm
    skin_z = block.onion_skin_mm
    z_bottom = -block.drill_breakthrough_mm          # drill through the bottom face

    centered_lens = center_on_origin(lens_outline)

    ops: list[CamOp] = [
        drill_holes_op(block.hole_centers(), top_z, z_bottom, drill_tool),
        block_profile_op(centered_lens, profile_tool,
                         block.hand_finishing_allowance_mm, top_z, skin_z, params,
                         holding=block.holding),
    ]
    return params.enabled_ops(ops)
