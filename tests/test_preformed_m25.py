"""The pre-curved blank (BUILDPLAN M25 §10.3), on the demo.

A flat project posts as it did: the formed path is off unless the stock is
pre-formed. With it on, the target is the formed model, its masks at the
back's footprint and its contours at the front's, the stock the pressed
slab; the eyewires and the perimeter follow the curve with the skin along
the local normal; the groove is refused with a sentence unless the
apertures are cut first, flat; and the simulation from the stock mesh
reports the flat case's completeness and no gouge beyond the walls' lean.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.project.schema import (CastleCamParams, CastleParams, FormingMetadata,
                                            LensGrooveParams, StockDefinition)

ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    od, os_ = sorted(lenses, key=lambda l: -l.centroid.x)
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges, od, os_


def _forming():
    return FormingMetadata().with_base_curve(6.0, 170.0)


def _castle(**stock):
    return CastleParams(stock=StockDefinition(use_pad_block=False, **stock))


@pytest.fixture(scope="module")
def reliefs(demo):
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.core.zmap import castle_relief
    partition, hinges, od, os_ = demo
    bridge = bridge_geometry(partition, od, os_)
    flat = castle_relief(partition, _castle(), hinges, kernel="mesh", resolution=0.3)
    formed = castle_relief(partition, _castle(preformed=True), hinges, kernel="mesh",
                           resolution=0.3, forming=_forming(), bridge=bridge)
    return flat, formed, bridge


def test_a_flat_project_is_untouched_by_a_forming_it_does_not_use(demo, reliefs):
    from guildmodel.core.zmap import castle_relief
    partition, hinges, _, _ = demo
    flat, _, bridge = reliefs
    again = castle_relief(partition, _castle(), hinges, kernel="mesh", resolution=0.3,
                          forming=_forming(), bridge=bridge)
    assert not again.preformed and again.stock_top is None
    assert np.array_equal(again.field.z, flat.field.z)
    assert np.array_equal(again.inside, flat.inside)


def test_the_formed_zmap_is_the_flat_zmap_warped_point_wise(demo, reliefs):
    from guildmodel.core.forming import ThermoformMap
    partition, _, _, _ = demo
    flat, formed, bridge = reliefs
    assert formed.preformed and formed.stock_top is not None and formed.stock_bottom is not None
    fmap = ThermoformMap.from_metadata(_forming(), bridge=bridge)
    f, g = flat.field, formed.field
    res = f.resolution
    rr, cc = np.nonzero(flat.inside)
    sel = np.random.default_rng(0).choice(len(rr), 800, replace=False)
    pts = np.column_stack([f.origin[0] + cc[sel] * res, f.origin[1] + rr[sel] * res, f.z[rr[sel], cc[sel]]])
    w = fmap(pts)
    ci = np.round((w[:, 0] - g.origin[0]) / res).astype(int)
    ri = np.round((w[:, 1] - g.origin[1]) / res).astype(int)
    rows, cols = g.z.shape
    ok = (ci >= 0) & (ci < cols) & (ri >= 0) & (ri < rows)
    ok[ok] &= formed.inside[ri[ok], ci[ok]]
    dz = np.abs(g.z[ri[ok], ci[ok]] - w[ok, 2])
    assert ok.sum() > 500
    assert np.median(dz) < 0.05 and np.percentile(dz, 95) < res   # within a cell
    # the back's footprint lies inside the front's by the walls' lean
    assert 0.5 < formed.wall_lean_mm < 5.0
    assert formed.inside.sum() < flat.inside.sum()
    assert formed.partition.body.area < partition.body.area


def test_the_contours_follow_the_curve_and_the_skin_is_along_the_normal(demo, reliefs):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    partition, hinges, _, _ = demo
    _, formed, _ = reliefs
    castle = _castle(preformed=True)
    ops = generate_castle_program(formed, castle, hinges, TOOLS["flat_3175"],
                                  params=CastleCamParams(), tools_cfg=TOOLS)
    names = [op.name for op in ops]
    assert "Eyewires" in names and "Perimeter" in names and "Lens Groove" not in names
    per = next(op for op in ops if op.name == "Perimeter")
    zs = np.array([p[2] for path in per.paths for p in path])
    assert zs.max() - zs.min() > 5.0                       # the pass rides the bowl
    # the last pass sits a skin above the pressed slab's bottom, along the normal
    last = per.paths[-1]
    xy = np.array([(x, y) for x, y, _ in last])
    z = np.array([p[2] for p in last])
    from guildmodel.core.cam.castle_ops import _surface_along
    bottom = _surface_along(formed.stock_bottom, xy)
    gy, gx = np.gradient(formed.stock_bottom.z, formed.stock_bottom.resolution)
    from guildmodel.core.relief.heightfield import Heightfield
    tilt = _surface_along(Heightfield(z=np.sqrt(np.nan_to_num(gx) ** 2 + np.nan_to_num(gy) ** 2),
                                      origin=formed.stock_bottom.origin,
                                      resolution=formed.stock_bottom.resolution), xy)
    want = castle.onion_skin_mm * np.sqrt(1.0 + tilt ** 2)
    assert np.abs((z - bottom) - want).max() < 0.05
    assert (want.max() - want.min()) > 0.01                 # and it varies with the tilt
    # the hinge pockets follow the curve too
    pockets = next(op for op in ops if op.name == "Hinge Pockets")
    pz = np.array([p[2] for path in pockets.paths for p in path])
    assert pz.max() - pz.min() > 1.0


def test_the_skin_along_the_normal_on_a_synthetic_cap():
    """A cap of R = 144: the last pass clears the bottom by skin / cos(tilt)."""
    from shapely.geometry import box
    from guildmodel.core.cam.castle_ops import CamOp, _curved_contour
    from guildmodel.core.project.schema import HoldingParams
    from guildmodel.core.relief.heightfield import Heightfield
    R, T, skin, res = 144.0, 6.0, 0.4, 0.5
    xs = np.arange(-70.0, 70.0 + res, res)
    ys = np.arange(-30.0, 30.0 + res, res)
    X, Y = np.meshgrid(xs, ys)
    bottom = R - np.sqrt(np.clip(R * R - X ** 2 - Y ** 2, 0.0, None))
    top = bottom + T
    hb = Heightfield(z=bottom, origin=(xs[0], ys[0]), resolution=res)
    ht = Heightfield(z=top, origin=(xs[0], ys[0]), resolution=res)
    ring = [(x, y) for x, y in box(-60, -20, 60, 20).exterior.coords]
    op = CamOp("Perimeter")
    _curved_contour(op, [ring], ht, hb, skin, CastleCamParams(), None, False)
    last = op.paths[-1]
    for x, y, z in last:
        r2 = x * x + y * y
        b = R - np.sqrt(R * R - r2)
        tilt = np.sqrt(r2) / np.sqrt(R * R - r2)          # |grad| of the cap
        assert z - b == pytest.approx(skin * np.sqrt(1.0 + tilt ** 2), abs=0.02)
    # tabs ride the local floor
    op2 = CamOp("Perimeter")
    _curved_contour(op2, [ring], ht, hb, skin, CastleCamParams(),
                    HoldingParams(strategy="tabs"), True)
    tabbed = op2.paths[-1]
    lift = [z - (R - np.sqrt(R * R - x * x - y * y)) for x, y, z in tabbed]
    assert min(lift) == pytest.approx(0.0, abs=0.02) and max(lift) > 0.5


def test_the_groove_is_refused_unless_the_apertures_go_first(demo):
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.core.zmap import castle_relief
    partition, hinges, od, os_ = demo
    bridge = bridge_geometry(partition, od, os_)
    grooved = _castle(preformed=True).model_copy(update={"lens_groove": LensGrooveParams(enabled=True)})
    relief = castle_relief(partition, grooved, hinges, kernel="mesh", resolution=0.3,
                           forming=_forming(), bridge=bridge)
    ops = generate_castle_program(relief, grooved, hinges, TOOLS["flat_3175"],
                                  params=CastleCamParams(), tools_cfg=TOOLS)
    assert "Lens Groove" not in [op.name for op in ops]
    eyewires = next(op for op in ops if op.name == "Eyewires")
    assert any("Lens Groove left out" in n and "Apertures and groove first" in n for n in eyewires.notes)
    # the hybrid: the pressed slab arrives with its apertures open
    hybrid = grooved.model_copy(update={"stock": grooved.stock.model_copy(update={"apertures_first": True})})
    relief_h = castle_relief(partition, hybrid, hinges, kernel="mesh", resolution=0.3,
                             forming=_forming(), bridge=bridge)
    c = od.centroid
    f = relief_h.field
    ci = int(round((c.x - f.origin[0]) / f.resolution))
    ri = int(round((c.y - f.origin[1]) / f.resolution))
    # the aperture's center maps near the same cell; the slab is open there,
    # which reads as stock far below the part, never as NaN in a toolpath
    assert relief_h.stock_top.z[ri, ci] < np.nanmin(relief_h.field.z[relief_h.inside]) - 0.5
    assert relief.stock_top.z[ri, ci] > relief_h.stock_top.z[ri, ci] + 3.0
    assert np.isfinite(relief_h.stock_top.z).all()


def test_the_simulation_from_the_stock_mesh(demo, reliefs):
    from guildmodel.core.cam.castle_ops import build_tool_settings, generate_castle_program, write_castle_program
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.forming import ThermoformMap
    from guildmodel.core.forming.blank import formed_blank_mesh
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.relief.castle import stock_top_heightfield
    from guildmodel.core.stock import DexelStock
    from guildmodel.gui.app import _simulate_program
    partition, hinges, _, _ = demo
    flat, formed, bridge = reliefs
    tool = TOOLS["flat_3175"]
    params = CastleCamParams()

    def program(relief, castle):
        ops = generate_castle_program(relief, castle, hinges, tool, params=params, tools_cfg=TOOLS)
        ts, _ = build_tool_settings(ops, TOOLS, default_feed=600, default_plunge=200, default_spindle=12000)
        f0 = ts[ops[0].tool_name]
        top = float(np.nanmax(relief.stock_top.z)) if relief.preformed else castle.stock.total_pad_height_mm
        post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                        spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                        plunge_rate_mmpm=f0.plunge_rate_mmpm, safe_z_mm=params.safe_z_for(top))
        write_castle_program(ops, post, tool_settings=ts, contour_op_names=CASTLE_CONTOUR_OPS)
        return post.to_string(), top

    castle = _castle(preformed=True)
    text, top = program(formed, castle)
    fmap = ThermoformMap.from_metadata(_forming(), bridge=bridge)
    mesh = formed_blank_mesh(castle.stock, fmap)
    g = formed.field
    rows, cols = g.z.shape
    v0 = DexelStock.from_mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces), g.origin, rows, cols, g.resolution)
    bhf = stock_top_heightfield(castle.stock, resolution=g.resolution)
    b0 = DexelStock.from_mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces), bhf.origin, *bhf.z.shape, g.resolution)
    report, lines, plan, _ = _simulate_program(text, formed, TOOLS, tool, init_z=top, stock_field=bhf,
                                               feed_mmpm=600, verdict0=v0, blank0=b0)
    assert report.status() == "ok", lines
    assert report.gouge.gouge_cells == 0
    # the flat case's completeness, give or take
    text_f, top_f = program(flat, _castle())
    report_f, _, _, _ = _simulate_program(text_f, flat, TOOLS, tool, init_z=top_f + 1.0,
                                          stock_field=stock_top_heightfield(_castle().stock, resolution=g.resolution),
                                          feed_mmpm=600)
    assert report.completeness.uncut_fraction <= 2.0 * max(report_f.completeness.uncut_fraction, 0.005)
    # and the playback starts from the pressed slab, not the box
    assert plan.stock_top.shape == bhf.z.shape
    assert np.nanmax(plan.stock_top) > castle.stock.blank_thickness_mm + 2.0


def test_the_workers_cut_the_pressed_blank(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.gui.app import GCodeWorker, SimWorker
    partition, hinges, od, os_ = demo
    bridge = bridge_geometry(partition, od, os_)
    castle = _castle(preformed=True, apertures_first=True).model_copy(
        update={"lens_groove": LensGrooveParams(enabled=True)})
    cam = CastleCamParams()
    done, errs, log = [], [], []
    worker = GCodeWorker(partition.body, castle, {"material_name": "acetate"}, partition=partition,
                         hinge_polys=hinges, cam_params=cam, forming=_forming(), bridge=bridge)
    worker.kernel = "mesh"
    worker.finished.connect(lambda s, rows: done.append((s, rows)))
    worker.error.connect(errs.append)
    worker.progress.connect(log.append)
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert set(worker.programs) == {"posterior_cut.nc", "apertures_cut.nc"}
    assert "--- Lens Groove ---" in worker.programs["apertures_cut.nc"]
    assert "--- Eyewires ---" not in worker.programs["posterior_cut.nc"]
    assert "--- Perimeter ---" in worker.programs["posterior_cut.nc"]
    setups = worker.setup_dict["setups"]
    assert [s["program"] for s in setups] == ["apertures_cut.nc", "posterior_cut.nc"]
    assert any("Pre-formed blank" in ln for ln in log)
    sim_done = []
    sim = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                    program_text=worker.programs["posterior_cut.nc"], forming=_forming(), bridge=bridge)
    sim.finished.connect(lambda r, lines, plan: sim_done.append((r, lines, plan)))
    sim.error.connect(errs.append)
    sim.run()
    assert errs == [], errs[0] if errs else ""
    report, lines, plan = sim_done[0]
    assert report.status() in {"ok", "warn"}, lines


def test_the_stock_tab_carries_the_pressed_blank(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    assert not p.stock_definition().preformed and not p.apertures_first.isEnabled()
    p.preformed.setChecked(True)
    assert p.apertures_first.isEnabled() and not p.use_pad_block.isChecked()
    p.apertures_first.setChecked(True)
    s = p.stock_definition()
    assert s.preformed and s.apertures_first and not s.use_pad_block
    p.set_castle_params(CastleParams(stock=StockDefinition()))
    assert not p.stock_definition().preformed and p.use_pad_block.isEnabled()


# ------------------------------------------------------------- session two

def _gdraw_front(tmp_path_factory, name):
    import zipfile
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    fixtures = ROOT / "tests" / "fixtures"
    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((fixtures / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


def test_a_second_side_on_the_pressed_blank_turns_the_slab_over(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.core.forming import bridge_geometry
    from guildmodel.core.project.schema import EdgeFeature
    from guildmodel.gui.app import GCodeWorker, SimWorker
    partition, hinges, od, os_ = demo
    bridge = bridge_geometry(partition, od, os_)
    brow = [z.name for z in partition.zones if z.name.startswith("eyewire_superior")][:1]
    castle = _castle(preformed=True).model_copy(update={"edge_features": [EdgeFeature(
        id="brow", label="Brow chamfer", face="anterior", edge="outline", zones=brow,
        profile="chamfer", width_mm=2.0, angle_deg=45.0, blend_mm=6.0, mirror=True)]})
    cam = CastleCamParams()
    done, errs, log = [], [], []
    worker = GCodeWorker(partition.body, castle, {"material_name": "acetate"}, partition=partition,
                         hinge_polys=hinges, cam_params=cam, forming=_forming(), bridge=bridge)
    worker.kernel = "mesh"
    worker.finished.connect(lambda s, rows: done.append((s, rows)))
    worker.error.connect(errs.append)
    worker.progress.connect(log.append)
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert set(worker.programs) == {"posterior_cut.nc", "back_cut.nc"}
    assert any("turns the slab over" in ln for ln in log)
    back = worker.programs["back_cut.nc"]
    assert "G55" in back and "--- Perimeter ---" in back
    assert "--- Features ---" in back or "--- Fine Relief ---" in back   # the chamfer's pass
    # side two's perimeter rides the turned slab: its Z varies along the ring
    zs = [float(ln.split("Z")[1].split()[0]) for ln in back.splitlines()
          if ln.startswith("G1") and "Z" in ln and "X" in ln]
    assert max(zs) - min(zs) > 3.0
    sim_done = []
    sim = SimWorker(partition, castle, cam, hinge_polys=hinges, resolution=0.3,
                    program_text=worker.programs["posterior_cut.nc"],
                    back_program_text=worker.programs["back_cut.nc"],
                    forming=_forming(), bridge=bridge)
    sim.finished.connect(lambda r, lines, plan: sim_done.append((r, lines, plan)))
    sim.error.connect(errs.append)
    sim.run()
    assert errs == [], errs[0] if errs else ""
    report, lines, plan = sim_done[0]
    assert any(ln.startswith("Side one:") for ln in lines) and any(ln.startswith("Side two:") for ln in lines)
    assert report.status() in {"ok", "warn"}, lines


def test_the_nest_is_the_cup_and_the_dome_on_the_dowels(demo):
    from guildmodel.core.forming import build_dies
    from guildmodel.core.model.kernel import to_trimesh
    from guildmodel.core.project.schema import PressDieParams
    partition, _, od, os_ = demo
    forming = _forming()
    castle = _castle(preformed=True)
    cup = build_dies(partition, castle, forming.model_copy(update={"dies": PressDieParams(mode="pre_cut")}),
                     od, os_).anterior
    dome = build_dies(partition, castle, forming.model_copy(update={"dies": PressDieParams(mode="post_cut")}),
                      od, os_).posterior
    for man in (cup, dome):
        assert man.volume() > 0 and to_trimesh(man).is_watertight and len(man.decompose()) == 1
    # the Forming panel asks for them
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.forming_panel import FormingPanel
    p = FormingPanel()
    asked = []
    p.nest_export_requested.connect(lambda: asked.append(1))
    p.nest_btn.click()
    assert asked == [1]


@pytest.mark.parametrize("name", ["aviator", "gabriel"])
def test_the_pressed_blank_on_the_maker_fixtures(name, tmp_path_factory):
    from guildmodel.core.cam.castle_ops import build_tool_settings, generate_castle_program, write_castle_program
    from guildmodel.core.cam.component import CASTLE_CONTOUR_OPS
    from guildmodel.core.forming import ThermoformMap, bridge_geometry
    from guildmodel.core.forming.blank import formed_blank_mesh
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.relief.castle import stock_top_heightfield
    from guildmodel.core.stock import DexelStock
    from guildmodel.core.zmap import castle_relief
    from guildmodel.gui.app import _simulate_program
    ws = _gdraw_front(tmp_path_factory, name)
    castle = (ws.castle_params or CastleParams()).model_copy(update={"stock": StockDefinition(
        preformed=True, use_pad_block=False)})
    bridge = bridge_geometry(ws.partition, ws.lens_od, ws.lens_os)
    forming = FormingMetadata().with_base_curve(4.0, 172.0)
    relief = castle_relief(ws.partition, castle, ws.hinge_polys, kernel="mesh", resolution=0.3,
                           forming=forming, bridge=bridge)
    assert relief.preformed and 0.2 < relief.wall_lean_mm < 6.0
    params = CastleCamParams()
    tool = TOOLS["flat_3175"]
    ops = generate_castle_program(relief, castle, ws.hinge_polys, tool, params=params, tools_cfg=TOOLS)
    ts, _ = build_tool_settings(ops, TOOLS, default_feed=600, default_plunge=200, default_spindle=12000)
    f0 = ts[ops[0].tool_name]
    top = float(np.nanmax(relief.stock_top.z))
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=f0.diameter_mm,
                    spindle_rpm=f0.spindle_rpm, feed_rate_mmpm=f0.feed_rate_mmpm,
                    plunge_rate_mmpm=f0.plunge_rate_mmpm, safe_z_mm=params.safe_z_for(top))
    write_castle_program(ops, post, tool_settings=ts, contour_op_names=CASTLE_CONTOUR_OPS)
    fmap = ThermoformMap.from_metadata(forming, bridge=bridge)
    mesh = formed_blank_mesh(castle.stock, fmap)
    g = relief.field
    rows, cols = g.z.shape
    v0 = DexelStock.from_mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces), g.origin, rows, cols, g.resolution)
    bhf = stock_top_heightfield(castle.stock, resolution=g.resolution)
    b0 = DexelStock.from_mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces), bhf.origin, *bhf.z.shape, g.resolution)
    report, lines, _, _ = _simulate_program(post.to_string(), relief, TOOLS, tool, init_z=top + 0.5,
                                            stock_field=bhf, feed_mmpm=600, verdict0=v0, blank0=b0)
    assert report.status() in {"ok", "warn"}, lines
    assert report.gouge.gouge_cells == 0, lines
