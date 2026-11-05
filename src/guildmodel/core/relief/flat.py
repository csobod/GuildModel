"""Flat-part relief + mesh for temples and base-curve blocks (per-component 3D).

Temples and base-curve blocks have no castle relief — they are flat acetate/acetal
blanks with shallow features. This builds the **same** heightfield structure the
castle mesher consumes (a z-field + an inside mask + the true boundary rings), so
`build_castle_mesh` turns them into watertight solids unchanged: the outline
extruded to the blank thickness, a flat anterior at z = 0, blind pockets/grooves
carved into the top, and drilled holes as real through-holes (excluded from the
mask, exactly like the frame's lens openings).

  * **Temple** — extrude the OUTLINE; carve the HINGE polys as blind pockets
    (floor = thickness − hinge_pocket_depth); carve the ENGRAVING curves (buffered
    to the engrave tool) as shallow grooves. Optionally snapped so the hinge/butt
    end registers to one end of the 170 mm blank (the injected metal core runs the
    temple's length), with the drawing's zero line kept on the blank's center
    line or the outline centered across it; the core itself is a 3D **visual
    reference**, not machined.
  * **Base-curve block** — the **lens shape itself** extruded to the blank
    thickness, with the M4 mounting holes as through-holes, centerd on the
    origin. There is no surrounding box and no scribe: the block *is* the lens
    shape, because it sits on the base-curve press holding the eyewire
    (confirmed with the user 2026-06-19, and matching what `block_ops` cuts).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

import numpy as np
from shapely import contains_xy, prepare
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from ..geometry.pocket_floor import PocketFloor, temple_pocket_floors
from ..geometry.regions import CastlePartition
from ..project.schema import BaseCurveBlockParams, TempleParams
from .castle import GRID_MARGIN_MM, PREVIEW_RES_MM, ProgressFn, _report
from .heightfield import Heightfield


@dataclass
class FlatRelief:
    """A flat-part relief, duck-compatible with what `build_castle_mesh` reads:
    `field`, `inside`, `partition.body`, `pocket_polys`, and since §8a the
    anterior map and its seat outlines (`anterior`, `anterior_pocket_polys`)."""
    field: Heightfield
    inside: np.ndarray
    partition: CastlePartition
    pocket_polys: list = dc_field(default_factory=list)
    # Material taken off the OUTER face (z = 0) by an anterior inlay seat
    # (§8a), on `field`'s grid; None when nothing cuts that face, which is
    # every temple without an INLAY curve and the fast path the mesher keeps.
    anterior: "np.ndarray | None" = None
    anterior_pocket_polys: list = dc_field(default_factory=list)
    # The debossed meshes' shadows (2026-11-02): on the hinge face, what the
    # temple program's Embossing op rides over; on the outer face, what the
    # anterior setup of a two-sided job rides over.
    sculpt_footprints: list = dc_field(default_factory=list)
    anterior_sculpt_footprints: list = dc_field(default_factory=list)

    @property
    def anterior_z(self) -> np.ndarray:
        if self.anterior is None:
            return np.zeros_like(self.field.z)
        return self.anterior

    def thickness(self) -> np.ndarray:
        """Remaining material at each cell."""
        return self.field.z - self.anterior_z

    @property
    def Xs(self) -> np.ndarray:
        cols = self.field.z.shape[1]
        xs = self.field.origin[0] + np.arange(cols) * self.field.resolution
        return np.broadcast_to(xs, self.field.z.shape)

    @property
    def Ys(self) -> np.ndarray:
        rows = self.field.z.shape[0]
        ys = self.field.origin[1] + np.arange(rows) * self.field.resolution
        return np.broadcast_to(ys[:, None], self.field.z.shape)


# ------------------------------------------------------------------ core builder

def _build_flat_relief(
    body: Polygon,
    thickness: float,
    resolution: float,
    *,
    pockets: list[tuple[Polygon, "float | PocketFloor"]] = (),
    grooves: list[tuple[Polygon, float]] = (),
    anterior_pockets: list[tuple[Polygon, "float | PocketFloor"]] = (),
    margin: float = GRID_MARGIN_MM,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """Rasterize a flat part: thickness inside `body`, with `pockets` / `grooves`
    carved down (min). `body`'s interior rings become through-holes (excluded from
    the mask). `pockets` (blind, walled) are returned for rim conforming; `grooves`
    (shallow scribes) are just z-depressions. `anterior_pockets` are cut up into
    the outer face (max into the anterior map) — the §8a inlay seats on the
    visible side of a temple.
    """
    _report(progress, "Rasterizing part", 0.10)
    minx, miny, maxx, maxy = body.bounds
    ox, oy = minx - margin, miny - margin
    rows = max(2, int(round((maxy - miny + 2 * margin) / resolution)))
    cols = max(2, int(round((maxx - minx + 2 * margin) / resolution)))
    xs = ox + np.arange(cols) * resolution
    ys = oy + np.arange(rows) * resolution
    Xs, Ys = np.meshgrid(xs, ys)
    fx, fy = Xs.ravel(), Ys.ravel()

    prepare(body)
    inside = contains_xy(body, fx, fy).reshape(rows, cols)
    z = np.where(inside, float(thickness), 0.0).astype(np.float64)

    _report(progress, "Carving features", 0.45)
    pocket_polys: list[Polygon] = []
    for poly, floor_z in pockets:
        if poly is None or poly.is_empty:
            continue
        prepare(poly)
        m = contains_xy(poly, fx, fy).reshape(rows, cols) & inside
        if isinstance(floor_z, PocketFloor):          # tilted (or flat) hinge floor
            z[m] = np.minimum(z[m], floor_z.z(Xs[m], Ys[m]))
        else:
            z[m] = np.minimum(z[m], float(floor_z))
        pocket_polys.append(poly)
    for poly, floor_z in grooves:
        if poly is None or poly.is_empty:
            continue
        prepare(poly)
        m = contains_xy(poly, fx, fy).reshape(rows, cols) & inside
        z[m] = np.minimum(z[m], float(floor_z))

    anterior = None
    anterior_polys: list[Polygon] = []
    for poly, ceiling in anterior_pockets:
        if poly is None or poly.is_empty:
            continue
        if anterior is None:
            anterior = np.zeros_like(z)
        prepare(poly)
        m = contains_xy(poly, fx, fy).reshape(rows, cols) & inside
        if isinstance(ceiling, PocketFloor):
            anterior[m] = np.maximum(anterior[m], ceiling.z(Xs[m], Ys[m]))
        else:
            anterior[m] = np.maximum(anterior[m], float(ceiling))
        anterior_polys.append(poly)
    if anterior is not None:
        anterior[~inside] = 0.0
        if not anterior.any():
            anterior = None

    z[~inside] = 0.0
    _report(progress, "Relief ready", 0.55)
    field = Heightfield(z=z, origin=(ox, oy), resolution=resolution)
    return FlatRelief(field=field, inside=inside,
                      partition=CastlePartition(body=body), pocket_polys=pocket_polys,
                      anterior=anterior, anterior_pocket_polys=anterior_polys)


# ------------------------------------------------------------------ temple

def temple_snap_offset(
    outline: Polygon, hinge_polys: list[Polygon], blank_length: float,
    *, origin_from_drawing: bool = True,
) -> tuple[float, float]:
    """Translation (dx, dy) that butts the temple's HINGE/butt end against one
    short end of the 170 mm blank and settles it across the blank's width.

    The temple's long axis is x (as GuildDraw draws/exports it). The hinge end is
    the x-extreme nearer the HINGE centroid (falling back to the +x extreme); the
    blank is centerd on the origin, so the hinge extreme lands on ±blank_length/2.

    Across the width (2026-10-14): with ``origin_from_drawing`` the drawing's
    y = 0 stays on the blank's center line, where the core runs, so the temple
    sits where the maker drew it against the core; otherwise the outline's
    bounding box is centered across the blank, as every project did before.
    """
    minx, miny, maxx, maxy = outline.bounds
    dy = 0.0 if origin_from_drawing else -(miny + maxy) / 2.0
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    half = blank_length / 2.0
    if abs(hx - maxx) <= abs(hx - minx):          # hinge on the +x end
        dx = half - maxx
    else:                                          # hinge on the -x end
        dx = -half - minx
    return dx, dy


def _hinge_on_plus_x(outline: Polygon, hinge_polys: list[Polygon]) -> bool:
    """True when the temple's HINGE end is at its +x extreme (its long axis is x)."""
    minx, _, maxx, _ = outline.bounds
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    return abs(hx - maxx) <= abs(hx - minx)


def temple_snap_transform(
    outline: Polygon, hinge_polys: list[Polygon], blank_length: float,
    *, stock_side: str = "right", snap: bool = True,
    origin_from_drawing: bool = True,
) -> tuple[bool, float, float]:
    """The rigid design→blank-frame transform the snap applies (BUILDPLAN M11):
    ``(flipped, dx, dy)`` such that a design point q maps to the blank frame as
    ``p = (−q if flipped else q) + (dx, dy)``. The GUI inverts this to draw the
    blank box / datum marker / toolpath overlay back in the design frame, so the
    2D view shows exactly where the cut lands on the blank. ``snap=False`` is the
    identity.

    The 180° spin is about the origin, so the drawing's zero line maps onto
    itself: an ``origin_from_drawing`` placement keeps the core line on the
    blank's center line whichever end the hinge is sent to."""
    if not snap:
        return False, 0.0, 0.0
    flipped = _hinge_on_plus_x(outline, hinge_polys) != (stock_side != "left")
    if flipped:
        from shapely.affinity import scale
        outline = scale(outline, xfact=-1.0, yfact=-1.0, origin=(0, 0))
        hinge_polys = [scale(h, xfact=-1.0, yfact=-1.0, origin=(0, 0))
                       for h in hinge_polys]
    dx, dy = temple_snap_offset(outline, hinge_polys, blank_length,
                                origin_from_drawing=origin_from_drawing)
    return flipped, dx, dy


def place_temple_on_blank(
    outline: Polygon, hinge_polys: list[Polygon], engraving: list,
    blank_length: float, *, stock_side: str = "right", snap: bool = True,
    origin_from_drawing: bool = True,
) -> tuple[Polygon, list[Polygon], list]:
    """Position a temple on its blank (BUILDPLAN M11). When ``snap``, butt the HINGE
    end against the chosen short end (``stock_side`` "right"=+x / "left"=-x), keeping
    the hinge pocket up. If the hinge naturally points at the wrong end, the temple is
    rotated 180° in-plane (x,y)->(-x,-y) — the same posterior flip the import applies —
    so the body runs inward from the chosen end rather than off the blank. Across the
    blank, ``origin_from_drawing`` keeps the drawing's zero line on the blank's center
    line; off centers the outline's width (see :func:`temple_snap_offset`). Returns
    the placed (outline, hinge_polys, engraving)."""
    from shapely.affinity import scale, translate as _translate
    hinge_polys = list(hinge_polys)
    engraving = [list(c) for c in engraving]
    if not snap:
        return outline, hinge_polys, engraving
    flipped, dx, dy = temple_snap_transform(
        outline, hinge_polys, blank_length, stock_side=stock_side, snap=True,
        origin_from_drawing=origin_from_drawing)
    if flipped:
        outline = scale(outline, xfact=-1.0, yfact=-1.0, origin=(0, 0))
        hinge_polys = [scale(h, xfact=-1.0, yfact=-1.0, origin=(0, 0)) for h in hinge_polys]
        engraving = [[(-x, -y) for x, y in c] for c in engraving]
    outline = _translate(outline, dx, dy)
    hinge_polys = [_translate(h, dx, dy) for h in hinge_polys]
    engraving = [[(x + dx, y + dy) for x, y in c] for c in engraving]
    return outline, hinge_polys, engraving


def place_temple_curves(
    curves: list, outline: Polygon, hinge_polys: list[Polygon], blank_length: float,
    *, stock_side: str = "right", snap: bool = True, origin_from_drawing: bool = True,
) -> list:
    """Carry any further polylines through the same rigid placement
    :func:`place_temple_on_blank` gives the temple — the drawn ENGRAVING
    graphics ride beside the text contours, and both must land where the
    outline does. ``outline`` and ``hinge_polys`` are the *unplaced* ones the
    transform is derived from."""
    return place_temple_on_blank(outline, hinge_polys, curves, blank_length,
                                 stock_side=stock_side, snap=snap,
                                 origin_from_drawing=origin_from_drawing)[2]


def place_temple_polygons(
    polys: list[Polygon], outline: Polygon, hinge_polys: list[Polygon],
    blank_length: float, *, stock_side: str = "right", snap: bool = True,
    origin_from_drawing: bool = True,
) -> list[Polygon]:
    """Carry closed regions — the INLAY seats (§8a) — through the same rigid
    placement :func:`place_temple_on_blank` gives the temple, order kept, so a
    seat and the feature it is paired with stay index-aligned. ``outline`` and
    ``hinge_polys`` are the *unplaced* ones the transform is derived from."""
    from shapely.affinity import scale, translate as _translate
    if not snap:
        return list(polys)
    flipped, dx, dy = temple_snap_transform(
        outline, hinge_polys, blank_length, stock_side=stock_side, snap=True,
        origin_from_drawing=origin_from_drawing)
    out = []
    for p in polys:
        if flipped:
            p = scale(p, xfact=-1.0, yfact=-1.0, origin=(0, 0))
        out.append(_translate(p, dx, dy))
    return out


def temple_core_guide(
    outline: Polygon, hinge_polys: list[Polygon], temple: TempleParams,
) -> Polygon:
    """The injected-core visual reference (BUILDPLAN M7): a `core_guide_width` ×
    `core_guide_length` bar laid along the temple's long axis from the hinge end,
    down the blank's center line. A 3D reference only — never machined.

    ``outline`` is the temple as PLACED on its blank, which is centered on the
    origin, so the center line is y = 0. Until 2026-10-14 the bar was centered on
    the outline's own bounding box instead; the two agreed only because the
    placement centered that box on the blank. The bar marks the wire, which is
    in the blank, not in the drawing: with the drawing placed by its origin the
    bar now shows where the temple sits against the core, which is the point of
    drawing it on the core line in the first place."""
    minx, _miny, maxx, _maxy = outline.bounds
    cy = 0.0
    w = temple.core_guide_width_mm
    length = min(temple.core_guide_length_mm, maxx - minx)
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    if abs(hx - maxx) <= abs(hx - minx):          # core runs in from the +x (hinge) end
        x0, x1 = maxx - length, maxx
    else:
        x0, x1 = minx, minx + length
    return box(x0, cy - w / 2.0, x1, cy + w / 2.0)


# ------------------------------------------------------------------ the meshes

@dataclass
class EmbossedFlat:
    """A flat part with the maker's meshes baked in (`emboss_flat_relief`)."""
    relief: FlatRelief           # the fields with the debosses cut in
    mesh: object                 # the baked solid (trimesh), for the viewer and the export
    host: object = None          # the solid without the meshes; a snap or a drag reads it
    notes: list = dc_field(default_factory=list)


def _face_of(feature) -> str:
    """Which face of the part a mesh sits on: its mount's face, or, for a
    pick, the face its normal names."""
    face = feature.mount.face
    if face in ("posterior", "anterior", "rim"):
        return face
    n = feature.mount.normal or [0.0, 0.0, 1.0]
    if len(n) >= 3 and n[2] < -0.5:
        return "anterior"
    if len(n) >= 3 and abs(n[2]) <= 0.5:
        return "rim"
    return "posterior"


def _shadow(placed):
    """A placed mesh's footprint on the grid plane, or None."""
    try:
        rings = placed.manifold.project().to_polygons()
    except Exception:                                    # noqa: BLE001
        return None
    polys = [Polygon(np.asarray(r)) for r in rings if len(r) >= 3]
    polys = [q.buffer(0) for q in polys if q.is_valid or q.buffer(0).area > 0]
    if not polys:
        return None
    shadow = unary_union(polys)
    if shadow.geom_type != "Polygon":
        shadow = max(shadow.geoms, key=lambda g: g.area)
    return shadow if shadow.area > 0 else None


def emboss_flat_relief(relief: FlatRelief, features, sources: dict, *,
                       progress: Optional[ProgressFn] = None) -> EmbossedFlat:
    """The flat part with the maker's meshes baked in (2026-11-02; the front
    has had them since M22).

    The part is built as a solid, the embosses added and the debosses taken
    away (`model.sculpt.bake`), and the solid is what the viewer shows and
    the export writes. The CAM reads the relief: under each mesh's shadow the
    hinge face takes the baked solid's upper envelope and the outer face its
    lower one, so a deboss on either face is in the map the program and the
    simulation cut from. An emboss stands above the blank's face: it is in
    the solid, and clamped out of the map with a note, since no program can
    put material on. `features` are the part's `SculptFeature`s, `sources`
    their STL bytes (or loaded sources) by sha256. A part with no mesh to
    bake comes back with its own relief and its plain solid.
    """
    import dataclasses

    from .castle import build_castle_mesh

    host = build_castle_mesh(relief, progress=progress)
    enabled = [f for f in (features or []) if getattr(f, "enabled", True)]
    if not enabled or not sources:
        return EmbossedFlat(relief, host, None, [])
    from ..model.kernel import ManifoldError, drop_degenerate, to_trimesh
    from ..model.sculpt import bake, manifold_from_arrays, placed_sculpts
    from ..zmap import triangle_envelopes

    _report(progress, "Baking the meshes", 0.80)
    solid = manifold_from_arrays(host.vertices, host.faces)
    per_face: dict = {"posterior": [], "anterior": [], "rim": []}
    # one call, so a source several meshes share is repaired once, not once
    # per mesh on every rebuild (the 2.1 bug hunt)
    placed_all = placed_sculpts(enabled, sources)
    by_id = {f.id: f for f in enabled}
    for p in placed_all:
        f = by_id.get(p.feature_id)
        if f is not None:
            per_face[_face_of(f)].append((f, p))
    if not placed_all:
        return EmbossedFlat(relief, host, None, [])
    try:
        baked = drop_degenerate(bake(solid, placed_all))
    except ManifoldError as exc:
        return EmbossedFlat(relief, host, None, [f"the meshes could not be baked: {exc}"])
    mesh = to_trimesh(baked)

    notes: list[str] = []
    hf = relief.field
    rows, cols = hf.z.shape
    res = float(hf.resolution)
    thickness = float(np.nanmax(hf.z)) if hf.z.size else 0.0
    upper, lower = triangle_envelopes(mesh.vertices, mesh.faces, hf.origin, rows, cols,
                                      res, background=np.nan, progress=None)
    xs = hf.origin[0] + np.arange(cols) * res
    ys = hf.origin[1] + np.arange(rows) * res
    Xs, Ys = np.meshgrid(xs, ys)
    fx, fy = Xs.ravel(), Ys.ravel()

    def mask_of(shadows):
        m = np.zeros((rows, cols), dtype=bool)
        for sh in shadows:
            grown = sh.buffer(res, join_style="round")
            prepare(grown)
            m |= contains_xy(grown, fx, fy).reshape(rows, cols)
        return m & relief.inside

    z = hf.z.copy()
    footprints, anterior_footprints = [], []
    post = [(f, _shadow(p)) for f, p in per_face["posterior"]]
    post = [(f, sh) for f, sh in post if sh is not None]
    if post:
        m = mask_of([sh for _, sh in post]) & np.isfinite(upper)
        z[m] = upper[m]
        if (z[m] > thickness + 1e-6).any():
            z = np.minimum(z, thickness)
        footprints = [sh for f, sh in post if f.op == "deboss"]
        if any(f.op == "emboss" for f, _ in post):
            notes.append("An emboss on the hinge face stands above the blank's face: it is "
                         "modeled and not cut. Deboss it, or cut it from the other face.")
    anterior = relief.anterior.copy() if relief.anterior is not None else np.zeros_like(z)
    ant = [(f, _shadow(p)) for f, p in per_face["anterior"]]
    ant = [(f, sh) for f, sh in ant if sh is not None]
    if ant:
        m = mask_of([sh for _, sh in ant]) & np.isfinite(lower)
        anterior[m] = np.maximum(anterior[m], np.maximum(lower[m], 0.0))
        anterior_footprints = [sh for f, sh in ant if f.op == "deboss"]
        if any(f.op == "emboss" for f, _ in ant):
            notes.append("An emboss on the outer face stands below the blank's face: it is "
                         "modeled and not cut. Deboss it instead.")
    if per_face["rim"]:
        notes.append("A mesh on the rim is modeled and not cut: a three-axis program "
                     "reaches the two faces alone.")
    anterior[~relief.inside] = 0.0
    z[~relief.inside] = 0.0
    out = dataclasses.replace(
        relief, field=Heightfield(z=z, origin=hf.origin, resolution=res),
        anterior=anterior if anterior.any() else None,
        sculpt_footprints=footprints, anterior_sculpt_footprints=anterior_footprints)
    _report(progress, "Meshes baked", 0.90)
    return EmbossedFlat(out, mesh, host, notes)


def build_temple_relief(
    outline: Polygon,
    temple: TempleParams,
    hinge_polys: list[Polygon] = (),
    engraving_curves: list = (),
    *,
    graphic_curves: list = (),
    inlay_polys: list = (),
    resolution: float = PREVIEW_RES_MM,
    engrave_tool_radius: float = 0.25,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """A temple solid: extrude the outline to the blank thickness, carve the HINGE
    pockets (1 mm default), the ENGRAVING grooves (0.3 mm default) and the inlay
    seats (§8a; ``inlay_polys`` index-aligned with ``temple.inlays``, placed on
    the blank like the outline). The geometry is taken as-drawn; the GUI applies
    the blank-end snap before calling this.

    Two kinds of engraving, cut with the same bit to the same depth:

    * ``engraving_curves`` — text: glyph outlines (or strokes) that
      ``temple.engrave_centerline`` reduces to one line down each stroke. A
      DXF, which cannot tell text from drawing, hands everything in here.
    * ``graphic_curves`` — what the maker drew on the ENGRAVING layer. An open
      curve is a stroke, grooved as drawn. A closed curve is a filled shape:
      the closed curves combine even-odd into regions, so a closed curve
      inside another is an island (an "O" is two circles, a disc is one), and
      each region is carved flat to the engraving depth — never skeletonized
      (2026-10-05: the medial axis of a six-armed logo is a forked stick
      figure, not the logo). The program fills the same regions
      (`cam.temple_ops.graphic_engraving_curves`).
    """
    from ..cam.engrave_centerline import even_odd_regions, is_closed_curve

    thickness = temple.blank_thickness_mm
    pockets = [(p, floor) for p, floor
               in temple_pocket_floors(hinge_polys, temple, outline)
               if p.is_valid]

    groove_floor = thickness - temple.engrave_depth_mm
    grooves: list[tuple[Polygon, float]] = []
    r = max(engrave_tool_radius, 0.15)
    if engraving_curves and temple.engrave_centerline:   # match the program (M11 #7)
        from ..cam.engrave_centerline import engraving_centerlines
        engraving_curves = engraving_centerlines(engraving_curves)
    strokes = [c for c in graphic_curves if not is_closed_curve(c)]
    shapes = [c for c in graphic_curves if is_closed_curve(c)]
    for curve in list(engraving_curves) + strokes:
        if len(curve) >= 2:
            g = LineString([(float(x), float(y)) for x, y in curve]).buffer(r)
            if not g.is_empty:
                grooves.append((g, groove_floor))
    for region in even_odd_regions(shapes):
        grooves.append((region, groove_floor))

    # Inlay seats (§8a): the one cut list, from the params. A seat on the
    # inner (hinge) face is a pocket like the hinge's; one on the outer face
    # goes into the anterior map, modeled until M24 posts it.
    from ..geometry.inlays import inlay_cuts
    seats = inlay_cuts(temple.inlays, list(inlay_polys),
                       temple_pocket_floors(hinge_polys, temple, outline),
                       posterior_reference=thickness)
    pockets += [(seat.region, seat.plane) for seat in seats if seat.posterior]
    anterior_pockets = [(seat.region, seat.plane) for seat in seats
                        if not seat.posterior]

    return _build_flat_relief(outline, thickness, resolution,
                              pockets=pockets, grooves=grooves,
                              anterior_pockets=anterior_pockets, progress=progress)


# ------------------------------------------------------------------ base-curve block

def build_block_relief(
    lens_outline: Polygon,
    block: BaseCurveBlockParams,
    *,
    resolution: float = PREVIEW_RES_MM,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """A base-curve block solid: the **lens shape** extruded to the blank thickness,
    centerd on the origin, with the M4 mounting holes as real through-holes. The
    block *is* the lens shape (it holds the eyewire on the base-curve press) — there
    is no scribe and no surrounding box, matching the cutting program."""
    from ..cam.block_ops import center_on_origin

    centered = center_on_origin(lens_outline)
    r_hole = block.hole_diameter_mm / 2.0
    holes = [Point(hx, hy).buffer(r_hole) for hx, hy in block.hole_centers()]
    body = centered.difference(unary_union(holes)) if holes else centered

    return _build_flat_relief(body, block.blank_thickness_mm, resolution,
                              progress=progress)
