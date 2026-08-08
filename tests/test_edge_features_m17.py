"""Two-sided modelling foundations: the anterior surface and partial-span edge
chamfers / fillets (BUILDPLAN M17).

The shape that motivated this: a chamfer on the **anterior brow**, over each
eyewire, on both sides, *not* carried across the bridge — a common feature of
thick modern frames and impossible to express with the M13 eyewire bezel, which
is a constant band all the way round a ring.

Three things had to exist for it:

  * an **anterior surface** in the relief (until now the front face was flat
    z = 0 by definition, and "the model" meant the posterior only);
  * a **span** naming part of an edge — chosen by castle zone rather than by an
    arc-length fraction, so it survives a re-imported drawing and mirrors by
    swapping `_od` for `_os`;
  * a **taper**, so the run feathers out instead of stopping at full depth.

Machining the anterior needs the flip setup (M9/V2); this milestone models and
previews it. The posterior program is unchanged, which several tests here pin.
"""
from pathlib import Path

import numpy as np
import pytest

from guildmodel.core.project.schema import (
    CastleParams, EdgeFeature, EyewireBezelParams,
)
from guildmodel.core.relief.edges import (
    chamfer_drop, fillet_drop, lens_rings, ring_for, span_intervals,
    spans_whole_ring, station_fraction, taper_weight,
)

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _relief(demo, castle, res=0.4):
    from guildmodel.core.relief.castle import build_castle_relief
    part, hinges = demo
    return build_castle_relief(part, castle, hinges, resolution=res)


def _cut_xy(relief):
    """World (x, y) of every cell where the anterior face was carved."""
    a = relief.anterior_z
    cut = a > 1e-9
    rows, cols = a.shape
    xs = relief.field.origin[0] + np.arange(cols) * relief.field.resolution
    ys = relief.field.origin[1] + np.arange(rows) * relief.field.resolution
    return (np.broadcast_to(xs, a.shape)[cut],
            np.broadcast_to(ys[:, None], a.shape)[cut])


BROW = EdgeFeature(
    id="brow", label="Anterior brow chamfer", face="anterior", edge="outline",
    zones=["eyewire_superior_od"], profile="chamfer",
    width_mm=2.5, angle_deg=45.0, blend_mm=6.0, mirror=True,
)


# ------------------------------------------------------------- profile maths

def test_chamfer_drop_is_full_at_the_edge_and_zero_at_its_width():
    d = np.array([0.0, 1.0, 2.0, 3.0])
    drop = chamfer_drop(d, np.full(4, 2.0), 45.0)
    assert drop[0] == pytest.approx(2.0)      # width * tan(45)
    assert drop[1] == pytest.approx(1.0)
    assert drop[2] == pytest.approx(0.0)
    assert drop[3] == pytest.approx(0.0)      # past the band, never negative


def test_fillet_drop_is_tangent_to_the_face_and_full_radius_at_the_edge():
    r = 3.0
    d = np.array([0.0, r * 0.5, r, r * 1.5])
    drop = fillet_drop(d, r)
    assert drop[0] == pytest.approx(r)        # the whole radius at the edge
    assert drop[-1] == pytest.approx(0.0)     # nothing past the radius
    assert drop[2] == pytest.approx(0.0)      # tangent where it meets the face — no crease
    # and it is convex between: a round-over, not a straight ramp
    assert drop[1] < r * 0.5


# --------------------------------------------------------------- the span

def test_empty_zone_list_means_the_whole_ring(demo):
    part, _ = demo
    ring = ring_for(part, "outline")
    assert span_intervals(ring, part, []) == [(0.0, ring.length)]


def test_span_covers_only_the_named_zones(demo):
    part, _ = demo
    ring = ring_for(part, "outline")
    spans = span_intervals(ring, part, ["eyewire_superior_od"])
    assert spans, "the OD superior eyewire owns none of the outline"
    covered = sum(s1 - s0 for s0, s1 in spans)
    assert 0 < covered < ring.length * 0.5      # a brow, not the whole outline


def test_trim_pulls_the_span_ends_in(demo):
    part, _ = demo
    ring = ring_for(part, "outline")
    plain = span_intervals(ring, part, ["eyewire_superior_od"])
    trimmed = span_intervals(ring, part, ["eyewire_superior_od"],
                             trim_start_mm=3.0, trim_end_mm=2.0)
    assert sum(b - a for a, b in trimmed) == pytest.approx(
        sum(b - a for a, b in plain) - 5.0 * len(plain))


def test_taper_weight_ramps_in_and_out():
    total = 100.0
    w = taper_weight(np.array([0.0, 10.0, 12.0, 30.0, 48.0, 50.0, 60.0]),
                     [(10.0, 50.0)], blend_mm=4.0, total=total)
    assert w[0] == 0.0                      # before the run
    assert w[1] == pytest.approx(0.0)       # exactly at the start
    assert 0.0 < w[2] < 1.0                 # ramping in
    assert w[3] == pytest.approx(1.0)       # full depth in the middle
    assert 0.0 < w[4] < 1.0                 # ramping out
    assert w[5] == pytest.approx(0.0)       # exactly at the end
    assert w[6] == 0.0                      # after the run


def test_taper_never_exceeds_half_the_run():
    """A blend longer than the run would otherwise wrap past the middle and
    produce a weight above 1 — a cut deeper than asked for."""
    w = taper_weight(np.linspace(0.0, 10.0, 21), [(0.0, 10.0)],
                     blend_mm=50.0, total=100.0)
    assert w.max() <= 1.0 + 1e-9
    assert w.max() == pytest.approx(1.0)    # the midpoint still reaches full depth


def test_station_fraction_runs_zero_to_one_across_the_span():
    t = station_fraction(np.array([10.0, 30.0, 50.0]), [(10.0, 50.0)], 100.0)
    assert t[0] == pytest.approx(0.0)
    assert t[1] == pytest.approx(0.5)
    assert t[2] == pytest.approx(1.0)


# ------------------------------------------------------- the anterior surface

def test_no_features_means_no_anterior_surface(demo):
    """The historical fast path: nothing cuts the front, so there is no second
    surface to carry, and every downstream reader sees the flat z=0 it always did."""
    r = _relief(demo, CastleParams())
    assert r.anterior is None
    assert not r.anterior_z.any()
    assert np.array_equal(r.thickness(), r.field.z)


def test_brow_chamfer_carves_the_anterior_only(demo):
    base = _relief(demo, CastleParams())
    brow = _relief(demo, CastleParams(edge_features=[BROW]))
    assert brow.anterior is not None
    assert brow.anterior_z.max() == pytest.approx(2.5, abs=0.05)   # width*tan(45)
    # the posterior surface is untouched — this is a front-face feature
    assert np.allclose(base.field.z, brow.field.z)


def test_brow_chamfer_does_not_cross_the_bridge(demo):
    """The whole point: 'on each side without connecting'."""
    r = _relief(demo, CastleParams(edge_features=[BROW]))
    x, y = _cut_xy(r)
    assert len(x) > 100
    # two clusters, one per side, with a clear gap over the nose
    assert (x > 5).any() and (x < -5).any()
    assert not ((np.abs(x) < 4).any()), "the chamfer reaches the bridge centreline"
    # and it is a BROW: everything above the frame's vertical middle
    assert y.min() > 0


def test_mirroring_produces_a_symmetric_pair(demo):
    r = _relief(demo, CastleParams(edge_features=[BROW]))
    x, _ = _cut_xy(r)
    right, left = (x > 0).sum(), (x < 0).sum()
    assert right > 0 and left > 0
    assert abs(right - left) / max(right, left) < 0.05      # symmetric to 5%


def test_mirror_off_cuts_one_side_only(demo):
    r = _relief(demo, CastleParams(
        edge_features=[BROW.model_copy(update={"mirror": False})]))
    x, _ = _cut_xy(r)
    assert (x > 0).sum() > 0
    assert (x < 0).sum() == 0


def test_a_run_with_no_ends_is_recognised_as_one(demo):
    """`spans_whole_ring` is what stops the solid kernels treating the ring's
    arbitrary coordinate seam as two ends of a run — duplicating a station,
    capping the sweep twice in the same place, and feathering the cut to nothing
    somewhere the maker never asked for.

    Both ways of getting there are checked. An empty `zones` is the documented
    one; a `zones` list that happens to cover every station is the one that
    would be missed, because it arrives through a different branch of
    `span_intervals` and looks like an ordinary run until you measure it.
    """
    part, _ = demo
    ring = ring_for(part, "outline")
    total = ring.length

    whole = span_intervals(ring, part, [])
    assert whole == [(0.0, total)]
    assert spans_whole_ring(whole[0], total)

    every = span_intervals(ring, part, [z.name for z in part.zones])
    assert every, "no zone owns any of the outline; this tests nothing"
    assert spans_whole_ring(every[0], total)

    brow = span_intervals(ring, part, ["eyewire_superior_od"])
    assert brow and not spans_whole_ring(brow[0], total)

    # A hair short of the ring is still a run with two real ends.
    assert not spans_whole_ring((0.0, total - 1e-3), total)


def test_mirrored_swaps_od_and_os_and_never_re_mirrors():
    m = BROW.mirrored()
    assert m.zones == ["eyewire_superior_os"]
    assert m.mirror is False
    assert m.face == BROW.face and m.width_mm == BROW.width_mm
    # a lens edge swaps sides too
    lens = EdgeFeature(edge="lens_od", zones=["eyewire_inferior_od"])
    assert lens.mirrored().edge == "lens_os"
    # a centre zone is its own mirror
    assert EdgeFeature(zones=["bridge"]).mirrored().zones == ["bridge"]


def test_variable_width_tapers_along_the_run(demo):
    const = _relief(demo, CastleParams(edge_features=[BROW]))
    taper = _relief(demo, CastleParams(edge_features=[
        BROW.model_copy(update={"width_mm": 1.0, "width_end_mm": 4.0})]))
    assert taper.anterior_z.max() > const.anterior_z.max()
    assert EdgeFeature(width_mm=1.0, width_end_mm=4.0).width_at(0.5) == pytest.approx(2.5)
    assert EdgeFeature(width_mm=2.0).width_at(0.5) == 2.0          # None = constant


def test_fillet_profile_rounds_the_edge(demo):
    r = _relief(demo, CastleParams(edge_features=[
        BROW.model_copy(update={"profile": "fillet", "radius_mm": 3.0})]))
    assert r.anterior_z.max() == pytest.approx(3.0, abs=0.15)


def test_posterior_edge_features_carve_the_back_not_the_front(demo):
    base = _relief(demo, CastleParams())
    r = _relief(demo, CastleParams(edge_features=[
        BROW.model_copy(update={"face": "posterior"})]))
    assert r.anterior is None                      # nothing touched the front
    assert (r.field.z < base.field.z - 1e-9).any()  # the back was cut


def test_min_thickness_is_never_violated(demo):
    """Two faces can cut toward each other; the part must survive both."""
    castle = CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="both",
                                         anterior_width_mm=3.0,
                                         anterior_angle_deg=70.0,
                                         min_thickness_mm=1.2),
        edge_features=[BROW.model_copy(update={
            "width_mm": 8.0, "angle_deg": 80.0, "min_thickness_mm": 1.2})],
    )
    r = _relief(demo, castle)
    assert r.thickness()[r.inside].min() >= 1.2 - 1e-6


def test_depth_limit_caps_the_cut(demo):
    r = _relief(demo, CastleParams(edge_features=[
        BROW.model_copy(update={"width_mm": 6.0, "depth_limit_mm": 0.8})]))
    assert r.anterior_z.max() == pytest.approx(0.8, abs=0.02)


def test_disabled_features_are_skipped(demo):
    r = _relief(demo, CastleParams(edge_features=[
        BROW.model_copy(update={"enabled": False})]))
    assert r.anterior is None


# ------------------------------------------------- the anterior eyewire bezel

def test_bezel_face_selects_which_side_is_cut(demo):
    post = _relief(demo, CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="posterior")))
    ant = _relief(demo, CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="anterior")))
    both = _relief(demo, CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="both")))
    base = _relief(demo, CastleParams())

    assert post.anterior is None                             # back only
    assert ant.anterior is not None                          # front only
    assert np.allclose(ant.field.z, base.field.z), "an anterior bezel cut the back"
    assert both.anterior is not None                         # front AND back
    assert (both.field.z < base.field.z - 1e-9).any()
    assert np.allclose(both.anterior_z, ant.anterior_z)


def test_anterior_bezel_rings_every_lens(demo):
    part, _ = demo
    r = _relief(demo, CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="anterior")))
    x, _ = _cut_xy(r)
    assert (x > 0).any() and (x < 0).any()       # both apertures
    assert r.anterior_z.max() == pytest.approx(1.5, abs=0.05)   # 1.5mm * tan(45)


def test_bezel_face_helpers():
    b = EyewireBezelParams(enabled=True, face="both")
    assert b.cuts_posterior() and b.cuts_anterior()
    off = EyewireBezelParams(enabled=False, face="both")
    assert not off.cuts_posterior() and not off.cuts_anterior()


# ------------------------------------------------------------------ rings

def test_lens_rings_are_ordered_od_first(demo):
    part, _ = demo
    rings = lens_rings(part)
    assert len(rings) == 2
    from shapely.geometry import Polygon
    assert Polygon(rings[0]).centroid.x > Polygon(rings[1]).centroid.x   # OD is +x


def test_missing_edge_ring_is_skipped_not_fatal(demo):
    """A one-aperture frame has no `lens_os`; the mirrored twin of an OD feature
    must not blow up the build."""
    part, _ = demo
    assert ring_for(part, "lens_os") is not None
    from guildmodel.core.geometry.regions import CastlePartition
    single = CastlePartition(body=part.body, zones=part.zones, edges=part.edges)
    assert ring_for(single, "outline") is not None
    # an edge name the drawing cannot supply returns None rather than raising
    assert ring_for(part, "lens_xx") is None


# ------------------------------------------------------------------- mesh

def test_mesh_bottom_rides_the_anterior_surface(demo):
    from guildmodel.core.relief.castle import build_castle_mesh

    flat = build_castle_mesh(_relief(demo, CastleParams()))
    carved = build_castle_mesh(_relief(demo, CastleParams(edge_features=[BROW])))
    assert flat.is_watertight and carved.is_watertight
    # the chamfer removes material, so the solid gets smaller
    assert carved.volume < flat.volume
    # …and the front face is no longer a single plane at z = 0
    zs = carved.vertices[:, 2]
    assert (zs > 1e-6).sum() > (flat.vertices[:, 2] > 1e-6).sum()


def test_posterior_program_is_unchanged_by_an_anterior_feature(demo):
    """M17 is modelling only — the posted posterior program must not move."""
    import yaml
    from guildmodel.core.cam.castle_ops import generate_castle_program

    tools = yaml.safe_load(
        (ROOT / "src" / "guildmodel" / "config" / "tools.yaml").read_text())
    part, hinges = demo
    base = generate_castle_program(_relief(demo, CastleParams()), CastleParams(),
                                   hinges, tools["flat_3175"], tools_cfg=tools)
    castle = CastleParams(edge_features=[BROW])
    with_brow = generate_castle_program(_relief(demo, castle), castle, hinges,
                                        tools["flat_3175"], tools_cfg=tools)
    assert [op.name for op in base] == [op.name for op in with_brow]
    for a, b in zip(base, with_brow):
        assert len(a.paths) == len(b.paths), a.name


# ------------------------------------------------------------------ schema

def test_castle_reports_whether_anything_cuts_the_front():
    assert not CastleParams().cuts_anterior()
    assert CastleParams(edge_features=[BROW]).cuts_anterior()
    assert not CastleParams(
        edge_features=[BROW.model_copy(update={"face": "posterior"})]).cuts_anterior()
    assert CastleParams(eyewire_bezel=EyewireBezelParams(
        enabled=True, face="anterior")).cuts_anterior()


def test_resolved_features_expand_mirrors_and_drop_disabled():
    castle = CastleParams(edge_features=[
        BROW,
        BROW.model_copy(update={"id": "off", "enabled": False}),
        BROW.model_copy(update={"id": "solo", "mirror": False}),
    ])
    resolved = castle.resolved_edge_features()
    assert len(resolved) == 3          # brow + its twin + the un-mirrored one
    assert [f.zones for f in resolved] == [
        ["eyewire_superior_od"], ["eyewire_superior_os"], ["eyewire_superior_od"]]


def test_old_projects_load_without_the_new_fields():
    raw = CastleParams().model_dump()
    raw.pop("edge_features")
    raw["eyewire_bezel"].pop("face")
    restored = CastleParams(**raw)
    assert restored.edge_features == []
    assert restored.eyewire_bezel.face == "posterior"


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


def test_panel_round_trips_edge_features_and_the_bezel_face(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    castle = CastleParams(
        eyewire_bezel=EyewireBezelParams(enabled=True, face="both",
                                         anterior_width_mm=1.8,
                                         anterior_angle_deg=50.0),
        edge_features=[BROW],
    )
    p.set_castle_params(castle)
    out = p.castle_params()
    assert out.eyewire_bezel.face == "both"
    assert out.eyewire_bezel.anterior_width_mm == 1.8
    assert out.eyewire_bezel.anterior_angle_deg == 50.0
    assert len(out.edge_features) == 1
    f = out.edge_features[0]
    assert f.label == BROW.label and f.face == "anterior"
    assert f.zones == ["eyewire_superior_od"]
    assert f.width_mm == BROW.width_mm and f.mirror is True


def test_panel_add_duplicate_remove(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    assert p.edge_list.count() == 0
    p._on_edge_add()
    p._on_edge_add()
    assert p.edge_list.count() == 2
    assert len({f.id for f in p.edge_features()}) == 2, "ids must be unique"
    p.edge_list.setCurrentRow(0)
    p._on_edge_duplicate()
    assert p.edge_list.count() == 3
    p._on_edge_remove()
    assert p.edge_list.count() == 2


def test_panel_zone_picker_follows_the_loaded_drawing(tmp_path, monkeypatch, demo):
    """A stale zone name from another frame would match nothing and the run would
    silently vanish, so the picker only ever offers this drawing's zones."""
    part, _ = demo
    p = _panel(tmp_path, monkeypatch)
    p._on_edge_add()
    assert p.ef_zones.count() == 0            # no drawing loaded yet
    p.set_zones(part)
    offered = {p.ef_zones.item(i).text() for i in range(p.ef_zones.count())}
    assert offered == {z.name for z in part.zones}


def test_panel_bezel_face_greys_the_other_side(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    p.bezel_enable.setChecked(True)
    p.bezel_face.setCurrentIndex(1)                 # Anterior
    assert not p.bezel_width.isEnabled()
    assert p.bezel_ant_width.isEnabled()
    p.bezel_face.setCurrentIndex(0)                 # Posterior
    assert p.bezel_width.isEnabled()
    assert not p.bezel_ant_width.isEnabled()
    p.bezel_face.setCurrentIndex(2)                 # Both
    assert p.bezel_width.isEnabled() and p.bezel_ant_width.isEnabled()


def test_panel_fillet_greys_the_chamfer_numbers(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    p._on_edge_add()
    p.ef_profile.setCurrentIndex(1)                 # Fillet
    assert p.ef_radius.isEnabled()
    assert not p.ef_angle.isEnabled() and not p.ef_width.isEnabled()
    p.ef_profile.setCurrentIndex(0)                 # Chamfer
    assert not p.ef_radius.isEnabled()
    assert p.ef_angle.isEnabled() and p.ef_width.isEnabled()
