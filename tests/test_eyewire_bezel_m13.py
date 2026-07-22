"""M13.2 tests: the bezeled eyewire — a constant-width chamfer band around
each lens opening's posterior rim.

Gates: schema round-trip (default OFF), toggle-off bit-identical, band width
respected, rim depth = width*tan(angle) below the pre-carve surface, both
lenses carved, anterior clamp floors the cut, and overlapping splay+bezel
compose as the elementwise min of the single-feature carves.
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


def _relief(demo, res=0.2, splay=False, bezel=False, **bezel_overrides):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    castle = CastleParams()
    castle.pad_splay.enabled = splay
    castle.eyewire_bezel.enabled = bezel
    for k, v in bezel_overrides.items():
        setattr(castle.eyewire_bezel, k, v)
    return build_castle_relief(part, castle, hinges, resolution=res)


# ------------------------------------------------------------------ schema

def test_bezel_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    proj = ProjectSchema(job_name="Bezel RT")
    proj.castle.eyewire_bezel.enabled = True
    proj.castle.eyewire_bezel.width_mm = 1.8
    proj.castle.eyewire_bezel.angle_deg = 22.0
    path = tmp_path / "bezel.guildmodel"
    save_project(proj, path)
    back = load_project(path)
    assert back.castle.eyewire_bezel.enabled is True
    assert back.castle.eyewire_bezel.width_mm == 1.8
    assert back.castle.eyewire_bezel.angle_deg == 22.0
    assert back.castle.eyewire_bezel.anterior_clamp_mm == 1.5
    assert back.castle.pad_splay.enabled is False


def test_bezel_off_is_bit_identical(demo, base_relief):
    again = _relief(demo, bezel=False)
    assert np.array_equal(base_relief.field.z, again.field.z)
    assert again.feature_band is None


# ------------------------------------------------------------------ geometry

def _lens_rings(relief):
    from shapely.geometry import LineString
    return [LineString(i) for i in relief.partition.body.interiors]


def test_bezel_band_width_and_rim_depth(demo, base_relief):
    from shapely import distance, points

    rel = _relief(demo, bezel=True)          # width 2.5, angle 30
    assert rel.feature_band is not None
    assert rel.feature_max_slope_deg == 30.0

    res = rel.field.resolution
    ox, oy = rel.field.origin
    rr, cc = np.nonzero(rel.feature_band)
    pts = points(ox + cc * res, oy + rr * res)
    rings = _lens_rings(rel)
    d = np.min(np.column_stack([distance(pts, ring) for ring in rings]), axis=1)
    # Every carved cell is within the band width of a lens rim.
    assert d.max() <= 2.5 + 1e-6
    # Both lenses got a band (carved cells on both sides of the frame).
    xs = ox + cc * res
    assert (xs < -5).any() and (xs > 5).any()

    # Rim depth: near the rim the carve below the pre-carve surface is close
    # to width*tan(angle); at the band's inner edge it tends to zero.
    drop = base_relief.field.z[rr, cc] - rel.field.z[rr, cc]
    near_rim = d < 2 * res
    inner = d > 2.5 - 2 * res
    want = 2.5 * np.tan(np.radians(30.0))
    assert np.median(drop[near_rim]) == pytest.approx(want, abs=0.2)
    assert np.median(drop[inner]) <= 0.15


def test_bezel_anterior_clamp_floor(demo):
    rel = _relief(demo, bezel=True, width_mm=6.0, angle_deg=55.0,
                  anterior_clamp_mm=2.0)
    zmin = float(rel.field.z[rel.feature_band].min())
    # 6 mm at 55 deg wants ~8.6 mm below a 4.2 wall — the clamp floors it.
    assert zmin == pytest.approx(2.0, abs=1e-9)


def test_splay_and_bezel_compose_as_min(demo):
    both = _relief(demo, splay=True, bezel=True)
    only_splay = _relief(demo, splay=True)
    only_bezel = _relief(demo, bezel=True)
    combined = np.minimum(only_splay.field.z, only_bezel.field.z)
    assert np.allclose(both.field.z, combined, atol=1e-9)
    # and the band is the union of the two
    union = only_splay.feature_band | only_bezel.feature_band
    assert np.array_equal(both.feature_band, union)
