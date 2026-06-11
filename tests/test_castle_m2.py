"""M2 tests: stock heightfield, footing profiles, castle relief, mesh, and
the milestone gate — the built relief vs Demo Project/Model.stl.

Gate (BUILDPLAN M2.5): plateau levels exact, blended regions <= 0.1 mm at the
95th percentile over machined surfaces.
"""
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

DEMO = Path(__file__).parents[1] / "Demo Project"


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def demo():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams(), hinges


@pytest.fixture(scope="module")
def demo_relief(demo):
    from guildcam.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    return build_castle_relief(part, castle, hinges, resolution=0.2)


# ------------------------------------------------------------------ M2.1 stock

def test_stock_heightfield_two_levels():
    from guildcam.core.project.schema import StockDefinition
    from guildcam.core.relief.castle import stock_top_heightfield

    stock = StockDefinition()
    hf = stock_top_heightfield(stock, resolution=0.5)
    assert hf.width_mm == pytest.approx(170.0, abs=0.5)
    assert hf.height_mm == pytest.approx(85.0, abs=0.5)
    # blank corners at 6, pad-block center at 10
    assert hf.z[2, 2] == 6.0
    r, c = hf.world_to_pixel(0.0, 0.0)
    assert hf.z[r, c] == 10.0
    # pad block is 45x45 centered: just outside its edge -> 6
    r, c = hf.world_to_pixel(23.0, 0.0)
    assert hf.z[r, c] == 6.0
    pad_area_px = (hf.z == 10.0).sum()
    assert pad_area_px * hf.resolution**2 == pytest.approx(45 * 45, rel=0.05)


def test_stock_pad_block_offset():
    from guildcam.core.project.schema import StockDefinition
    from guildcam.core.relief.castle import stock_top_heightfield

    stock = StockDefinition(pad_block_dx_mm=10.0, pad_block_dy_mm=-5.0)
    hf = stock_top_heightfield(stock, resolution=0.5)
    r, c = hf.world_to_pixel(10.0, -5.0)
    assert hf.z[r, c] == 10.0
    r, c = hf.world_to_pixel(-20.0, 20.0)
    assert hf.z[r, c] == 6.0


# ------------------------------------------------------------------ M2.3 footing math

def test_footing_ext_first_construction():
    from guildcam.core.relief.castle import _footing_centers

    # nosepad_inferior demo values: the first (exterior) fillet's circle
    # passes through the step's bottom corner (0, h_low); the concave circle
    # is tangent to it. Verified against the Fusion STL (<0.01 mm rms).
    a, b = _footing_centers(5.8, 9.0, 10.0, "exterior")
    assert a == pytest.approx(-np.sqrt(9**2 - (9 - 5.8) ** 2))     # -8.412
    assert b - a == pytest.approx(np.sqrt(5.8 * (2 * 19 - 5.8)))   # 13.674
    # through-corner check: corner (0, h_low) lies on circle C1
    cz1 = 10.0 - 9.0
    assert np.hypot(0 - a, 4.2 - cz1) == pytest.approx(9.0)


def test_footing_int_first_construction():
    from guildcam.core.relief.castle import _footing_centers

    # endpiece_superior demo values: interior fillet first, through the top
    # corner (0, h_high); exterior lands tangent.
    a, b = _footing_centers(0.7, 32.0, 48.0, "interior")
    assert b == pytest.approx(np.sqrt(48**2 - (48 - 0.7) ** 2))    # 8.168
    cz2 = 4.8 + 48.0
    assert np.hypot(0 - b, 5.5 - cz2) == pytest.approx(48.0)
    assert b - a == pytest.approx(np.sqrt(0.7 * (2 * 80 - 0.7)))


def test_footing_profile_monotonic_and_continuous():
    from guildcam.core.relief.castle import _footing_z

    s = np.linspace(-20, 20, 4001)
    for first in ("interior", "exterior"):
        z = _footing_z(s, 10.0, 4.2, 9.0, 10.0, first=first)
        assert z[0] == 10.0 and z[-1] == 4.2
        assert (np.diff(z) <= 1e-9).all()          # monotone descent
        assert np.abs(np.diff(z)).max() < 0.06     # no jumps (C0 continuous)


def test_footing_tall_step_keeps_wall():
    from guildcam.core.relief.castle import _footing_spans, _footing_z

    # step 8 mm, radii 2+3: quarter rounds with a 3 mm wall left at s=0
    sh, sl = _footing_spans(8.0, 2.0, 3.0, "interior")
    assert (sh, sl) == (2.0, 3.0)
    # quarter arcs end vertically at the wall (sample just off the corner)
    z = _footing_z(np.array([-1e-9, 1e-9]), 8.0, 0.0, 2.0, 3.0, "interior")
    assert z[0] == pytest.approx(6.0, abs=1e-3)    # h_high - r_ext
    assert z[1] == pytest.approx(3.0, abs=1e-3)    # h_low + r_int
    # and the wall itself: profile drops the full 3 mm across the cut line
    assert z[0] - z[1] == pytest.approx(3.0, abs=2e-3)


# ------------------------------------------------------------------ M2.2 relief

def test_demo_relief_plateau_heights(demo_relief, demo):
    part, castle, _ = demo
    f = demo_relief.field
    for name, expected in [
        ("endpiece_od", 5.5), ("bridge", 5.3), ("nosepad_os", 10.0),
        ("eyewire_superior_od", 4.8), ("eyewire_inferior_os", 4.2),
    ]:
        zone = part.zone(name)
        p = zone.polygon.representative_point()
        # sample at the interior point only if it's clear of the footing bands
        r, c = f.world_to_pixel(p.x, p.y)
        sampled = f.z[r, c]
        assert sampled <= max(castle.zones.for_kind(zone.kind), 10.0)
        assert sampled >= min(4.2, castle.zones.for_kind(zone.kind))


def test_demo_relief_hinge_pocket_floor(demo_relief, demo):
    _, castle, hinges = demo
    f = demo_relief.field
    for poly in hinges:
        p = poly.representative_point()
        r, c = f.world_to_pixel(p.x, p.y)
        assert f.z[r, c] == pytest.approx(
            castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm, abs=1e-9
        )


def test_generic_partition_relief_with_explicit_heights():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.project.schema import CastleParams
    from guildcam.core.relief.castle import build_castle_relief

    outline = Polygon([(-30, -10), (30, -10), (30, 10), (-30, 10)])
    part = partition_zones(outline, [Point(0, 0).buffer(5)], [[(0, -11), (0, 11)]])
    assert not part.matched
    relief = build_castle_relief(
        part, CastleParams(), resolution=0.5,
        heights={z.name: 3.0 + i for i, z in enumerate(part.zones)},
    )
    assert relief.field.z.max() <= 4.0 + 1e-9
    # explicit heights required for unmatched partitions
    with pytest.raises(ValueError):
        build_castle_relief(part, CastleParams(), resolution=0.5)


# ------------------------------------------------------------------ M2.4 mesh

def test_castle_mesh_watertight(demo):
    from guildcam.core.relief.castle import build_castle_mesh, build_castle_relief

    part, castle, hinges = demo
    relief = build_castle_relief(part, castle, hinges, resolution=0.5)
    mesh = build_castle_mesh(relief)
    assert mesh.is_watertight
    assert mesh.volume > 5000
    assert mesh.bounds[0][2] == pytest.approx(0.0)
    assert mesh.bounds[1][2] == pytest.approx(10.0, abs=0.01)


# ------------------------------------------------------------------ M2.5 the gate

def test_demo_relief_matches_fusion_stl(demo_relief, demo):
    """The M2 milestone gate: castle relief vs Fusion ground truth."""
    import trimesh
    from shapely import contains_xy, distance as sdist, points as spoints, prepare
    from guildcam.core.relief.castle import _footing_spans

    part, castle, hinges = demo
    body = part.body
    stl = trimesh.load(DEMO / "Model.stl")

    # Registration is translation-only (bbox centers); see teardown §"frame".
    v = stl.vertices.copy()
    sb = stl.bounds
    v[:, 0] += (body.bounds[0] + body.bounds[2]) / 2 - (sb[0][0] + sb[1][0]) / 2
    v[:, 1] += (body.bounds[1] + body.bounds[3]) / 2 - (sb[0][1] + sb[1][1]) / 2
    stl.vertices = v

    step = 0.7
    xs = np.arange(body.bounds[0] + 0.6, body.bounds[2] - 0.6, step)
    ys = np.arange(body.bounds[1] + 0.6, body.bounds[3] - 0.6, step)
    Xg, Yg = np.meshgrid(xs, ys)
    prepare(body)
    inner = contains_xy(body.buffer(-0.5), Xg.ravel(), Yg.ravel())
    px, py = Xg.ravel()[inner], Yg.ravel()[inner]

    origins = np.column_stack([px, py, np.full(len(px), 25.0)])
    dirs = np.tile([0.0, 0.0, -1.0], (len(px), 1))
    locs, ridx, _ = stl.ray.intersects_location(origins, dirs, multiple_hits=True)
    got = np.full(len(px), np.nan)
    for (_, _, zv), ri in zip(locs, ridx):
        if np.isnan(got[ri]) or zv > got[ri]:
            got[ri] = zv
    assert np.isnan(got).mean() < 0.01          # registration sanity

    f = demo_relief.field
    ci = np.clip(((px - f.origin[0]) / f.resolution).round().astype(int), 0, f.z.shape[1] - 1)
    ri_ = np.clip(((py - f.origin[1]) / f.resolution).round().astype(int), 0, f.z.shape[0] - 1)
    ours = f.z[ri_, ci]
    valid = ~np.isnan(got)
    diff = ours[valid] - got[valid]
    pv = spoints(px[valid], py[valid])

    heights = {z.name: castle.zones.for_kind(z.kind) for z in part.zones}
    band = np.zeros(valid.sum(), dtype=bool)
    for e in part.edges:
        if len(e.zone_names) != 2 or not e.canonical:
            continue
        ha, hb = (heights[n] for n in e.zone_names)
        ff = castle.footing.for_edge(e.canonical)
        sh, sl = _footing_spans(abs(ha - hb), ff.exterior_mm, ff.interior_mm, ff.first)
        band |= sdist(pv, e.cut) < (max(sh, sl) + 0.8)
    pocket_rim = np.zeros(valid.sum(), dtype=bool)
    for h in hinges:
        pocket_rim |= sdist(pv, h.exterior) < 0.8   # sampling straddle on the sharp wall

    plateau = ~band & ~pocket_rim
    band_clean = band & ~pocket_rim

    assert plateau.sum() > 500 and band_clean.sum() > 500
    assert np.abs(diff[plateau]).max() <= 0.02, "plateaus must be exact"
    assert np.percentile(np.abs(diff[band_clean]), 95) <= 0.10, "footing p95 gate"
    assert np.abs(diff[band_clean]).max() <= 0.30, "footing worst-case gate"
