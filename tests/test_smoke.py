"""Smoke tests — verify core modules import and basic types are constructable.

These tests run headless (no GUI, no hardware). They prove the scaffold is
wired correctly and all pure-Python logic is reachable before any deps are
exercised.
"""
import numpy as np
import pytest


def test_heightfield_construction():
    from guildmodel.core.relief.heightfield import Heightfield

    hf = Heightfield.flat(width_mm=60.0, height_mm=40.0, z_value=6.0, resolution=0.5)
    assert hf.z.shape == (80, 120)
    assert np.allclose(hf.z, 6.0)
    assert hf.width_mm == pytest.approx(60.0)
    assert hf.height_mm == pytest.approx(40.0)


def test_heightfield_coordinate_roundtrip():
    from guildmodel.core.relief.heightfield import Heightfield

    hf = Heightfield.flat(width_mm=50.0, height_mm=30.0, z_value=0.0, resolution=0.1, origin=(5.0, 10.0))
    row, col = hf.world_to_pixel(10.0, 15.0)
    x, y = hf.pixel_to_world(row, col)
    assert x == pytest.approx(10.0, abs=0.1)
    assert y == pytest.approx(15.0, abs=0.1)


def test_boxing_dimensions_defaults():
    from guildmodel.core.geometry.boxing import BoxingDimensions

    bd = BoxingDimensions()
    assert bd.a == 50.0
    assert bd.b == 38.0
    assert bd.dbl == 18.0
    assert bd.derived_frame_width() == pytest.approx(50.0 * 2 + 18.0)


def test_boxing_dimensions_override():
    from guildmodel.core.geometry.boxing import BoxingDimensions

    bd = BoxingDimensions(a=52.0, b=40.0, dbl=20.0, frame_width=130.0)
    assert bd.derived_frame_width() == pytest.approx(130.0)


def test_project_schema_defaults():
    from guildmodel.core.project.schema import ProjectSchema

    schema = ProjectSchema(job_name="Test Frame")
    assert schema.job_name == "Test Frame"
    assert schema.boxing.a == 50.0
    assert schema.cam.two_file_output is True


def test_project_schema_roundtrip(tmp_path):
    from guildmodel.core.project.schema import ProjectSchema
    from guildmodel.core.project.save_load import save_project, load_project

    schema = ProjectSchema(job_name="Roundtrip Test", stock_thickness_mm=7.5)
    path = tmp_path / "test.guildmodel"
    save_project(schema, path)
    loaded = load_project(path)
    assert loaded.job_name == "Roundtrip Test"
    assert loaded.stock_thickness_mm == pytest.approx(7.5)


def test_grbl_post_emits_header():
    from guildmodel.core.post.grbl import GRBLPost

    post = GRBLPost(
        job_name="SmokeTest",
        material="acetate",
        tool_diameter_mm=3.0,
        spindle_rpm=18000,
        feed_rate_mmpm=800,
        plunge_rate_mmpm=200,
    )
    post.header(side="back")
    post.spindle_on()
    post.end_program()
    gcode = post.to_string()
    assert "GuildModel" in gcode
    assert "G90" in gcode
    assert "G21" in gcode
    assert "M3" in gcode
    assert "M30" in gcode


def test_validate_missing_outline():
    from guildmodel.core.io_import.validate import validate

    result = validate({})
    assert not result.ok
    assert any("OUTLINE" in e for e in result.errors)


def test_validate_ok(tmp_path):
    from shapely.geometry import Polygon
    from guildmodel.core.io_import.validate import validate

    outline = Polygon([(0, 0), (60, 0), (60, 40), (0, 40)])
    lens_od = Polygon([(5, 5), (30, 5), (30, 35), (5, 35)])
    lens_os = Polygon([(32, 5), (57, 5), (57, 35), (32, 35)])
    result = validate({"OUTLINE": [outline], "LENS": [lens_od, lens_os]})
    assert result.ok
    assert result.errors == []


# ── New tests (Session 3) ──────────────────────────────────────────────────────

def test_tabs_single_tab_raises_z():
    """insert_tabs must produce at least one waypoint above z_cut."""
    from guildmodel.core.cam.tabs import insert_tabs

    # Square path: 4 × 20 mm sides = 80 mm perimeter
    pts = [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]
    result = insert_tabs(pts, tab_count=1, tab_width_mm=4.0, tab_height_mm=1.5, z_cut=-3.0)
    zs = [z for _, _, z in result]
    assert max(zs) == pytest.approx(-1.5), "tab top must be z_cut + tab_height"
    assert min(zs) == pytest.approx(-3.0)
    # At least one waypoint inside the tab and one outside
    assert any(z > -3.0 + 1e-9 for z in zs)
    assert any(z < -3.0 + 1e-9 for z in zs)


def test_tabs_width_maintained():
    """Tab should span at least tab_width_mm of travel at raised height."""
    from guildmodel.core.cam.tabs import insert_tabs
    import math

    pts = [(0, 0), (100, 0)]  # straight 100 mm line
    result = insert_tabs(pts, tab_count=1, tab_width_mm=5.0, tab_height_mm=1.0, z_cut=-2.0)

    # Find entry and exit x positions (points at raised z)
    raised = [(x, y, z) for x, y, z in result if z > -2.0 + 1e-9]
    assert len(raised) >= 2, "need at least entry and exit waypoints above z_cut"

    x_start = min(x for x, _, _ in raised)
    x_end = max(x for x, _, _ in raised)
    span = math.sqrt((x_end - x_start) ** 2)
    assert span == pytest.approx(5.0, abs=0.01), "tab span must match tab_width_mm"


def test_tabs_no_tabs_passthrough():
    """tab_count=0 must return the path unchanged at z_cut."""
    from guildmodel.core.cam.tabs import insert_tabs

    pts = [(0, 0), (10, 0), (10, 10)]
    result = insert_tabs(pts, tab_count=0, tab_width_mm=3.0, tab_height_mm=1.0, z_cut=-2.0)
    assert all(z == pytest.approx(-2.0) for _, _, z in result)
    assert len(result) == len(pts)


def test_measure_from_polygon():
    """measure_from_polygon must recover A, B, DBL from synthetic rectangular lenses."""
    from shapely.geometry import Polygon
    from guildmodel.core.geometry.boxing import measure_from_polygon

    # Two 25 × 30 mm lenses separated by 15 mm (DBL) centred symmetrically
    # Left lens: x ∈ [0, 25],  y ∈ [0, 30]
    # Right lens: x ∈ [40, 65], y ∈ [0, 30]
    left  = Polygon([(0, 0), (25, 0), (25, 30), (0, 30)])
    right = Polygon([(40, 0), (65, 0), (65, 30), (40, 30)])
    bd = measure_from_polygon(left, right)

    assert bd.a == pytest.approx(25.0, abs=0.1)
    assert bd.b == pytest.approx(30.0, abs=0.1)
    assert bd.dbl == pytest.approx(15.0, abs=0.1)
    # ED of a 25×30 rectangle: 2 × distance from centre to corner = 2 × sqrt(12.5²+15²) ≈ 39.1
    import math
    expected_ed = 2.0 * math.sqrt(12.5 ** 2 + 15.0 ** 2)
    assert bd.ed == pytest.approx(expected_ed, abs=0.5)


def test_hinge_catalog_loads():
    """load_hinge_catalog must parse the bundled standard.yaml without error."""
    from pathlib import Path
    from guildmodel.core.relief.hinge import load_hinge_catalog

    catalog_path = (
        Path(__file__).parent.parent
        / "src" / "guildmodel" / "config" / "hinges" / "standard.yaml"
    )
    catalog = load_hinge_catalog(catalog_path)
    assert "screw_barrel_14x5p5" in catalog
    spec = catalog["screw_barrel_14x5p5"]
    assert spec.footprint_w_mm == pytest.approx(14.0)
    assert spec.footprint_h_mm == pytest.approx(5.5)
    assert spec.pocket_depth_mm == pytest.approx(1.2)
    assert not spec.has_ramp()


def test_hinge_pocket_polygon_shape():
    """hinge_pocket_polygon must return a rotated rectangle of the correct area."""
    from guildmodel.core.relief.hinge import (
        HingePlacement, HingeSpec, hinge_pocket_polygon
    )

    spec = HingeSpec(name="test", footprint_w_mm=14.0, footprint_h_mm=5.5, pocket_depth_mm=1.2)
    placement = HingePlacement(x=10.0, y=5.0, rotation_deg=30.0)
    poly = hinge_pocket_polygon(placement, spec)

    expected_area = 14.0 * 5.5
    assert poly.area == pytest.approx(expected_area, rel=1e-4)
    # Centroid must be at placement point
    assert poly.centroid.x == pytest.approx(10.0, abs=1e-6)
    assert poly.centroid.y == pytest.approx(5.0, abs=1e-6)


def test_integration_bevel_to_gcode(tmp_path):
    """Synthetic lens outline → bevel_flank → GRBLPost → .nc file.

    Verifies the full toolpath pipeline from geometry to emitted G-code.
    The output must contain G1 feed moves and end with M30.
    """
    import math
    from shapely.geometry import Polygon
    from guildmodel.core.relief.groove import bevel_flank
    from guildmodel.core.post.grbl import GRBLPost

    # Synthetic rounded-ish lens: regular 32-gon approximating a 25 × 20 mm ellipse
    n = 32
    lens_pts = [
        (25.0 * math.cos(2 * math.pi * i / n),
         20.0 * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    lens_poly = Polygon(lens_pts)

    toolpath = bevel_flank(
        lens_poly,
        tool_dia_mm=3.0,
        n=100,        # smaller n for fast test
        side="inner",
        z_a=0.0,
        z_b=-2.0,
        flank_offset_mm=3.0,
    )
    assert len(toolpath) > 0, "bevel_flank must return points"

    post = GRBLPost(
        job_name="SmokeIntegration",
        material="acetate",
        tool_diameter_mm=3.0,
        spindle_rpm=18000,
        feed_rate_mmpm=800,
        plunge_rate_mmpm=200,
    )
    post.header(side="back")
    post.spindle_on()
    post.emit_polyline(toolpath)
    post.end_program()

    nc_path = tmp_path / "smoke.nc"
    post.write(nc_path)

    gcode = nc_path.read_text(encoding="utf-8")
    assert "G1" in gcode,  "must contain at least one G1 feed move"
    assert "M30" in gcode, "must end with M30 program end"
    assert "M3" in gcode,  "must start spindle with M3"
