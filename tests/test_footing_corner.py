"""The sharp fin at the inferior nosepad, and the gate that would have caught it.

A footing band is a ribbon swept along a zone seam, so it has square ends and
never carves the corner just off one. The raster has no such notion — it carves
by Euclidean distance to the seam, which rounds the corner for free. So the
raster and *both* solid kernels disagreed exactly there, and the two solid
kernels agreed with each other perfectly, which is why every parity gate passed.

It survived from before UI-0 ("a visibly corrupt model — a spike of material off
the nosepad") until 2026-08-08, and nothing automated ever saw it: the part is
watertight, one body, one connected piece, and correct to 0.04% on volume with a
9 mm wedge of uncarved material standing on it. It took a maker looking at the
render.

**What makes it appear.** A fillet large against the seam it runs along. On the
gabriel, `nosepad_inferior` is a **5.19 mm** seam carrying **9.0 / 10.0 mm**
radii, so the blend reaches nearly twice as far as the seam is long and the
uncarved corner comes out as a long wedge tapering to a point. The demo's same
seam is 10.14 mm and shows nothing — which is the lesson about fixture choice,
not about the demo.

`geometry.footings.CUT_LEAD_MM` runs the stations past both ends.

These compare against the **raster**, deliberately. The two solid kernels agreeing
with each other is exactly the condition that hid this, so a mesh-vs-B-Rep gate
would not have caught it and will not catch the next one.

----

**2026-08-12 — the same fin, and why this file did not catch it either.** A maker
reported "protrusion of material at the nosepad, across many frames" with two
drawings attached; the Calasanz stands a **2.4 mm** fin at the nose notch, and
since M-N3 the mesh kernel is not just the preview but the surface the CAM posts
from, so it was going to be cut.

Nothing above is wrong. What was wrong is that all of it was read on one meter —
`_tongue`, the lowest full-height cell in a nosepad *zone*, on three fixtures —
and `CUT_LEAD_MM` was then set to the value that meter stopped moving at. A
constant lead cannot be right: how far a square cap has to travel to leave the
zone is a property of the drawing. Where the outline flares away from the end of
a seam, the zone reaches back under a cap that has already passed it.

`footings.cap_leads` measures it per end instead, and it measures **every fixture
in this repo short** — demo 1.14 mm, gabriel 0.85, aviator 1.76 against the 0.5
they were given. So the gate this file was missing is not another fixture and not
a wider tolerance: it is
`test_every_band_end_clears_the_zone_it_acts_on`, which asks the question
directly and fails on all three fixtures against the old constant.

Whole-surface mesh-vs-raster would *not* have caught it, and that is worth
recording: on the three fixtures the old code's worst disagreement anywhere was
0.10 mm (gabriel), inside any tolerance anyone would have written. The Calasanz's
was 2.05.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
from shapely import contains_xy, prepare

FIXTURES = Path(__file__).parent / "fixtures"

#: How far the lowest full-height cell in a nosepad zone may sit below the
#: raster's answer, mm. One 0.15 mm CAM cell of slack, doubled: the three paths
#: land within a cell of each other and the defect this guards against was
#: 1.95 mm — a hundred times this — so there is no need to sit on the noise.
TONGUE_TOL_MM = 0.3


def _demo_front():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws


def _gdraw_front(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def demo_front():
    return _demo_front()


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "gabriel")


def _tongue(relief, partition):
    """Lowest y still standing at full nosepad height, per nosepad zone."""
    f = relief.field
    rows, cols = f.z.shape
    xs = f.origin[0] + np.arange(cols) * f.resolution
    ys = f.origin[1] + np.arange(rows) * f.resolution
    grid_x, grid_y = np.meshgrid(xs, ys)

    out = {}
    for zone in partition.zones:
        if "nosepad" not in zone.name:
            continue
        prepare(zone.polygon)
        inside = contains_xy(zone.polygon, grid_x.ravel(),
                             grid_y.ravel()).reshape(rows, cols)
        tall = inside & (f.z > 9.5)
        out[zone.name] = float(grid_y[tall].min()) if tall.any() else None
    return out


@pytest.mark.parametrize("fixture",
                         ["gabriel_front", "aviator_front", "demo_front"])
def test_no_uncarved_wedge_survives_at_the_nosepad_corner(fixture, request):
    """Both solid kernels must stop full-height material where the raster does.

    Measured before the fix, lowest full-height cell: gabriel **-6.697** against
    the raster's -4.747, aviator -8.366 against -7.016. After: -4.597 / -4.747
    and -7.016 / -7.016. The demo's nosepads do not move at all — its seams are
    long enough that the corner was never visible — though the part as a whole
    loses 0.674 mm3 of uncarved corner elsewhere (`test_bridge_tangency_mn0`).
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import build_castle_model, mesh_to_relief
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, clear_base_cache,
                                       solid_to_relief)

    front = request.getfixturevalue(fixture)
    part, hinges = front.partition, front.hinge_polys
    castle = CastleParams()

    raster = _tongue(build_castle_relief(part, castle, hinges,
                                         resolution=CUT_RES_MM), part)
    mesh = _tongue(mesh_to_relief(build_castle_model(part, castle, hinges),
                                  part, castle, resolution=CUT_RES_MM), part)
    clear_base_cache()
    brep = _tongue(solid_to_relief(build_castle_solid(part, castle, hinges),
                                   part, castle, resolution=CUT_RES_MM), part)

    assert raster, "no nosepad zones on this drawing; the test proves nothing"
    for zone, reference in raster.items():
        for label, table in (("mesh", mesh), ("brep", brep)):
            got = table[zone]
            assert got is not None, f"{label} carved the whole {zone} away"
            assert got >= reference - TONGUE_TOL_MM, (
                f"{label} leaves full-height material down to y={got:.3f} in "
                f"{zone}, where the raster stops at {reference:.3f} — an "
                "uncarved wedge off the end of a footing band")


@pytest.mark.parametrize("fixture",
                         ["gabriel_front", "aviator_front", "demo_front"])
def test_every_band_end_clears_the_zone_it_acts_on(fixture, request):
    """The gate the constant needed: ask each cap whether it left the zone.

    Rebuilds exactly what `footing_tools` builds — the same per-band reach, the
    same `cap_leads`, the same `cut_stations` — then checks the thing a ribbon
    can never do for itself: that no material of the acting zone, within the
    reach of *that* band, lies beyond its final station's cap plane.

    Fails on all three fixtures against the old fixed 0.5 mm (needing 1.14 /
    0.85 / 1.76 mm), which is what makes it a gate rather than a restatement.
    """
    from guildmodel.core.geometry.footings import cap_leads, cut_stations
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import _footing_reach

    front = request.getfixturevalue(fixture)
    part = front.partition
    castle = CastleParams()
    heights = {z.name: castle.zones.for_kind(z.kind) for z in part.zones}

    checked = 0
    for edge in part.edges:
        if not edge.canonical:
            continue
        try:
            fillet = castle.footing.for_edge(edge.canonical)
        except AttributeError:
            continue
        names = edge.zone_names
        if len(names) != 2 or not all(n in heights for n in names):
            continue
        hi, lo = ((names[0], names[1]) if heights[names[0]] > heights[names[1]]
                  else (names[1], names[0]))
        if heights[hi] - heights[lo] < 1e-9:
            continue
        reach_hi, reach_lo = _footing_reach(heights[hi] - heights[lo],
                                            fillet.exterior_mm,
                                            fillet.interior_mm, fillet.first)

        for zone, reach in ((hi, reach_hi), (lo, reach_lo)):
            poly = part.zone(zone).polygon
            band = [(poly, reach)]
            pts, _ = cut_stations(edge.cut, 30, cap_leads(edge.cut, band))
            near = poly.intersection(edge.cut.buffer(float(reach)))
            if near.is_empty:
                continue
            for tip, inner in ((pts[0], pts[1]), (pts[-1], pts[-2])):
                t = np.asarray(tip) - np.asarray(inner)
                t /= np.linalg.norm(t)
                for geom in getattr(near, "geoms", (near,)):
                    ring = getattr(geom, "exterior", None)
                    if ring is None or ring.is_empty:
                        continue
                    q = np.asarray(ring.coords)[:, :2]
                    beyond = ((q - tip) @ t).max()
                    assert beyond <= 0.0, (
                        f"{edge.canonical}/{zone}: the band's cap stops "
                        f"{beyond:.3f} mm short of the last material its own "
                        "profile would have moved — an uncarved fin off the "
                        "end of a footing band")
            checked += 1

    assert checked >= 10, "no seams carried a footing; the test proves nothing"


def test_the_reach_stops_where_the_blend_stops_mattering():
    """`_footing_reach` against `_footing_spans`, and why the difference is not
    a shortcut.

    A blend touches down tangentially, so the span's last stretch is flat: on
    the `endpiece_superior` schedule (32 / 48 mm radii over a 0.7 mm step) the
    low half spans 8.17 mm and the outermost 1.4 mm of that is within 0.02 mm of
    the terrace. Covering it costs a millimeter of lead and moves nothing.
    """
    from guildmodel.core.relief.castle import (FOOTING_FLAT_TOL_MM,
                                               _footing_reach, _footing_spans,
                                               _footing_z)

    delta, r_ext, r_int = 0.7, 32.0, 48.0
    span_hi, span_lo = _footing_spans(delta, r_ext, r_int, "interior")
    reach_hi, reach_lo = _footing_reach(delta, r_ext, r_int, "interior")

    assert 0.0 < reach_hi < span_hi and 0.0 < reach_lo < span_lo
    assert span_lo == pytest.approx(8.17, abs=0.05)
    assert reach_lo == pytest.approx(6.78, abs=0.05)

    # The claim, checked rather than asserted: the reach brackets the crossing.
    # It is the last *sample* still outside the tolerance, so the true crossing
    # sits within one sample spacing beyond it — the reach is conservative by
    # under a hundredth of a millimeter of run, on the flattest part of the
    # curve there is.
    for span, reach, terrace, sign in ((span_hi, reach_hi, delta, -1.0),
                                       (span_lo, reach_lo, 0.0, 1.0)):
        step = span / 511.0
        inside = _footing_z(np.array([sign * reach]), delta, 0.0,
                            r_ext, r_int, "interior")[0]
        outside = _footing_z(np.array([sign * (reach + 2 * step)]), delta, 0.0,
                             r_ext, r_int, "interior")[0]
        assert abs(inside - terrace) > FOOTING_FLAT_TOL_MM
        assert abs(outside - terrace) <= FOOTING_FLAT_TOL_MM
        assert step < 0.02, "the sampling is the accuracy of the bracket"

    # A degenerate edge reaches nowhere, and says so rather than raising.
    assert _footing_reach(0.0, 4.0, 4.0) == (0.0, 0.0)


def test_cap_leads_asks_for_the_floor_on_a_seam_that_needs_nothing():
    """A straight seam across a straight strip: the cap is clear at once.

    Two flanking cases in one, because the whole risk of an adaptive rule is
    that it quietly becomes a constant again (always the floor) or quietly runs
    away (unbounded). A rectangle strip crossed square asks for the floor; the
    same strip with the outline flared past the seam's end asks for more, and
    never for more than the blend's own reach.
    """
    from shapely.geometry import LineString, Polygon

    from guildmodel.core.geometry.footings import (CAP_CROSS_MM, CUT_LEAD_MM,
                                                   cap_leads)

    seam = LineString([(0.0, -1.0), (0.0, 11.0)])       # crosses y in [0, 10]
    strip = Polygon([(0, 0), (6, 0), (6, 10), (0, 10)])
    assert cap_leads(seam, [(strip, 4.0)]) == (CUT_LEAD_MM, CUT_LEAD_MM)

    # Flared: the zone reaches 2 mm past the seam's low end (y = -2), so the
    # cap must travel that far plus its crossing margin.
    flared = Polygon([(0, -2), (6, -2), (6, 10), (0, 10)])
    head, tail = cap_leads(seam, [(flared, 4.0)])
    assert head == pytest.approx(1.0 + CAP_CROSS_MM)    # tip is at y = -1
    assert tail == CUT_LEAD_MM

    # Self-bounding: nothing can be asked for beyond the profile's reach, since
    # past that the blend has flattened to the terrace and carves nothing.
    tall = Polygon([(0, -50), (6, -50), (6, 10), (0, 10)])
    head, _ = cap_leads(seam, [(tall, 4.0)])
    assert head <= 4.0 + CAP_CROSS_MM


def test_the_stations_run_past_both_ends_of_the_cut():
    """The mechanism, checked directly rather than through a build.

    This used to sample 2%..98% of the cut, and on a short seam that trim is a
    tenth of a millimeter — which under a 9 mm blend is a 9 mm wedge. The
    stations now cover the whole cut and `CUT_LEAD_MM` past each end.
    """
    from shapely.geometry import LineString

    from guildmodel.core.geometry.footings import CUT_LEAD_MM, cut_stations

    line = LineString([(0.0, 0.0), (10.0, 0.0)])
    pts, perps = cut_stations(line, 12)

    assert pts[0][0] == pytest.approx(-CUT_LEAD_MM)
    assert pts[-1][0] == pytest.approx(10.0 + CUT_LEAD_MM)
    assert 0.0 < CUT_LEAD_MM <= 1.0, (
        "this is the FLOOR under `cap_leads`, not the lead itself. A floor "
        "above ~1 mm would spend length on the ends that measured they do not "
        "need it, which is the uniform 2 mm that cost OpenCASCADE its booleans "
        "on the aviator — see the constant's own note")
    assert len(pts) == len(perps) == 12
    # Left-normals of a +x cut point at +y, and stay unit length.
    assert np.allclose(np.linalg.norm(perps, axis=1), 1.0)
    assert perps[0][1] == pytest.approx(1.0)

    # A lead of zero still spans the cut exactly — the old behavior minus its
    # trim, which is what the parametrisation is for.
    plain, _ = cut_stations(line, 5, lead_mm=0.0)
    assert plain[0][0] == pytest.approx(0.0)
    assert plain[-1][0] == pytest.approx(10.0)

    # The two ends are led independently: `cap_leads` routinely returns a pair
    # differing by more than a millimeter, and one shared number is what the
    # 2026-08-12 fin was.
    pair, _ = cut_stations(line, 9, lead_mm=(2.0, 0.0))
    assert pair[0][0] == pytest.approx(-2.0)
    assert pair[-1][0] == pytest.approx(10.0)


def test_a_curved_cut_is_extrapolated_along_its_end_tangents():
    """The lead is a straight extension of the end segment, so a gently curved
    SCULPT line does not get a kink. Short by design: 2 mm on a spline whose
    curvature is measured in tens of millimeters."""
    from shapely.geometry import LineString

    from guildmodel.core.geometry.footings import CUT_LEAD_MM, cut_stations

    arc = LineString([(np.cos(t), np.sin(t)) for t in
                      np.linspace(0.0, np.pi / 2, 24)])
    pts, _ = cut_stations(arc, 30)

    start_seg = np.asarray(arc.coords[0]) - np.asarray(arc.coords[1])
    start_seg /= np.linalg.norm(start_seg)
    expected = np.asarray(arc.coords[0]) + start_seg * CUT_LEAD_MM
    assert np.allclose(pts[0], expected, atol=1e-9)
