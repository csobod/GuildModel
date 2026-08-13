"""M13.3 tests: the bridge projection relief — a conic scoop running on Y down
the posterior bridge (reworked per user direction 2026-07-02): base = widest,
deepest cut opening through the top edge over the bridge; sides taper at the
cone angle to a rounded tip on the lower bridge; depth scaling to the local
width (a true cone imprint), so the cut is crease-free and flows with the
footing.

The cross-section was a tangent cosine bell and is now the footing-style U in
`geometry.blends` (field report 2026-08-11: the bell was smooth but carried no
numbers, so there was no way to ask for a tighter trough or a wider rim blend).
Its two radii are the same exterior/interior pair `FootingFillet` uses.

Gates: schema round-trip (default OFF), toggle-off bit-identical, the carved
cross-section equals the shared U, the radii actually change the section and the
reported slope, the fit cap, orientation/taper (base at the top, narrowing +
shallowing toward the tip), tangent edges, generic (no-SCULPT) partitions, and
resolution stability.
"""
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).parents[1] / "tests" / "fixtures" / "demo"


@pytest.fixture(scope="module")
def demo():
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


@pytest.fixture(scope="module")
def base_relief(demo):
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    return build_castle_relief(part, castle, hinges, resolution=0.2)


def _scoop_relief(demo, res=0.2, **overrides):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    castle = CastleParams()
    castle.bridge_relief.enabled = True
    for k, v in overrides.items():
        setattr(castle.bridge_relief, k, v)
    return build_castle_relief(part, castle, hinges, resolution=res)


def _strip_top_y(relief, x=0.0):
    res = relief.field.resolution
    ox, oy = relief.field.origin
    col = int(round((x - ox) / res))
    return oy + np.flatnonzero(relief.inside[:, col]).max() * res


# ------------------------------------------------------------------ schema

def test_bridge_relief_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    proj = ProjectSchema(job_name="Scoop RT")
    proj.castle.bridge_relief.enabled = True
    proj.castle.bridge_relief.width_mm = 10.0
    proj.castle.bridge_relief.taper_angle_deg = 20.0
    path = tmp_path / "scoop.guildmodel"
    save_project(proj, path)
    back = load_project(path)
    assert back.castle.bridge_relief.enabled is True
    assert back.castle.bridge_relief.width_mm == 10.0
    assert back.castle.bridge_relief.taper_angle_deg == 20.0
    assert back.castle.bridge_relief.depth_mm == 1.2
    assert back.castle.bridge_relief.anterior_clamp_mm == 1.5


def test_bridge_relief_off_is_bit_identical(demo, base_relief):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    again = build_castle_relief(part, CastleParams(), hinges, resolution=0.2)
    assert np.array_equal(base_relief.field.z, again.field.z)
    assert again.feature_band is None


# ------------------------------------------------------------------ geometry

def test_scoop_cross_section_is_the_shared_u(demo, base_relief):
    """The section is `geometry.blends.scoop_drop`, not the cosine bell it was.

    The bell was smooth but had no numbers in it — a maker who wanted the trough
    tighter or the rim blended further out had nothing to turn (field report,
    2026-08-11). The U carries the footing's own exterior/interior pair, and this
    pins the raster against the one function all three kernels call rather than
    against a second copy of the formula.
    """
    from guildmodel.core.geometry.blends import scoop_drop

    rel = _scoop_relief(demo)                 # W=8, D=1.2, taper 30
    assert rel.feature_band is not None

    res = rel.field.resolution
    ox, oy = rel.field.origin
    y_base = _strip_top_y(rel)
    y_tip = y_base - 4.0 / np.tan(np.radians(30.0))
    y = y_base - 2.0
    row = int(round((y - oy) / res))
    sel = rel.feature_band[row]
    assert sel.any()
    xs = ox + np.flatnonzero(sel) * res
    r = (y - y_tip) * np.tan(np.radians(30.0))
    d = 1.2 * (r / 4.0)
    want = scoop_drop(xs, r, d, 3.0, 3.0)      # the schema defaults
    drop = base_relief.field.z[row, sel] - rel.field.z[row, sel]
    assert np.allclose(drop, want, atol=0.02)
    # tangent edges: the outermost carved cells are a whisper deep, no wall
    assert drop[0] <= 0.12 * d and drop[-1] <= 0.12 * d


def test_scoop_radii_change_the_section_and_the_slope():
    """The two radii are the controls the feature was missing: a bigger pair
    hollows the U (steeper walls, flatter trough) and the CAM's finishing
    stepover follows, because the ramp between the arcs *is* the max slope."""
    from guildmodel.core.geometry.blends import scoop_drop
    from guildmodel.core.project.schema import BridgeReliefParams

    xs = np.linspace(-4.0, 4.0, 401)
    sharp = scoop_drop(xs, 4.0, 1.2, 0.0, 0.0)
    round_ = scoop_drop(xs, 4.0, 1.2, 3.0, 3.0)

    # Full depth at the centerline and nothing at the rim, whatever the radii.
    for w in (sharp, round_):
        assert w[len(w) // 2] == pytest.approx(1.2, abs=1e-6)
        assert w[0] == pytest.approx(0.0, abs=1e-9)
        assert w[-1] == pytest.approx(0.0, abs=1e-9)

    # A V is straight-sided; the blended one is not, and is steeper in the wall.
    assert np.abs(np.diff(sharp)).max() < np.abs(np.diff(round_)).max()
    assert (BridgeReliefParams(exterior_radius_mm=0.0, interior_radius_mm=0.0)
            .max_slope_deg()
            < BridgeReliefParams(exterior_radius_mm=3.0, interior_radius_mm=3.0)
            .max_slope_deg())

    # The reported slope is the section's real one, to the grid.
    p = BridgeReliefParams(exterior_radius_mm=3.0, interior_radius_mm=3.0)
    measured = np.degrees(np.arctan(np.abs(np.diff(round_) / np.diff(xs)).max()))
    assert measured == pytest.approx(p.max_slope_deg(), abs=0.2)


def test_a_zero_rim_radius_still_builds_a_closed_solid():
    """The `MIN_RIM_RADIUS_MM` floor, and the measurement behind it.

    A scoop whose exterior radius is exactly zero left the demo frame with gaps
    along 15 edges — the cutter's rim ran into the surface it exits rather than
    crossing it. Measured across all three fixtures: 0 fails, 0.01 mm and above
    is clean, and the *interior* radius makes no difference either way. The
    floor is on the rim alone, so a sharp V **trough** still means what it says.
    """
    from guildmodel.core.geometry.blends import MIN_RIM_RADIUS_MM, scoop_ramp_angle

    _theta, re, ri = scoop_ramp_angle(np.array(4.0), np.array(1.2), 0.0, 0.0)
    assert float(re) == pytest.approx(MIN_RIM_RADIUS_MM)
    assert float(ri) == 0.0            # the trough is left sharp

    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model.build import build_castle_model
    from guildmodel.core.model.kernel import to_trimesh
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    part = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                           [points_to_polygon(c) for c in raw["LENS"]],
                           raw["SCULPT"])
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    castle = CastleParams()
    castle.bridge_relief.enabled = True
    castle.bridge_relief.exterior_radius_mm = 0.0
    castle.bridge_relief.interior_radius_mm = 0.0
    verdict = verify_mesh(to_trimesh(build_castle_model(part, castle, hinges)))
    assert verdict.ok, verdict.summary


def test_a_sharp_v_section_samples_its_own_apex():
    """An even section count puts the two innermost samples either side of the
    trough and replaces it with a chord — a straight V came out 3.7% shallow at
    the 28 points the solid kernels lofted. `scoop_section_x` is odd, so the
    apex is always a sample and a V (whose flanks are straight lines) is
    reproduced exactly."""
    from guildmodel.core.geometry.blends import scoop_drop, scoop_section_x

    xs = scoop_section_x(4.0, 28)
    assert len(xs) % 2 == 1
    assert 0.0 in xs
    w = scoop_drop(xs, 4.0, 1.2, 0.0, 0.0)
    assert w.max() == pytest.approx(1.2, abs=1e-6)


def test_scoop_radii_are_capped_to_fit_the_width_and_depth():
    """Past `(a^2 + d^2) / 2d` on their sum there is no straight ramp left, so
    both radii shrink in proportion rather than the section ceasing to exist.
    Proportional and continuous, so the swept surface stays smooth through the
    stations where the cap starts to bite as the cone tapers."""
    from guildmodel.core.geometry.blends import scoop_drop, scoop_ramp_angle

    a, d = 4.0, 1.2
    cap = (a * a + d * d) / (2.0 * d)
    _theta, re, ri = scoop_ramp_angle(np.array(a), np.array(d), 20.0, 20.0)
    assert float(re) + float(ri) == pytest.approx(0.999 * cap, rel=1e-6)
    assert float(re) == pytest.approx(float(ri))       # asked for equal, got equal

    # Still a well-formed section at the cap.
    xs = np.linspace(-a, a, 201)
    w = scoop_drop(xs, a, d, 20.0, 20.0)
    assert w[len(w) // 2] == pytest.approx(d, abs=1e-6)
    assert np.all(np.diff(w[:len(w) // 2]) >= -1e-12)   # monotone down to the trough


def test_scoop_runs_on_y_base_at_top(demo, base_relief):
    rel = _scoop_relief(demo)
    res = rel.field.resolution
    ox, oy = rel.field.origin
    rr, cc = np.nonzero(rel.feature_band)
    xs, ys = ox + cc * res, oy + rr * res
    drop = base_relief.field.z[rr, cc] - rel.field.z[rr, cc]
    y_base = _strip_top_y(rel)

    # widest + deepest at the base (the top edge of the frame over the bridge)
    assert ys.max() == pytest.approx(y_base, abs=2 * res)
    assert drop.max() == pytest.approx(1.2, abs=0.02)
    assert ys[np.argmax(drop)] == pytest.approx(y_base, abs=3 * res)
    # bounded by the base half-width, centered on the bridge
    assert np.abs(xs).max() <= 4.0 + res
    # narrower AND shallower toward the tip (a true cone section)
    def row_stats(y):
        row = int(round((y - oy) / res))
        s = rel.feature_band[row]
        x_row = ox + np.flatnonzero(s) * res
        d_row = base_relief.field.z[row, s] - rel.field.z[row, s]
        return x_row.max() - x_row.min(), d_row.max()
    w_hi, d_hi = row_stats(y_base - 1.5)
    w_lo, d_lo = row_stats(y_base - 4.5)
    assert w_lo < w_hi and d_lo < d_hi
    # the tip lands where the taper says (half-width / tan(taper) below base)
    y_tip = y_base - 4.0 / np.tan(np.radians(30.0))
    assert ys.min() >= y_tip - 2 * res


def test_scoop_taper_angle_moves_the_tip(demo):
    steep = _scoop_relief(demo, taper_angle_deg=45.0)
    shallow = _scoop_relief(demo, taper_angle_deg=25.0)
    res = steep.field.resolution
    oy = steep.field.origin[1]

    def tip_y(rel):
        rr, _ = np.nonzero(rel.feature_band)
        return oy + rr.min() * res

    # a steeper taper reaches its tip sooner (higher on the bridge)
    assert tip_y(steep) > tip_y(shallow) + 1.0


def test_scoop_generic_partition_fallback():
    from shapely.geometry import Point, Polygon
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    outline = Polygon([(-50, -20), (50, -20), (50, 20), (-50, 20)])
    lenses = [Point(-25, 0).buffer(12), Point(25, 0).buffer(12)]
    part = partition_zones(outline, lenses, [])
    assert part.matched is False
    castle = CastleParams()
    castle.bridge_relief.enabled = True
    heights = {z.name: 5.0 for z in part.zones}
    rel = build_castle_relief(part, castle, [], resolution=0.3, heights=heights)
    assert rel.feature_band is not None
    rr, cc = np.nonzero(rel.feature_band)
    xs = rel.field.origin[0] + cc * rel.field.resolution
    ys = rel.field.origin[1] + rr * rel.field.resolution
    assert np.abs(xs).max() <= 4.0 + rel.field.resolution
    assert ys.max() == pytest.approx(20.0, abs=2 * rel.field.resolution)
    drop = 5.0 - rel.field.z[rr, cc]
    assert drop.max() == pytest.approx(1.2, abs=0.03)


def test_scoop_resolution_stability(demo):
    rel_a = _scoop_relief(demo, res=0.3)
    rel_b = _scoop_relief(demo, res=0.15)

    def depth_below_base(rel, dy=2.0):
        res = rel.field.resolution
        ox, oy = rel.field.origin
        row = int(round((_strip_top_y(rel) - dy - oy) / res))
        col = int(round((0.0 - ox) / res))
        return float(rel.surface_field.z[row, col])

    assert abs(depth_below_base(rel_a) - depth_below_base(rel_b)) <= 0.06
