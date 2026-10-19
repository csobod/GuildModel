"""Press dies (BUILDPLAN M23 §8.3), on the demo front.

The dies come from the forming map and the silhouette, never from the
featured model: the posterior dome follows the eyewire terrace and cuts
away under every taller zone, the nosepads first; the anterior cup is the
plain negative set back by the silicone mat and the clearance. The closed
gap is terrace + mat + clearance over the whole face, the formed front lies
between the two faces and touches the dome on its rims, each eyewire's face
is a sphere at the over-bent radius, pre-cut dies carry no eyewire
geometry, post-cut dies relieve the inside of each eyewire, the punch and
the anvil close at the bridge, and every solid is watertight, positive and
clear of the formed part at closure.
"""
from pathlib import Path

import numpy as np
import pytest
from manifold3d import Manifold, OpType

from guildmodel.core.forming import build_dies, die_map, forming_readouts
from guildmodel.core.model.kernel import surface_z_at, to_trimesh
from guildmodel.core.project.schema import CastleParams, FormingMetadata, PressDieParams

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    od, os_ = sorted(lenses, key=lambda l: -l.centroid.x)
    return partition_zones(outline, lenses, raw["SCULPT"]), od, os_, hinges


def _forming(**dies):
    return FormingMetadata().with_base_curve(6.0, 170.0, bridge_projection_mm=3.0,
                                             dies=PressDieParams(**dies).model_dump())


@pytest.fixture(scope="module")
def post_cut(demo):
    partition, od, os_, _ = demo
    return build_dies(partition, CastleParams(), _forming(), od, os_)


@pytest.fixture(scope="module")
def pre_cut(demo):
    partition, od, os_, _ = demo
    return build_dies(partition, CastleParams(), _forming(mode="pre_cut"), od, os_)


def _meshes(ds):
    return {name: to_trimesh(man) for name, man in ds.parts().items()}


def test_every_solid_is_watertight_positive_and_one_body(post_cut, pre_cut):
    for ds in (post_cut, pre_cut):
        for name, man in ds.parts().items():
            assert man.volume() > 0, name
            assert len(man.decompose()) == 1, name
            m = to_trimesh(man)
            assert m.is_watertight, name
    assert post_cut.punch is not None and post_cut.anvil is not None
    assert pre_cut.punch is None and pre_cut.anvil is None       # bench tooling is post-cut's


def test_the_closed_gap_is_terrace_plus_mat_plus_clearance(demo, post_cut):
    partition, od, os_, _ = demo
    r = post_cut.report
    t = r["terrace_mm"]
    assert r["closed_gap_mm"] == pytest.approx(t + 3.0 + 0.08)
    fmap = die_map(_forming(), partition, od, os_)
    meshes = _meshes(post_cut)
    # the faces are the map at the two heights, over the rims: the dome's
    # underside and the cup's floor, read by vertical ray at the formed x, y
    probes = []
    for lens in (od, os_):
        x0, y0, x1, y1 = lens.bounds
        probes += [(lens.centroid.x, y0 - 2.0), (lens.centroid.x, y1 + 2.0)]   # the eyewire terraces
    flat = np.array([(x, y, 0.0) for x, y in probes])
    post = fmap(np.column_stack([flat[:, :2], np.full(len(flat), t)]))
    ant = fmap(np.column_stack([flat[:, :2], np.full(len(flat), -(3.0 + 0.08))]))
    z_dome = surface_z_at(meshes["die_posterior"], post[:, :2], face="bottom")
    z_cup = surface_z_at(meshes["die_anterior"], ant[:, :2], face="top")
    assert np.all(np.isfinite(z_dome)) and np.all(np.isfinite(z_cup))
    assert np.abs(z_dome - post[:, 2]).max() < 0.05
    assert np.abs(z_cup - ant[:, 2]).max() < 0.05
    # and the dies close flange to flange on one plane
    bp = np.asarray(post_cut.posterior.bounding_box()).reshape(2, 3)
    ba = np.asarray(post_cut.anterior.bounding_box()).reshape(2, 3)
    assert ba[1, 2] == pytest.approx(r["flange_plane_z"], abs=1e-6)
    assert bp[1, 2] == pytest.approx(r["flange_plane_z"] + 12.0, abs=1e-6)


def test_the_formed_front_lies_between_the_faces_and_rests_on_its_rims(demo, post_cut):
    from guildmodel.core.forming import form_trimesh
    from guildmodel.core.model import build_castle_model
    partition, od, os_, hinges = demo
    castle = CastleParams()
    flat = to_trimesh(build_castle_model(partition, castle, hinges))
    # at closure the front is curved and not yet bridged: post-cut, the punch
    # sets the bridge afterward, so the part is formed by the dies' own map
    fmap = die_map(_forming(), partition, od, os_)
    formed = form_trimesh(flat, fmap)
    # no interpenetration at closure: the dies and the part share nothing but
    # the chordal noise of two tessellations of one surface (microns deep
    # over the rims, a few cubic millimeters in all)
    from guildmodel.core.forming import manifold_from_trimesh
    part = manifold_from_trimesh(formed) if formed.is_watertight else None
    assert part is not None
    for man in (post_cut.posterior, post_cut.anterior):
        shared = Manifold.batch_boolean([man, part], OpType.Intersect)
        assert shared.volume() < 5.0, "the die cuts into the formed part"
    # the rims touch the dome: the eyewire terrace's points, through the map,
    # sit on the dome's underside within the tolerance (the formed mesh is
    # re-tessellated, so the flat vertices are mapped here rather than matched)
    t = post_cut.report["terrace_mm"]
    on_terrace = np.isclose(flat.vertices[:, 2], t, atol=1e-6)
    pts = fmap(np.asarray(flat.vertices)[on_terrace])
    dome = to_trimesh(post_cut.posterior)
    z = surface_z_at(dome, pts[:, :2], face="bottom")
    ok = np.isfinite(z)
    assert ok.sum() > 100
    gap = z[ok] - pts[ok, 2]
    assert gap.min() > -0.05                                     # never inside the die
    assert np.percentile(gap, 50) < 0.05                         # and resting on it


def test_each_eyewire_face_is_a_sphere_at_the_over_bent_radius(demo):
    partition, od, os_, _ = demo
    forming = _forming(over_bend=0.98)
    ds = build_dies(partition, CastleParams(), forming, od, os_)
    fmap = die_map(forming, partition, od, os_)
    assert fmap.R == pytest.approx(forming.base_radius_mm * 0.98)
    t = ds.report["terrace_mm"]
    dome = to_trimesh(ds.posterior)
    from shapely.ops import unary_union
    terraces = unary_union([z.polygon for z in partition.zones if z.name.startswith("eyewire")])
    grown = {name: grow for name, _, grow in ds.report["cutaways"]}
    lifted = unary_union([z.polygon.buffer(grown.get(z.name, 0.0) + 0.5) for z in partition.zones
                          if z.name in grown])
    for lens in (od, os_):
        # the rim band around the aperture, on the eyewire terraces the dome follows
        ring = lens.buffer(3.0).difference(lens.buffer(-6.0)).intersection(terraces).difference(lifted)
        x0, y0, x1, y1 = ring.bounds
        xs, ys = np.meshgrid(np.linspace(x0, x1, 25), np.linspace(y0, y1, 25))
        from shapely import contains_xy
        inside = contains_xy(ring, xs.ravel(), ys.ravel())
        flat = np.column_stack([xs.ravel()[inside], ys.ravel()[inside]])
        formed = fmap(np.column_stack([flat, np.full(len(flat), t)]))
        z = surface_z_at(dome, formed[:, :2], face="bottom")
        pts = np.column_stack([formed[:, :2], z])[np.isfinite(z)]
        # algebraic sphere fit
        A = np.column_stack([2 * pts, np.ones(len(pts))])
        b = (pts ** 2).sum(axis=1)
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        c = sol[:3]
        radius = float(np.sqrt(sol[3] + (c ** 2).sum()))
        # the back face at height t sits one terrace inside the sphere of the map
        assert radius == pytest.approx(fmap.R - t, abs=0.1)
        assert np.abs(np.linalg.norm(pts - c, axis=1) - radius).max() < 0.05


def test_cutaways_under_every_zone_taller_than_the_terrace(demo, post_cut):
    partition, od, os_, _ = demo
    names = [c[0] for c in post_cut.report["cutaways"]]
    assert "nosepad_od" in names and "nosepad_os" in names
    from guildmodel.core.geometry.heights import zone_heights
    h = zone_heights(partition, CastleParams(), None)
    t = post_cut.report["terrace_mm"]
    for name, depth, grow in post_cut.report["cutaways"]:
        assert h[name] > t + 0.2
        assert depth == pytest.approx((h[name] - t) + 1.0, abs=1e-6)
        assert grow >= 2.0                                 # the margin, plus the footing's reach
    # the dome's underside is lifted by the cutaway over the pad: the pocket
    # floor is the map at the pad's height plus the clearance, read where the
    # floor's own formed x, y meets the probe's
    fmap = die_map(_forming(), partition, od, os_)
    dome = to_trimesh(post_cut.posterior)
    pad = partition.zone("nosepad_od").polygon.representative_point()
    at = fmap(np.array([[pad.x, pad.y, t]]))[0]
    xs, ys = np.meshgrid(np.linspace(pad.x - 3, pad.x + 3, 49), np.linspace(pad.y - 3, pad.y + 3, 49))
    floor = fmap(np.column_stack([xs.ravel(), ys.ravel(), np.full(xs.size, h["nosepad_od"] + 1.0)]))
    nearest = floor[np.argmin(np.hypot(floor[:, 0] - at[0], floor[:, 1] - at[1]))]
    z = surface_z_at(dome, at[None, :2], face="bottom")[0]
    assert z == pytest.approx(nearest[2], abs=0.05)
    # and none without cutaways
    no_cut = build_dies(partition, CastleParams(), _forming(cutaways=False), od, os_)
    assert no_cut.report["cutaways"] == []
    z0 = surface_z_at(to_trimesh(no_cut.posterior), at[None, :2], face="bottom")[0]
    assert z0 == pytest.approx(at[2], abs=0.1)


def test_pre_cut_dies_cover_the_blank_and_carry_no_eyewire_geometry(demo, pre_cut, post_cut):
    partition, od, os_, _ = demo
    castle = CastleParams()
    r = pre_cut.report
    assert r["eyewire_relief"] == 0 and post_cut.report["eyewire_relief"] == 2
    w, hgt = r["outer_mm"]
    assert w == pytest.approx(castle.stock.blank_length_mm + 2 * 10.0 + 2 * 12.0, abs=0.5)
    assert hgt == pytest.approx(castle.stock.blank_width_mm + 2 * 10.0 + 2 * 12.0, abs=0.5)
    fmap = die_map(_forming(mode="pre_cut"), partition, od, os_)
    # the press takes the blank, its own thickness and no zone proud of it
    # (the 2.0 bug hunt: the gap was the cut front's eyewire terrace)
    t = r["terrace_mm"]
    assert t == pytest.approx(castle.stock.blank_thickness_mm) and r["cutaways"] == []
    c = od.centroid
    at = fmap(np.array([[c.x, c.y, t]]))[0]
    z_pre = surface_z_at(to_trimesh(pre_cut.posterior), at[None, :2], face="bottom")[0]
    assert z_pre == pytest.approx(at[2], abs=0.05)              # the smooth map, no pocket
    fmap_post = die_map(_forming(), partition, od, os_)
    t = post_cut.report["terrace_mm"]
    at_post = fmap_post(np.array([[c.x, c.y, t]]))[0]
    relieved = fmap_post(np.array([[c.x, c.y, t + 1.0]]))[0]
    z_post = surface_z_at(to_trimesh(post_cut.posterior), at_post[None, :2], face="bottom")[0]
    assert z_post == pytest.approx(relieved[2], abs=0.05)       # the relief, one deep
    # the rim band itself is supported in both: the eyewire terrace above the aperture
    _, _, _, y1 = od.bounds
    rim = fmap_post(np.array([[c.x, y1 + 2.0, t]]))[0]
    z_rim = surface_z_at(to_trimesh(post_cut.posterior), rim[None, :2], face="bottom")[0]
    assert z_rim == pytest.approx(rim[2], abs=0.05)


def test_dowels_vents_and_the_mounting_pattern(demo, post_cut):
    partition, od, os_, _ = demo
    meshes = _meshes(post_cut)
    for x, y in post_cut.report["dowels"]:
        for name in ("die_posterior", "die_anterior"):
            assert not np.isfinite(surface_z_at(meshes[name], [(x, y)])[0]), name    # through
            assert np.isfinite(surface_z_at(meshes[name], [(x + 5.0, y)])[0]), name
    fmap = die_map(_forming(), partition, od, os_)
    for lens in (od, os_):
        v = fmap(np.array([[lens.centroid.x, lens.centroid.y, 0.0]]))[0]
        assert not np.isfinite(surface_z_at(meshes["die_anterior"], [tuple(v[:2])])[0])
    with_holes = build_dies(partition, CastleParams(), _forming(mounting_pattern=True), od, os_)
    assert with_holes.posterior.volume() < post_cut.posterior.volume()


def test_the_punch_and_the_anvil_close_at_the_bridge(demo, post_cut):
    partition, od, os_, _ = demo
    fmap = die_map(_forming(), partition, od, os_)
    punch, anvil = to_trimesh(post_cut.punch), to_trimesh(post_cut.anvil)
    t = post_cut.report["terrace_mm"]
    # the nose stands the projection proud of the shoulders, which stop on the
    # sheet's back: the sheet under it goes down by the projection, not by the
    # projection and its own thickness (the 2.0 bug hunt)
    assert punch.bounds[0, 2] == pytest.approx(t - 3.0, abs=1e-6)
    ox = fmap.offset
    shoulder = surface_z_at(punch, [(ox + 0.5 * fmap.gap + 8.0, fmap.bridge.top_y)], face="bottom")[0]
    assert shoulder == pytest.approx(t, abs=1e-6)
    assert anvil.bounds[1, 2] == pytest.approx(0.0, abs=1e-6)
    # the notch is the gap wide at the top edge and open through the plate
    at_top = surface_z_at(anvil, [(ox, fmap.bridge.top_y)])[0]
    assert not np.isfinite(at_top)
    edge = surface_z_at(anvil, [(ox + 0.5 * fmap.gap + 1.0, fmap.bridge.top_y)])[0]
    assert edge == pytest.approx(0.0, abs=1e-6)


def test_readouts_and_the_label_say_what_the_dies_are(demo, post_cut):
    partition, od, os_, _ = demo
    r = post_cut.report
    fmap = die_map(_forming(), partition, od, os_)
    assert r == {**r, **forming_readouts(fmap, partition, od, os_)}
    assert r["dbl_formed_mm"] < r["dbl_flat_mm"] and r["width_formed_mm"] < r["width_flat_mm"]
    assert "base 6 D" in post_cut.label and "post-cut" in post_cut.label
    assert "gap 7.88" in post_cut.label
    # the die parameters persist with the forming, and a file from before opens with them
    f = FormingMetadata()
    assert f.dies.mode == "post_cut" and f.dies.mat_thickness_mm == 3.0
    back = FormingMetadata.model_validate_json(FormingMetadata().model_dump_json())
    assert back.dies == PressDieParams()
