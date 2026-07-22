"""M13.1 tests: the pad-splay chamfer under the bridge.

Gates: schema round-trip (default OFF), toggle-off leaves the relief
bit-identical (so the M2 STL / M3-M4 NC gates hold by construction), the
carved cross-section matches the splay inputs (angle at the crest offset,
toric blend, anterior clamp, end feather), and the teaching stages show the
feature from the footing stage onward.
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


def _splay_relief(demo, res=0.2, **overrides):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    castle = CastleParams()
    castle.pad_splay.enabled = True
    for k, v in overrides.items():
        setattr(castle.pad_splay, k, v)
    return build_castle_relief(part, castle, hinges, resolution=res)


def _bottom_column_profile(relief, x=0.0):
    """(ys, zs) walking up the inside cells of the column nearest world x."""
    res = relief.field.resolution
    ox, oy = relief.field.origin
    col = int(round((x - ox) / res))
    rows = np.flatnonzero(relief.inside[:, col])
    return (oy + rows * res, relief.field.z[rows, col], rows, col)


# ------------------------------------------------------------------ schema

def test_splay_schema_defaults_off():
    from guildmodel.core.project.schema import CastleParams

    c = CastleParams()
    assert c.pad_splay.enabled is False
    assert c.eyewire_bezel.enabled is False
    assert c.bridge_relief.enabled is False
    assert c.pad_splay.run_mm == 18.0
    assert c.pad_splay.crest_deviation_center_mm == 6.0
    assert c.pad_splay.angle_center_deg == 30.0
    assert c.pad_splay.anterior_clamp_mm == 1.5


def test_splay_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    proj = ProjectSchema(job_name="Splay RT")
    proj.castle.pad_splay.enabled = True
    proj.castle.pad_splay.toric = True
    proj.castle.pad_splay.angle_middle_deg = 24.0
    proj.castle.pad_splay.crest_deviation_end_mm = 0.5
    path = tmp_path / "splay.guildmodel"
    save_project(proj, path)
    back = load_project(path)
    assert back.castle.pad_splay.enabled is True
    assert back.castle.pad_splay.toric is True
    assert back.castle.pad_splay.angle_middle_deg == 24.0
    assert back.castle.pad_splay.crest_deviation_end_mm == 0.5
    # untouched fields keep defaults; siblings stay off
    assert back.castle.pad_splay.angle_center_deg == 30.0
    assert back.castle.eyewire_bezel.enabled is False


# ------------------------------------------------------ off = bit-identical

def test_splay_off_is_bit_identical(demo, base_relief):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    part, _, hinges = demo
    castle = CastleParams()          # every feature explicitly at defaults
    again = build_castle_relief(part, castle, hinges, resolution=0.2)
    assert np.array_equal(base_relief.field.z, again.field.z)
    assert np.array_equal(base_relief.surface_field.z, again.surface_field.z)
    assert base_relief.feature_band is None
    assert base_relief.feature_max_slope_deg == 0.0


# ------------------------------------------------------------------ geometry

def test_splay_cross_section_slope_and_crest(demo, base_relief):
    rel = _splay_relief(demo)        # 30 deg, crest 6 mm, run 18, clamp 1.5
    assert rel.feature_band is not None
    assert rel.feature_max_slope_deg == 30.0

    ys, zs, rows, col = _bottom_column_profile(rel)
    zb = base_relief.field.z[rows, col]
    carved = np.flatnonzero((zb - zs) > 1e-9)
    assert carved.size > 10
    # Carve starts at the bottom rim and spans ~the crest deviation inward
    # (plus the crest round-over's small lead-in past the crest).
    assert carved[0] == 0
    span_mm = carved.size * rel.field.resolution
    assert span_mm == pytest.approx(6.3, abs=4 * rel.field.resolution)
    # Mid-ramp slope matches the splay angle.
    ramp = zs[carved]
    dz = np.diff(ramp)
    mid = dz[len(dz) // 4: max(len(dz) // 4 + 1, 3 * len(dz) // 4)]
    slope_deg = np.degrees(np.arctan(np.mean(mid) / rel.field.resolution))
    assert slope_deg == pytest.approx(30.0, abs=2.0)
    # The chamfer toe lands at crest height - 6*tan(30) above the clamp.
    toe = 5.3 - 6.0 * np.tan(np.radians(30.0))
    assert zs[carved[0]] == pytest.approx(toe, abs=0.15)


def test_splay_crest_is_tangent_not_ridged(demo, base_relief):
    """The M13 fixes gate: the chamfer meets the surface through a convex
    round-over — the last cells before the crest approach slope zero instead
    of breaking at the full splay angle (the 'sharp ridge' complaint)."""
    res = 0.2

    def top_slope_deg(rel):
        ys, zs, rows, col = _bottom_column_profile(rel)
        zb = base_relief.field.z[rows, col]
        carved = np.flatnonzero((zb - zs) > 1e-9)
        top = zs[carved[-3:]]                 # the cells nearest the crest
        return np.degrees(np.arctan(np.diff(top).mean() / res))

    blended = _splay_relief(demo)             # crest_blend default 2.0
    sharp = _splay_relief(demo, crest_blend_mm=0.0)
    assert top_slope_deg(blended) < 12.0      # rolls off tangentially
    assert top_slope_deg(sharp) > 25.0        # the old hard crease


def test_default_splay_run_from_nosepad_line(demo):
    from guildmodel.core.relief.features import default_splay_run_mm
    from shapely.geometry import Point, Polygon
    from guildmodel.core.geometry.regions import partition_zones

    part, _, _ = demo
    run = default_splay_run_mm(part)
    # bottom-center to past the lower nosepad SCULPT line, +5 mm
    assert run is not None and 10.0 < run < 60.0
    assert run - default_splay_run_mm(part, extra_mm=0.0) == pytest.approx(5.0)

    # no nosepad edges (generic partition) -> None, caller keeps its default
    outline = Polygon([(-50, -20), (50, -20), (50, 20), (-50, 20)])
    generic = partition_zones(outline, [Point(0, 0).buffer(10)], [])
    assert default_splay_run_mm(generic) is None


def test_splay_toric_angles_blend(demo, base_relief):
    rel = _splay_relief(demo, toric=True, angle_center_deg=20.0,
                        angle_middle_deg=30.0, angle_end_deg=40.0)
    assert rel.feature_max_slope_deg == 40.0
    ys, zs, rows, col = _bottom_column_profile(rel)
    zb = base_relief.field.z[rows, col]
    carved = np.flatnonzero((zb - zs) > 1e-9)
    ramp = zs[carved]
    dz = np.diff(ramp)
    mid = dz[len(dz) // 4: 3 * len(dz) // 4]
    slope_deg = np.degrees(np.arctan(np.mean(mid) / rel.field.resolution))
    # At the bottom-center column the toric blend is at its center angle.
    assert slope_deg == pytest.approx(20.0, abs=2.0)
    # A steeper center angle than the constant-20 case appears off-center:
    # the deepest carve grows toward the run ends under 40 deg ends.
    flat = _splay_relief(demo, toric=False, angle_center_deg=20.0)
    deeper = (flat.field.z - rel.field.z) > 0.05
    assert deeper.any()


def test_splay_anterior_clamp_floor(demo):
    rel = _splay_relief(demo, angle_center_deg=55.0, anterior_clamp_mm=2.0)
    band = rel.feature_band
    assert band is not None
    zmin = float(rel.field.z[band].min())
    # 6 mm crest at 55 deg wants to cut to 5.3-8.6 < 0 — the clamp floors it.
    assert zmin == pytest.approx(2.0, abs=1e-9)


def test_splay_feather_and_run_guard(demo):
    # A huge run must clamp (not wrap the ring) and still build.
    rel = _splay_relief(demo, run_mm=500.0)
    assert rel.feature_band is not None
    # The run bounds the band: every carved cell lies within run + crest of the
    # nose-arch anchor (Euclidean <= arc distance), and a shorter run carves a
    # strictly smaller band.
    rel18 = _splay_relief(demo)
    rel9 = _splay_relief(demo, run_mm=9.0)
    assert rel9.feature_band.sum() < rel18.feature_band.sum()

    res = rel18.field.resolution
    ox, oy = rel18.field.origin
    rr, cc = np.nonzero(rel18.feature_band)
    xs, ys = ox + cc * res, oy + rr * res
    # anchor = the lowest carved cell on the centerline column (the arch apex)
    col0 = int(round((0.0 - ox) / res))
    r0 = np.flatnonzero(rel18.feature_band[:, col0]).min()
    ax, ay = 0.0, oy + r0 * res
    dist = np.hypot(xs - ax, ys - ay)
    assert dist.max() <= 18.0 + 6.0 + 2.0     # run + crest + blend lead-in


def test_splay_crest_tables_are_smooth_on_narrow_rims():
    """Field regression (2026-07-02, 'jagged points where the cut terminates'):
    on a frame whose lens rims run close to the bottom edge, the per-sample rim
    clamp + in-body bisection notched the crest offsets, and anchor heights
    bilinear-sampled beside the boundary blended in outside-body zeros —
    multi-mm teeth along the chamfer's termination. The tables must now be
    slope-limited and sampled from the nearest-inside surface."""
    from shapely import contains_xy, prepare
    from shapely.geometry import Point, Polygon
    from guildmodel.core.project.schema import PadSplayParams
    from guildmodel.core.relief.features import (
        _CREST_MAX_SLOPE, _splay_crest_tables,
    )

    outline = Polygon([(-50, -20), (50, -20), (50, 20), (-50, 20)]).buffer(4.0)
    lenses = [Point(-24, 0).buffer(17), Point(24, 0).buffer(17)]
    body = outline
    for hole in lenses:
        body = body.difference(hole)

    res = 0.3
    minx, miny, maxx, maxy = body.bounds
    xs = np.arange(minx - 1, maxx + 1, res)
    ys = np.arange(miny - 1, maxy + 1, res)
    X, Y = np.meshgrid(xs, ys)
    prepare(body)
    inside = contains_xy(body, X.ravel(), Y.ravel()).reshape(X.shape)
    z_pre = np.where(inside, 5.0, 0.0)

    p = PadSplayParams(enabled=True, run_mm=30.0,
                       crest_deviation_center_mm=4.0,
                       crest_deviation_end_mm=2.0)
    tables = _splay_crest_tables(body, z_pre, inside, xs[0], ys[0], res, p)
    assert tables is not None
    run, u_tab, p0, crest, c_tab, h_tab, tan_tab, w_tab = tables
    step = u_tab[1] - u_tab[0]
    # crest offsets: no per-sample teeth (the rim clamp varies along the run)
    assert (c_tab > 0.5).any()                 # the clamp actually engaged
    assert np.abs(np.diff(c_tab)).max() <= _CREST_MAX_SLOPE * step + 1e-9
    # anchor heights: the plateau is 5.0 everywhere INSIDE — any dip means
    # outside-body zeros leaked into the sampling (the old crater bug)
    assert h_tab.min() > 4.8 and h_tab.max() < 5.2


def test_splay_crest_tables_smooth_on_demo_steep_toric(demo, base_relief):
    """The user's steep settings (toric 60/60/15, crest 3->1) on real footed
    terrain: crest offsets and anchor heights stay continuous — the ridge line
    where the cut terminates must be clean."""
    from guildmodel.core.project.schema import PadSplayParams
    from guildmodel.core.relief.features import (
        _CREST_MAX_SLOPE, _splay_crest_tables,
    )

    part, _, _ = demo
    f = base_relief.surface_field
    p = PadSplayParams(enabled=True, run_mm=29.4,
                       crest_deviation_center_mm=3.0,
                       crest_deviation_end_mm=1.0, toric=True,
                       angle_center_deg=60.0, angle_middle_deg=60.0,
                       angle_end_deg=15.0)
    tables = _splay_crest_tables(part.body, f.z, base_relief.inside,
                                 f.origin[0], f.origin[1], f.resolution, p)
    assert tables is not None
    run, u_tab, p0, crest, c_tab, h_tab, tan_tab, w_tab = tables
    step = u_tab[1] - u_tab[0]
    assert np.abs(np.diff(c_tab)).max() <= _CREST_MAX_SLOPE * step + 1e-9
    assert np.abs(np.diff(h_tab)).max() <= 0.35   # no crater teeth in the anchors


def test_splay_stage_gating(demo):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_stage

    part, _, hinges = demo
    castle = CastleParams()
    castle.pad_splay.enabled = True
    walls = build_castle_stage(part, castle, hinges, stage="walls", resolution=0.3)
    footing = build_castle_stage(part, castle, hinges, stage="footing", resolution=0.3)
    assert walls.feature_band is None          # features wait for the footing
    assert footing.feature_band is not None    # then appear with it
