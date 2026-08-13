"""Decorative OUTLINE openings — holes drawn inside the frame profile.

Any closed OUTLINE curve inside the outermost one is an opening (an aviator's
bridge keyhole, a cut-out temple, perforated "swiss cheese" designs). It becomes
an interior ring of the outline polygon, so the relief mask, the mesh rim, and
the inside-contour CAM all pick it up — but unlike a LENS aperture it takes no
bevel groove and seeds no work-holding keep-out.

Ground truth is the aviator fixture (bridge opening ≈ 98 mm²) — the GuildDraw
workspace SVGs vendored under tests/fixtures/aviator, zipped into a .gdraw here.
"""
import zipfile
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Point, Polygon, box

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
AVIATOR_DIR = FIXTURES / "aviator"
TOOLS = yaml.safe_load((ROOT / "src" / "guildmodel" / "config"
                        / "tools.yaml").read_text())
BRIDGE_OPENING_MM2 = 97.9


@pytest.fixture(scope="module")
def aviator_gdraw(tmp_path_factory) -> Path:
    """Repack the unzipped demo contents into a .gdraw the reader can open."""
    path = tmp_path_factory.mktemp("gdraw") / "aviator.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(AVIATOR_DIR.iterdir()):
            zf.write(f, f.name)
    return path


@pytest.fixture(scope="module")
def aviator_front(aviator_gdraw):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    workspaces, _ = build_workspaces_from_gdraw(aviator_gdraw)
    return workspaces[0]


def _square(cx, cy, half):
    return [(cx - half, cy - half), (cx + half, cy - half),
            (cx + half, cy + half), (cx - half, cy + half)]


# ---------------------------------------------------------------- assemble_outline

def test_largest_curve_is_the_profile_and_inner_curves_are_holes():
    from guildmodel.core.io_import.normalize import assemble_outline

    a = assemble_outline([_square(0, 0, 50), _square(0, 0, 5)])

    assert len(a.holes) == 1
    assert not a.stray
    assert len(a.polygon.interiors) == 1
    # The profile's area is the shell minus the opening.
    assert a.polygon.area == pytest.approx(100 * 100 - 10 * 10)


def test_curves_outside_the_profile_are_stray_not_holes():
    from guildmodel.core.io_import.normalize import assemble_outline

    a = assemble_outline([_square(0, 0, 50), _square(200, 0, 5)])

    assert not a.holes
    assert len(a.stray) == 1
    assert not a.polygon.interiors


def test_holes_are_named_and_ordered_top_to_bottom_then_left_to_right():
    from guildmodel.core.io_import.normalize import assemble_outline

    # Deliberately out of order: bottom, top-right, top-left.
    a = assemble_outline([
        _square(0, 0, 50), _square(0, -20, 3), _square(20, 20, 3), _square(-20, 20, 3),
    ])

    assert a.hole_labels == ["Hole1", "Hole2", "Hole3"]
    centers = [(round(h.centroid.x), round(h.centroid.y)) for h in a.holes]
    assert centers == [(-20, 20), (20, 20), (0, -20)]


def test_a_single_outline_curve_is_unchanged():
    from guildmodel.core.io_import.normalize import assemble_outline, points_to_polygon

    curve = _square(0, 0, 50)
    a = assemble_outline([curve])

    assert not a.holes and not a.stray
    assert a.polygon.equals(points_to_polygon(curve))


# ---------------------------------------------------------------- import → workspace

def test_aviator_bridge_opening_survives_import(aviator_front):
    assert len(aviator_front.outline_holes) == 1
    assert aviator_front.outline_holes[0].area == pytest.approx(BRIDGE_OPENING_MM2, abs=0.5)
    assert not aviator_front.outline_stray
    assert len(aviator_front.outline_poly.interiors) == 1


def test_partition_tells_the_bridge_opening_from_the_lens_apertures(aviator_front):
    partition = aviator_front.partition

    assert len(partition.holes) == 1
    # The body carries three interior rings: two lenses + the bridge opening.
    flags = [partition.is_hole(r) for r in partition.body.interiors]
    assert sorted(flags) == [False, False, True]


def test_no_zone_is_placed_inside_the_opening(aviator_front):
    inside = aviator_front.outline_holes[0].representative_point()

    assert not any(z.polygon.contains(inside) for z in aviator_front.partition.zones)


# ---------------------------------------------------------------- CAM

@pytest.fixture(scope="module")
def aviator_program(aviator_front):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    castle = CastleParams()
    # The aviator's fused brow bar is not the standard 9-zone layout, so heights
    # are supplied explicitly (the labeler is a separate concern from holes).
    heights = {z.name: 4.8 for z in aviator_front.partition.zones}
    relief = build_castle_relief(
        aviator_front.partition, castle, aviator_front.hinge_polys,
        resolution=0.8, heights=heights)
    ops = generate_castle_program(
        relief, castle, aviator_front.hinge_polys,
        {"type": "flat", "radius_mm": 1.5875, "diameter_mm": 3.175})
    return relief, ops


def test_the_opening_gets_its_own_cut_op(aviator_front, aviator_program):
    _relief, ops = aviator_program
    hole = aviator_front.outline_holes[0]

    holes_op = next(op for op in ops if op.name == "Holes")
    assert holes_op.paths
    for path in holes_op.paths:
        for x, y, _z in path:
            assert hole.buffer(0.5).contains(Point(x, y))


def test_the_eyewire_op_stays_on_the_lenses(aviator_front, aviator_program):
    _relief, ops = aviator_program
    hole = aviator_front.outline_holes[0].buffer(0.5)

    eyewires = next(op for op in ops if op.name == "Eyewires")
    assert not any(hole.contains(Point(x, y))
                   for path in eyewires.paths for x, y, _z in path)


def test_holes_share_the_eyewire_tool_so_they_add_no_tool_change(aviator_program):
    _relief, ops = aviator_program

    by_name = {op.name: op for op in ops}
    assert by_name["Holes"].tool == by_name["Eyewires"].tool


def test_the_opening_is_cut_through_the_full_depth(aviator_program):
    _relief, ops = aviator_program

    by_name = {op.name: op for op in ops}
    hole_zs = {round(z, 4) for path in by_name["Holes"].paths for _x, _y, z in path}
    eye_zs = {round(z, 4) for path in by_name["Eyewires"].paths for _x, _y, z in path}
    assert hole_zs == eye_zs      # same depth stack as an eyewire through-cut


def test_the_holes_op_is_a_ramped_contour_everywhere_it_is_posted():
    """A hole is an inside through-cut like an eyewire, so every contour-op set
    that feeds write_castle_program must include "Holes" — otherwise it posts as
    a full-depth straight plunge. This is a three-places-must-agree invariant
    (the frame default, the nest/bed frame set, and the temple set)."""
    import inspect

    from guildmodel.core.cam import castle_ops
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.cam.temple_ops import TEMPLE_CONTOUR_OPS

    assert "Holes" in CASTLE_CONTOUR_OPS
    assert "Holes" in TEMPLE_CONTOUR_OPS
    # The default set baked into write_castle_program (frame worker relies on it).
    src = inspect.getsource(castle_ops.write_castle_program)
    assert '"Holes"' in src.split("contour_op_names if")[1].split("\n")[0]


def test_a_posted_frame_with_a_hole_lints_clean():
    """End-to-end: the aviator posts a valid program that contains the Holes op
    and passes the machine lint."""
    import yaml

    from guildmodel.core.cam.castle_ops import (
        build_tool_settings, generate_castle_program, write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.post.machine import lint_program
    from guildmodel.core.project.schema import (
        CastleCamParams, CastleParams, MachineProfile)
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    tools = yaml.safe_load(
        (ROOT / "src" / "guildmodel" / "config" / "tools.yaml").read_text())
    import zipfile
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "aviator.gdraw"
    with zipfile.ZipFile(tmp, "w") as zf:
        for f in sorted(AVIATOR_DIR.iterdir()):
            zf.write(f, f.name)
    front = build_workspaces_from_gdraw(tmp)[0][0]

    relief = build_castle_relief(front.partition, CastleParams(), front.hinge_polys,
                                 resolution=0.8)
    ops = generate_castle_program(relief, CastleParams(), front.hinge_polys,
                                  tools["flat_3175"], params=CastleCamParams(),
                                  tools_cfg=tools)
    post = GRBLPost(job_name="aviator", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=18000, feed_rate_mmpm=1200, plunge_rate_mmpm=400)
    settings, _ = build_tool_settings(
        ops, tools, default_feed=1200, default_plunge=400, default_spindle=18000,
        machine=MachineProfile())
    write_castle_program(ops, post, tool_settings=settings)
    text = post.to_string()

    assert "Holes" in text
    assert lint_program(text, MachineProfile()) == []


def test_the_opening_seeds_no_work_holding_keepout(aviator_front, aviator_program):
    from guildmodel.core.cam.castle_ops import work_holding_keepouts
    from guildmodel.core.project.schema import CastleParams

    relief, _ops = aviator_program
    partition = aviator_front.partition
    hole_center = aviator_front.outline_holes[0].centroid

    keepouts = work_holding_keepouts(
        partition.body, CastleParams().stock, 1.5875, is_hole=partition.is_hole)

    # Four blank corners + the two lens centers — nothing at the bridge opening.
    assert len(keepouts) == 6
    assert not any(Point(cx, cy).distance(hole_center) < 1.0 for cx, cy, _r in keepouts)


# ---------------------------------------------------------------- lens groove

def test_the_lens_groove_skips_decorative_holes(aviator_front):
    from guildmodel.core.project.schema import CastleParams, LensGrooveParams
    from guildmodel.core.relief.castle import build_castle_relief

    castle = CastleParams(lens_groove=LensGrooveParams(enabled=True, depth_mm=0.6))
    heights = {z.name: 4.8 for z in aviator_front.partition.zones}
    relief = build_castle_relief(
        aviator_front.partition, castle, aviator_front.hinge_polys,
        resolution=0.8, heights=heights)

    # Only the two lenses are grooved.
    assert len(relief.groove_lens_polys) == 2
    # The opening keeps its drawn size — an undersized rim lip would shrink it.
    hole = aviator_front.outline_holes[0]
    kept = [Polygon(r) for r in relief.mask_body.interiors
            if r.centroid.distance(hole.centroid) < 1.0]
    assert len(kept) == 1
    assert kept[0].area == pytest.approx(hole.area, rel=1e-6)


# ---------------------------------------------------------------- flat parts

def test_a_temple_with_a_cut_out_gets_a_holes_op():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    from guildmodel.core.project.schema import TempleParams

    outline = Polygon(_square(0, 0, 40), [_square(0, 0, 4)])
    ops = generate_temple_program(outline, [], TempleParams(), TOOLS)

    holes_op = next(op for op in ops if op.name == "Holes")
    assert holes_op.paths
    opening = Polygon(_square(0, 0, 4)).buffer(0.5)
    for path in holes_op.paths:
        for x, y, _z in path:
            assert opening.contains(Point(x, y))
    # The profile still releases the part last.
    assert ops[-1].name == "Temple Profile"


def test_a_flat_relief_makes_the_cut_out_a_through_hole():
    from guildmodel.core.relief.flat import build_temple_relief
    from guildmodel.core.project.schema import TempleParams

    outline = Polygon(_square(0, 0, 40), [_square(0, 0, 5)])
    relief = build_temple_relief(outline, TempleParams(), resolution=0.5)

    field = relief.field
    rows, cols = relief.inside.shape
    r = int((0 - field.origin[1]) / field.resolution)
    c = int((0 - field.origin[0]) / field.resolution)
    assert 0 <= r < rows and 0 <= c < cols
    assert not relief.inside[r, c]        # the opening is outside the solid


def test_profile_cut_cuts_the_opening_inward_and_untabbed():
    from guildmodel.core.cam.profile import profile_cut

    outline = Polygon(_square(0, 0, 20), [_square(0, 0, 5)])
    passes = profile_cut(outline, tool_radius_mm=1.0, stock_thickness_mm=2.0,
                         stepdown_mm=1.0, tab_count=4)

    assert passes
    for depth_pass in passes:
        assert len(depth_pass) == 2               # opening + perimeter
        hole_path = depth_pass[0]
        # Offset INWARD: every point sits inside the drawn opening.
        assert all(box(-5, -5, 5, 5).buffer(1e-6).contains(Point(x, y))
                   for x, y, _z in hole_path)
        # ...and clear of the wall by the tool radius.
        assert max(abs(x) for x, _y, _z in hole_path) == pytest.approx(4.0, abs=0.05)
        # Untabbed: the slug is waste, so the opening stays at one z per pass.
        assert len({round(z, 6) for _x, _y, z in hole_path}) == 1


# ---------------------------------------------------------------- zone classification

def test_the_standard_castle_still_matches_with_the_canonical_names():
    """The reference Demo Project must be untouched by the tolerant classifier."""
    from guildmodel.core.geometry.regions import STANDARD_ZONE_NAMES, partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import assemble_outline, points_to_polygon

    layers = import_dxf(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    outline = assemble_outline(layers["OUTLINE"]).polygon
    lenses = [p for p in (points_to_polygon(c) for c in layers["LENS"] if len(c) >= 3)
              if p.area > 1.0]

    partition = partition_zones(outline, lenses[:2], layers["SCULPT"])

    assert partition.matched is True
    assert partition.classified is True
    assert {z.name for z in partition.zones} == STANDARD_ZONE_NAMES


def test_the_aviator_classifies_its_brow_bar_and_bridge(aviator_front):
    partition = aviator_front.partition

    # Not the reference layout — but every zone is named, so it builds.
    assert partition.matched is False
    assert partition.classified is True

    by_kind = {}
    for z in partition.zones:
        by_kind.setdefault(z.kind, []).append(z)
    assert set(by_kind) == {"endpiece", "eyewire_superior", "bridge", "nosepad",
                            "eyewire_inferior"}
    # The fused brow is ONE superior eyewire serving both eyes (side "ou") —
    # not a separate kind; it rides the ordinary superior-eyewire control.
    (brow,) = by_kind["eyewire_superior"]
    assert brow.side == "ou"
    assert brow.name == "eyewire_superior_ou"
    assert brow.polygon.bounds[0] < aviator_front.lens_os.centroid.x
    assert brow.polygon.bounds[2] > aviator_front.lens_od.centroid.x
    # The bridge is the saddle under the opening.
    assert by_kind["bridge"][0].polygon.centroid.y < brow.polygon.centroid.y


def test_a_classified_partition_builds_without_explicit_heights(aviator_front):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_relief

    # No `heights=` argument: the classifier named every zone, so the per-kind
    # defaults resolve on their own. This is what Build 3D does.
    relief = build_castle_relief(
        aviator_front.partition, CastleParams(), aviator_front.hinge_polys,
        resolution=0.6)
    # conform=False isolates the masked-grid solid from the rim-snapping stage,
    # which has a separate defect on this frame's small hinge pockets.
    mesh = build_castle_mesh(relief, conform=False)

    assert mesh.is_watertight
    # Two lenses + the bridge opening.
    assert (2 - mesh.euler_number) // 2 == 3


def test_the_opening_is_a_real_through_hole_in_the_solid(aviator_front):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    relief = build_castle_relief(
        aviator_front.partition, CastleParams(), aviator_front.hinge_polys,
        resolution=0.6)

    field, inside = relief.field, relief.inside
    center = aviator_front.outline_holes[0].representative_point()
    r = int(round((center.y - field.origin[1]) / field.resolution))
    c = int(round((center.x - field.origin[0]) / field.resolution))

    assert not inside[r, c]          # no material at the opening's center


def test_a_generic_partition_still_refuses_to_build():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    # No lenses -> nothing to classify against -> generic zones.
    outline = Polygon(_square(0, 0, 40))
    partition = partition_zones(outline, [], [[(-50.0, 0.0), (50.0, 0.0)]])

    assert partition.classified is False
    with pytest.raises(ValueError, match="recognizable castle zones"):
        build_castle_relief(partition, CastleParams(), [], resolution=2.0)


def test_zone_height_overrides_win_over_the_per_kind_default(aviator_front):
    import numpy as np
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    brow = next(z for z in aviator_front.partition.zones if z.side == "ou")

    def _brow_height(castle):
        relief = build_castle_relief(
            aviator_front.partition, castle, aviator_front.hinge_polys,
            resolution=0.8)
        idx = [z.name for z in relief.partition.zones].index(brow.name)
        return float(np.max(relief.field.z[relief.zone_index == idx]))

    default = _brow_height(CastleParams())
    raised = _brow_height(
        CastleParams(zone_height_overrides={brow.name: default + 2.0}))

    assert raised == pytest.approx(default + 2.0, abs=0.05)


def test_an_override_for_a_zone_the_drawing_lacks_is_ignored(aviator_front):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    # Must not raise, and must not invent a zone.
    relief = build_castle_relief(
        aviator_front.partition,
        CastleParams(zone_height_overrides={"no_such_zone": 9.0}),
        aviator_front.hinge_polys, resolution=0.8)

    assert relief.field.z.size


def test_zone_height_overrides_round_trip_through_the_schema():
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams(zone_height_overrides={"eyewire_superior_ou": 6.25})
    restored = CastleParams.model_validate(castle.model_dump())

    assert restored.zone_height_overrides == {"eyewire_superior_ou": 6.25}


def test_the_unified_brow_rides_the_superior_eyewire_control(aviator_front):
    """No separate brow-bar parameter: raising the ordinary superior-eyewire
    height raises the OU brow with it."""
    import numpy as np
    from guildmodel.core.project.schema import CastleParams, ZoneThicknesses
    from guildmodel.core.relief.castle import build_castle_relief

    brow = next(z for z in aviator_front.partition.zones if z.side == "ou")
    assert brow.kind == "eyewire_superior"

    castle = CastleParams(zones=ZoneThicknesses(eyewire_superior_mm=6.0))
    relief = build_castle_relief(
        aviator_front.partition, castle, aviator_front.hinge_polys,
        resolution=0.8)
    idx = [z.name for z in relief.partition.zones].index(brow.name)

    assert float(np.max(relief.field.z[relief.zone_index == idx])) == pytest.approx(6.0, abs=0.05)


def test_a_unified_inferior_wire_classifies_as_eyewire_inferior_ou():
    """The OU rule is not brow-specific: a full-width lower wall (no cuts
    splitting it per side) reads as one inferior eyewire for both eyes."""
    from guildmodel.core.geometry.regions import partition_zones

    outline = Polygon([(-60, -25), (60, -25), (60, 25), (-60, 25)])
    lenses = [Point(-30, 0).buffer(15), Point(30, 0).buffer(15)]
    # One horizontal cut just below the lens centers: everything under it is a
    # single band spanning both lenses.
    cuts = [[(-61.0, -8.0), (61.0, -8.0)]]

    partition = partition_zones(outline, lenses, cuts)

    assert partition.classified
    lower = next(z for z in partition.zones if z.polygon.centroid.y < -10)
    assert (lower.kind, lower.side) == ("eyewire_inferior", "ou")


def test_edge_names_stay_unique_when_a_zone_pair_repeats(aviator_front):
    names = [e.name for e in aviator_front.partition.edges]

    assert len(names) == len(set(names))


# ---------------------------------------------------------------- validation

def test_validate_reports_openings_as_a_warning_not_an_error():
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.io_import.validate import validate

    layers = {
        "OUTLINE": [points_to_polygon(_square(0, 0, 50)),
                    points_to_polygon(_square(0, 0, 5))],
        "LENS": [points_to_polygon(_square(-20, 0, 10)),
                 points_to_polygon(_square(20, 0, 10))],
    }
    result = validate(layers)

    assert result.ok
    assert any("Hole1" in w for w in result.warnings)


def test_validate_flags_an_outline_curve_outside_the_profile():
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.io_import.validate import validate

    layers = {
        "OUTLINE": [points_to_polygon(_square(0, 0, 50)),
                    points_to_polygon(_square(200, 0, 5))],
        "LENS": [points_to_polygon(_square(-20, 0, 10)),
                 points_to_polygon(_square(20, 0, 10))],
    }
    result = validate(layers)

    assert result.ok
    assert any("outside the profile" in w for w in result.warnings)
