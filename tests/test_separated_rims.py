"""Separated rims: one Frame Front with a body per rim (2026-10-16).

A combination frame's acetate rims sit on a metal bridge and temples. GuildDraw
hands such a front over baked (both rims and both lenses drawn), and sorts its
OUTLINE as its validator does: of the contours inside no other, the largest is
a body and so is any that holds a lens. GuildModel used to keep the largest
contour only: the second rim was a stray, its lens lay outside the part, and
the castle still reported ready.

Now both rims are bodies, cut from one front blank. Each partitions as a
standard half (endpiece, eyewire superior and inferior, nosepad, and the rim's
end of the bridge where the fifth cut is drawn), with no bridge zone between
them, and every kernel and the CAM work per rim. The bridge's mount is one
HINGE shape across the gap, cut into each rim's nasal end.

A front with one rim and one lens, a monocle, is a single rim and is built
the same way: GuildModel reads the curves drawn and never applies GuildDraw's
Ghost.

The drawings here are synthetic: two rectangular rims, drawn in GuildDraw's
scene coordinates (y down) and read through the `.gdraw` intake.
"""
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import yaml
from shapely.geometry import MultiPolygon, Point, Polygon, box

from guildmodel.core.io_import.gdraw import TABS
from guildmodel.core.project.schema import CastleCamParams, CastleParams, EdgeFeature
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

_SVG_NS = "http://www.w3.org/2000/svg"
CONFIG = Path(__file__).parents[1] / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))

HALF_NAMES = {f"{kind}_{side}" for side in ("od", "os") for kind in
              ("endpiece", "bridge", "nosepad", "eyewire_superior", "eyewire_inferior")}


# ------------------------------------------------------------------ the drawing

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": float(x), "y": float(y)} for x, y in pts]}


def _rect(layer, x0, y0, x1, y1):
    return _line(layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True)


def _rim(sign, gap, bridge_cut=True):
    """One rim, on the scene's left (sign -1) or right (+1): a 64 x 44 mm
    frame round a 48 x 32 lens, its nasal edge `gap` mm off the axis, with
    the five section cuts of a standard half (four without the bridge cut)."""
    def x(v):
        return sign * v
    g = gap
    curves = [
        _rect("OUTLINE", min(x(70), x(g)), -22, max(x(70), x(g)), 22),
        _rect("LENS", min(x(62), x(g + 8)), -16, max(x(62), x(g + 8)), 16),
        _line("SCULPT", [(x(70), -10), (x(62), -10)]),            # endpiece, superior
        _line("SCULPT", [(x(70), 10), (x(62), 10)]),              # endpiece, inferior
        _line("SCULPT", [(x(g + 8), -4), (x(g), -4)]),            # nosepad, superior
        _line("SCULPT", [(x(g + 8), 12), (x(g), 12)]),            # nosepad, inferior
    ]
    if bridge_cut:
        curves.append(_line("SCULPT", [(x(g + 10), -22), (x(g + 10), -16)]))
    return curves


def _front(gap=6.0, *, bridge_cut=True, mount=True, extra=(), ghost=False,
           one_rim=False, shift=0.0):
    curves = _rim(-1, gap, bridge_cut) + ([] if one_rim else _rim(1, gap, bridge_cut))
    if mount:
        # the bridge's mount, from behind: one shape across the gap, 4 mm into
        # each rim's nasal end
        curves.append(_rect("HINGE", -(gap + 4), -20, gap + 4, -17))
    curves += list(extra)
    for curve in curves:                          # a drawing off its origin
        for node in curve["nodes"]:
            node["x"] += shift
    return {"mirror": {"x": 0.0, "enabled": ghost}, "curves": curves}


def _gdraw(path, front):
    ET.register_namespace("", _SVG_NS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab in TABS:
            state = front if tab == "front" else {"mirror": {"enabled": False},
                                                   "curves": []}
            root = ET.Element(f"{{{_SVG_NS}}}svg")
            ET.SubElement(root, f"{{{_SVG_NS}}}metadata").text = json.dumps(state)
            zf.writestr(f"{tab}.svg", ET.tostring(root, xml_declaration=True,
                                                  encoding="utf-8"))
    return path


def _workspace(tmp_path, **kw):
    return build_workspaces_from_gdraw(_gdraw(tmp_path / "rims.gdraw", _front(**kw)))[0][0]


@pytest.fixture(scope="module")
def rims(tmp_path_factory):
    return _workspace(tmp_path_factory.mktemp("rims"))


# ------------------------------------------------------------------ intake

def test_each_rim_that_holds_a_lens_is_a_body():
    from guildmodel.core.io_import.normalize import assemble_outline

    left, right = box(-70, -22, -6, 22), box(6, -22, 70, 22)
    lenses = [box(-62, -16, -14, 16), box(14, -16, 62, 16)]
    a = assemble_outline([list(left.exterior.coords), list(right.exterior.coords)],
                         lenses=lenses)
    assert isinstance(a.polygon, MultiPolygon) and len(a.bodies) == 2
    assert a.bodies[0].centroid.x < 0 < a.bodies[1].centroid.x       # OS first
    assert a.stray == []


def test_without_lenses_or_with_none_held_a_second_contour_is_a_stray():
    """The rule GuildDraw states: a contour that holds no lens is a stray."""
    from guildmodel.core.io_import.normalize import assemble_outline

    left, right = box(-70, -22, -6, 22), box(6, -22, 70, 22)
    rings = [list(left.exterior.coords), list(right.exterior.coords)]
    for lenses in ((), [box(-62, -16, -14, 16)]):
        a = assemble_outline(rings, lenses=lenses)
        assert isinstance(a.polygon, Polygon) and len(a.stray) == 1


def test_the_validator_calls_a_rim_a_body_not_a_stray():
    from guildmodel.core.io_import.validate import validate

    rims = {"OUTLINE": [box(-70, -22, -6, 22), box(6, -22, 70, 22)],
            "LENS": [box(-62, -16, -14, 16), box(14, -16, 62, 16)]}
    result = validate(rims)
    assert result.ok and not any("outside" in w for w in result.warnings)


def test_the_front_reads_as_two_rims_and_two_lenses(rims):
    assert isinstance(rims.outline_poly, MultiPolygon)
    assert len(rims.outline_poly.geoms) == 2 and rims.outline_stray == []
    assert rims.lens_od.centroid.x > 0 > rims.lens_os.centroid.x
    assert rims.lens_outside == []
    assert rims.boxing.a == pytest.approx(48.0, abs=0.05)
    assert rims.boxing.dbl == pytest.approx(28.0, abs=0.05)
    assert rims.castle_ready


# ------------------------------------------------------------------ the partition

def test_each_rim_partitions_as_a_standard_half(rims):
    """The maker's ask: no stray `eyewire_inferior_od_2`, no 'non-standard
    layout', and the nosepad where the nosepad is."""
    p = rims.partition
    assert p.separated and p.matched and p.classified
    assert {z.name for z in p.zones} == HALF_NAMES
    assert all(e.canonical for e in p.edges)
    assert {e.name for e in p.edges} == {
        f"{c}_{s}" for s in ("od", "os") for c in
        ("endpiece_superior", "endpiece_inferior", "bridge_superior",
         "nosepad_superior", "nosepad_inferior")}
    # posterior: superior is +y; the rim's bridge end sits over its nosepad
    for side in ("od", "os"):
        assert (p.zone(f"bridge_{side}").polygon.centroid.y
                > p.zone(f"nosepad_{side}").polygon.centroid.y)
    # no zone spans the gap
    assert all(z.polygon.bounds[0] > 0 or z.polygon.bounds[2] < 0 for z in p.zones)


def test_rims_drawn_off_the_origin_are_told_apart(tmp_path):
    """The axis is midway between the rims' lenses, not x = 0: a pair drawn
    40 mm off the origin, both rims on one side of it, is still OD and OS."""
    p = _workspace(tmp_path, shift=40.0).partition
    assert p.matched and {z.name for z in p.zones} == HALF_NAMES
    od, os_ = p.zone("endpiece_od").polygon, p.zone("endpiece_os").polygon
    assert od.centroid.x > os_.centroid.x                       # posterior: OD on +x


def test_a_rim_without_the_bridge_cut_is_a_standard_half_of_four(tmp_path):
    p = _workspace(tmp_path, bridge_cut=False).partition
    assert p.matched and len(p.zones) == 8
    assert {z.kind for z in p.zones} == {"endpiece", "nosepad", "eyewire_superior",
                                         "eyewire_inferior"}


def test_a_rim_with_an_extra_cut_is_named_by_position(tmp_path):
    extra = [_line("SCULPT", [(-40, -22), (-40, -16)])]
    ws = _workspace(tmp_path, extra=extra)
    p = ws.partition
    assert p.classified and not p.matched and ws.castle_ready
    assert len(p.zones) == 11


def test_the_default_heights_follow_the_zones(rims):
    """Each rim takes the shop's per-kind heights: the nosepad at the nosepad's,
    the bridge end at the bridge's, as on an ordinary front."""
    from guildmodel.core.relief.castle import build_castle_relief

    castle = CastleParams()
    relief = build_castle_relief(rims.partition, castle, [], resolution=0.25)
    names = [z.name for z in rims.partition.zones]
    for zone in rims.partition.zones:
        cells = relief.field.z[relief.zone_index == names.index(zone.name)]
        # the terrace is the zone's commonest height; its seams are blends
        heights, counts = np.unique(np.round(cells, 2), return_counts=True)
        assert heights[counts.argmax()] == pytest.approx(
            castle.zones.for_kind(zone.kind)), zone.name


def test_a_lens_outside_every_body_stops_the_castle(tmp_path):
    """GuildDraw's rule, kept here too: only a body's lens is cut."""
    stray = _rect("LENS", 80, -10, 100, 10)
    ws = _workspace(tmp_path, extra=[stray], mount=False)
    assert len(ws.lens_outside) == 1 and not ws.castle_ready


def test_one_rim_and_one_lens_is_a_monocle(tmp_path):
    """The Ghost is never applied, so one rim drawn with it on is one rim and
    one lens: a monocle, named as a standard half and built like either rim
    of a pair."""
    ws = _workspace(tmp_path, one_rim=True, ghost=True, mount=False)
    assert isinstance(ws.outline_poly, Polygon)
    assert ws.lens_od is not None and ws.lens_os is None
    assert ws.lens_outside == [] and ws.castle_ready
    p = ws.partition
    assert not p.separated and p.halves and p.matched
    assert {z.name for z in p.zones} == {n for n in HALF_NAMES if n.endswith("_od")}


def test_a_monocle_builds_and_cuts(tmp_path):
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.relief.features import bridge_features_apply

    ws = _workspace(tmp_path, one_rim=True, mount=False)
    mesh = to_trimesh(build_castle_model(ws.partition, CastleParams()))
    assert mesh.body_count == 1 and verify_mesh(mesh).ok
    assert not bridge_features_apply(ws.partition)
    _, ops = _program(ws)
    assert len(_rings(ops["Perimeter"])) == 1 and len(_rings(ops["Eyewires"])) == 1


def test_a_monocle_forms_to_its_base_curve_alone(tmp_path):
    """A monocle has no second eye to wrap toward: the map takes no face form,
    whoever builds it, and the rim is one sphere apexed at its own lens. A
    rim drawn across the center line is apexed on the line, where theta = x/R
    is one sphere whatever the band (the 2.0 bug hunt). The press's wrap used
    to crease a monocle at the band."""
    from guildmodel.core.forming import ThermoformMap, bridge_geometry
    from guildmodel.core.forming.dies import die_map
    from guildmodel.core.project.schema import FormingMetadata

    forming = FormingMetadata().with_base_curve(6.0, 170.11)
    for shift in (0.0, 30.0, -30.0):
        ws = _workspace(tmp_path, one_rim=True, mount=False, shift=shift)
        geom = bridge_geometry(ws.partition, ws.lens_od, ws.lens_os)
        assert not geom.projects and not geom.wraps
        x0, _, x1, _ = ws.partition.body.bounds
        apex = 0.0 if x0 < 0.0 < x1 else ws.lens_od.centroid.x
        xs = np.linspace(x0, x1, 41)
        for fmap in (ThermoformMap.from_metadata(forming, bridge=geom),
                     die_map(forming, ws.partition, ws.lens_od, ws.lens_os)):
            assert fmap.wrap == 0.0 and fmap.p == 0.0
            theta = np.interp(xs, fmap._xs, fmap._theta)
            assert np.allclose(theta, (xs - apex) / fmap.R, atol=1e-9), shift
    # separated rims keep the face form: each rim turns about the bridge
    rims = _workspace(tmp_path, mount=False)
    assert bridge_geometry(rims.partition, rims.lens_od, rims.lens_os).wraps


def test_a_rim_drawn_in_pieces_is_reported(tmp_path):
    """GuildDraw refuses a contour in pieces; a file can still carry one, and
    each piece is closed on its own with a straight line, so intake counts
    them for the log rather than closing them in silence."""
    from guildmodel.core.io_import.gdraw import open_outline_count

    pieces = [_line("OUTLINE", [(-70, -22), (-6, -22), (-6, 22), (-70, 22)]),
              _line("OUTLINE", [(-70, 22), (-70, -22)])]
    assert open_outline_count({"curves": pieces}) == 2
    nearly = [_line("OUTLINE", [(-70, -22), (-6, -22), (-6, 22), (-70, 22),
                                (-70, -21.95)])]
    assert open_outline_count({"curves": nearly}) == 0       # within 0.1 mm: closed
    whole = _workspace(tmp_path)
    assert whole.open_outline == 0
    front = _front(mount=False)
    front["curves"] = [c for c in front["curves"]
                       if not (c["layer"] == "OUTLINE" and c["nodes"][0]["x"] < 0)] + pieces
    ws = build_workspaces_from_gdraw(_gdraw(tmp_path / "pieces.gdraw", front))[0][0]
    assert ws.open_outline == 2


def test_the_groove_shrinks_both_rims_apertures(rims):
    from guildmodel.core.geometry.rings import lip_body, lip_partition

    lip = lip_partition(rims.partition, 0.6)
    assert lip.separated and {z.name for z in lip.zones} == HALF_NAMES
    body = lip_body(rims.partition.body, 0.6)
    assert isinstance(body, MultiPolygon)
    assert body.area == pytest.approx(rims.partition.body.area + 2 * (
        48 * 32 - 46.8 * 30.8), rel=2e-3)


# ------------------------------------------------------------------ the model

@pytest.mark.parametrize("kernel", ["mesh", "raster", "brep"])
def test_every_kernel_builds_a_body_per_rim(rims, kernel):
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.gui.mesh_build import build_component_mesh

    if kernel == "brep":
        pytest.importorskip("OCP")

    spec = {"mode": "castle", "partition": rims.partition, "castle": CastleParams(),
            "hinge": rims.hinge_polys, "inlay": rims.inlay_polys}
    mesh, _, _ = build_component_mesh(spec, resolution=0.2, kernel=kernel)
    verdict = verify_mesh(mesh, expected_bodies=2)
    assert verdict.ok, verdict.problems
    assert mesh.body_count == 2
    halves = sorted(m.volume for m in mesh.split(only_watertight=False))
    assert halves[0] == pytest.approx(halves[1], rel=2e-3)          # mirror twins


def test_the_mount_pocket_cuts_each_rims_end(rims):
    """One HINGE shape across the gap: each rim loses its own end of it, and
    the gap is waste. A pocket that reaches no endpiece is a mount, its depth
    taken from the terrace it sits in, here the rims' bridge ends."""
    from shapely import contains_xy

    from guildmodel.core.relief.castle import build_castle_relief

    castle = CastleParams()
    mount = rims.hinge_polys[0]
    assert mount.intersection(rims.partition.parts[0]).area == pytest.approx(12.0)
    assert mount.intersection(rims.partition.parts[1]).area == pytest.approx(12.0)
    relief = build_castle_relief(rims.partition, castle, rims.hinge_polys, resolution=0.2)
    f = relief.field
    inside = contains_xy(mount, relief.Xs.ravel(), relief.Ys.ravel()).reshape(f.z.shape)
    floor = castle.zones.bridge_mm - castle.hinge_pocket_depth_mm
    cut = inside & relief.inside
    assert cut.any()
    assert np.allclose(f.z[cut], floor)
    for x in (-8.0, 8.0):                          # in each rim's end of the shape
        col = int(round((x - f.origin[0]) / f.resolution))
        row = int(round((18.5 - f.origin[1]) / f.resolution))     # posterior: y up
        assert relief.inside[row, col] and f.z[row, col] == pytest.approx(floor)


def test_a_hinge_pocket_keeps_the_endpiece_rule_and_a_mount_does_not_tilt(rims):
    """A pocket on an endpiece is a hinge pocket: the endpiece height less the
    depth, tilted by the hinge pocket angle. The mount stays flat."""
    from guildmodel.core.geometry.heights import zone_heights
    from guildmodel.core.geometry.pocket_floor import castle_pocket_floors

    castle = CastleParams(hinge_pocket_angle_deg=5.0)
    p = rims.partition
    hinge = Polygon([(64, -4), (69, -4), (69, 4), (64, 4)])        # the OD endpiece
    mount = rims.hinge_polys[0]
    floors = dict((id(poly), floor) for poly, floor in castle_pocket_floors(
        [hinge, mount], castle, p, zone_heights(p, castle, None)))
    assert floors[id(hinge)].z_fixed == pytest.approx(
        castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm)
    assert not floors[id(hinge)].flat
    assert floors[id(mount)].flat and floors[id(mount)].z_fixed == pytest.approx(
        castle.zones.bridge_mm - castle.hinge_pocket_depth_mm)
    # without the partition every pocket is a hinge pocket, as before
    (_, plain), = castle_pocket_floors([mount], castle)
    assert plain.z_fixed == pytest.approx(
        castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm)


def test_the_pocket_depth_answers_to_the_mounts_terrace(rims):
    from guildmodel.core.project.limits import MIN_POCKET_FLOOR_MM, castle_limits

    castle = CastleParams()
    limits = castle_limits(castle, rims.partition, hinge_polys=rims.hinge_polys)
    depth = limits["hinge_pocket_depth_mm"]
    assert depth.high == pytest.approx(castle.zones.bridge_mm - MIN_POCKET_FLOOR_MM)
    assert "bridge mount" in depth.reason


def test_a_front_mounted_bridge_seat_cuts_each_rims_end(tmp_path):
    """The bridge mounting from the front: the same shape on INLAY, cut on the
    visible face into each rim's end, and posted in the anterior setup, cut
    first with the front face up (2.0)."""
    from guildmodel.core.cam.two_sided import plan_two_sided
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.zmap import castle_relief

    ws = _workspace(tmp_path, mount=False, extra=[_rect("INLAY", -10, -20, 10, -17)])
    (seat,) = ws.castle_params.inlays
    assert seat.face == "anterior" and seat.enabled
    plain = to_trimesh(build_castle_model(ws.partition, CastleParams()))
    cut = to_trimesh(build_castle_model(ws.partition, ws.castle_params,
                                        inlays=ws.inlay_polys))
    assert cut.body_count == 2
    assert plain.volume - cut.volume == pytest.approx(2 * 12.0 * seat.depth_mm, rel=1e-3)

    relief = castle_relief(ws.partition, ws.castle_params, [], kernel="mesh",
                           resolution=0.3, inlays=ws.inlay_polys)
    job = plan_two_sided(relief, ws.castle_params, [], TOOLS["flat_3175"],
                         CastleCamParams(), TOOLS, inlay_polys=ws.inlay_polys)
    assert job.two_sided and [op.name for op in job.anterior] == ["Inlays"]
    assert job.setups[0].side == "anterior"


def test_bridge_features_stand_down_on_separated_rims(rims):
    """The pad splay sits under a one-piece bridge and the bridge relief is
    scooped into it; separated rims have neither, and the castle is unchanged."""
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.relief.features import default_splay_run_mm

    plain = build_castle_relief(rims.partition, CastleParams(), [], resolution=0.25)
    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.bridge_relief.enabled = True
    featured = build_castle_relief(rims.partition, castle, [], resolution=0.25)
    assert np.array_equal(plain.field.z, featured.field.z)
    assert featured.feature_band is None
    assert default_splay_run_mm(rims.partition) is None


def test_an_outline_edge_feature_follows_each_rim(rims):
    from guildmodel.core.relief.castle import build_castle_relief

    def carved(zones):
        castle = CastleParams(edge_features=[EdgeFeature(
            id="round", label="Round-over", face="posterior", edge="outline",
            zones=zones, profile="chamfer", width_mm=1.5, angle_deg=45.0,
            blend_mm=2.0, mirror=False)])
        relief = build_castle_relief(rims.partition, castle, [], resolution=0.25)
        band = relief.feature_band
        xs = relief.Xs[band]
        return (xs > 0).any(), (xs < 0).any()

    assert carved([]) == (True, True)                  # the whole outline: both rims
    assert carved(["eyewire_superior_od"]) == (True, False)


# ------------------------------------------------------------------ the CAM

def _program(ws, castle=None, tool="flat_3175"):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.relief.castle import build_castle_relief

    castle = castle or CastleParams()
    relief = build_castle_relief(ws.partition, castle, ws.hinge_polys, resolution=0.2)
    ops = generate_castle_program(relief, castle, ws.hinge_polys, TOOLS[tool],
                                  params=CastleCamParams(), tools_cfg=TOOLS)
    return relief, {op.name: op for op in ops}


def _rings(op):
    """The distinct XY loops an op cuts, one per ring through its depth stack
    (told apart by extent, which a tabbed release pass keeps). A pass over the
    pad block alone is an open run of a ring its full passes show (2.0)."""
    loops = {}
    for path in op.paths:
        xy = np.asarray(path)[:, :2]
        if not np.allclose(xy[0], xy[-1]):
            continue
        key = tuple(np.round([*xy.min(axis=0), *xy.max(axis=0)], 1))
        loops.setdefault(key, xy)
    return list(loops.values())


def test_the_program_releases_both_rims(rims):
    from guildmodel.core.cam.castle_ops import work_holding_keepouts

    relief, ops = _program(rims)
    perimeter = _rings(ops["Perimeter"])
    assert len(perimeter) == 2
    for loop, rim in zip(sorted(perimeter, key=lambda xy: xy[:, 0].mean()),
                         rims.partition.parts):
        ring = Polygon(loop)
        assert ring.contains(rim) and not ring.contains(Point(0.0, 0.0))
    assert len(_rings(ops["Eyewires"])) == 2
    keep = work_holding_keepouts(relief.mask_body, CastleParams().stock, 1.5875)
    centers = {(round(x, 1), round(y, 1)) for x, y, _ in keep}
    for lens in (rims.lens_od, rims.lens_os):
        assert (round(lens.centroid.x, 1), round(lens.centroid.y, 1)) in centers
    assert ops["Perimeter"].notes == []


def test_rims_too_close_for_the_tool_get_one_ring_and_a_note(tmp_path):
    """Two rings a gap too narrow apart would each cut into the other rim; one
    ring round both cuts neither, and the maker is told the gap stays."""
    ws = _workspace(tmp_path, gap=1.0, mount=False)
    _, ops = _program(ws)
    assert len(_rings(ops["Perimeter"])) == 1
    assert any("rims are 2.00 mm apart" in note for note in ops["Perimeter"].notes)


def test_the_fallback_profile_cuts_a_perimeter_per_rim(rims):
    from guildmodel.core.cam.profile import profile_cut

    passes = profile_cut(rims.outline_poly, 1.5875, 4.0, 2.0)
    assert passes and all(len(p) == 2 for p in passes)


def test_the_posterior_after_the_flip_releases_both_rims(rims):
    """A two-sided job's through-cuts are the posterior's, the one-sided
    program's (2.0): both rims are released there, on the onion skin."""
    from guildmodel.core.cam.two_sided import plan_two_sided
    from guildmodel.core.zmap import castle_relief

    castle = CastleParams(
        edge_features=[EdgeFeature(
            id="brow", label="Brow", face="anterior", edge="outline",
            zones=["eyewire_superior_od"], profile="chamfer", width_mm=2.0,
            angle_deg=45.0, blend_mm=4.0, mirror=True)])
    relief = castle_relief(rims.partition, castle, rims.hinge_polys, kernel="mesh",
                           resolution=0.3)
    job = plan_two_sided(relief, castle, rims.hinge_polys, TOOLS["flat_3175"],
                         CastleCamParams(), TOOLS)
    assert job.two_sided
    back = {op.name: op for op in job.posterior}
    assert len(_rings(back["Perimeter"])) == 2 and len(_rings(back["Eyewires"])) == 2
    assert not {"Perimeter", "Eyewires"} & {op.name for op in job.anterior}


# ------------------------------------------------------------------ the rest

def test_the_verdict_expects_a_body_per_rim():
    import trimesh

    from guildmodel.core.mesh_check import verify_mesh

    two = trimesh.util.concatenate([trimesh.creation.box((10, 10, 4)),
                                    trimesh.creation.box((10, 10, 4)).apply_translation((30, 0, 0))])
    assert verify_mesh(two, expected_bodies=2).ok
    assert not verify_mesh(two).ok
    three = trimesh.util.concatenate([two, trimesh.creation.box((10, 10, 4))
                                      .apply_translation((60, 0, 0))])
    assert "one body per rim" in verify_mesh(three, expected_bodies=2).summary
    # rims a build joined are not a front with separated rims (the 2.0 bug hunt)
    joined = verify_mesh(trimesh.creation.box((40, 10, 4)), expected_bodies=2)
    assert not joined.ok and "joined" in joined.summary


def test_a_sculpt_dropped_on_the_front_lands_on_a_rim(rims):
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.model.sculpt import snap_target

    host = to_trimesh(build_castle_model(rims.partition, CastleParams()))
    target = snap_target(host, "posterior", None, outline=rims.outline_poly)
    assert rims.outline_poly.buffer(1e-6).contains(Point(*target.point[:2]))
    assert np.isfinite(target.point[2]) and target.point[2] > 0.0


def test_separated_rims_form_to_the_base_curve_with_no_projection(rims):
    """The maker's rule: the base curve forms, the bridge projection does not,
    whatever the metadata carries; the dies get no bridge punch."""
    from guildmodel.core.forming import ThermoformMap, bridge_geometry, build_dies
    from guildmodel.core.project.schema import FormingMetadata

    forming = FormingMetadata().with_base_curve(6.0, 170.0, bridge_projection_mm=3.0)
    bridge = bridge_geometry(rims.partition, rims.lens_od, rims.lens_os)
    assert not bridge.projects
    fmap = ThermoformMap.from_metadata(forming, bridge=bridge)
    assert fmap.p == 0.0 and fmap.R == pytest.approx(forming.base_radius_mm)
    assert not fmap.is_flat
    dies = build_dies(rims.partition, CastleParams(), forming, rims.lens_od, rims.lens_os)
    assert dies.punch is None and dies.anvil is None


def test_the_dies_take_both_rims(rims):
    from guildmodel.core.forming import build_dies
    from guildmodel.core.project.schema import FormingMetadata

    forming = FormingMetadata().with_base_curve(6.0, 170.0)
    dies = build_dies(rims.partition, CastleParams(), forming, rims.lens_od, rims.lens_os)
    assert dies.posterior.volume() > 0 and dies.anterior.volume() > 0
    width, height = dies.report["outer_mm"]
    assert width > 140.0                       # both rims, gap and all, under one die


@pytest.mark.gui
def test_the_window_opens_separated_rims(tmp_path, monkeypatch):
    """Opening and activating the front runs every per-tab refresh (the splay
    default among them) on a two-body front."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    win._load_model(_gdraw(tmp_path / "rims.gdraw", _front()))
    win._activate_workspace(0)
    assert win._partition is not None and win._partition.separated
    assert "a standard half per rim" in win.params.zones_status.text()
