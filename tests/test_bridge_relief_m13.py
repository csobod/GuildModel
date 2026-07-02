"""M13.3 tests: the bridge projection relief — a V/U groove swept OD<->OS
across the posterior bridge, constant depth below the local surface.

Gates: schema round-trip (default OFF), toggle-off bit-identical, the carved
cross-section equals the analytic V-flank + circular-root profile, the axis
offset moves the groove, the carve is masked to the bridge span between the
lens rims, the groove works on generic (no-SCULPT) partitions, and the carve
is stable across grid resolutions.
"""
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).parents[1] / "Demo Project"


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


def _groove_relief(demo, res=0.2, **overrides):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    castle = CastleParams()
    castle.bridge_relief.enabled = True
    for k, v in overrides.items():
        setattr(castle.bridge_relief, k, v)
    return build_castle_relief(part, castle, hinges, resolution=res)


# ------------------------------------------------------------------ schema

def test_bridge_relief_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    proj = ProjectSchema(job_name="Groove RT")
    proj.castle.bridge_relief.enabled = True
    proj.castle.bridge_relief.depth_mm = 0.8
    proj.castle.bridge_relief.axis_offset_mm = -1.5
    path = tmp_path / "groove.guildmodel"
    save_project(proj, path)
    back = load_project(path)
    assert back.castle.bridge_relief.enabled is True
    assert back.castle.bridge_relief.depth_mm == 0.8
    assert back.castle.bridge_relief.axis_offset_mm == -1.5
    assert back.castle.bridge_relief.flank_angle_deg == 30.0
    assert back.castle.bridge_relief.root_radius_mm == 1.0


def test_bridge_relief_off_is_bit_identical(demo, base_relief):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    again = build_castle_relief(part, CastleParams(), hinges, resolution=0.2)
    assert np.array_equal(base_relief.field.z, again.field.z)
    assert again.feature_band is None


# ------------------------------------------------------------------ geometry

def test_groove_cross_section_matches_profile(demo, base_relief):
    from guildmodel.core.relief.features import _groove_profile

    rel = _groove_relief(demo)               # D=1.2, flank 30, root 1.0
    assert rel.feature_band is not None
    assert rel.feature_max_slope_deg == 30.0

    res = rel.field.resolution
    ox, oy = rel.field.origin
    col0 = int(round((0.0 - ox) / res))
    carved_rows = np.flatnonzero(rel.feature_band[:, col0])
    assert carved_rows.size > 10
    # groove axis = mid of the bridge strip on the centerline column
    strip = np.flatnonzero(rel.inside[:, col0])
    y_axis = oy + 0.5 * (strip.min() + strip.max()) * res
    ys = oy + carved_rows * res
    v = np.abs(ys - y_axis)
    p_want, W = _groove_profile(v, 1.2, 30.0, 1.0)
    drop = base_relief.field.z[carved_rows, col0] - rel.field.z[carved_rows, col0]
    # depth below the local pre-carve surface equals the analytic profile
    assert np.allclose(drop, p_want, atol=0.02)
    # deepest cut = the full depth, at the axis
    assert drop.max() == pytest.approx(1.2, abs=0.02)
    assert v[np.argmax(drop)] <= res + 1e-9
    # the groove spans the analytic half-width
    assert v.max() == pytest.approx(W, abs=2 * res)


def test_groove_axis_offset_moves_it(demo):
    rel0 = _groove_relief(demo)
    rel2 = _groove_relief(demo, axis_offset_mm=2.0)
    res = rel0.field.resolution
    ox, oy = rel0.field.origin
    col0 = int(round((0.0 - ox) / res))

    def deepest_y(rel):
        rows = np.flatnonzero(rel.feature_band[:, col0])
        drop = rel.surface_field.z[rows, col0]
        return oy + rows[np.argmin(drop)] * res

    assert deepest_y(rel2) - deepest_y(rel0) == pytest.approx(2.0, abs=2 * res)


def test_groove_masked_to_bridge_span(demo):
    rel = _groove_relief(demo)
    res = rel.field.resolution
    ox, _ = rel.field.origin
    rr, cc = np.nonzero(rel.feature_band)
    xs = ox + cc * res
    # the demo lenses flank the bridge at roughly |x| > 15; the endpieces live
    # beyond |x| ~ 50 — the groove must stay between the lens rims.
    assert np.abs(xs).max() < 30.0


def test_groove_generic_partition_fallback():
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
    # carved only on the span between the two lens holes
    assert np.abs(xs).max() < 13.5
    # full depth achieved on the flat plateau
    drop = 5.0 - rel.field.z[rr, cc]
    assert drop.max() == pytest.approx(1.2, abs=0.03)


def test_groove_resolution_stability(demo):
    rel_a = _groove_relief(demo, res=0.3)
    rel_b = _groove_relief(demo, res=0.15)

    def depth_at_axis(rel):
        res = rel.field.resolution
        ox, oy = rel.field.origin
        col0 = int(round((0.0 - ox) / res))
        rows = np.flatnonzero(rel.feature_band[:, col0])
        pre = rel.surface_field.z[rows, col0]  # post-carve surface
        return float(rel.field.z[rows, col0].min())

    assert abs(depth_at_axis(rel_a) - depth_at_axis(rel_b)) <= 0.06
