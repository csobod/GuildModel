"""Press dies for the formed front (BUILDPLAN M23 §8).

The dies are made from the forming map and the frame's silhouette, never
from the featured model: hinge pockets, inlay seats, chamfers and sculpts
play no part in a mold's surface, and the less a die carries the better it
presses (the maker, 2026-10-15). Two closed solids per job, plus the bridge
tooling in post-cut mode:

* **Posterior die** — the master: a convex dome under a flange plate, the
  forming map applied to the eyewire terrace's height (the surface most of
  the back rests on). Any zone that stands taller than that terrace — the
  nosepads first — gets a **cutaway**, a pocket the zone's shape and its
  extra height deep, so the die holds the frame on its rims and never
  presses the pads. A loose form, with pressure where it counts.
* **Anterior die** — a cup in a block, the plain negative of the front at
  the base curve and face form, set back by the silicone mat the maker
  rolls over the dome and by the clearance. The mat gives the compliance;
  the die gives the curve.
* **Bridge punch and V anvil** (post-cut mode): the convex cylinder that
  sets the bridge, pressed from the posterior against a plate with the V
  notch the creases follow, with the punch's shoulders as the depth stop.

The two faces are the same map at two heights, so the closed gap between
them is ``t + mat + c`` by construction, and the dies close flange to
flange: no kiss blocks to cut. Post-cut dies trim the faces to the
silhouette and relieve the inside of each eyewire so only a rim band is
supported; pre-cut dies cover the blank and carry no eyewire geometry at
all, and the formed blank they make is the stock M25 machines.

Everything here is numpy and Manifold; the window writes the STLs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import Error, Manifold, OpType
from shapely.geometry import Polygon, box

from ..model.kernel import ManifoldError, drop_degenerate, extrude, to_trimesh
from .thermoform import ThermoformMap, bridge_geometry

__all__ = ["DieSet", "build_dies", "die_map", "forming_readouts", "DIE_GRID_MM"]

#: The grid the die faces are sampled on, mm: the chord sag on a 100 mm
#: sphere is a micron and a quarter.
DIE_GRID_MM = 0.75
#: How far the flange plate clears the dome's highest point, mm.
RIM_CLEAR_MM = 2.0
#: A zone stands proud of the terrace the die follows when it is taller by
#: this much, mm; it then gets a cutaway.
PROUD_MM = 0.2
#: How far a cutaway's pocket runs past its zone, mm, beyond the footing
#: blend's own reach onto the terrace: the raise toward a taller zone
#: climbs above the terrace over that reach, and the die must clear it too.
CUTAWAY_GROW_MM = 2.0


@dataclass
class DieSet:
    """The dies and what was decided making them."""
    posterior: Manifold
    anterior: Manifold
    punch: Manifold | None = None
    anvil: Manifold | None = None
    label: str = ""
    report: dict = field(default_factory=dict)

    def parts(self) -> dict:
        """The STL names and their solids, in the order they are written."""
        out = {"die_posterior": self.posterior, "die_anterior": self.anterior}
        if self.punch is not None:
            out["bridge_punch"] = self.punch
        if self.anvil is not None:
            out["bridge_anvil"] = self.anvil
        return out


# ------------------------------------------------------------------ the map

def die_map(forming, partition, lens_od=None, lens_os=None) -> ThermoformMap:
    """The forming map the dies are cut to: the project's, with the radius
    times the over-bend, the face form kept or dropped as the die parameters
    say, and the bridge projection only when the dies carry it."""
    d = forming.dies
    bridge = bridge_geometry(partition, lens_od, lens_os)
    radius = float(forming.base_radius_mm) * float(d.over_bend) if forming.base_radius_mm > 0 else 0.0
    gap = float(forming.crease_gap_mm) or float(bridge.top_width)
    return ThermoformMap(
        radius_mm=radius,
        face_form_deg=forming.face_form_deg if d.face_form_in_die else 180.0,
        projection_mm=float(forming.bridge_projection_mm) if d.bridge_in_die else 0.0,
        crease_gap_mm=gap, crease_angle_deg=float(forming.crease_angle_deg),
        bridge_offset_mm=float(forming.bridge_offset_mm),
        die_radius_mm=float(forming.die_radius_mm),
        crease_blend_mm=float(forming.crease_blend_mm), bridge=bridge)


# ------------------------------------------------------------------ meshes

def _formed_polygon(fmap: ThermoformMap, poly: Polygon, z_flat: float) -> Polygon:
    """`poly`'s rings through the map at height `z_flat`, as the polygon
    their formed x, y make: the footprint a cap is clipped to."""
    def ring(coords):
        pts = np.array([(x, y, z_flat) for x, y in coords], dtype=np.float64)
        return [tuple(p) for p in fmap(pts)[:, :2]]
    out = Polygon(ring(poly.exterior.coords), [ring(r.coords) for r in poly.interiors])
    return out if out.is_valid else out.buffer(0)


def _grid_cap(fmap: ThermoformMap, z_flat: float, bounds, z_plane: float,
              grid_mm: float) -> Manifold:
    """The solid between the mapped surface at `z_flat` and the plane
    `z_plane`, over the flat rectangle `bounds`: the surface as a sheet of
    quads, its mirror on the plane, vertical walls along the rim. Closed as
    long as the formed x, y of the grid do not fold over, which a forming
    map does not do."""
    x0, y0, x1, y1 = bounds
    nx = max(2, int(math.ceil((x1 - x0) / grid_mm)) + 1)
    ny = max(2, int(math.ceil((y1 - y0) / grid_mm)) + 1)
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    X, Y = np.meshgrid(xs, ys)
    flat = np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, float(z_flat))])
    top = fmap(flat)
    n = len(top)
    bottom = top.copy()
    bottom[:, 2] = float(z_plane)
    verts = np.vstack([top, bottom])
    idx = np.arange(n).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    up = z_plane > float(np.mean(top[:, 2]))      # the body lies above the surface
    # the surface sheet faces away from the body; the plane sheet the other way
    sheet = np.vstack([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    if up:
        sheet = sheet[:, ::-1]
    plane = np.vstack([np.column_stack([a, c, b]), np.column_stack([a, d, c])]) + n
    if up:
        plane = plane[:, ::-1]
    # the rim, counter-clockwise around the grid
    rim = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, ::-1][:-1], idx[::-1, 0][:-1]])
    r0, r1 = rim, np.roll(rim, -1)
    walls = np.vstack([np.column_stack([r0, r1, r1 + n]), np.column_stack([r0, r1 + n, r0 + n])])
    if not up:
        walls = walls[:, ::-1]          # as built they face out when the body is above
    faces = np.vstack([sheet, plane, walls])
    from ..model.sculpt import manifold_from_arrays
    man = manifold_from_arrays(verts, faces)
    if man.status() != Error.NoError or man.volume() <= 0:
        # the winding guess was the other way round
        man = manifold_from_arrays(verts, faces[:, ::-1])
    if man.status() != Error.NoError:
        raise ManifoldError(f"die cap: {man.status()}")
    return man


def _cap(fmap: ThermoformMap, z_flat: float, footprint: Polygon, z_plane: float,
         grid_mm: float = DIE_GRID_MM, reach: float = 1.0) -> Manifold:
    """`_grid_cap` clipped to `footprint` (a flat polygon), whose walls are
    then the footprint's own, vertical in formed space."""
    x0, y0, x1, y1 = footprint.bounds
    cap = _grid_cap(fmap, z_flat, (x0 - reach, y0 - reach, x1 + reach, y1 + reach),
                    z_plane, grid_mm)
    lo, hi = np.asarray(cap.bounding_box()).reshape(2, 3)[:, 2]
    prism = extrude(_formed_polygon(fmap, footprint, z_flat), hi - lo + 2.0, base=lo - 1.0)
    out = Manifold.batch_boolean([cap, prism], OpType.Intersect)
    if out.status() != Error.NoError or out.is_empty():
        raise ManifoldError("die cap: the footprint left nothing")
    return out


def _cylinder(x: float, y: float, dia: float, z0: float, z1: float) -> Manifold:
    return Manifold.cylinder(float(z1 - z0), dia / 2.0, dia / 2.0, 48).translate([x, y, z0])


def _drafted_plate(outline: Polygon, z0: float, thickness: float, draft_deg: float) -> Manifold:
    """The flange plate, its walls drafted inward toward `z0 + thickness`."""
    from ..model.kernel import cross_section
    cs = cross_section(outline)
    cx, cy = outline.centroid.x, outline.centroid.y
    x0, y0, x1, y1 = outline.bounds
    shrink = thickness * math.tan(math.radians(max(0.0, draft_deg)))
    sx = max(0.1, 1.0 - 2.0 * shrink / max(x1 - x0, 1e-6))
    sy = max(0.1, 1.0 - 2.0 * shrink / max(y1 - y0, 1e-6))
    man = Manifold.extrude(cs.translate([-cx, -cy]), float(thickness), 0, 0.0, (sx, sy))
    return man.translate([cx, cy, float(z0)])


# ------------------------------------------------------------------ the dies

def _terrace_heights(partition, castle) -> dict:
    from ..geometry.heights import zone_heights
    return zone_heights(partition, castle, None)


def _cutaway_grow(partition, castle, zone_name: str, heights: dict) -> float:
    """How far past `zone_name` its cutaway runs: the footing blend's reach
    onto the lower terrace at every seam the zone shares, plus the margin.
    The raise toward a taller zone stands above the terrace over that
    reach, so a pocket that stopped at the zone's edge would press on it."""
    from ..relief.castle import _footing_reach
    reach = 0.0
    for edge in getattr(partition, "edges", []):
        names = list(getattr(edge, "zone_names", []) or [])
        if zone_name not in names or len(names) != 2 or not getattr(edge, "canonical", None):
            continue
        other = names[0] if names[1] == zone_name else names[1]
        if other not in heights or zone_name not in heights:
            continue
        dh = heights[zone_name] - heights[other]
        if dh <= 1e-9:
            continue
        try:
            fillet = castle.footing.for_edge(edge.canonical)
            _, reach_lo = _footing_reach(dh, fillet.exterior_mm, fillet.interior_mm, fillet.first)
        except Exception:                                    # noqa: BLE001
            continue
        reach = max(reach, float(reach_lo))
    return reach + CUTAWAY_GROW_MM


def _face_footprint(partition, castle, d) -> Polygon:
    """Post-cut: the silhouette (apertures filled) grown by the trim. Pre-cut:
    the blank plus the margin."""
    if d.mode == "pre_cut":
        s = castle.stock
        return box(-s.blank_length_mm / 2 - d.margin_mm, -s.blank_width_mm / 2 - d.margin_mm,
                   s.blank_length_mm / 2 + d.margin_mm, s.blank_width_mm / 2 + d.margin_mm)
    body = Polygon(partition.body.exterior.coords)
    return body.buffer(float(d.trim_mm), join_style="round")


def _label(forming, d, t: float, gap: float, fmap: ThermoformMap) -> str:
    from datetime import date
    r = fmap.R if np.isfinite(fmap.R) else 0.0
    return (f"{forming.press_preset or 'custom'} · base {forming.base_curve:g} D · "
            f"R {r:.1f} mm · face form {fmap.face_form_deg:g}° · t {t:.2f} · "
            f"gap {gap:.2f} · over-bend {d.over_bend:g} · {d.mode.replace('_', '-')} · "
            f"{date.today().isoformat()}")


def build_dies(partition, castle, forming, lens_od=None, lens_os=None,
               grid_mm: float = DIE_GRID_MM) -> DieSet:
    """The die set for a front: `partition` and the lens polygons from the
    drawing, `castle` for the terrace heights and the blank, `forming` for
    the map and its `dies` parameters."""
    d = forming.dies
    fmap = die_map(forming, partition, lens_od, lens_os)
    heights = _terrace_heights(partition, castle)
    eyewires = [h for name, h in heights.items() if name.startswith("eyewire")]
    t = float(max(eyewires) if eyewires else max(heights.values()))
    mat, c = float(d.mat_thickness_mm), float(d.clearance_mm)
    gap = t + mat + c
    F = _face_footprint(partition, castle, d)
    fx0, fy0, fx1, fy1 = F.bounds
    G = box(fx0 - d.flange_mm, fy0 - d.flange_mm, fx1 + d.flange_mm, fy1 + d.flange_mm)

    # where the two faces lie in formed space, and the plane the dies close on
    probe = _grid_cap(fmap, t, (fx0, fy0, fx1, fy1), 0.0, max(grid_mm, 2.0))
    z_post_max = float(np.asarray(probe.bounding_box()).reshape(2, 3)[1, 2])
    z_f = z_post_max + RIM_CLEAR_MM
    probe_a = _grid_cap(fmap, -(mat + c), (fx0, fy0, fx1, fy1), 0.0, max(grid_mm, 2.0))
    z_ant_min = float(np.asarray(probe_a.bounding_box()).reshape(2, 3)[0, 2])
    z_ant_min = min(z_ant_min, 0.0)
    z_lo = z_ant_min - 10.0            # a plane under everything, for the pockets in the dome

    # --- the posterior die: the dome under its flange plate
    dome = _cap(fmap, t, F, z_f, grid_mm)
    plate = _drafted_plate(G, z_f, float(d.flange_thickness_mm), float(d.draft_deg))
    posterior = Manifold.batch_boolean([dome, plate], OpType.Add)
    cuts = []
    cutaways = []
    if d.cutaways:
        for zone in partition.zones:
            h = float(heights.get(zone.name, t))
            if h > t + PROUD_MM and not zone.polygon.is_empty:
                depth = (h - t) + float(d.cutaway_clearance_mm)
                grow = _cutaway_grow(partition, castle, zone.name, heights)
                poly = zone.polygon.buffer(grow, join_style="round")
                # everything under the pocket's floor, within the zone: a
                # pocket `depth` deep in the dome's underside
                cuts.append(_cap(fmap, t + depth, poly, z_lo, grid_mm))
                cutaways.append((zone.name, round(depth, 3), round(grow, 2)))
    relief = []
    if d.mode == "post_cut":
        for lens in (lens_od, lens_os):
            if lens is None:
                continue
            inner = lens.buffer(-float(d.relief_rim_mm), join_style="round")
            if inner.is_empty or inner.area <= 0:
                continue
            inner = inner if inner.geom_type == "Polygon" else max(inner.geoms, key=lambda g: g.area)
            relief.append(inner)
            cuts.append(_cap(fmap, t + float(d.relief_depth_mm), inner, z_lo, grid_mm))
    if cuts:
        posterior = Manifold.batch_boolean([posterior] + cuts, OpType.Subtract)

    # --- the anterior die: the cup in its block, closing on the same plane
    depth_block = (z_f - z_ant_min) + float(d.flange_thickness_mm)
    block = _drafted_plate(G, z_f - depth_block, depth_block, 0.0)
    cup = _cap(fmap, -(mat + c), F, z_f + 1.0, grid_mm)
    a_cuts = [cup]
    for inner in relief:
        a_cuts.append(_cap(fmap, -(mat + c + float(d.relief_depth_mm)), inner, z_f + 1.0, grid_mm))
    anterior = Manifold.batch_boolean([block] + a_cuts, OpType.Subtract)

    # --- dowels, vents, the mounting pattern
    gx0, gy0, gx1, gy1 = G.bounds
    inset = float(d.flange_mm) / 2.0
    dowels = [(gx0 + inset, gy0 + inset), (gx1 - inset, gy1 - inset)]
    z_lo, z_hi = z_f - depth_block - 1.0, z_f + float(d.flange_thickness_mm) + 1.0
    post_holes = [_cylinder(x, y, float(d.dowel_mm) - 0.05, z_lo, z_hi) for x, y in dowels]
    ant_holes = [_cylinder(x, y, float(d.dowel_mm) + float(d.dowel_fit_mm), z_lo, z_hi)
                 for x, y in dowels]
    vents = []
    for lens in (lens_od, lens_os):
        if lens is not None:
            cx, cy = lens.centroid.x, lens.centroid.y
            vx, vy = fmap(np.array([[cx, cy, 0.0]]))[0, :2]
            vents.append(_cylinder(vx, vy, float(d.vent_mm), z_lo, z_hi))
    vents.append(_cylinder(0.0, 0.0, float(d.vent_mm), z_lo, z_hi))
    if d.mounting_pattern:
        pitch, n = 10.0, 3
        for k in range(n):
            x = (k - (n - 1) / 2.0) * pitch
            y = gy0 + inset
            post_holes.append(_cylinder(x, y, 4.5, z_lo, z_hi))
            ant_holes.append(_cylinder(x, y, 4.5, z_lo, z_hi))
    posterior = Manifold.batch_boolean([posterior] + post_holes, OpType.Subtract)
    anterior = Manifold.batch_boolean([anterior] + ant_holes + vents, OpType.Subtract)
    posterior, anterior = drop_degenerate(posterior), drop_degenerate(anterior)
    for name, man in (("posterior", posterior), ("anterior", anterior)):
        if man.status() != Error.NoError or man.volume() <= 0:
            raise ManifoldError(f"the {name} die did not close: {man.status()}")

    # --- the bridge punch and the V anvil, post-cut only
    punch = anvil = None
    if d.mode == "post_cut" and forming.bridge_projection_mm > 0.0:
        punch, anvil = _bridge_tooling(fmap, forming, d, t)

    label = _label(forming, d, t, gap, fmap)
    report = {
        "mode": d.mode, "terrace_mm": t, "mat_mm": mat, "clearance_mm": c,
        "closed_gap_mm": gap, "radius_mm": fmap.R if np.isfinite(fmap.R) else 0.0,
        "face_form_deg": fmap.face_form_deg, "flange_plane_z": z_f,
        "cutaways": cutaways, "eyewire_relief": len(relief),
        "outer_mm": (round(gx1 - gx0, 1), round(gy1 - gy0, 1)),
        "dowels": dowels, "label": label,
    }
    report.update(forming_readouts(fmap, partition, lens_od, lens_os))
    return DieSet(posterior, anterior, punch, anvil, label, report)


def _bridge_tooling(fmap: ThermoformMap, forming, d, t: float):
    """The punch, a cylinder of the die radius along the bridge with its
    shoulders as the depth stop, and the anvil, a plate with the V notch the
    creases follow. Flat-space tooling: the bridge is set at the bench after
    the front is curved, on the maker's own fixture."""
    R = float(d.punch_radius_mm) or fmap.die_radius_mm()
    if not np.isfinite(R) or R <= 0:
        R = 10.0
    R = min(R, 60.0)
    p = float(forming.bridge_projection_mm)
    b = fmap.bridge
    gap = fmap.gap
    v_angle = float(d.v_angle_deg) or fmap.crease_angle_deg
    half_tan = math.tan(math.radians(0.5 * v_angle))
    reach = 0.5 * gap / max(half_tan, 1e-6) if half_tan > 0 else 40.0
    length = min(reach, 40.0) + 10.0
    top_y = float(b.top_y)
    nd = float(b.nose_dir)
    ox = fmap.offset
    # the notch: the gap at the top edge, parallel above it, converging below
    y_far = top_y - nd * 10.0
    y_apex = top_y + nd * min(reach, 40.0)
    h_apex = max(0.5 * gap - min(reach, 40.0) * half_tan, 0.0)
    notch = Polygon([(ox - 0.5 * gap, y_far), (ox + 0.5 * gap, y_far),
                     (ox + 0.5 * gap, top_y), (ox + h_apex, y_apex),
                     (ox - h_apex, y_apex), (ox - 0.5 * gap, top_y)])
    plate_t = 10.0
    plate = box(ox - 0.5 * gap - 25.0, min(y_far, y_apex) - 10.0,
                ox + 0.5 * gap + 25.0, max(y_far, y_apex) + 10.0)
    anvil = Manifold.batch_boolean(
        [extrude(plate, plate_t, base=-plate_t), extrude(notch, plate_t + 2.0, base=-plate_t - 1.0)],
        OpType.Subtract)
    # the punch: the cylinder's axis along y, its lowest line at z = -p when
    # the shoulders rest on the sheet's back at z = t
    width = min(2.0 * R, gap - 0.2) if gap > 0.4 else 2.0 * R
    y0, y1 = min(y_far, y_apex) + 2.0, max(y_far, y_apex) - 2.0
    cyl = (Manifold.cylinder(y1 - y0, R, R, 96).rotate([-90.0, 0.0, 0.0])
           .translate([ox, y0, R - p]))
    clip = extrude(box(ox - width / 2, y0 - 1.0, ox + width / 2, y1 + 1.0), 2 * R + p + 2.0,
                   base=-p - 1.0)
    nose = Manifold.batch_boolean([cyl, clip], OpType.Intersect)
    body = extrude(box(ox - 0.5 * gap - 15.0, y0, ox + 0.5 * gap + 15.0, y1), 20.0, base=t)
    punch = drop_degenerate(Manifold.batch_boolean([body, nose], OpType.Add))
    anvil = drop_degenerate(anvil)
    return punch, anvil


# ------------------------------------------------------------------ readouts

def forming_readouts(fmap: ThermoformMap, partition, lens_od=None, lens_os=None) -> dict:
    """Flat against formed, mm: the DBL, each lens's width (A), the frame PD
    and the overall width. The bump consumes length at the bridge and the
    curve shortens every chord; the drawing stays GuildDraw's."""
    out: dict = {}

    def chord(p, q):
        return float(np.linalg.norm(fmap(np.array([p]))[0] - fmap(np.array([q]))[0]))

    if lens_od is not None and lens_os is not None:
        xs = sorted([lens_od, lens_os], key=lambda l: l.centroid.x)
        left, right = xs
        inner_l = max(left.exterior.coords, key=lambda c: c[0])
        inner_r = min(right.exterior.coords, key=lambda c: c[0])
        flat_dbl = float(inner_r[0] - inner_l[0])
        out["dbl_flat_mm"] = round(flat_dbl, 2)
        out["dbl_formed_mm"] = round(chord((*inner_l, 0.0), (*inner_r, 0.0)), 2)
        cl, cr = left.centroid, right.centroid
        out["pd_flat_mm"] = round(float(cr.x - cl.x), 2)
        out["pd_formed_mm"] = round(chord((cl.x, cl.y, 0.0), (cr.x, cr.y, 0.0)), 2)
        a_flat, a_formed = [], []
        for lens in (left, right):
            x0, _, x1, _ = lens.bounds
            y = lens.centroid.y
            a_flat.append(x1 - x0)
            a_formed.append(chord((x0, y, 0.0), (x1, y, 0.0)))
        out["a_flat_mm"] = round(float(np.mean(a_flat)), 2)
        out["a_formed_mm"] = round(float(np.mean(a_formed)), 2)
    x0, y0, x1, y1 = partition.body.bounds
    ym = 0.5 * (y0 + y1)
    out["width_flat_mm"] = round(float(x1 - x0), 2)
    pts = fmap(np.array([(x0, ym, 0.0), (x1, ym, 0.0)]))
    out["width_formed_mm"] = round(float(pts[1, 0] - pts[0, 0]), 2)
    return out
