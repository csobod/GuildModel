"""Inlays: the INLAY layer, modeled and cut (BUILDPLAN §8a, 2026-10-15).

A closed INLAY curve on a front or a temple is a seat for a plaque, a laminate
or a plate. GuildDraw sends the geometry; GuildModel keeps one `InlayFeature`
per curve — face, depth, step or island, tool — matched to its seat on every
re-import by containment order and centroid, and resolves the lot into one
list of cuts (`geometry.inlays`) that the raster, the mesh kernel, the B-Rep
and the CAM all read: the bezel's lesson, applied before a second copy of the
maths could exist.

What is pinned here, in order: the schema; the containment tree and the match;
the cuts; the raster on both faces, with the hinge pocket's tilt inherited;
the three kernels against each other on the three fixtures; the Inlays op,
its place in the program, the island, the tilted floor, a seat on its own
tool, the reach and thickness checks, and the posterior program byte-identical
with an anterior seat present; the simulation reaching a seat's floor; the
intake from a drawing and a project; the panel and the Parts page.
"""
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import yaml
from shapely import contains_xy
from shapely.affinity import translate
from shapely.geometry import Point, box

from guildmodel.core.geometry.inlays import (
    containment, inlay_cuts, nesting_levels, ordered, reconcile, zone_reference,
)
from guildmodel.core.geometry.pocket_floor import (
    PocketFloor, castle_pocket_floors, temple_pocket_floors,
)
from guildmodel.core.project.schema import CastleParams, InlayFeature, TempleParams

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TOOLS = yaml.safe_load((ROOT / "src" / "guildmodel" / "config" / "tools.yaml").read_text())
_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def demo():
    """The demo front's partition and hinge polygons, from the DXF fixture."""
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _gdraw_front(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    ws = build_workspaces_from_gdraw(path)[0][0]
    return ws.partition, ws.hinge_polys


@pytest.fixture(scope="module")
def aviator(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def gabriel(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "gabriel")


def _bridge_plaque(partition, w=6.0, h=4.0):
    """A plaque-sized seat on the bridge bar of `partition`."""
    bridge = next(z for z in partition.zones if z.name == "bridge")
    c = bridge.polygon.representative_point()
    return box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)


def _seats_for(partition, hinges, *, inset=0.5, angle=0.0, depth=1.0):
    """An anterior plaque on the bridge and a seat inside every hinge pocket,
    with a castle whose features are reconciled to them."""
    polys = [_bridge_plaque(partition)]
    for h in hinges:
        s = h.buffer(-inset)
        if not s.is_empty and s.geom_type == "Polygon":
            polys.append(s)
    polys = ordered(polys, hinges)
    castle = CastleParams(hinge_pocket_angle_deg=angle, inlay_depth_mm=depth)
    castle.inlays = reconcile([], polys, hinges, default_depth_mm=depth)
    return castle, polys


def _heights(partition, castle):
    return {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}


def _cells(relief, poly, erode=0.4):
    """Body cells well inside `poly` on the relief's grid."""
    inner = poly.buffer(-erode)
    m = contains_xy(inner, relief.Xs.ravel(), relief.Ys.ravel()).reshape(relief.field.z.shape)
    return m & relief.inside


# ------------------------------------------------------------------ the drawing

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path):
    """A front with a plaque, a step inside it and a seat in a hinge; a right
    temple with one seat. The validator's rules hold: every seat inside the
    profile, clear of the lenses, nested or apart, inside a HINGE or beside it."""
    front = {"curves": [
        _line("OUTLINE", _rect(-60, -20, 60, 20), closed=True),
        _line("LENS", _rect(20, -12, 45, 12), closed=True),
        _line("LENS", _rect(-45, -12, -20, 12), closed=True),
        _line("SCULPT", [(0, -20), (0, 20)]),
        _line("SCULPT", [(30, -20), (30, 20)]),
        _line("HINGE", _rect(50, -5, 58, 5), closed=True),
        _line("INLAY", _rect(-8, 14, 8, 19), closed=True),       # a plaque on the bar
        _line("INLAY", _rect(-3, 15, 3, 18), closed=True),       # a step inside it
        _line("INLAY", _rect(52, -3, 56, 3), closed=True),       # inside the hinge
    ]}
    temple = {"curves": [
        _line("OUTLINE", _rect(-70, -6, 70, 6), closed=True),
        _line("HINGE", _rect(55, -3, 65, 3), closed=True),
        _line("INLAY", _rect(-30, -3, 0, 3), closed=True),
    ]}
    states = {"front": front, "temple_r": temple,
              "temple_l": {"curves": []}, "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


# ------------------------------------------------------------------ schema

def test_a_seat_starts_on_the_visible_face_and_old_projects_load():
    f = InlayFeature()
    assert (f.face, f.depth_mm, f.mode, f.enabled) == ("anterior", 1.0, "step", True)
    assert f.tool == "" and f.stepdown_mm is None
    for cls in (CastleParams, TempleParams):
        raw = cls().model_dump()
        raw.pop("inlays")
        raw.pop("inlay_depth_mm")
        p = cls.model_validate(raw)
        assert p.inlays == [] and p.inlay_depth_mm == 1.0


def test_the_cut_depth_is_the_insert_less_the_flush():
    assert InlayFeature(depth_mm=1.0, flush_mm=0.2).cut_depth_mm() == pytest.approx(0.8)
    assert InlayFeature(depth_mm=1.0, flush_mm=-0.3).cut_depth_mm() == pytest.approx(1.3)
    assert InlayFeature(depth_mm=0.5, flush_mm=0.9).cut_depth_mm() == 0.0


def test_an_anterior_seat_is_what_cuts_the_front():
    assert not CastleParams().cuts_anterior()
    assert CastleParams(inlays=[InlayFeature()]).cuts_anterior()
    assert not CastleParams(inlays=[InlayFeature(face="posterior")]).cuts_anterior()
    assert not CastleParams(inlays=[InlayFeature(enabled=False)]).cuts_anterior()
    assert InlayFeature(face="posterior").posted()
    assert not InlayFeature().posted()


# ------------------------------------------------------------------ the tree

HINGE = box(50, -5, 58, 5)
IN_HINGE = box(52, -3, 56, 3)
PLAQUE = box(-30, -10, 0, 10)
MONO = box(-20, -4, -10, 4)
DEEP = box(-28, 6, -24, 9)


def test_the_tree_reads_parents_and_hinges_off_the_polygons():
    nodes = containment([MONO, IN_HINGE, PLAQUE, DEEP], [HINGE])
    by = {n.index: n for n in nodes}
    assert by[2].parent is None and by[2].hinge is None and by[2].level == 0
    assert by[0].parent == 2 and by[0].level == 1 and by[0].relative_to == "seat"
    assert by[3].parent == 2 and by[3].level == 1
    assert by[1].parent is None and by[1].hinge == 0 and by[1].level == 1
    assert by[1].relative_to == "hinge"


def test_the_order_puts_parents_first_then_the_larger_seat():
    polys = ordered([DEEP, MONO, IN_HINGE, PLAQUE], [HINGE])
    assert polys[0].equals(PLAQUE)                    # the only root seat
    nodes = containment(polys, [HINGE])
    for n in nodes:
        if n.parent is not None:
            assert n.parent < n.index
    assert [n.level for n in nodes] == sorted(n.level for n in nodes)
    areas = [n.polygon.area for n in nodes if n.level == 1]
    assert areas == sorted(areas, reverse=True)


def test_nesting_levels_follow_the_curves_as_drawn():
    curves = [list(MONO.exterior.coords), list(PLAQUE.exterior.coords),
              list(IN_HINGE.exterior.coords), [(0, 0), (1, 1)]]
    assert nesting_levels(curves, [list(HINGE.exterior.coords)]) == [1, 0, 1, 0]


# ------------------------------------------------------------------ the match

def test_fresh_seats_take_the_part_defaults_and_the_derived_faces():
    polys = ordered([MONO, IN_HINGE, PLAQUE], [HINGE])
    feats = reconcile([], polys, [HINGE], default_depth_mm=1.2)
    assert [f.id for f in feats] == ["inlay_1", "inlay_2", "inlay_3"]
    assert all(f.depth_mm == 1.2 for f in feats)
    by = {f.relative_to: f for f in feats}
    assert by["face"].face == "anterior"
    assert by["seat"].face == "anterior"               # follows its parent
    assert by["hinge"].face == "posterior"             # the hinge's face
    assert by["hinge"].level == 1 and by["face"].level == 0


def test_a_child_takes_its_parents_face_whatever_was_stored():
    polys = ordered([MONO, PLAQUE], [])
    feats = reconcile([], polys, [])
    feats[0] = feats[0].model_copy(update={"face": "posterior"})
    feats[1] = feats[1].model_copy(update={"face": "anterior"})
    again = reconcile(feats, polys, [])
    assert [f.face for f in again] == ["posterior", "posterior"]


def test_reconcile_is_idempotent():
    polys = ordered([MONO, IN_HINGE, PLAQUE, DEEP], [HINGE])
    feats = reconcile([], polys, [HINGE])
    again = reconcile(feats, polys, [HINGE])
    assert [f.model_dump() for f in again] == [f.model_dump() for f in feats]


def test_a_reimported_drawing_keeps_each_seats_settings():
    polys = ordered([MONO, IN_HINGE, PLAQUE, DEEP], [HINGE])
    feats = reconcile([], polys, [HINGE])
    edited = [f.model_copy(update={"depth_mm": 2.5, "label": "Plaque"}) if f.level == 0
              else f.model_copy(update={"mode": "island"}) if f.area_mm2 == MONO.area
              else f for f in feats]
    # the maker nudged the plaque and its monogram, redrew the deep step
    # elsewhere, and added a seat beside the hinge one
    moved = ordered([translate(MONO, 0.8, -0.4), IN_HINGE, translate(PLAQUE, 0.8, -0.4),
                     box(-10, -9, -4, -6), box(-14, -2, -11, 2)], [HINGE])
    out = reconcile(edited, moved, [HINGE])
    assert len(out) == 5
    plaque = next(f for f in out if f.level == 0)
    assert plaque.depth_mm == 2.5 and plaque.label == "Plaque"
    mono = next(f for f in out if abs(f.area_mm2 - MONO.area) < 1e-6)
    assert mono.mode == "island"
    assert len({f.id for f in out}) == 5                # every seat its own id


def test_a_seat_moved_beyond_the_match_distance_is_paired_in_order():
    polys = ordered([PLAQUE], [])
    feats = reconcile([], polys, [])
    feats = [feats[0].model_copy(update={"depth_mm": 3.0})]
    far = ordered([translate(PLAQUE, 40.0, 0.0)], [])
    out = reconcile(feats, far, [])
    assert out[0].depth_mm == 3.0 and out[0].id == feats[0].id


# ------------------------------------------------------------------ the cuts

def test_a_step_is_cut_from_its_parents_floor_and_a_hinge_child_keeps_the_tilt():
    polys = ordered([MONO, IN_HINGE, PLAQUE], [HINGE])
    feats = reconcile([], polys, [HINGE], default_depth_mm=1.0)
    tilted = PocketFloor(z_fixed=4.5, axis=(0.0, -1.0), edge=-5.0, slope=0.05)
    cuts = inlay_cuts(feats, polys, [(HINGE, tilted)], posterior_reference=5.5)
    by = {c.feature.relative_to: c for c in cuts}
    assert by["face"].face == "anterior" and by["face"].plane.z_fixed == pytest.approx(1.0)
    assert by["seat"].plane.z_fixed == pytest.approx(2.0)      # a step down from 1.0
    assert by["seat"].reference.z_fixed == pytest.approx(1.0)
    h = by["hinge"]
    assert h.face == "posterior" and h.plane.slope == tilted.slope
    assert h.plane.z_fixed == pytest.approx(3.5)
    assert h.plane.z(54.0, 0.0) == pytest.approx(tilted.z(54.0, 0.0) - 1.0)


def test_a_posterior_root_seat_measures_from_the_terrace():
    polys = ordered([PLAQUE], [])
    feats = [reconcile([], polys, [])[0].model_copy(update={"face": "posterior"})]
    cut = inlay_cuts(feats, polys, [], posterior_reference=lambda p: 5.3)[0]
    assert cut.plane.z_fixed == pytest.approx(4.3)


def test_an_island_is_left_standing_in_its_parent():
    polys = ordered([MONO, PLAQUE], [])
    feats = reconcile([], polys, [])
    feats[1] = feats[1].model_copy(update={"mode": "island", "depth_mm": 0.0})
    cuts = inlay_cuts(feats, polys, [], posterior_reference=5.0)
    parent, island = cuts[0], cuts[1]
    assert len(parent.region.interiors) == 1
    assert parent.region.area == pytest.approx(PLAQUE.area - MONO.area)
    assert island.plane.z_fixed == pytest.approx(0.0)          # untouched at depth 0
    feats[1] = feats[1].model_copy(update={"depth_mm": 0.4})
    island = inlay_cuts(feats, polys, [], posterior_reference=5.0)[1]
    assert island.plane.z_fixed == pytest.approx(0.4)          # sunk, still proud of 1.0


def test_a_disabled_seat_takes_its_children_with_it():
    polys = ordered([MONO, PLAQUE], [])
    feats = reconcile([], polys, [])
    feats[0] = feats[0].model_copy(update={"enabled": False})
    assert inlay_cuts(feats, polys, []) == []


def test_zone_reference_is_the_highest_terrace_the_seat_touches(demo):
    partition, _ = demo
    castle = CastleParams()
    ref = zone_reference(partition, _heights(partition, castle))
    bridge = next(z for z in partition.zones if z.name == "bridge")
    assert ref(_bridge_plaque(partition)) == pytest.approx(castle.zones.bridge_mm)
    # a seat spanning the bridge and a nosepad takes the nosepad's height
    nose = next(z for z in partition.zones if z.kind == "nosepad")
    span = bridge.polygon.union(nose.polygon).convex_hull
    assert ref(span) == pytest.approx(castle.zones.nosepad_mm)


# ------------------------------------------------------------------ the raster

def _relief(demo, castle, polys, res=0.3):
    from guildmodel.core.relief.castle import build_castle_relief
    partition, hinges = demo
    return build_castle_relief(partition, castle, hinges, resolution=res, inlay_polys=polys)


def test_the_raster_carves_a_posterior_seat_below_the_surface_snapshot(demo):
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges)
    relief = _relief(demo, castle, polys)
    cuts = inlay_cuts(castle.inlays, polys, castle_pocket_floors(hinges, castle),
                      posterior_reference=zone_reference(partition, _heights(partition, castle)))
    seat = next(c for c in cuts if c.posterior)
    m = _cells(relief, seat.outline)
    assert m.any()
    np.testing.assert_allclose(relief.field.z[m], seat.plane.z_fixed, atol=1e-9)
    # the relief passes ride the pre-pocket surface, which the seat never touched
    assert (relief.surface_field.z[m] > seat.plane.z_fixed + 0.9).all()
    assert any(p.equals(seat.outline) for p in relief.pocket_polys)


def test_the_raster_carves_an_anterior_seat_into_the_front(demo):
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges, depth=0.8)
    relief = _relief(demo, castle, polys)
    plaque = polys[0]
    m = _cells(relief, plaque)
    assert relief.anterior is not None
    np.testing.assert_allclose(relief.anterior[m], 0.8, atol=1e-9)
    assert relief.anterior[relief.inside & ~_cells(relief, plaque, erode=-0.4)].max() == 0.0
    assert any(p.equals(plaque) for p in relief.anterior_pocket_polys)
    # the back is untouched by a seat on the front
    bare = _relief(demo, CastleParams(), [])
    np.testing.assert_allclose(relief.field.z[m], bare.field.z[m], atol=1e-9)


def test_a_seat_in_a_tilted_hinge_pocket_follows_the_pockets_plane(demo):
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges, angle=6.0)
    relief = _relief(demo, castle, polys, res=0.2)
    for seat in inlay_cuts(castle.inlays, polys, castle_pocket_floors(hinges, castle),
                           posterior_reference=5.5):
        if not seat.posterior:
            continue
        assert not seat.plane.flat
        m = _cells(relief, seat.outline, erode=0.3)
        np.testing.assert_allclose(relief.field.z[m],
                                   seat.plane.z(relief.Xs[m], relief.Ys[m]), atol=1e-9)
        hinge_floor = seat.reference
        np.testing.assert_allclose(
            relief.field.z[m], hinge_floor.z(relief.Xs[m], relief.Ys[m]) - 1.0, atol=1e-9)


def test_the_raster_mesh_closes_with_seats_on_both_faces(demo):
    from guildmodel.core.relief.castle import build_castle_mesh
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges)
    mesh = build_castle_mesh(_relief(demo, castle, polys))
    assert mesh.is_watertight
    bare = build_castle_mesh(_relief(demo, CastleParams(), []))
    assert mesh.volume < bare.volume


def _temple(angle=0.0, outer_depth=1.0, inner_depth=1.0):
    from guildmodel.core.relief.flat import build_temple_relief
    t = TempleParams(hinge_pocket_angle_deg=angle)
    outline = box(-80.0, -6.0, 60.0, 6.0)
    hinge = box(45.0, -3.0, 55.0, 3.0)
    outer = box(-40.0, -3.0, -10.0, 3.0)
    inner = box(0.0, -2.0, 20.0, 2.0)
    polys = ordered([outer, inner], [hinge])
    t.inlays = reconcile([], polys, [hinge])
    for f in t.inlays:
        if f.area_mm2 == pytest.approx(inner.area):
            f.face, f.depth_mm = "posterior", inner_depth
        else:
            f.depth_mm = outer_depth
    relief = build_temple_relief(outline, t, [hinge], [], inlay_polys=polys, resolution=0.1)
    return t, outline, hinge, polys, relief


def test_the_temple_relief_carves_both_faces():
    from guildmodel.core.relief.castle import build_castle_mesh
    t, outline, hinge, polys, relief = _temple()
    inner = next(p for p in polys if p.bounds[0] == 0.0)
    outer = next(p for p in polys if p.bounds[0] == -40.0)
    m_in = _cells(relief, inner)
    np.testing.assert_allclose(relief.field.z[m_in], t.blank_thickness_mm - 1.0, atol=1e-9)
    m_out = _cells(relief, outer)
    assert relief.anterior is not None
    np.testing.assert_allclose(relief.anterior[m_out], 1.0, atol=1e-9)
    np.testing.assert_allclose(relief.field.z[m_out], t.blank_thickness_mm, atol=1e-9)
    assert build_castle_mesh(relief).is_watertight


# ------------------------------------------------------------------ the kernels

def test_the_mesh_kernel_removes_area_times_depth(demo):
    from guildmodel.core.model import build_castle_model, to_trimesh
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges, depth=1.0)
    bare = to_trimesh(build_castle_model(partition, CastleParams(), hinges))
    seated = to_trimesh(build_castle_model(partition, castle, hinges, inlays=polys))
    assert seated.is_watertight
    expected = sum(p.area for p in polys) * 1.0
    assert bare.volume - seated.volume == pytest.approx(expected, rel=0.01)


@pytest.mark.parametrize("fixture", ["demo", "aviator", "gabriel"])
def test_the_mesh_kernel_agrees_with_the_raster_on_every_fixture(fixture, request):
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.zmap import castle_relief
    partition, hinges = request.getfixturevalue(fixture)
    castle, polys = _seats_for(partition, hinges, angle=3.0)
    assert len(polys) >= 2, "the fixture should carry a plaque and a hinge seat"
    raster = build_castle_relief(partition, castle, hinges, resolution=0.3, inlay_polys=polys)
    mesh = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3,
                         inlays=polys)
    for seat in polys:
        m = _cells(raster, seat, erode=0.45)
        assert m.any()
        assert np.abs(raster.field.z[m] - mesh.field.z[m]).max() < 0.01
        assert np.abs(raster.anterior_z[m] - mesh.anterior_z[m]).max() < 0.01
    # the CAM relief from the mesh carries what posting needs, like the raster's
    assert mesh.surface_field is not None and mesh.anterior is not None
    assert len(mesh.pocket_polys) == len(raster.pocket_polys)
    assert len(mesh.anterior_pocket_polys) == 1


def test_the_brep_kernel_cuts_the_same_seats(demo):
    pytest.importorskip("OCP")
    from guildmodel.core.solid.build import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges, angle=3.0)
    clear_base_cache()
    bare = tessellate(build_castle_solid(partition, CastleParams(hinge_pocket_angle_deg=3.0),
                                         hinges), with_edges=False).to_trimesh()
    clear_base_cache()
    seated = tessellate(build_castle_solid(partition, castle, hinges, inlays=polys),
                        with_edges=False).to_trimesh()
    expected = sum(p.area for p in polys) * 1.0
    assert bare.volume - seated.volume == pytest.approx(expected, rel=0.02)


# ------------------------------------------------------------------ the CAM

def _program(demo, castle, polys, res=0.3):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    partition, hinges = demo
    relief = _relief(demo, castle, polys, res=res)
    return relief, generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"],
                                           tools_cfg=TOOLS, inlay_polys=polys)


def _posted(ops, top_z):
    from guildmodel.core.cam.castle_ops import write_castle_program
    from guildmodel.core.post.grbl import GRBLPost
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=600, plunge_rate_mmpm=200,
                    safe_z_mm=top_z + 5.0, feed_plane_mm=top_z + 1.0)
    write_castle_program(ops, post)
    return post.to_string()


def test_the_inlays_op_pockets_the_posterior_seat_after_the_relief(demo):
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges)
    relief, ops = _program(demo, castle, polys)
    names = [op.name for op in ops]
    assert "Inlays" in names
    assert names.index("Fine Relief") < names.index("Inlays") < names.index("Eyewires")
    op = next(op for op in ops if op.name == "Inlays")
    assert op.tool_name == "flat_2mm"
    cuts = inlay_cuts(castle.inlays, polys, castle_pocket_floors(hinges, castle),
                      posterior_reference=zone_reference(partition, _heights(partition, castle)))
    posted = [c for c in cuts if c.posterior]
    assert len(posted) == 2                          # one seat in each hinge pocket
    seat = posted[0]
    zmin, zmax = op.z_range()
    assert zmin == pytest.approx(seat.plane.z_fixed)
    # it starts just above the hinge floor it steps, not at the stock top
    assert zmax == pytest.approx(seat.reference.z_fixed + 0.5)
    # every point a tool radius inside one of the seats, within the chord the
    # two round offsets (pyclipper's rings, shapely's check) disagree by
    from shapely.ops import unary_union
    r = op.tool["radius_mm"]
    inside = unary_union([c.outline.buffer(-r + 0.02) for c in posted])
    for path in op.paths:
        for x, y, _z in path:
            assert inside.covers(Point(x, y))


def test_anterior_inlay_is_not_cut(demo):
    """The milestone's byte-identity: a front whose only seat is on the front
    posts the program it posted without any seat."""
    partition, hinges = demo
    plaque = ordered([_bridge_plaque(partition)], hinges)
    castle = CastleParams()
    castle.inlays = reconcile([], plaque, hinges)
    assert castle.inlays[0].face == "anterior" and castle.cuts_anterior()
    _, with_seat = _program(demo, castle, plaque)
    _, without = _program(demo, CastleParams(), [])
    top = castle.stock.total_pad_height_mm
    assert _posted(with_seat, top) == _posted(without, top)
    assert [op.name for op in with_seat] == [op.name for op in without]


def test_a_seat_the_tool_cannot_enter_is_named_with_one_that_fits(demo):
    from guildmodel.core.cam.castle_ops import analyze_program_reach, resolve_tool
    from guildmodel.core.cam.inlay_ops import inlay_op_groups
    partition, hinges = demo
    castle, polys = _seats_for(partition, hinges, inset=1.1)      # under 2 mm wide
    relief, ops = _program(demo, castle, polys)
    assert "Inlays" not in [op.name for op in ops]
    cuts = inlay_cuts(castle.inlays, polys, castle_pocket_floors(hinges, castle),
                      posterior_reference=5.5)
    groups = inlay_op_groups(cuts, TOOLS, resolve_tool("flat_2mm", TOOLS))
    warnings = analyze_program_reach(ops, hinges, TOOLS, inlay_groups=groups)
    seat = [w for w in warnings if "inlay seat" in w.feature]
    assert seat and seat[0].op_name == "Inlays"
    assert seat[0].suggested_tool == "ball_1mm"


def test_an_island_keeps_its_material_in_the_program():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    t = TempleParams()
    outline = box(-80.0, -6.0, 60.0, 6.0)
    plaque, mono = box(-40.0, -4.0, -10.0, 4.0), box(-30.0, -1.5, -20.0, 1.5)
    polys = ordered([mono, plaque], [])
    t.inlays = reconcile([], polys, [])
    t.inlays[0] = t.inlays[0].model_copy(update={"face": "posterior"})
    t.inlays[1] = t.inlays[1].model_copy(update={"mode": "island", "depth_mm": 0.0})
    ops = generate_temple_program(outline, [], t, TOOLS, inlay_polys=polys)
    op = next(op for op in ops if op.name == "Inlays")
    r = op.tool["radius_mm"]
    floor = t.blank_thickness_mm - 1.0
    keep = mono.buffer(r - 1e-6)
    for path in op.paths:
        for x, y, z in path:
            assert not keep.contains(Point(x, y)), "the tool entered the island"
    assert op.z_range()[0] == pytest.approx(floor)


def test_a_seat_in_a_tilted_pocket_never_gouges_the_plane():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    t = TempleParams(hinge_pocket_angle_deg=5.0)
    outline = box(-80.0, -6.0, 60.0, 6.0)
    hinge = box(44.0, -4.0, 58.0, 4.0)
    seat = box(46.0, -2.5, 56.0, 2.5)
    polys = ordered([seat], [hinge])
    t.inlays = reconcile([], polys, [hinge])
    assert t.inlays[0].relative_to == "hinge"
    ops = generate_temple_program(outline, [], t, TOOLS, hinge_polys=[hinge],
                                  inlay_polys=polys)
    op = next(op for op in ops if op.name == "Inlays")
    (_, floor), = temple_pocket_floors([hinge], t, outline)
    r = op.tool["radius_mm"]
    lift = r * abs(floor.slope)
    pts = np.array([p for path in op.paths for p in path])
    plane = floor.z(pts[:, 0], pts[:, 1]) - 1.0
    assert (pts[:, 2] >= plane + lift - 1e-6).all()
    assert len(op.paths) > 1                         # the finishing lines follow


def test_a_seat_on_its_own_tool_posts_as_its_own_inlays_op():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    t = TempleParams()
    outline = box(-80.0, -6.0, 60.0, 6.0)
    a, b = box(-40.0, -3.0, -20.0, 3.0), box(0.0, -3.0, 20.0, 3.0)
    polys = ordered([a, b], [])
    t.inlays = [f.model_copy(update={"face": "posterior"}) for f in reconcile([], polys, [])]
    t.inlays[1] = t.inlays[1].model_copy(update={"tool": "ball_1mm", "stepdown_mm": 0.3})
    ops = generate_temple_program(outline, [], t, TOOLS, inlay_polys=polys)
    names = [op.name for op in ops]
    assert "Inlays" in names and "Inlays 2" in names
    assert names.index("Inlays 2") < names.index("Temple Profile")
    second = next(op for op in ops if op.name == "Inlays 2")
    assert second.tool_name == "ball_1mm"
    levels = sorted({round(p[2], 3) for path in second.paths for p in path})
    assert levels[0] == pytest.approx(t.blank_thickness_mm - 1.0)
    assert len(levels) > 3                            # 0.3 mm per pass, not 1.0


def test_a_temple_with_an_outer_face_seat_posts_byte_identically():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    t = TempleParams()
    outline = box(-80.0, -6.0, 60.0, 6.0)
    polys = ordered([box(-40.0, -3.0, -10.0, 3.0)], [])
    t.inlays = reconcile([], polys, [])
    with_seat = generate_temple_program(outline, [], t, TOOLS, inlay_polys=polys)
    without = generate_temple_program(outline, [], TempleParams(), TOOLS)
    assert _posted(with_seat, 4.0) == _posted(without, 4.0)


def test_the_thickness_check_names_the_seat_that_fails():
    from guildmodel.core.cam.inlay_ops import inlay_thickness_warnings
    t, outline, hinge, polys, relief = _temple(outer_depth=1.0, inner_depth=1.0)
    cuts = inlay_cuts(t.inlays, polys, temple_pocket_floors([hinge], t, outline),
                      posterior_reference=t.blank_thickness_mm)
    assert inlay_thickness_warnings(relief, cuts) == []
    # a 2.5 mm outer seat over the 4 mm blank leaves 1.5 mm; its own minimum of
    # 2 mm is what it fails, by name
    t.inlays = [f.model_copy(update={"depth_mm": 2.5, "min_thickness_mm": 2.0,
                                     "label": "Logo plate"})
                if f.face == "anterior" else f for f in t.inlays]
    from guildmodel.core.relief.flat import build_temple_relief
    relief = build_temple_relief(outline, t, [hinge], [], inlay_polys=polys, resolution=0.1)
    cuts = inlay_cuts(t.inlays, polys, temple_pocket_floors([hinge], t, outline),
                      posterior_reference=t.blank_thickness_mm)
    (w,) = inlay_thickness_warnings(relief, cuts)
    assert w.seat == "Logo plate" and w.thinnest_mm == pytest.approx(1.5, abs=1e-6)
    assert "Logo plate" in w.message() and w.op_name == "Inlays"


def test_the_sim_reaches_the_seats_floor():
    from guildmodel.core.cam.temple_ops import generate_temple_program
    from guildmodel.core.sim import ToolProfile, achieved_floor_grouped
    t, outline, hinge, polys, relief = _temple()
    ops = generate_temple_program(outline, [], t, TOOLS, hinge_polys=[hinge],
                                  inlay_polys=polys)
    op = next(op for op in ops if op.name == "Inlays")
    groups = [(path, op.tool_name) for op in ops for path in op.paths]
    profiles = {n: ToolProfile.from_tool(TOOLS[n]) for n in {k for _, k in groups}}
    f = relief.field
    floor = achieved_floor_grouped(groups, profiles, ToolProfile.from_tool(TOOLS["flat_3175"]),
                                   f.origin, f.z.shape, f.resolution,
                                   t.blank_thickness_mm + 1.0)
    inner = next(p for p in polys if p.bounds[0] == 0.0)
    m = _cells(relief, inner, erode=op.tool["radius_mm"] + 0.2)
    np.testing.assert_allclose(floor[m], f.z[m], atol=0.02)


def test_the_cut_time_model_bills_the_inlays_section():
    from guildmodel.core.cam.cuttime import _canon_op
    assert _canon_op("--- Inlays ---") == "Inlays"
    assert _canon_op("--- Inlays 2 ---") == "Inlays"


def test_the_seats_sit_after_the_relief_and_before_the_eyewires_in_the_tiers():
    from guildmodel.core.cam.castle_ops import CASTLE_OP_TIERS, CamOp
    from guildmodel.core.cam.sequence import order_by_tool_work
    from guildmodel.core.cam.temple_ops import TEMPLE_OP_TIERS
    names = [next(iter(t)) for t in CASTLE_OP_TIERS]
    assert names.index("Features") < names.index("Inlays") < names.index("Eyewires")
    assert "Inlays" in TEMPLE_OP_TIERS[0]

    def op(name, tool, length):
        o = CamOp(name, tool={"name": tool, "radius_mm": 1.0})
        o.paths = [[(0.0, 0.0, 0.0), (length, 0.0, 0.0)]]
        return o
    ops = [op("Hinge Pockets", "flat_2mm", 50), op("Rough Relief", "flat_3175", 900),
           op("Fine Relief", "flat_3175", 800), op("Inlays", "flat_2mm", 60),
           op("Eyewires", "flat_3175", 300), op("Perimeter", "flat_3175", 400)]
    assert [o.name for o in order_by_tool_work(ops, CASTLE_OP_TIERS)] == [o.name for o in ops]


# ------------------------------------------------------------------ intake

def test_a_gdraw_with_seats_arrives_paired_on_every_part(tmp_path):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    wss, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "seats.gdraw"))
    front = wss[0]
    assert len(front.inlay_polys) == 3
    feats = front.castle_params.inlays
    assert [f.relative_to for f in feats] == ["face", "hinge", "seat"]
    assert [f.face for f in feats] == ["anterior", "posterior", "anterior"]
    assert all(f.depth_mm == front.castle_params.inlay_depth_mm for f in feats)
    for f, p in zip(feats, front.inlay_polys):
        assert f.centroid == pytest.approx((p.centroid.x, p.centroid.y))
    temple = next(w for w in wss if w.source_workspace == "temple_r")
    assert len(temple.inlay_polys) == 1
    (tf,) = temple.temple_params.inlays
    assert tf.relative_to == "face" and tf.face == "anterior"
    left = next(w for w in wss if w.source_workspace == "temple_l")
    assert left.inlay_polys == [] and left.temple_params.inlays == []


def test_a_project_keeps_the_seats_and_a_reload_matches_them_to_the_drawing(tmp_path):
    from guildmodel.core.project.schema import Component, ComponentKind, ProjectSchema
    from guildmodel.gui.component_workspace import (build_workspaces_from_gdraw,
                                                    seed_inlay_features)
    wss, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "seats.gdraw"))
    front = wss[0]
    front.castle_params.inlays[0] = front.castle_params.inlays[0].model_copy(
        update={"depth_mm": 1.6, "label": "Brow plate"})
    proj = ProjectSchema()
    proj.components = [Component(id="front", kind=ComponentKind.FRAME_FRONT,
                                 castle=front.castle_params)]
    back = ProjectSchema.model_validate_json(proj.model_dump_json())
    saved = back.components[0].castle
    assert saved.inlays[0].depth_mm == 1.6 and saved.inlays[0].label == "Brow plate"
    # the drawing reopened: the saved params land on a fresh workspace and the
    # seats follow the redrawn curves
    fresh, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "again.gdraw"))
    ws = fresh[0]
    ws.castle_params = saved
    seed_inlay_features(ws)
    assert ws.castle_params.inlays[0].depth_mm == 1.6
    assert len(ws.castle_params.inlays) == 3


def test_the_mesh_builder_carries_the_seats_for_every_part(tmp_path):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    from guildmodel.gui.mesh_build import build_component_mesh
    wss, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "seats.gdraw"))
    temple = next(w for w in wss if w.source_workspace == "temple_r")
    temple.temple_params.inlays[0].face = "posterior"
    spec = {"mode": "temple", "outline": temple.outline_poly, "temple": temple.temple_params,
            "hinge": temple.hinge_polys, "inlay": temple.inlay_polys,
            "engraving": [], "graphics": []}
    seated, _, _ = build_component_mesh(spec, resolution=0.2)
    spec_bare = dict(spec, inlay=[], temple=TempleParams())
    bare, _, _ = build_component_mesh(spec_bare, resolution=0.2)
    assert seated.is_watertight
    assert bare.volume - seated.volume == pytest.approx(temple.inlay_polys[0].area * 1.0,
                                                        rel=0.03)


# ------------------------------------------------------------------ the panel

def _panel(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


def test_the_panel_round_trips_the_seats_and_the_inlay_depth_on_both_tabs(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(tmp_path, monkeypatch)
    castle = CastleParams(inlay_depth_mm=1.5, inlays=[
        InlayFeature(id="inlay_1", label="Plaque", depth_mm=0.8, flush_mm=0.1,
                     mode="island", tool="ball_1mm", stepdown_mm=0.25,
                     centroid=(0.0, 5.0), area_mm2=24.0)])
    p.set_castle_params(castle)
    out = p.castle_params()
    assert out.inlay_depth_mm == 1.5
    assert [f.model_dump() for f in out.inlays] == [f.model_dump() for f in castle.inlays]
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    t = TempleParams(inlay_depth_mm=0.6, inlays=[InlayFeature(id="inlay_1", face="posterior")])
    p.set_temple_params(t)
    tp = p.temple_params()
    assert tp.inlay_depth_mm == 0.6 and tp.inlays[0].face == "posterior"
    assert ("flat_2mm", ["Hinge Pockets", "Inlays"]) in p.tools_for_active_component()
    assert "Inlays" in p._visible_op_names()


def test_the_panel_rows_follow_the_drawing_and_say_what_is_not_posted(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(tmp_path, monkeypatch)
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    p.inlay_depth.setValue(1.3)
    p.set_inlay_geometry(ordered([MONO, IN_HINGE, PLAQUE], [HINGE]), [HINGE])
    feats = p.castle_params().inlays
    assert len(feats) == 3 and all(f.depth_mm == 1.3 for f in feats)
    rows = [p.inlays_front.rows.item(i).text() for i in range(3)]
    in_hinge = next(i for i, f in enumerate(feats) if f.relative_to == "hinge")
    assert "not posted" in rows[0] and "not posted" not in rows[in_hinge]
    assert "hinge pocket" in rows[in_hinge]
    p.inlays_front.rows.setCurrentRow(in_hinge)            # the seat in the hinge
    assert not p.inlays_front.face.isEnabled()
    p.inlays_front.rows.setCurrentRow(0)
    assert p.inlays_front.face.isEnabled()
    # the same seats again: nothing moves
    before = [f.model_dump() for f in feats]
    p.set_inlay_geometry(ordered([MONO, IN_HINGE, PLAQUE], [HINGE]), [HINGE])
    assert [f.model_dump() for f in p.castle_params().inlays] == before


def test_the_parts_page_defaults_the_inlay_depth():
    from guildmodel.gui import part_defaults as pd
    assert "inlay_depth_mm" in pd.PARAM_FIELDS["frame_front"]
    assert "inlay_depth_mm" in pd.PARAM_FIELDS["temple"]
    assert pd.sparse_params("frame_front", CastleParams(inlay_depth_mm=1.5)) == {
        "inlay_depth_mm": 1.5}
    assert pd.with_overrides(TempleParams(), "temple",
                             {"inlay_depth_mm": 0.7}).inlay_depth_mm == 0.7


def test_the_parts_page_round_trips_the_inlay_depth(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui import prefs as prefs_mod
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsPage
    prefs = dict(prefs_mod.DEFAULTS)
    prefs["part_defaults"] = {"frame_front": {"params": {"inlay_depth_mm": 1.5}},
                              "temple": {"params": {"inlay_depth_mm": 0.6}}}
    page = PartDefaultsPage(prefs)
    assert page.front_inlay_depth.value() == 1.5 and page.temple_inlay_depth.value() == 0.6
    assert page.front_params().inlay_depth_mm == 1.5
    assert page.temple_params().inlay_depth_mm == 0.6
    out = page.to_prefs()
    assert out["frame_front"]["params"] == {"inlay_depth_mm": 1.5}
    assert out["temple"]["params"] == {"inlay_depth_mm": 0.6}


def test_the_canvas_has_a_dark_gold_for_the_layer():
    from guildmodel.core.layers import LAYER_STYLES
    from guildmodel.gui.style import theme
    light = LAYER_STYLES["INLAY"][0]
    assert theme.layer_color(light, False) == light
    assert theme.layer_color(light, True) == "#e0b84c"
