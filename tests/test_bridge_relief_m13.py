"""M13.3 tests: the bridge projection relief — a conic scoop running on Y down
the posterior bridge (reworked per user direction 2026-07-02): base = widest,
deepest cut opening through the top edge over the bridge; sides taper at the
cone angle to a rounded tip on the lower bridge; tangent cosine-bell
cross-section with depth scaling to the local width (a true cone imprint), so
the cut is crease-free and flows with the footing.

Gates: schema round-trip (default OFF), toggle-off bit-identical, the carved
cross-section equals the analytic bell, orientation/taper (base at the top,
narrowing + shallowing toward the tip), tangent edges, generic (no-SCULPT)
partitions, and resolution stability.
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

def test_scoop_cross_section_matches_bell(demo, base_relief):
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
    want = d * (0.5 + 0.5 * np.cos(np.pi * xs / r))
    drop = base_relief.field.z[row, sel] - rel.field.z[row, sel]
    assert np.allclose(drop, want, atol=0.02)
    # tangent edges: the outermost carved cells are a whisper deep, no wall
    assert drop[0] <= 0.12 * d and drop[-1] <= 0.12 * d


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
