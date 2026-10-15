"""Sculpts, the kernel side (BUILDPLAN M22 §7.2, §7.3, §7.6).

An STL dropped on the frame is split into shells, welded, flipped if inside
out, repaired if open, unioned, and never read as the sum of overlapping
volumes. Its flat back is found exactly on a sculpt cut by a plane and grown
under noise on a scanned one. Snapped to the frame it is sunk so the union is
one body, a hover is refused with its gap named, an emboss adds what a deboss
removes, the mirror twin is derived, the baked part verifies, and what a
three-axis tool cannot reach is reported. The project file carries the bytes.
"""
import io
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold, OpType

from guildmodel.core.model.kernel import to_trimesh
from guildmodel.core.model.sculpt import (
    HOVER_MM, PlacedSculpt, apply_transform, bake, contact_gap, default_overlap,
    flat_back, load_sculpt, mirror_twin, mount_transform, placed_sculpts, sag_under,
    snap_target, undercuts,
)
from guildmodel.core.project.schema import CastleParams, SculptFeature, SculptMount

ROOT = Path(__file__).parents[1]
DISK = np.pi * 9.0                      # the dome's back: a disk of radius 3


def _stl(mesh) -> bytes:
    return trimesh.exchange.stl.export_stl(mesh)


def _dome(subdivisions: int = 4, radius: float = 3.0):
    """A sphere cut at its equator, cap on: a sculpt with one exact flat back."""
    sph = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    return trimesh.intersections.slice_mesh_plane(
        sph, plane_normal=[0, 0, 1], plane_origin=[0, 0, 0], cap=True)


def _slab(length=40.0, width=20.0, thick=4.0):
    return Manifold.cube([length, width, thick]).translate([-length / 2, -width / 2, 0.0])


# ------------------------------------------------------------- import

def test_merge_makes_a_duplicated_vertex_stl_a_solid():
    box = trimesh.creation.box(extents=(2, 2, 2))
    soup = trimesh.Trimesh(vertices=box.vertices[box.faces].reshape(-1, 3),
                           faces=np.arange(len(box.faces) * 3).reshape(-1, 3), process=False)
    src = load_sculpt(_stl(soup), "box.stl")
    assert src.volume == pytest.approx(8.0)
    assert src.shells == 1 and src.repaired == 0 and src.hulled == 0
    assert src.mesh.is_watertight


def test_an_inverted_stl_flips():
    box = trimesh.creation.box(extents=(2, 2, 2))
    inv = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:, ::-1], process=False)
    src = load_sculpt(_stl(inv), "inverted.stl")
    assert src.volume == pytest.approx(8.0) and src.flipped == 1


def test_an_open_mesh_repairs():
    sph = trimesh.creation.icosphere(subdivisions=3, radius=2.0)
    keep = np.ones(len(sph.faces), dtype=bool)
    keep[sph.triangles_center[:, 2] > 1.9] = False        # a hole at the pole
    holed = sph.submesh([np.flatnonzero(keep)], append=True)
    assert not holed.is_watertight
    src = load_sculpt(_stl(holed), "holed.stl")
    assert src.repaired == 1 and src.hulled == 0
    assert src.mesh.is_watertight
    assert src.volume == pytest.approx(sph.volume, rel=0.02)


def test_two_overlapping_shells_union_and_never_add():
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10)).apply_translation([5, 0, 0])
    src = load_sculpt(_stl(trimesh.util.concatenate([a, b])), "pair.stl")
    assert src.shells == 2
    assert src.volume == pytest.approx(1500.0)            # 2000 less the 500 shared
    # and a self-intersecting single soup is read the same way, not as 2000
    merged = trimesh.util.concatenate([a, b])
    assert load_sculpt(_stl(merged)).volume == pytest.approx(1500.0)


def test_a_multi_shell_input_survives_repair():
    a = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    keep = np.ones(len(a.faces), dtype=bool)
    keep[a.triangles_center[:, 2] > 0.9] = False
    a_open = a.submesh([np.flatnonzero(keep)], append=True)
    b = trimesh.creation.box(extents=(2, 2, 2)).apply_translation([6, 0, 0])
    src = load_sculpt(_stl(trimesh.util.concatenate([a_open, b])), "two.stl")
    assert src.shells == 2 and src.repaired == 1
    assert src.volume == pytest.approx(a.volume + 8.0, rel=0.03)


def test_an_empty_or_degenerate_file_is_refused():
    from guildmodel.core.model.kernel import ManifoldError
    with pytest.raises(ManifoldError):
        load_sculpt(_stl(trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=[[0, 1, 2]])))


# ------------------------------------------------------------- the flat back

def test_the_exact_facet_is_found():
    src = load_sculpt(_stl(_dome()), "dome.stl")
    cands = flat_back(src.mesh)
    back = cands[0]
    assert back.exact
    assert np.allclose(back.normal, [0, 0, -1], atol=1e-9)
    assert back.area == pytest.approx(DISK, rel=0.01)
    assert np.allclose(back.point[:2], 0.0, atol=1e-6) and back.point[2] == pytest.approx(0.0, abs=1e-9)
    rim = back.boundary_points(src.mesh)
    assert np.allclose(np.hypot(rim[:, 0], rim[:, 1]), 3.0, atol=0.02)


def test_the_noisy_facet_is_found_under_rotation():
    rng = np.random.default_rng(1)
    R = trimesh.transformations.rotation_matrix(np.radians(37), [0.3, 1.0, 0.2])
    noisy = _dome().copy()
    noisy.apply_transform(R)
    noisy.vertices += rng.normal(0, 0.01, noisy.vertices.shape)      # ten microns
    src = load_sculpt(_stl(noisy), "scan.stl")
    back = flat_back(src.mesh)[0]
    assert not back.exact
    true_n = R[:3, :3] @ np.array([0.0, 0.0, -1.0])
    assert np.linalg.norm(back.normal - true_n) < 2e-3
    assert back.area > 0.8 * DISK


# ------------------------------------------------------------- mounting

def test_snap_normals_on_the_faces_and_the_rim():
    from shapely.geometry import box
    host = to_trimesh(_slab())
    top = snap_target(host, "posterior", (5.0, 2.0))
    assert np.allclose(top.point, [5.0, 2.0, 4.0]) and np.allclose(top.normal, [0, 0, 1])
    front = snap_target(host, "anterior", (5.0, 2.0))
    assert np.allclose(front.point, [5.0, 2.0, 0.0]) and np.allclose(front.normal, [0, 0, -1])
    rim = snap_target(host, "rim", (25.0, 3.0, 2.0), outline=box(-20, -10, 20, 10))
    assert np.allclose(rim.point, [20.0, 3.0, 2.0]) and np.allclose(rim.normal, [1, 0, 0])
    pick = snap_target(host, "pick", (1.0, 1.0, 4.0), pick_normal=(0, 0.6, 0.8))
    assert np.allclose(pick.normal, [0, 0.6, 0.8])
    with pytest.raises(ValueError):
        snap_target(host, "rim", (0, 0))


def test_the_back_lands_on_the_target_facing_in():
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    host = to_trimesh(_slab())
    target = snap_target(host, "posterior", (5.0, 2.0))
    T = mount_transform(back, target, overlap_mm=0.0)
    placed = apply_transform(src.manifold, T)
    lo, hi = np.asarray(placed.bounding_box()).reshape(2, 3)
    assert lo[2] == pytest.approx(4.0, abs=1e-9) and hi[2] == pytest.approx(7.0, abs=1e-6)
    assert (lo[:2] + hi[:2]) / 2 == pytest.approx([5.0, 2.0], abs=1e-6)
    # on the rim it stands out sideways, and a spin turns it about the normal
    from shapely.geometry import box as sbox
    rim = snap_target(host, "rim", (25.0, 3.0, 2.0), outline=sbox(-20, -10, 20, 10))
    side = apply_transform(src.manifold, mount_transform(back, rim, overlap_mm=0.0))
    lo, hi = np.asarray(side.bounding_box()).reshape(2, 3)
    assert lo[0] == pytest.approx(20.0, abs=1e-9) and hi[0] == pytest.approx(23.0, abs=1e-6)
    scaled = apply_transform(src.manifold, mount_transform(back, target, overlap_mm=0.0, scale=2.0))
    assert scaled.volume() == pytest.approx(8.0 * src.volume, rel=1e-6)


def test_sinking_gives_one_body_and_a_hover_is_refused():
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    slab = _slab()
    host = to_trimesh(slab)
    target = snap_target(host, "posterior", (5.0, 2.0))
    T0 = mount_transform(back, target, overlap_mm=0.0)
    assert sag_under(host, back, src.mesh, T0, target) == 0.0          # a flat terrace
    overlap = default_overlap(0.0)
    sunk = apply_transform(src.manifold, mount_transform(back, target, overlap_mm=overlap))
    assert contact_gap(slab, sunk) <= HOVER_MM
    assert len(bake(slab, [PlacedSculpt(sunk, "emboss")]).decompose()) == 1
    hover = apply_transform(src.manifold, mount_transform(back, target, overlap_mm=-0.02))
    gap = contact_gap(slab, hover)
    assert gap == pytest.approx(0.02, abs=1e-6)                         # the gap, named
    assert len(Manifold.batch_boolean([slab, hover], OpType.Add).decompose()) == 2


def test_the_sag_is_the_step_under_a_back_across_a_seam():
    # two terraces: the back spans the step, and the sag is its height
    low = Manifold.cube([40.0, 20.0, 3.0]).translate([-20.0, -10.0, 0.0])
    high = Manifold.cube([20.0, 20.0, 4.0]).translate([-20.0, -10.0, 0.0])
    stepped = Manifold.batch_boolean([low, high], OpType.Add)
    host = to_trimesh(stepped)
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    target = snap_target(host, "posterior", (-1.0, 0.0))               # on the high side
    assert target.point[2] == pytest.approx(4.0)
    T0 = mount_transform(back, target, overlap_mm=0.0)
    assert sag_under(host, back, src.mesh, T0, target) == pytest.approx(1.0, abs=1e-6)
    assert default_overlap(1.0) == pytest.approx(1.05)


def test_flush_on_a_flat_host_is_one_body():
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    slab = _slab()
    target = snap_target(to_trimesh(slab), "posterior", (5.0, 2.0))
    flush = apply_transform(src.manifold, mount_transform(back, target, overlap_mm=0.0))
    baked = bake(slab, [PlacedSculpt(flush, "emboss")])
    assert len(baked.decompose()) == 1
    assert baked.volume() == pytest.approx(slab.volume() + src.volume, rel=1e-6)


# ------------------------------------------------------------- baking

def _placed_dome(overlap=0.05, at=(5.0, 2.0), face="posterior"):
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    slab = _slab()
    target = snap_target(to_trimesh(slab), face, at)
    return src, slab, apply_transform(src.manifold, mount_transform(back, target, overlap_mm=overlap))


def test_an_emboss_adds_and_a_deboss_removes_the_embedded_volume():
    src, slab, placed = _placed_dome()
    sliver = DISK * 0.05                                                # what the sink buries
    emboss = bake(slab, [PlacedSculpt(placed, "emboss")])
    assert emboss.volume() == pytest.approx(slab.volume() + src.volume - sliver, rel=1e-3)
    deboss = bake(slab, [PlacedSculpt(placed, "deboss")])
    assert deboss.volume() == pytest.approx(slab.volume() - sliver, rel=1e-3)
    # a deboss cuts an emboss: the order is adds first
    both = bake(slab, [PlacedSculpt(placed, "emboss"),
                       PlacedSculpt(placed.translate([0.0, 0.0, 1.5]), "deboss")])
    assert both.volume() < emboss.volume()


def test_the_mirror_twin_has_the_volume_and_the_mirrored_box():
    src, slab, placed = _placed_dome()
    twin = mirror_twin(placed)
    assert twin.volume() == pytest.approx(placed.volume(), rel=1e-9)
    lo, hi = np.asarray(placed.bounding_box()).reshape(2, 3)
    tlo, thi = np.asarray(twin.bounding_box()).reshape(2, 3)
    assert tlo[0] == pytest.approx(-hi[0]) and thi[0] == pytest.approx(-lo[0])
    assert np.allclose(tlo[1:], lo[1:]) and np.allclose(thi[1:], hi[1:])


def test_placed_sculpts_expand_the_mirror_and_skip_what_is_off_or_missing():
    src, slab, placed = _placed_dome()
    data = _stl(_dome())
    feature = SculptFeature(id="crest", source_name="dome.stl", source_sha256=src.sha256,
                            mirror=True).with_transform(np.eye(4))
    off = SculptFeature(id="off", source_sha256=src.sha256, enabled=False)
    lost = SculptFeature(id="lost", source_sha256="0" * 64)
    sources = {src.sha256: data}
    out = placed_sculpts([feature, off, lost], sources)
    assert [(p.feature_id, p.mirrored, p.op) for p in out] == [("crest", False, "emboss"),
                                                               ("crest", True, "emboss")]
    assert sources[src.sha256] == data                           # the bytes are left as they came
    castle = CastleParams(sculpts=[feature, off])
    assert [s.id for s in castle.resolved_sculpts()] == ["crest"]


def test_provenance_survives_the_bake():
    src, slab, placed = _placed_dome()
    host = slab.as_original()
    sculpt = placed.as_original()
    baked = bake(host, [PlacedSculpt(sculpt, "emboss")])
    ids = set(np.asarray(baked.to_mesh64().run_original_id).tolist())
    assert sculpt.original_id() in ids and host.original_id() in ids


def test_the_baked_part_verifies_and_exports_watertight():
    from guildmodel.core.mesh_check import verify_mesh
    src, slab, placed = _placed_dome()
    baked = bake(slab, [PlacedSculpt(placed, "emboss"), PlacedSculpt(mirror_twin(placed), "deboss")])
    mesh = to_trimesh(baked)
    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict
    out = trimesh.load(io.BytesIO(_stl(mesh)), file_type="stl")
    assert out.is_watertight and out.volume == pytest.approx(baked.volume(), rel=1e-6)


def test_the_demo_front_bakes_a_sculpt_through_the_build(tmp_path):
    """The mesh kernel's whole build, a dome embossed on the posterior: one
    body, more volume, and the project file round-trips the bytes."""
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.model import build_castle_model
    from guildmodel.core.project.gmodel import FORMAT_VERSION, load_gmodel, save_gmodel
    from guildmodel.core.project.schema import Component, ComponentKind, ProjectSchema

    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    partition = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    plain = build_castle_model(partition, castle, hinges)
    host = to_trimesh(plain)
    data = _stl(_dome())
    src = load_sculpt(data, "dome.stl")
    back = flat_back(src.mesh)[0]
    at = np.asarray(host.bounds).mean(axis=0)[:2]
    target = snap_target(host, "posterior", at)
    T0 = mount_transform(back, target, overlap_mm=0.0)
    overlap = default_overlap(sag_under(host, back, src.mesh, T0, target))
    feature = SculptFeature(id="crest", source_name="dome.stl", source_sha256=src.sha256,
                            mount=SculptMount(face="posterior", point=[float(at[0]), float(at[1])],
                                              overlap_mm=overlap),
                            triangles=src.triangles).with_transform(
        mount_transform(back, target, overlap_mm=overlap))
    castle.sculpts = [feature]
    sculpts = placed_sculpts(castle.resolved_sculpts(), {src.sha256: src})
    with_sculpt = build_castle_model(partition, castle, hinges, sculpts=sculpts)
    assert len(with_sculpt.decompose()) == 1
    assert with_sculpt.volume() > plain.volume() + 0.9 * src.volume

    proj = ProjectSchema(components=[Component(id="front", kind=ComponentKind.FRAME_FRONT,
                                               castle=castle)])
    path = tmp_path / "crest.gmodel"
    save_gmodel(path, project=proj, features={"crest": data})
    bundle = load_gmodel(path)
    assert bundle.manifest["format_version"] == FORMAT_VERSION == 2
    assert bundle.features == {"crest": data}
    back_feature = bundle.project.components[0].castle.sculpts[0]
    assert back_feature.source_sha256 == src.sha256
    assert np.allclose(back_feature.transform_matrix(), feature.transform_matrix())
    # a version-1 file, with no features folder, loads with none
    v1 = tmp_path / "old.gmodel"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(v1, "w") as zout:
        for name in zin.namelist():
            if name.startswith("features/"):
                continue
            data_ = zin.read(name)
            if name == "manifest.json":
                import json
                m = json.loads(data_)
                m["format_version"] = 1
                m["contents"] = {k: v for k, v in m["contents"].items()
                                 if not k.startswith("features/")}
                data_ = json.dumps(m).encode()
            zout.writestr(name, data_)
    old = load_gmodel(v1)
    assert old.features == {} and old.project.components[0].castle.sculpts[0].id == "crest"


# ------------------------------------------------------------- undercuts

def _emboss_sphere(dz: float, radius: float = 3.0):
    slab = _slab()
    ball = Manifold.sphere(radius, 64).translate([5.0, 2.0, dz])
    return to_trimesh(bake(slab, [PlacedSculpt(ball, "emboss")]))


def test_the_undercut_fixtures():
    # an emboss with its equator above the surface hides its underside
    above = undercuts(_emboss_sphere(4.0 + 1.0), 0.25)
    assert above and above.area_mm2 > 5.0 and len(above.faces) > 0
    # one with its equator below the surface hides nothing
    below = undercuts(_emboss_sphere(4.0 - 1.0), 0.25)
    assert not below and len(below.faces) == 0
    # a deboss whose equator lies below the surface leaves a cavity that narrows upward
    slab = _slab()
    ball = Manifold.sphere(3.0, 64).translate([5.0, 2.0, 2.0])
    cavity = undercuts(to_trimesh(bake(slab, [PlacedSculpt(ball, "deboss")])), 0.25)
    assert cavity and cavity.area_mm2 > 5.0
    # and a plain slab has none
    assert not undercuts(to_trimesh(slab), 0.25)


# ------------------------------------------------------------- performance

def test_the_union_of_a_plate_and_a_large_sculpt_is_quick():
    import time
    plate = Manifold.sphere(20.0, 440)                     # about 97k triangles
    sculpt = Manifold.sphere(6.0, 400).translate([0.0, 0.0, 18.0])   # about 80k
    assert plate.num_tri() > 50_000 and sculpt.num_tri() > 50_000
    t = time.perf_counter()
    out = bake(plate, [PlacedSculpt(sculpt, "emboss")])
    dt = time.perf_counter() - t
    assert out.volume() > plate.volume()
    assert dt < 1.0, f"union took {dt:.2f} s"


# ------------------------------------------------------------- the schema

def test_the_feature_round_trips_its_transform_and_defaults():
    f = SculptFeature(id="a")
    assert np.allclose(f.transform_matrix(), np.eye(4))
    T = np.arange(16, dtype=float).reshape(4, 4)
    g = f.with_transform(T)
    assert g.transform == [float(x) for x in range(16)]
    assert np.allclose(g.transform_matrix(), T)
    assert g.op == "emboss" and g.mount.face == "posterior" and g.mount.overlap_mm == 0.05
    bad = SculptFeature(id="b", transform=[1.0, 2.0])
    assert np.allclose(bad.transform_matrix(), np.eye(4))   # a short list reads as identity
    castle = CastleParams()
    assert castle.sculpts == [] and castle.resolved_sculpts() == []
    assert CastleParams.model_validate_json(castle.model_dump_json()).sculpts == []
