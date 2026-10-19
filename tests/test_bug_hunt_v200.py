"""The 2.0 bug hunt, in the core (2026-10-16).

Each test here pins a defect a review found before the 2.0 release, fixed the
same day. The window's findings are in `test_bug_hunt_v200_gui.py`.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

CONFIG = Path(__file__).parents[1] / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rims(tmp_path_factory):
    """The two-rim front of `test_separated_rims`, its mount under the pad block."""
    from tests.test_separated_rims import _workspace
    return _workspace(tmp_path_factory.mktemp("rims"))


# ------------------------------------------------------------------ the CAM

def test_a_pocket_under_the_pad_block_starts_above_the_pad(rims):
    """The pockets are cut first, on raw stock, and every one began its
    descent at the blank's top: a separated-rims mount, under the pad block,
    plunged 3.5 mm into it and lapped its first ramp 4 mm deep."""
    from guildmodel.core.cam.castle_ops import generate_castle_program, pocket_starts
    from guildmodel.core.project.schema import CastleCamParams, CastleParams
    from guildmodel.core.relief.castle import build_castle_relief

    castle = CastleParams()
    stock = castle.stock
    assert pocket_starts(rims.hinge_polys, stock) == [stock.total_pad_height_mm + 0.5]
    relief = build_castle_relief(rims.partition, castle, rims.hinge_polys, resolution=0.3)
    ops = {op.name: op for op in generate_castle_program(
        relief, castle, rims.hinge_polys, TOOLS["flat_3175"],
        params=CastleCamParams(), tools_cfg=TOOLS)}
    first = np.asarray(ops["Component Pockets"].paths[0])
    assert first[0, 2] == pytest.approx(stock.total_pad_height_mm + 0.5)
    # an endpiece's hinge pocket, off the pad block, starts where it always did
    from shapely.geometry import box
    assert pocket_starts([box(60, -4, 66, 4)], stock) == [stock.blank_thickness_mm + 0.5]


def test_a_formed_pockets_floor_is_fitted_on_the_part_not_the_gap(rims):
    """On a pre-formed blank a pocket's floor is a plane fitted to the formed
    relief under it. The fit took every cell, and a mount across the gap
    between separated rims took the gap's cells, which the relief holds at 0,
    and set its floor 3 mm below the rims'."""
    from guildmodel.core.cam.castle_ops import formed_pocket_floors
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.core.project.schema import (CastleParams, FormingMetadata,
                                                StockDefinition)
    from guildmodel.core.zmap import castle_relief
    from shapely import contains_xy

    castle = CastleParams(stock=StockDefinition(use_pad_block=False, preformed=True))
    forming = FormingMetadata().with_base_curve(6.0, 170.0)
    bridge = bridge_geometry(rims.partition, rims.lens_od, rims.lens_os)
    relief = castle_relief(rims.partition, castle, rims.hinge_polys, kernel="mesh",
                           resolution=0.3, forming=forming, bridge=bridge)
    from guildmodel.core.cam.castle_ops import split_across_rims

    halves = split_across_rims(relief.hinge_polys_formed, relief.partition)
    assert len(halves) == 2                       # one plane per rim
    f = relief.field
    X, Y = relief.Xs, relief.Ys
    for poly, floor in formed_pocket_floors(halves, castle, relief):
        # the floor, clear of the pocket's walls, as the fit samples it
        over = (contains_xy(poly.buffer(-0.3), X.ravel(), Y.ravel()).reshape(f.z.shape)
                & relief.inside)
        assert over.any()
        # the plane lies with the formed floor over its rim, not under it
        assert np.max(np.abs(floor.z(X[over], Y[over]) - f.z[over])) < 0.25


# ------------------------------------------------------------------ the post and the simulation

def test_the_simulation_reads_setup_words_as_setup_not_moves():
    """`G53 G0 Z0` is the retract to the top of travel before a rotary turns;
    `G38.2` probes and `G10 L20` sets an offset. Read as moves they put the
    tool at Z0 or Z-25 in the program's coordinates, through the stock."""
    from guildmodel.core.stock.program import parse_program

    runs = parse_program("G21 G90\nG0 Z11\nG0 X10 Y0\nG53 G0 Z0\nG0 A180\n"
                         "G38.2 Z-25 F100\nG10 L20 P2 Z0\nG0 X20 Y5\n")
    zs = [p[2] for r in runs for p in r.points][1:]      # after the start point
    assert min(zs) >= 11.0                     # nothing went down to Z0 or Z-25
    assert max(zs) >= 50.0                     # the retract lifted the tool


def test_the_rotary_turns_from_the_top_of_travel():
    """The indexed flip and the unwind turned the blank with the tool parked a
    few millimeters over the stock, inside the blank's swing."""
    from guildmodel.core.post.grbl import GRBLPost

    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=18000, feed_rate_mmpm=1200, plunge_rate_mmpm=300,
                    safe_z_mm=11.0, axes="XYZA", wcs="G55", index_a_deg=180.0)
    post.header("side two")
    post.end_program()
    lines = [ln.split(";")[0].strip() for ln in post.to_string().splitlines()]
    lines = [ln for ln in lines if ln]
    for i, ln in enumerate(lines):
        if ln.startswith("G0 A") or ln.startswith("G53 G0 A"):
            assert lines[i - 1] == "G53 G0 Z0", (i, ln)


def test_side_two_is_zeroed_where_its_program_expects():
    """Side two's probe ran to absolute Z-25 and made the plate's top Z0, and
    without the probe the note said to zero Z on the stock top. The program's
    Z0 is the program zero's face, the blank's bottom by default: the probe
    left every cut a blank's thickness and a plate high, and the note a
    blank's thickness deep."""
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import ProgramZero, StockDefinition

    stock = StockDefinition(use_pad_block=False)
    T = stock.blank_thickness_mm

    def post(z_ref):
        return GRBLPost(job_name="back_cut", material="acetate", tool_diameter_mm=3.175,
                        spindle_rpm=18000, feed_rate_mmpm=1200, plunge_rate_mmpm=300,
                        safe_z_mm=T + 5.0, wcs="G55",
                        work_offset=ProgramZero(z_ref=z_ref).work_offset(stock))

    bottom = post("bottom").probe_z_block(T, 6.0)
    assert bottom[1:4] == ["G91", "G38.2 Z-25.0 F100", "G90"]
    assert bottom[4] == f"G10 L20 P2 Z{T + 6.0:.3f}"     # the plate's top, from the bottom
    assert post("top").probe_z_block(T, 6.0)[4] == "G10 L20 P2 Z6.000"
    assert post("top").probe_z_block(T)[4] == "G10 L20 P2 Z0.000"
    # without the probe, the note names the value to set
    assert f"Z{T:.3f}" in post("bottom").rezero_note(T)
    assert "is Z0" in post("top").rezero_note(T)


def test_a_stored_program_is_simulated_from_its_program_zero(monkeypatch):
    """A stored program's coordinates are the design frame's plus the program
    zero's offset, and the simulation read them as the design frame's: a
    temple zeroed on its blank's corner and top face simulated as a cut
    beside and above the part, and failed."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from shapely.geometry import box
    from guildmodel.core.cam.castle_ops import build_tool_settings, write_castle_program
    from guildmodel.core.cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleCamParams, ProgramZero, TempleParams
    from guildmodel.core.relief.flat import place_temple_on_blank
    from guildmodel.gui.app import FlatSimWorker

    outline, hinges, t = box(-70.0, -6.0, 70.0, 6.0), [box(55.0, -3.0, 65.0, 3.0)], TempleParams()
    corner = ProgramZero(x_ref="left", y_ref="bottom", z_ref="top")
    offset = corner.work_offset(t.stock())
    assert all(abs(v) > 1.0 for v in offset)
    placed, placed_hinges, _ = place_temple_on_blank(
        outline, hinges, [], t.blank_length_mm, stock_side=t.stock_side,
        snap=t.snap_to_blank_end, origin_from_drawing=t.origin_from_drawing)
    ops = generate_temple_program(placed, [], t, TOOLS, hinge_polys=placed_hinges)
    ts, _ = build_tool_settings(ops, TOOLS, default_feed=600, default_plunge=200,
                                default_spindle=12000)
    f0 = ts[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm, safe_z_mm=9.0, work_offset=offset)
    write_castle_program(ops, post, tool_settings=ts, contour_op_names=TEMPLE_CONTOUR_OPS)

    done, errs = [], []
    worker = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinges,
                           cam_params=CastleCamParams(program_zero=corner), resolution=0.3,
                           program_text=post.to_string())
    worker.finished.connect(lambda r, lines, plan: done.append(r))
    worker.error.connect(errs.append)
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert done[0].status() == "ok" and not done[0].faults
    # read unshifted, the profile ran 85 mm along and 15 mm across: 96.4 %
    assert done[0].completeness.uncut_fraction < 0.005


def test_a_forced_anterior_turns_the_way_the_blank_does():
    """Two-sided On, a front with nothing cut on it: the anterior setup was
    made flat and mirrored in X whatever the flip. On the rotary, which turns
    the blank about X, its cuts ran where the part is not. A front with nothing
    on its anterior now posts the posterior alone, with a note (2.0), and the
    anterior relief itself still turns the way the blank does."""
    from guildmodel.core.cam.two_sided import anterior_setup_relief
    from guildmodel.core.cam.two_sided import plan_two_sided
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.post.machine import load_machine_profile
    from guildmodel.core.project.schema import CastleCamParams, CastleParams, StockDefinition
    from guildmodel.core.zmap import castle_relief

    raw = import_dxf(Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    partition = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                                [points_to_polygon(c) for c in raw["LENS"]], raw["SCULPT"])
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    castle = CastleParams(stock=StockDefinition(use_pad_block=False))
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.5)
    rotary = load_machine_profile("guild_cnc_rotary", CONFIG).rotary
    yc = float(rotary.center_y_mm)
    job = plan_two_sided(relief, castle, hinges, TOOLS["flat_3175"],
                         CastleCamParams(two_sided="on"), TOOLS, flip="rotary", rotary=rotary)
    assert not job.two_sided and any("nothing to cut" in n for n in job.notes)
    ra = anterior_setup_relief(relief, castle, flip="rotary", center_y=yc,
                               center_z=float(rotary.center_z_mm), force=True)
    x0, y0, x1, y1 = partition.body.bounds
    b = ra.partition.body.bounds
    assert b[0] == pytest.approx(x0, abs=1e-9) and b[2] == pytest.approx(x1, abs=1e-9)
    assert b[1] == pytest.approx(2 * yc - y1, abs=1e-9)
    assert b[3] == pytest.approx(2 * yc - y0, abs=1e-9)


def test_a_padded_blank_lies_front_face_up_on_its_spacer():
    """The anterior first (the maker, 2026-10-17): a blank with the pad block
    lies front face up on a spacer as thick as the pad, the pad in its
    cut-out, so the stack is what turns and Z0 is the stock's bottom on the
    bed for both setups. The anterior's stock is that stack; the posterior,
    after the flip, is the one-sided program on the stock as it always was."""
    from guildmodel.core.cam.two_sided import flip_height, plan_two_sided
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleCamParams, CastleParams, EdgeFeature
    from guildmodel.core.zmap import castle_relief

    raw = import_dxf(Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    partition = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                                [points_to_polygon(c) for c in raw["LENS"]], raw["SCULPT"])
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    brow = [z.name for z in partition.zones if z.name.startswith("eyewire_superior")][:1]
    castle = CastleParams(edge_features=[EdgeFeature(           # the shipped pad block
        id="brow", label="Brow", face="anterior", edge="outline", zones=brow,
        profile="chamfer", width_mm=2.0, angle_deg=45.0, blend_mm=6.0, mirror=True)])
    st = castle.stock
    stack, pad_t = st.total_pad_height_mm, st.total_pad_height_mm - st.blank_thickness_mm
    assert flip_height(st) == stack and pad_t > 0
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.5)
    job = plan_two_sided(relief, castle, hinges, TOOLS["flat_3175"], CastleCamParams(), TOOLS)
    assert job.two_sided
    front = job.relief_anterior
    assert float(front.stock_top.z.min()) == float(front.stock_top.z.max()) == stack
    assert sorted(set(np.unique(front.stock_bottom.z).round(6))) == [0.0, pad_t]
    assert job.castle_anterior.stock.blank_thickness_mm == stack       # a top-face zero
    assert job.setups[0].stock_top_mm == stack
    assert any("spacer" in n for n in job.setups[0].notes)
    # the anterior never cuts below its features, the spacer least of all
    deepest = min(float(np.min([q[2] for path in op.paths for q in path])) for op in job.anterior)
    assert deepest > stack - 3.0
    assert job.setups[1].stock_top_mm == stack and job.setups[1].flip == "manual"

def _links_outside(paths, region, r, above):
    """Feed segments below `above` that leave the region the tool center may
    reach: each one cuts a wall or an island."""
    from shapely.geometry import LineString
    reach = region.buffer(-(r - 0.02), join_style="round")
    return sum(1 for p in paths for a, b in zip(p[:-1], p[1:])
               if (a[2] < above or b[2] < above)
               and not reach.covers(LineString([a[:2], b[:2]])))


def test_a_pocket_whose_offsets_split_never_links_across_the_neck():
    """The cascade linked its rings with straight moves at the cutting level:
    a pocket with a neck narrower than the tool split into loops, and every
    link between them crossed the neck, cutting both of its walls."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    from guildmodel.core.cam.castle_ops import hinge_pocket_op
    from guildmodel.core.project.schema import CastleCamParams

    r = 3.175 / 2
    dumbbell = unary_union([box(0, 0, 8, 8), box(12, 0, 20, 8), box(7, 3, 13, 5)])
    op = hinge_pocket_op([dumbbell], floor_z=4.0, start_z=6.5, tool_radius_mm=r,
                         params=CastleCamParams())
    assert _links_outside(op.paths, dumbbell, r, 6.0) == 0
    # both lobes are cut to the floor
    for lobe in (box(0, 0, 8, 8), box(12, 0, 20, 8)):
        c = lobe.centroid
        assert any(abs(p[0] - c.x) < 2.5 and abs(p[1] - c.y) < 2.5 and p[2] == pytest.approx(4.0)
                   for path in op.paths for p in path)
    # a convex pocket posts one path, as before
    rect = hinge_pocket_op([box(0, 0, 12, 8)], floor_z=4.0, start_z=6.5, tool_radius_mm=r,
                           params=CastleCamParams())
    assert len(rect.paths) == 1


def test_an_inlay_seat_never_links_across_its_island():
    """A seat with an island was cleared by one path whose links ran straight
    across the island, cutting what the seat keeps."""
    from types import SimpleNamespace
    from shapely.geometry import Point, box
    from guildmodel.core.cam.inlay_ops import _seat_path
    from guildmodel.core.project.schema import CastleCamParams

    region = box(0, 0, 16, 10).difference(Point(8, 5).buffer(2.0))

    class Plane:
        flat, z_fixed, slope = True, 4.0, 0.0

        def extremes(self, g):
            return 4.0, 4.0

    class Reference:
        def extremes(self, g):
            return 6.0, 6.0

    seat = SimpleNamespace(region=region, outline=region, plane=Plane(), reference=Reference())
    paths = _seat_path(seat, 1.0, CastleCamParams(), 1.0)
    assert paths and _links_outside(paths, region, 1.0, 6.0) == 0


# ------------------------------------------------------------------ the intake

def test_a_curve_that_crosses_itself_keeps_its_area():
    """The repair buffered the ring, a line, whose buffer by 0 is always
    empty: an outline or a lens that crossed itself vanished."""
    from guildmodel.core.io_import.normalize import points_to_polygon
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert points_to_polygon(square).area == pytest.approx(100.0)
    # a small loop where the curve was joined
    looped = square + [(0, 0.5), (-0.2, 0.3), (0.1, 0.2)]
    assert points_to_polygon(looped).area == pytest.approx(100.0, abs=0.1)
    assert points_to_polygon([(0, 0), (10, 10), (10, 0), (0, 10)]).area == pytest.approx(25.0)
    # too few points for a ring: empty, not an exception
    assert points_to_polygon([(0, 0), (1, 1)]).is_empty


def test_one_unreadable_curve_does_not_stop_the_drawing():
    """A coordinate that is not a number, or a circle of no positive radius,
    raised out of the reader and the drawing never opened."""
    from guildmodel.core.io_import.gdraw import read_workspace_curves, unreadable_curve_count
    good = {"kind": "line", "layer": "OUTLINE", "closed": True,
            "nodes": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 5}]}
    state = {"curves": [
        good,
        {"kind": "circle", "layer": "HINGE", "radius": -2, "nodes": [{"x": 0, "y": 0}]},
        {"kind": "line", "layer": "LENS", "nodes": [{"x": None, "y": 0}, {"x": 1, "y": 1}]},
        None,
    ]}
    pts, curves = read_workspace_curves(state)
    assert len(pts["OUTLINE"]) == 1 and not pts["COMPONENT"] and not pts["LENS"]
    assert unreadable_curve_count(state) == 3
    assert read_workspace_curves({"curves": None})[0]["OUTLINE"] == []


def test_a_front_drawn_off_its_origin_is_named_about_its_own_axis():
    """The one-piece classifier took x = 0, the drawing's origin, for the
    front's axis: moved along x, the bridge, the nosepads and the sides were
    named against a line through one rim."""
    from shapely.affinity import translate
    from shapely.geometry import LineString
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]

    def zones(dx):
        sculpt = [list(translate(LineString(c), dx).coords) for c in raw["SCULPT"]]
        part = partition_zones(translate(outline, dx), [translate(p, dx) for p in lenses], sculpt)
        return part, sorted(z.name for z in part.zones)

    here, names = zones(0.0)
    moved, moved_names = zones(40.0)
    assert here.matched and moved.matched
    assert moved_names == names and "bridge" in names


def _front_workspace(curves):
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import ComponentWorkspace, derive_workspace
    layers: dict = {}
    for layer, pts in curves:
        layers.setdefault(layer, []).append(pts)
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="Frame Front",
                            layers=layers)
    return derive_workspace(ws)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_one_lens_in_an_outline_drawn_for_two_is_not_a_monocle():
    """With the Ghost never read, a front drawn whole with its second lens
    left to the Ghost reached the monocle path and was cut with the other
    eye solid."""
    whole = [("OUTLINE", _rect(-70, -22, 70, 22)), ("LENS", _rect(14, -16, 62, 16)),
             ("SCULPT", [(70, -10), (62, -10)]), ("SCULPT", [(70, 10), (62, 10)]),
             ("SCULPT", [(14, -4), (6, -4)]), ("SCULPT", [(14, 12), (6, 12)])]
    ws = _front_workspace(whole)
    assert ws.half_drawn and ws.partition is None and not ws.castle_ready
    # a monocle's outline is one rim round its lens
    rim = [("OUTLINE", _rect(6, -22, 70, 22))] + whole[1:]
    mono = _front_workspace(rim)
    assert not mono.half_drawn and mono.castle_ready


def test_a_third_lens_is_refused_not_guessed():
    """The partition took the first two lenses in drawing order, the boxing
    the same two, while the eyes were the outermost two."""
    curves = [("OUTLINE", _rect(-70, -22, 70, 22)), ("LENS", _rect(-62, -16, -14, 16)),
              ("LENS", _rect(-4, -3, 4, 3)), ("LENS", _rect(14, -16, 62, 16)),
              ("SCULPT", [(0, -22), (0, 22)])]
    ws = _front_workspace(curves)
    assert ws.extra_lenses == 1 and ws.partition is None and not ws.castle_ready
    assert ws.boxing is not None and ws.boxing.dbl == pytest.approx(28.0, abs=0.01)


# ------------------------------------------------------------------ forming

def test_a_pressed_blank_takes_only_what_the_dies_press():
    """The pre-formed CAM modeled the slab with the bridge projection and the
    face form whatever the dies carried. The shipped dies leave the
    projection to the bench: the bridge was cut against a slab 3 mm off the
    one in the nest."""
    from guildmodel.core.project.schema import FormingMetadata, PressDieParams
    f = FormingMetadata(bridge_projection_mm=3.0).with_base_curve(6.0, 170.0)
    assert f.pressed().bridge_projection_mm == 0.0
    assert f.pressed().face_form_deg == pytest.approx(170.0)
    both = f.model_copy(update={"dies": PressDieParams(bridge_in_die=True)})
    assert both.pressed().bridge_projection_mm == 3.0
    flat_face = f.model_copy(update={"dies": PressDieParams(face_form_in_die=False)})
    assert flat_face.pressed().face_form_deg == pytest.approx(180.0)


def test_a_grooved_pressed_front_is_cut_round_its_front_edge(rims):
    """With the lens groove on, the mask body stayed the back's lip body when
    the partition moved to the front's footprint: the perimeter and the
    eyewires were cut inside the front's edge by the walls' lean."""
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.core.geometry.regions import body_exteriors
    from guildmodel.core.project.schema import CastleParams, FormingMetadata, StockDefinition
    from guildmodel.core.zmap import castle_relief
    from shapely.geometry import Polygon

    castle = CastleParams(stock=StockDefinition(use_pad_block=False, preformed=True))
    castle.lens_groove.enabled = True
    forming = FormingMetadata().with_base_curve(6.0, 170.0)
    bridge = bridge_geometry(rims.partition, rims.lens_od, rims.lens_os)
    relief = castle_relief(rims.partition, castle, rims.hinge_polys, kernel="mesh",
                           resolution=0.3, forming=forming, bridge=bridge)
    assert relief.mask_body_override is not None
    for mask, part in zip(body_exteriors(relief.mask_body),
                          body_exteriors(relief.partition.body)):
        assert Polygon(mask).symmetric_difference(Polygon(part)).area < 0.5


# ------------------------------------------------------------------ the kernels

def test_the_raster_bezel_leaves_a_decorative_opening_square(tmp_path):
    """The mesh and B-Rep kernels bevel the lens openings only, by the
    maker's decision; the raster kernel beveled the aviator's bridge opening
    too."""
    import zipfile
    from shapely import contains_xy
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    gdraw = tmp_path / "aviator.gdraw"
    with zipfile.ZipFile(gdraw, "w") as zf:
        for f in sorted((Path(__file__).parent / "fixtures" / "aviator").iterdir()):
            zf.write(f, f.name)
    front = build_workspaces_from_gdraw(gdraw)[0][0]
    (hole,) = front.outline_holes
    plain = CastleParams()
    beveled = CastleParams()
    beveled.eyewire_bezel.enabled = True
    a = build_castle_relief(front.partition, plain, [], resolution=0.3)
    b = build_castle_relief(front.partition, beveled, [], resolution=0.3)
    # round the opening, clear of the lenses' own bands (the aviator's
    # opening sits within a few millimeters of its lenses)
    from shapely.geometry import Polygon
    from guildmodel.core.geometry.regions import body_interiors
    part = front.partition
    lenses = [Polygon(r) for r in body_interiors(part.body) if not part.is_hole(r)]
    clear = hole.buffer(3.0).difference(hole)
    for lens in lenses:
        clear = clear.difference(lens.buffer(beveled.eyewire_bezel.width_mm + 0.5))
    near = (contains_xy(clear, a.Xs.ravel(), a.Ys.ravel()).reshape(a.field.z.shape)
            & a.inside)
    assert near.any()
    assert np.allclose(a.field.z[near], b.field.z[near])
    # the lenses are beveled
    assert (b.field.z < a.field.z - 0.1).any()


# ------------------------------------------------------------------ the project file

def test_a_file_from_before_two_sided_machining_opens_one_sided(tmp_path):
    """A 1.8 file has no `two_sided` key and was cut from the back alone, its
    anterior features modeled and never posted. Read as Auto, it became a
    two-setup job on its first Generate."""
    import hashlib
    import json
    import zipfile
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import ProjectSchema

    path = tmp_path / "new.gmodel"
    save_gmodel(path, project=ProjectSchema(job_name="t"))
    assert load_gmodel(path).project.cam_params.two_sided == "auto"
    assert load_gmodel(path).migrated == []

    old = tmp_path / "old.gmodel"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(old, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        for name in src.namelist():
            data = src.read(name)
            if name == "project.json":
                proj = json.loads(data)
                proj["cam_params"].pop("two_sided")
                data = json.dumps(proj).encode("utf-8")
                manifest["contents"][name]["sha256"] = hashlib.sha256(data).hexdigest()
            if name != "manifest.json":
                dst.writestr(name, data)
        dst.writestr("manifest.json", json.dumps(manifest))
    bundle = load_gmodel(old)
    assert bundle.project.cam_params.two_sided == "off" and bundle.migrated


def test_a_damaged_project_file_is_a_gmodel_error(tmp_path):
    """A damaged member raised its own error past the window's handler, and a
    damaged file opened from the desktop closed the app at launch."""
    import zipfile
    from guildmodel.core.project.gmodel import GModelError, load_gmodel
    bad = tmp_path / "bad.gmodel"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", "{not json")
        zf.writestr("project.json", "{}")
    with pytest.raises(GModelError):
        load_gmodel(bad)
    with pytest.raises(GModelError):
        load_gmodel(tmp_path / "missing.gmodel")


def test_seats_keep_their_settings_when_the_front_moves_on_its_blank():
    """The seats' settings find their seats again by centroid, and the
    centroids stayed behind when the front moved: two seats 5 mm apart on a
    front drawn off center swapped settings at every toggle."""
    from guildmodel.core.project.schema import CastleParams, ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace, derive_workspace,
                                                     place_front_on_blank)

    curves = [("OUTLINE", _rect(-60, -22, 80, 22)), ("LENS", _rect(-52, -16, -4, 16)),
              ("LENS", _rect(24, -16, 72, 16)), ("SCULPT", [(10, -22), (10, 22)]),
              ("INLAY", _rect(5, 17, 8, 20)), ("INLAY", _rect(10, 17, 13, 20))]
    layers: dict = {}
    for layer, pts in curves:
        layers.setdefault(layer, []).append(pts)
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="Frame Front",
                            layers=layers, castle_params=CastleParams())
    derive_workspace(ws)
    seats = ws.castle_params.inlays
    assert len(seats) == 2
    # side by side, 5 mm apart; the front moves 10 mm when it is centered
    right = max(range(2), key=lambda i: ws.inlay_polys[i].centroid.x)
    ws.castle_params.inlays = [f.model_copy(update={"depth_mm": 2.0 if i == right else 0.3})
                               for i, f in enumerate(seats)]

    def depth_of_right():
        i = max(range(2), key=lambda k: ws.inlay_polys[k].centroid.x)
        return ws.castle_params.inlays[i].depth_mm

    for origin in (False, True, False):
        assert place_front_on_blank(ws, origin)
        assert depth_of_right() == 2.0, origin


def test_a_value_out_of_range_is_corrected_and_said_so(tmp_path):
    """A skin of -2 posted a block's profile inside its lens, a feed of -500
    passed, and a NaN, written back as null, left a file that no longer
    opened. Such a value is replaced as the file is read, and the open says
    which; a refusal would turn away a hand-edited file that opens today."""
    import hashlib
    import json
    import math
    import zipfile
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    from guildmodel.core.project.schema import CastleCamParams, CastleParams, ProjectSchema

    assert CastleParams(onion_skin_mm=-2.0).onion_skin_mm == CastleParams().onion_skin_mm
    assert CastleCamParams(feed_rate_mmpm=-500.0).feed_rate_mmpm is None
    path = tmp_path / "p.gmodel"
    save_gmodel(path, project=ProjectSchema(job_name="t"))
    bad = tmp_path / "bad.gmodel"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(bad, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        for name in src.namelist():
            data = src.read(name)
            if name == "project.json":
                proj = json.loads(data)
                proj["castle"]["onion_skin_mm"] = -2.0
                proj["cam_params"]["rough_axial_stock_mm"] = math.nan
                data = json.dumps(proj).encode("utf-8")         # NaN is written bare
                manifest["contents"][name]["sha256"] = hashlib.sha256(data).hexdigest()
            if name != "manifest.json":
                dst.writestr(name, data)
        dst.writestr("manifest.json", json.dumps(manifest))
    bundle = load_gmodel(bad)
    assert bundle.project.castle.onion_skin_mm == CastleParams().onion_skin_mm
    assert math.isfinite(bundle.project.cam_params.rough_axial_stock_mm)
    said = " ".join(bundle.migrated)
    assert "onion_skin_mm" in said and "rough_axial_stock_mm" in said


# ------------------------------------------------------------------ the verdict

def _box_stock(z, res=0.25, shape=(40, 40)):
    from guildmodel.core.relief.heightfield import Heightfield
    from guildmodel.core.stock import DexelStock
    zz = np.asarray(z, dtype=np.float64)
    return DexelStock.from_heightfield(Heightfield(z=zz, origin=(0.0, 0.0), resolution=res),
                                       z_bottom=-1.0)


def test_one_piece_left_standing_is_judged_by_its_volume():
    """The verdict judged the uncut fraction of the body: a hinge pocket left
    uncut is a fraction of a percent, and passed. One piece standing more than
    2 mm³ fails it, more than 0.5 mm³ warns; the corners a round tool cannot
    reach, and the grid's slivers, are not pieces."""
    from guildmodel.core.stock.compare import compare
    target = np.full((40, 40), 4.0)
    target[10:22, 10:22] = 3.0                       # a 3 x 3 mm pocket, 1 mm deep
    inside = np.ones((40, 40), dtype=bool)
    report = compare(_box_stock(np.full((40, 40), 4.0)), _box_stock(target), inside)
    assert report.uncut_fraction < 0.10                # 9 %: the fractions alone did not fail it
    # its inside, the cells along its walls left to the grid: 2.25 mm square
    assert report.largest_piece_mm3 == pytest.approx(2.25 ** 2, rel=0.05)
    assert report.status() == "fail" and "one piece" in report.piece_line()
    corner = target.copy()
    corner[10:22, 10:22] = 4.0
    corner[10:12, 10:12] = 3.0                         # 0.25 mm³ in a corner
    left = np.where(corner < 4.0, 4.0, corner)
    assert compare(_box_stock(left), _box_stock(corner), inside).status() == "ok"


def test_a_cut_into_a_wall_is_a_gouge_beside_the_step():
    """The gouge check kept 1.7 mm off every step for the grid's sake, and a
    cut into the wall itself, which takes the wall's whole height, passed in
    that band. A gouge deeper than a millimeter counts from two cells out."""
    from guildmodel.core.stock.compare import compare
    target = np.full((40, 40), 2.0)
    target[:, 20:] = 5.0                               # a 3 mm step at x = 5 mm
    stock = target.copy()
    stock[10:30, 23:25] = 2.0                          # 0.75 mm into the high side: 3 mm deep
    report = compare(_box_stock(stock), _box_stock(target), np.ones((40, 40), dtype=bool))
    assert report.gouge_cells > 0 and report.max_gouge_mm == pytest.approx(3.0)
    assert report.status() == "fail"
    shallow = target.copy()
    shallow[10:30, 23:25] = 4.7                        # 0.3 mm by the step: the grid's
    assert compare(_box_stock(shallow), _box_stock(target),
                   np.ones((40, 40), dtype=bool)).gouge_cells == 0
    # What the blank never had is short, not gouged: a tower taller than the
    # stock, beside its step, as a pressed blank's nosepads stand over a slab
    # with no pad block. Without `top0` the tier counted it as a cut.
    tower = target.copy()
    tower[10:30, 21:30] = 7.0                          # 2 mm over a 5 mm stock top
    blank = np.minimum(tower, 5.0)                     # the stock, uncut
    whole = np.ones((40, 40), dtype=bool)
    assert compare(_box_stock(blank), _box_stock(tower), whole).gouge_cells > 0
    assert compare(_box_stock(blank), _box_stock(tower), whole,
                   top0=np.full((40, 40), 5.0)).gouge_cells == 0
    # and a pressed blank's lean takes a wall's whole height on purpose
    leaned = compare(_box_stock(stock), _box_stock(target), np.ones((40, 40), dtype=bool),
                     gouge_rim_margin_mm=1.7 + 1.0, wall_lean_mm=1.0)
    assert leaned.gouge_cells == 0


def test_the_verdict_asks_whether_the_part_is_released(monkeypatch):
    """The verdict looked inside the body only: a perimeter or an eyewire that
    did not cut through passed it. A stored program missing either fails,
    and the verdict's stock no longer stands a millimeter over the stock,
    which read the nosepads' tops as uncut on every front."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.cam.castle_ops import (build_tool_settings, generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleCamParams, CastleParams
    from guildmodel.core.zmap import castle_relief
    from guildmodel.gui.app import SimWorker

    raw = import_dxf(Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    partition = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                                [points_to_polygon(c) for c in raw["LENS"]], raw["SCULPT"])
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    castle, cam = CastleParams(), CastleCamParams(two_sided="off")
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.15)
    ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"], params=cam,
                                  tools_cfg=TOOLS)
    ts, _ = build_tool_settings(ops, TOOLS, default_feed=1200, default_plunge=300,
                                default_spindle=18000)
    f0 = ts[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm,
                    safe_z_mm=cam.safe_z_for(castle.stock.total_pad_height_mm),
                    feed_plane_mm=castle.stock.total_pad_height_mm + 1.0)
    write_castle_program(ops, post, tool_settings=ts)
    text = post.to_string()

    def without(section):
        out, skip = [], False
        for ln in text.splitlines():
            if ln.startswith("; ---"):
                skip = section in ln
            if not skip:
                out.append(ln)
        return "\n".join(out) + "\n"

    def verdict(program):
        done, errs = [], []
        w = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                      program_text=program)
        w.kernel = "mesh"
        w.finished.connect(lambda r, lines, plan: done.append(r))
        w.error.connect(errs.append)
        w.run()
        assert errs == [], errs[0] if errs else ""
        return done[0]

    whole = verdict(text)
    assert whole.status() == "ok" and whole.completeness.uncut_fraction < 0.005
    assert any("not released" in f for f in verdict(without("Perimeter")).faults)
    assert any("lens opening" in f for f in verdict(without("Eyewires")).faults)


def test_the_dock_shows_only_what_the_kernel_builds(monkeypatch, tmp_path):
    """A control a kernel ignores is not shown (the maker, 2026-10-17). The
    Sculpts section and the Sculpt Finish op belong to the mesh kernel; the
    splay's crest blend, the raster's alone, is gone, and its seam blend,
    which every kernel cuts, takes its place."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import SCULPTS_FOLD, ParamsPanel

    p = ParamsPanel()
    box = p._folds[SCULPTS_FOLD]
    for kernel, shown in (("mesh", True), ("brep", False), ("raster", False), ("mesh", True)):
        p.set_model_kernel(kernel)
        assert box.isHidden() is not shown, kernel
        assert p.op_checks["Sculpt Finish"].isHidden() is not shown, kernel
        assert all(w.isHidden() is not shown for w in p._op_tool_rows["Sculpt Finish"]), kernel
    assert not hasattr(p, "splay_blend")
    assert p.castle_params().pad_splay.seam_blend_mm == 1.0
    p.splay_seam.setValue(0.6)
    assert p.castle_params().pad_splay.seam_blend_mm == pytest.approx(0.6)


def test_a_kernel_without_sculpts_says_it_leaves_them_off():
    from guildmodel.gui.app import sculpts_left_off

    class Front:
        def resolved_sculpts(self):
            return ["logo", "crest"]

    assert sculpts_left_off(Front(), "mesh") == ""
    assert sculpts_left_off(None, "brep") == ""
    note = sculpts_left_off(Front(), "brep")
    assert note.startswith("The B-Rep kernel builds no sculpts") and "2 sculpts are left off" in note
