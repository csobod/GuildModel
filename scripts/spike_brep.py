#!/usr/bin/env python3
"""Stage 1 kernel spike — BREP-REWRITE-REPORT.md §6.

Not a production code path. This exists to answer the two go/no-go questions in
§5 of the report, against the **Demo Project frame**, not a synthetic shape:

  §5.1  Can BRepOffsetAPI_MakePipeShell build a tapered, partial-span chamfer
        along an organic outline spline? (The M17 brow chamfer. The report calls
        this "the single item most likely to force a fallback".)

  §5.2  Does BRepFilletAPI_MakeFillet survive the castle's footing edges --
        spline SCULPT cuts meeting an organic outline at shallow angles, with
        high curvature at the nosepad and endpiece transitions?

Kill criteria (report §6, Stage 1): if the sweep cannot build a tapered
partial-span chamfer on the demo outline, or if fillets fail on more than a
small minority of footing edges with no workable fallback, stop and take the
Manifold mesh-boolean route instead.

Usage:
    DISPLAY= .venv/bin/python scripts/spike_brep.py
"""
from __future__ import annotations

import math
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEMO = ROOT / "tests" / "fixtures" / "demo"

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse        # noqa: E402
from OCP.BRepBuilderAPI import (                                     # noqa: E402
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_TransitionMode,
)
from OCP.BRepCheck import BRepCheck_Analyzer                         # noqa: E402
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet               # noqa: E402
from OCP.BRepGProp import BRepGProp                                  # noqa: E402
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell            # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism                    # noqa: E402
from OCP.GeomAPI import GeomAPI_PointsToBSpline                      # noqa: E402
from OCP.GProp import GProp_GProps                                   # noqa: E402
from OCP.TColgp import TColgp_Array1OfPnt                            # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum                              # noqa: E402
from OCP.TopExp import TopExp_Explorer                               # noqa: E402
from OCP.TopoDS import TopoDS, TopoDS_Shape                          # noqa: E402
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec                            # noqa: E402


# ------------------------------------------------------------------ reporting

TIMINGS: list[tuple[str, float, str]] = []


@contextmanager
def step(label: str):
    """Time a stage and record its outcome, without letting a failure abort the
    rest of the spike -- a spike that stops at the first exception answers
    nothing."""
    t0 = time.perf_counter()
    box = {"note": ""}
    try:
        yield box
    except Exception as exc:                                 # noqa: BLE001
        dt = time.perf_counter() - t0
        TIMINGS.append((label, dt, f"FAILED: {type(exc).__name__}: {exc}"))
        print(f"  [{dt:7.2f}s] {label}: FAILED — {type(exc).__name__}: {exc}")
        raise
    dt = time.perf_counter() - t0
    TIMINGS.append((label, dt, box["note"] or "ok"))
    print(f"  [{dt:7.2f}s] {label}: {box['note'] or 'ok'}")


def validity(shape: TopoDS_Shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


def volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def count(shape: TopoDS_Shape, kind) -> int:
    exp, n = TopExp_Explorer(shape, kind), 0
    while exp.More():
        n += 1
        exp.Next()
    return n


# ------------------------------------------------------- shapely -> OCC bridge

def _ring_wire(coords, z: float):
    """A closed polygonal wire at height z from a shapely coordinate sequence."""
    mp = BRepBuilderAPI_MakePolygon()
    pts = list(coords)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    for x, y in pts:
        mp.Add(gp_Pnt(float(x), float(y), float(z)))
    mp.Close()
    return mp.Wire()


def polygon_to_face(poly, z: float = 0.0):
    """Planar face at height z, with holes."""
    outer = _ring_wire(poly.exterior.coords, z)
    mf = BRepBuilderAPI_MakeFace(outer)
    for interior in poly.interiors:
        hole = _ring_wire(interior.coords, z)
        hole.Reverse()
        mf.Add(hole)
    return mf.Face()


def extrude(face, height: float):
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, float(height))).Shape()


def fuse_all(shapes: list[TopoDS_Shape]) -> TopoDS_Shape:
    out = shapes[0]
    for s in shapes[1:]:
        op = BRepAlgoAPI_Fuse(out, s)
        op.Build()
        if not op.IsDone():
            raise RuntimeError("fuse failed")
        out = op.Shape()
    return out


# ------------------------------------------------------------ the demo castle

def load_demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams(), hinges


def build_castle_solid(partition, castle):
    """Every zone extruded to its own height, fused. The stepped castle, with
    real edges where the raster had a sampled staircase."""
    heights = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}
    heights.update({n: mm for n, mm in castle.zone_height_overrides.items()
                    if n in heights})
    solids = []
    for zone in partition.zones:
        poly = zone.polygon
        if poly.is_empty or poly.area <= 0:
            continue
        solids.append(extrude(polygon_to_face(poly, 0.0), heights[zone.name]))
    return fuse_all(solids), heights


# --------------------------------------- §5.2  fillet the footing step edges

def _edge_points(edge, n: int = 5):
    """n points along an edge. BRepAdaptor_Curve rather than BRep_Tool.Curve_s:
    the OCP binding for the latter returns only the curve, not the parameter
    range, so the range has to come from the adaptor anyway."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    try:
        ad = BRepAdaptor_Curve(edge)
        u0, u1 = ad.FirstParameter(), ad.LastParameter()
        if not np.isfinite(u0) or not np.isfinite(u1):
            return None
        return [ad.Value(u0 + (u1 - u0) * i / (n - 1)) for i in range(n)]
    except Exception:                                        # noqa: BLE001
        return None


def step_edges(solid, body, max_h: float, probe_mm: float = 0.35):
    """Horizontal interior edges: the terrace steps the footing blend rounds.

    A step edge is level (constant z), strictly between the anterior face and
    the tallest terrace, and has material on *both* sides in plan — which is
    what separates it from the outline silhouette, whose top edge is level too
    but has material on one side only.
    """
    from shapely.geometry import Point

    out = []
    exp = TopExp_Explorer(solid, TopAbs_ShapeEnum.TopAbs_EDGE)
    seen = set()
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        pts = _edge_points(edge)
        if pts is None:
            continue
        zs = [p.Z() for p in pts]
        if max(zs) - min(zs) > 1e-7:
            continue                                  # not level
        z = float(np.mean(zs))
        if z <= 1e-6 or z >= max_h - 1e-6:
            continue
        p0, p1 = pts[0], pts[-1]
        key = (round(p0.X(), 4), round(p0.Y(), 4), round(p1.X(), 4),
               round(p1.Y(), 4), round(z, 4))
        if key in seen or key[2:4] + key[0:2] + (key[4],) in seen:
            continue
        seen.add(key)
        mid = pts[len(pts) // 2]
        t = np.array([p1.X() - p0.X(), p1.Y() - p0.Y()])
        ln = np.linalg.norm(t)
        if ln < 1e-9:
            continue
        t /= ln
        nrm = np.array([-t[1], t[0]]) * probe_mm
        a = Point(mid.X() + nrm[0], mid.Y() + nrm[1])
        b = Point(mid.X() - nrm[0], mid.Y() - nrm[1])
        if body.contains(a) and body.contains(b):
            out.append((edge, z, ln))
    return out


def try_fillet(solid, edges, radius_of):
    """Fillet the step edges one at a time, longest first (a long clean edge is
    the kernel's best case; failures cluster on the short high-curvature ones).
    Returns (shape, n_ok, failures)."""
    shape = solid
    ok, failures = 0, []
    for edge, z, ln in sorted(edges, key=lambda e: -e[2]):
        r = radius_of(z, ln)
        if r <= 0:
            continue
        try:
            mk = BRepFilletAPI_MakeFillet(shape)
            mk.Add(float(r), edge)
            mk.Build()
            if not mk.IsDone():
                failures.append((z, ln, r, "not done"))
                continue
            cand = mk.Shape()
            if not validity(cand):
                failures.append((z, ln, r, "invalid result"))
                continue
            shape, ok = cand, ok + 1
        except Exception as exc:                             # noqa: BLE001
            failures.append((z, ln, r, f"{type(exc).__name__}"))
    return shape, ok, failures


# ------------- the correction §5.2 implies: footing as a SWEPT cross-section
#
# The scheduled footing radii (4-48 mm) are an order of magnitude larger than
# the steps they blend (0.2-5.8 mm). A 48 mm edge fillet on a 0.7 mm step is not
# a fillet any kernel can build -- there is nowhere near 48 mm of adjacent face
# to land it on. So these radii were never 3D edge fillets in Fusion either;
# they are radii of a *cross-section* S-blend, which is exactly what the
# analytic `_footing_z` implements ("the cross-section profile depends only on
# the signed distance to the cut line"). The B-Rep equivalent is therefore the
# same operation that worked in §5.1: sweep the profile along the SCULPT cut.

def footing_profile_wire(p_xy, perp, h_high, h_low, r_ext, r_int, first,
                         n=40, margin=1.0):
    """The material *above* the S-blend, as a closed section in the plane
    spanned by `perp` (signed distance from the cut) and Z."""
    from guildmodel.core.relief.castle import _footing_spans, _footing_z

    span_hi, span_lo = _footing_spans(h_high - h_low, r_ext, r_int, first)
    if span_hi <= 0 and span_lo <= 0:
        raise RuntimeError("degenerate footing span")
    s = np.linspace(-span_hi, span_lo, n)
    z = _footing_z(s, h_high, h_low, r_ext, r_int, first)

    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(perp[0]), float(perp[1])
    top = h_high + margin

    def at(u, v):
        return gp_Pnt(px + nx * u, py + ny * u, float(v))

    mp = BRepBuilderAPI_MakePolygon()
    for si, zi in zip(s, z):
        mp.Add(at(si, zi))
    mp.Add(at(s[-1], top))
    mp.Add(at(s[0], top))
    mp.Close()
    return mp.Wire()


def swept_footing_cutter(partition, zone_edge, heights, fillet, n_stations=30):
    """Sweep the footing S-blend along one real SCULPT cut line."""
    from shapely.geometry import Point

    cut = zone_edge.cut
    names = zone_edge.zone_names
    if len(names) != 2:
        raise RuntimeError(f"edge {zone_edge.name} has {len(names)} neighbours")
    h_a, h_b = heights[names[0]], heights[names[1]]
    if abs(h_a - h_b) < 1e-9:
        raise RuntimeError("no step across this edge")

    total = cut.length
    ss = np.linspace(0.02 * total, 0.98 * total, n_stations)
    pts, perps = [], []
    for s in ss:
        p = cut.interpolate(float(s))
        a = cut.interpolate(float(max(0.0, s - 0.05)))
        b = cut.interpolate(float(min(total, s + 0.05)))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append(np.array([p.x, p.y]))
        perps.append(np.array([-t[1], t[0]]))
    pts, perps = np.array(pts), np.array(perps)

    # Orient the perpendicular so -u is the HIGH side, matching _footing_z.
    mid, pn = pts[len(pts) // 2], perps[len(perps) // 2]
    probe = Point(*(mid - pn * 0.3))
    owner = None
    for zone in partition.zones:
        if zone.polygon.contains(probe):
            owner = zone.name
            break
    high = names[0] if h_a > h_b else names[1]
    if owner is not None and owner != high:
        perps = -perps
    h_high, h_low = max(h_a, h_b), min(h_a, h_b)

    ps = BRepOffsetAPI_MakePipeShell(spine_wire(pts, 0.0, spline=True))
    ps.SetMode(gp_Dir(0.0, 0.0, 1.0))
    ps.SetTransitionMode(
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RightCorner)
    for p, pn in zip(pts, perps):
        ps.Add(footing_profile_wire(
            p, pn, h_high, h_low, fillet.exterior_mm, fillet.interior_mm,
            fillet.first), False, False)
    ps.Build()
    if not ps.IsDone():
        raise RuntimeError("MakePipeShell.Build() not done")
    if not ps.MakeSolid():
        raise RuntimeError("MakePipeShell.MakeSolid() failed")
    return ps.Shape(), h_high - h_low


# ------------------------------- §5.1  tapered partial-span chamfer, by sweep

def _outward_normal(poly, p_xy: np.ndarray, tangent: np.ndarray) -> np.ndarray:
    """Unit outward normal of the ring at p, disambiguated by point-in-polygon
    rather than by trusting the ring's winding."""
    from shapely.geometry import Point

    n = np.array([tangent[1], -tangent[0]])
    n /= max(np.linalg.norm(n), 1e-12)
    if poly.contains(Point(*(p_xy + n * 1e-4))):
        n = -n
    return n


def span_stations(ring, s0: float, s1: float, n: int):
    """n points along the ring between arc-lengths s0..s1, with unit tangents."""
    total = ring.length
    ss = np.linspace(s0, s1, n)
    pts, tans = [], []
    for s in ss:
        p = ring.interpolate(float(s % total))
        eps = min(0.05, (s1 - s0) / (4 * n))
        a = ring.interpolate(float((s - eps) % total))
        b = ring.interpolate(float((s + eps) % total))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append(np.array([p.x, p.y]))
        tans.append(t)
    return ss, np.array(pts), np.array(tans)


def taper(ss: np.ndarray, s0: float, s1: float, blend_mm: float) -> np.ndarray:
    """M17's taper law: cosine feather to nothing over `blend_mm` at each end,
    capped at half the run so a long blend cannot ramp past the middle."""
    run = s1 - s0
    b = min(blend_mm, run / 2.0)
    if b <= 0:
        return np.ones_like(ss)
    d = np.minimum(ss - s0, s1 - ss)
    w = np.clip(d / b, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * w)


def chamfer_profile_wire(p_xy, normal, z_top, width, angle_deg, margin=1.5):
    """Closed pentagon in the plane normal to the spine: everything above the
    chamfer line near the corner, extended `margin` outside the part so the
    boolean has clean overlap rather than a tangency."""
    drop = width * math.tan(math.radians(angle_deg))
    nx, ny = float(normal[0]), float(normal[1])
    px, py = float(p_xy[0]), float(p_xy[1])

    def at(u, v):
        return gp_Pnt(px + nx * u, py + ny * u, z_top + v)

    mp = BRepBuilderAPI_MakePolygon()
    for u, v in ((-width, 0.0), (0.0, -drop), (margin, -drop),
                 (margin, margin), (-width, margin)):
        mp.Add(at(u, v))
    mp.Close()
    return mp.Wire()


def spine_wire(pts_xy: np.ndarray, z: float, spline: bool = True):
    """The swept path. spline=True fits a B-spline through the station points —
    the organic case the report says is the real risk; spline=False falls back
    to a polyline spine."""
    if not spline:
        mp = BRepBuilderAPI_MakePolygon()
        for x, y in pts_xy:
            mp.Add(gp_Pnt(float(x), float(y), z))
        return mp.Wire()
    arr = TColgp_Array1OfPnt(1, len(pts_xy))
    for i, (x, y) in enumerate(pts_xy, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), z))
    curve = GeomAPI_PointsToBSpline(arr).Curve()
    edge = BRepBuilderAPI_MakeEdge(curve).Edge()
    return BRepBuilderAPI_MakeWire(edge).Wire()


def swept_chamfer_cutter(partition, zone_names, z_top, width_mm, angle_deg,
                         blend_mm, n_stations=25, use_spline=True,
                         min_width=0.0):
    """The M17 brow chamfer as a swept solid: a varying profile along the span
    of the outline the given zones own, feathered to nothing at each end."""
    from guildmodel.core.relief.edges import span_intervals

    ring = partition.body.exterior
    spans = span_intervals(ring, partition, list(zone_names))
    if not spans:
        raise RuntimeError(f"no span for zones {zone_names}")
    s0, s1 = max(spans, key=lambda iv: iv[1] - iv[0])

    ss, pts, tans = span_stations(ring, s0, s1, n_stations)
    w = taper(ss, s0, s1, blend_mm) * width_mm
    if min_width > 0:
        w = np.maximum(w, min_width)

    ps = BRepOffsetAPI_MakePipeShell(spine_wire(pts, z_top, use_spline))
    ps.SetMode(gp_Dir(0.0, 0.0, 1.0))     # fixed binormal: the chamfer stays
    ps.SetTransitionMode(                 # upright, it does not roll with Frenet
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RightCorner)
    added = 0
    for p, t, wi in zip(pts, tans, w):
        if wi <= 1e-9:
            continue
        nrm = _outward_normal(partition.body, p, t)
        ps.Add(chamfer_profile_wire(p, nrm, z_top, float(wi), angle_deg),
               False, False)
        added += 1
    ps.Build()
    if not ps.IsDone():
        raise RuntimeError(f"MakePipeShell.Build() not done ({added} profiles)")
    if not ps.MakeSolid():
        raise RuntimeError("MakePipeShell.MakeSolid() failed")
    return ps.Shape(), (s1 - s0), added


# ------------------------------------------------------------------ main spike

def main() -> None:
    print("=" * 72)
    print("Stage 1 kernel spike — OCCT 7.9 via cadquery-ocp, Demo Project frame")
    print("=" * 72)

    print("\n[load]")
    with step("import demo + partition zones") as s:
        partition, castle, hinges = load_demo()
        s["note"] = (f"{len(partition.zones)} zones, {len(partition.edges)} "
                     f"zone edges, classified={partition.classified}")

    print("\n[part A] build the castle as a B-Rep solid")
    with step("extrude + fuse zone terraces") as s:
        solid, heights = build_castle_solid(partition, castle)
        s["note"] = (f"valid={validity(solid)} vol={volume(solid):.2f} mm^3 "
                     f"faces={count(solid, TopAbs_ShapeEnum.TopAbs_FACE)} "
                     f"edges={count(solid, TopAbs_ShapeEnum.TopAbs_EDGE)}")

    print("\n[part B] §5.2 — fillet robustness on the footing step edges")
    max_h = max(heights.values())
    with step("locate interior step edges") as s:
        edges = step_edges(solid, partition.body, max_h)
        zs = sorted({round(z, 3) for _, z, _ in edges})
        s["note"] = (f"{len(edges)} level interior edges, "
                     f"total length {sum(e[2] for e in edges):.1f} mm, "
                     f"at z {zs}")

    sched = castle.footing
    print("    scheduled footing radii (ext/int, mm): " + ", ".join(
        f"{name}={getattr(sched, name).exterior_mm:g}/"
        f"{getattr(sched, name).interior_mm:g}"
        for name in ("endpiece_superior", "endpiece_inferior",
                     "bridge_superior", "nosepad_superior",
                     "nosepad_inferior")))
    steps_mm = sorted({round(abs(a - b), 2)
                       for a in heights.values() for b in heights.values()
                       if 0 < abs(a - b) < 6})
    print(f"    terrace step heights present: {steps_mm} mm")

    with step("fillet at the SCHEDULED radii (exterior 6-32 mm)") as s:
        _, ok, fails = try_fillet(solid, edges, lambda z, ln: 6.0)
        s["note"] = f"{ok}/{len(edges)} succeeded, {len(fails)} failed"
        if fails:
            kinds: dict[str, int] = {}
            for *_, why in fails:
                kinds[why] = kinds.get(why, 0) + 1
            print(f"        failure modes: {kinds}")

    for r in (1.0, 0.5, 0.25):
        with step(f"fillet at r = {r} mm (small, geometrically admissible)") as s:
            shp, ok, fails = try_fillet(solid, edges, lambda z, ln, r=r: r)
            s["note"] = (f"{ok}/{len(edges)} succeeded, {len(fails)} failed, "
                         f"valid={validity(shp)}")
            if fails:
                kinds = {}
                for *_, why in fails:
                    kinds[why] = kinds.get(why, 0) + 1
                print(f"        failure modes: {kinds}")

    print("\n[part B2] the correction: footing as a swept cross-section")
    swept_ok, swept_fail, cut_ok, cut_fail = 0, [], 0, []
    running = solid
    for ze in partition.edges:
        if not ze.canonical:
            continue
        try:
            fillet = castle.footing.for_edge(ze.canonical)
        except AttributeError:
            continue
        try:
            cutter, dh = swept_footing_cutter(partition, ze, heights, fillet)
        except Exception as exc:                             # noqa: BLE001
            swept_fail.append((ze.name, f"{type(exc).__name__}: {exc}"))
            continue
        if not validity(cutter):
            swept_fail.append((ze.name, "invalid sweep"))
            continue
        swept_ok += 1
        try:
            op = BRepAlgoAPI_Cut(running, cutter)
            op.Build()
            if op.IsDone() and validity(op.Shape()):
                running, cut_ok = op.Shape(), cut_ok + 1
            else:
                cut_fail.append((ze.name, "boolean not done/invalid"))
        except Exception as exc:                             # noqa: BLE001
            cut_fail.append((ze.name, f"{type(exc).__name__}"))

    n_named = sum(1 for e in partition.edges if e.canonical)
    with step("sweep + subtract the footing blend on every named edge") as s:
        s["note"] = (f"swept {swept_ok}/{n_named} valid, "
                     f"booleans {cut_ok}/{swept_ok} valid, "
                     f"result valid={validity(running)} "
                     f"vol={volume(running):.2f} mm^3")
    for name, why in (swept_fail + cut_fail)[:8]:
        print(f"        {name}: {why}")

    print("\n[part C] §5.1 — tapered partial-span chamfer on the anterior brow")
    brow = "eyewire_superior_od"
    z_top = heights[brow]
    cutter = None
    for label, kw in (
        ("spline spine, taper to zero", dict(use_spline=True, min_width=0.0)),
        ("spline spine, taper to 0.02", dict(use_spline=True, min_width=0.02)),
        ("polyline spine, taper to zero", dict(use_spline=False, min_width=0.0)),
    ):
        try:
            with step(f"sweep chamfer — {label}") as s:
                shp, run, added = swept_chamfer_cutter(
                    partition, [brow], z_top, width_mm=2.0, angle_deg=45.0,
                    blend_mm=4.0, **kw)
                s["note"] = (f"valid={validity(shp)} run={run:.2f} mm "
                             f"profiles={added} vol={volume(shp):.2f} mm^3")
            if cutter is None:
                cutter = shp
        except Exception:                                    # noqa: BLE001, S110
            pass

    if cutter is not None:
        with step("subtract chamfer from castle") as s:
            op = BRepAlgoAPI_Cut(solid, cutter)
            op.Build()
            if not op.IsDone():
                raise RuntimeError("cut failed")
            chamfered = op.Shape()
            s["note"] = (f"valid={validity(chamfered)} "
                         f"vol={volume(chamfered):.2f} mm^3 "
                         f"(removed {volume(solid) - volume(chamfered):.3f})")

    print("\n--- summary " + "-" * 60)
    for label, dt, note in TIMINGS:
        print(f"  {dt:7.2f}s  {label:44s} {note}")


if __name__ == "__main__":
    main()
