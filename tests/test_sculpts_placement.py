"""Sculpt placement, redone (BUILDPLAN §7.8, 2026-11-01).

The maker's own elements import whole and fast: holes are capped along the
faces' fans (a relief whose back was cut away at export, a filigree with
pinched holes), a shell past capping is rebuilt as a relief over its back,
and pymeshfix sits behind a loss guard. One back can come as many facets.
A sculpt flips: the relief turned into the frame, the crown sunk by the
depth, so a deboss imprints it as a stamp. The panel ranges Sink to the
relief and reads Size in mm; the app seats a drop under the cursor and a
drag where it let go, on the face the surface normal names.
"""
import io
import os
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold, OpType

from guildmodel.core.model.kernel import ManifoldError, surface_z_at, to_trimesh
from guildmodel.core.model.mesh_repair import (
    boundary_loops, cap_holes, drop_fins, ear_clip, kept_enough, relief_remesh,
    relief_resolution,
)
from guildmodel.core.model.sculpt import (
    PlacedSculpt, apply_transform, bake, flat_back, load_sculpt, manifold_from_arrays,
    mount_transform, relief_height, sag_under, snap_target,
)
from guildmodel.core.project.schema import CastleParams, SculptFeature, SculptMount

ROOT = Path(__file__).parents[1]
#: The maker's elements (a baroque panel and an ornament), read when present;
#: set the variable to "" to skip on purpose.
_ELEMENTS_ENV = "GUILDMODEL_ELEMENTS"
_ELEMENTS_DEFAULT = Path.home() / "Documents" / "Spectacles" / "elements"


def _elements_dir():
    root = os.environ.get(_ELEMENTS_ENV)
    if root == "":
        return None
    p = Path(root) if root else _ELEMENTS_DEFAULT
    return p if p.is_dir() and any(p.glob("*.stl")) else None


def _stl(mesh) -> bytes:
    return trimesh.exchange.stl.export_stl(mesh)


def _dome(subdivisions=3, radius=3.0, cap=True):
    sph = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    return trimesh.intersections.slice_mesh_plane(
        sph, plane_normal=[0, 0, 1], plane_origin=[0, 0, 0], cap=cap)


def _slab(length=40.0, width=20.0, thick=4.0):
    return Manifold.cube([length, width, thick]).translate([-length / 2, -width / 2, 0.0])


# ------------------------------------------------------------- capping

def test_a_relief_whose_back_was_cut_away_is_capped_and_the_cap_is_its_back():
    """The maker's ornament came as sixteen open pieces, each missing its
    back plane: the boundary loop is the back, capped exactly."""
    open_dome = _dome(cap=False)
    open_dome.merge_vertices()                                 # as a file read welds it
    assert not open_dome.is_watertight
    loops, dups = boundary_loops(np.asarray(open_dome.faces))
    assert len(loops) == 1 and dups == 0
    src = load_sculpt(_stl(open_dome), "open.stl")
    assert src.capped == 1 and src.repaired == 0 and src.remeshed == 0
    assert src.mesh.is_watertight
    assert src.volume == pytest.approx(_dome(cap=True).volume, rel=1e-6)
    back = flat_back(src.mesh)[0]
    assert back.exact and np.allclose(back.normal, [0, 0, -1], atol=1e-9)
    assert back.area == pytest.approx(np.pi * 9.0, rel=0.02)
    assert relief_height(src.mesh, back) == pytest.approx(3.0, abs=1e-6)
    src.back = back
    assert src.height_mm == pytest.approx(3.0, abs=1e-6)
    assert src.extent_mm == pytest.approx(6.0, abs=1e-6)


def test_two_holes_sharing_a_vertex_are_walked_through_the_pinch():
    """A box with two faces removed that meet at a corner: the fan walk
    passes the shared vertex on each hole's own side, and both cap."""
    box = trimesh.creation.box(extents=(2, 2, 2))
    box = box.subdivide()
    centers = box.triangles_center
    # two holes on the top face, at two triangles that share a vertex
    top = np.flatnonzero(centers[:, 2] > 0.99)
    faces = np.asarray(box.faces)
    shared = None
    for i in top:
        for j in top:
            if i < j and len(set(faces[i]) & set(faces[j])) == 1:
                shared = (i, j)
                break
        if shared:
            break
    assert shared is not None
    keep = np.ones(len(faces), dtype=bool)
    keep[list(shared)] = False
    holed = trimesh.Trimesh(box.vertices, faces[keep], process=False)
    loops, dups = boundary_loops(np.asarray(holed.faces))
    assert len(loops) == 2 and all(len(lp) == 3 for lp in loops) and dups == 0
    V, F, info = cap_holes(np.asarray(holed.vertices), np.asarray(holed.faces))
    assert info["capped"] == 2
    man = manifold_from_arrays(V, F)
    assert man.volume() == pytest.approx(8.0, rel=1e-9)


def test_a_fin_is_dropped_before_capping():
    box = trimesh.creation.box(extents=(2, 2, 2))
    faces = np.asarray(box.faces)
    # a sliver drawn on top of an existing face, sharing one of its edges
    a, b, c = faces[0]
    extra = np.array([[a, b, c]])                         # the same face twice: a fin
    finned = np.vstack([faces, extra])
    areas = trimesh.triangles.area(np.asarray(box.vertices)[finned])
    F2, dropped = drop_fins(finned, areas)
    assert dropped == 1 and len(F2) == len(faces)
    src = load_sculpt(_stl(trimesh.Trimesh(box.vertices, finned, process=False)), "fin.stl")
    assert src.volume == pytest.approx(8.0, rel=1e-9) and src.hulled == 0


def test_ear_clip_follows_the_polygon_winding_and_refuses_a_fold():
    sq = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    tris = ear_clip(sq)
    assert len(tris) == 2
    # every triangle has the square's (positive) winding
    def turn(p, a, b, c):
        return (p[b][0] - p[a][0]) * (p[c][1] - p[a][1]) - (p[b][1] - p[a][1]) * (p[c][0] - p[a][0])
    for a, b, c in tris:
        assert turn(sq, a, b, c) > 0
    for a, b, c in ear_clip(sq[::-1]):
        assert turn(sq[::-1], a, b, c) < 0
    L = np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], float)
    assert len(ear_clip(L)) == 4
    flat = np.array([[0, 0], [2, 0], [1, 0], [3, 0]], float)    # all on one line: no ear
    with pytest.raises(ValueError):
        ear_clip(flat)


# ------------------------------------------------------------- the relief remesh

def test_the_relief_remesh_rebuilds_a_dome_as_a_solid_over_its_back():
    dome = _dome(subdivisions=4)
    V, F, res = relief_remesh(np.asarray(dome.vertices), np.asarray(dome.faces),
                              [0, 0, -1], [0, 0, 0], resolution=0.05)
    assert res == 0.05
    man = manifold_from_arrays(V, F)
    assert man.status().name == "NoError"
    assert man.volume() == pytest.approx(dome.volume, rel=0.03)
    lo, hi = np.asarray(man.bounding_box()).reshape(2, 3)
    assert lo[2] == pytest.approx(0.0, abs=1e-9) and hi[2] == pytest.approx(3.0, abs=0.06)
    # rotated: the remesh works in the back's own frame and comes back in ours
    R = trimesh.transformations.rotation_matrix(np.radians(40), [1, 0.3, 0.2])
    turned = dome.copy()
    turned.apply_transform(R)
    n = R[:3, :3] @ np.array([0, 0, -1.0])
    V2, F2, _ = relief_remesh(np.asarray(turned.vertices), np.asarray(turned.faces),
                              n, R[:3, 3], resolution=0.05)
    man2 = manifold_from_arrays(V2, F2)
    assert man2.volume() == pytest.approx(dome.volume, rel=0.03)
    assert relief_resolution([326.0, 210.0, 6.0]) == pytest.approx(326.0 / 600)
    assert relief_resolution([2.0, 2.0, 1.0]) == 0.02


def test_a_shell_past_capping_is_rebuilt_as_a_relief_not_handed_to_the_fixer():
    """A dome with a bow-tie hole the cap cannot close (two triangles that
    cross) is rebuilt over its back, and the record says so."""
    dome = _dome(subdivisions=3)
    faces = np.asarray(dome.faces).copy()
    # cross two neighboring triangles' edges: swap a vertex between them
    adj = dome.face_adjacency
    i, j = adj[0]
    shared = list(set(faces[i]) & set(faces[j]))
    oi = [v for v in faces[i] if v not in shared][0]
    oj = [v for v in faces[j] if v not in shared][0]
    faces[i] = [shared[0], oi, oj]
    faces[j] = [shared[1], oj, oi]
    broken = trimesh.Trimesh(dome.vertices, faces, process=False)
    src = load_sculpt(_stl(broken), "broken.stl")
    assert src.hulled == 0
    assert src.capped or src.remeshed or src.repaired
    assert src.volume == pytest.approx(dome.volume, rel=0.05)


def test_an_open_relief_with_a_plateau_is_rebuilt_over_its_hole_not_its_top():
    """A box without its bottom: the largest facet is the top, but the shell
    lies below it, so the hole's plane is the back; inside out, the same."""
    from guildmodel.core.model.sculpt import _shell_back_plane
    box = trimesh.creation.box(extents=(10, 10, 2))
    keep = box.face_normals[:, 2] > -0.5
    open_box = trimesh.Trimesh(box.vertices, np.asarray(box.faces)[keep], process=False)
    n, pt = _shell_back_plane(open_box)
    assert np.allclose(n, [0, 0, -1], atol=1e-6) and pt[2] == pytest.approx(-1.0, abs=1e-6)
    V, F, _ = relief_remesh(np.asarray(open_box.vertices), np.asarray(open_box.faces), n, pt,
                            resolution=0.25)
    assert manifold_from_arrays(V, F).volume() == pytest.approx(200.0, rel=0.1)
    inside_out = trimesh.Trimesh(open_box.vertices, np.asarray(open_box.faces)[:, ::-1],
                                 process=False)
    V2, F2, _ = relief_remesh(np.asarray(inside_out.vertices), np.asarray(inside_out.faces),
                              n, pt, resolution=0.25)
    assert manifold_from_arrays(V2, F2).volume() == pytest.approx(200.0, rel=0.1)


def test_the_loss_guard_refuses_a_corner_of_the_mesh():
    box = trimesh.creation.box(extents=(10, 10, 2))
    V, F = np.asarray(box.vertices), np.asarray(box.faces)
    assert kept_enough(V, F, V, F)
    corner = F[:2]
    assert not kept_enough(V, F, V, corner)


# ------------------------------------------------------------- one back, many facets

def test_facets_on_one_plane_are_one_back():
    """Two domes side by side in one file: two shells, two exact facets on
    z = 0, one back candidate with both their areas."""
    a = _dome()
    b = _dome().apply_translation([8.0, 0.0, 0.0])
    src = load_sculpt(_stl(trimesh.util.concatenate([a, b])), "pair.stl")
    assert src.shells == 2
    cands = flat_back(src.mesh)
    assert len(cands) == 1
    back = cands[0]
    assert back.area == pytest.approx(2 * np.pi * 9.0, rel=0.02)
    assert np.allclose(back.normal, [0, 0, -1], atol=1e-9)
    assert back.point[0] == pytest.approx(4.0, abs=1e-6) and back.point[2] == pytest.approx(0.0, abs=1e-9)
    rim = back.boundary_points(src.mesh)
    assert len(rim) > 40                                    # both rims


def test_simplified_keeps_the_repair_and_finds_the_back_again():
    open_dome = _dome(subdivisions=5, cap=False)
    src = load_sculpt(_stl(open_dome), "open.stl")
    src.back = flat_back(src.mesh)[0]
    fine = src.triangles
    coarse = src.simplified(0.05)
    assert coarse.triangles < fine and coarse.simplify_tol == 0.05
    assert coarse.capped == 1 and coarse.sha256 == src.sha256 and coarse.name == src.name
    assert coarse.back is not None and np.allclose(coarse.back.normal, [0, 0, -1], atol=1e-6)
    assert coarse.volume == pytest.approx(src.volume, rel=0.05)
    assert "simplified to 0.05 mm" in coarse.notes() and "1 hole capped" in coarse.notes()


# ------------------------------------------------------------- the flip

def test_a_flipped_mount_puts_the_crown_at_the_depth_and_the_back_above():
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    h = relief_height(src.mesh, back)
    slab = _slab()
    target = snap_target(to_trimesh(slab), "posterior", (5.0, 2.0))
    T = mount_transform(back, target, overlap_mm=1.0, flip=True, height_mm=h)
    placed = apply_transform(src.manifold, T)
    lo, hi = np.asarray(placed.bounding_box()).reshape(2, 3)
    assert lo[2] == pytest.approx(3.0, abs=1e-6)             # the crown 1 mm into the slab
    assert hi[2] == pytest.approx(6.0, abs=1e-6)             # the back 2 mm above it
    assert (lo[:2] + hi[:2]) / 2 == pytest.approx([5.0, 2.0], abs=1e-6)
    # scaled: the height scales with it
    T2 = mount_transform(back, target, overlap_mm=0.5, flip=True, height_mm=h, scale=0.5)
    lo2, hi2 = np.asarray(apply_transform(src.manifold, T2).bounding_box()).reshape(2, 3)
    assert lo2[2] == pytest.approx(3.5, abs=1e-6) and hi2[2] == pytest.approx(5.0, abs=1e-6)
    # relief out is as it was: the back sunk by the overlap
    lo3, hi3 = np.asarray(apply_transform(
        src.manifold, mount_transform(back, target, overlap_mm=0.2)).bounding_box()).reshape(2, 3)
    assert lo3[2] == pytest.approx(3.8, abs=1e-6) and hi3[2] == pytest.approx(6.8, abs=1e-6)


def test_a_flipped_deboss_imprints_the_relief():
    """The stamp: what the subtract removes is exactly the sculpt below the
    surface, and the surface under the point is lower by the depth."""
    src = load_sculpt(_stl(_dome(subdivisions=4)), "dome.stl")
    back = flat_back(src.mesh)[0]
    slab = _slab()
    target = snap_target(to_trimesh(slab), "posterior", (5.0, 2.0))
    depth = 1.2
    T = mount_transform(back, target, overlap_mm=depth, flip=True,
                        height_mm=relief_height(src.mesh, back))
    placed = apply_transform(src.manifold, T)
    baked = bake(slab, [PlacedSculpt(placed, "deboss")])
    buried = Manifold.batch_boolean([slab, placed], OpType.Intersect).volume()
    assert buried > 1.0
    assert slab.volume() - baked.volume() == pytest.approx(buried, rel=1e-6)
    # read a hair off the apex (a vertical ray through a vertex is a miss);
    # the floor there is the sphere's own sag higher
    z = surface_z_at(to_trimesh(baked), [(5.3, 2.0)], face="top")[0]
    assert z == pytest.approx(4.0 - depth + (3.0 - np.sqrt(9.0 - 0.09)), abs=0.02)
    # the same sculpt relief-out, sunk 0.05, removes only the sliver
    T0 = mount_transform(back, target, overlap_mm=0.05)
    thin = bake(slab, [PlacedSculpt(apply_transform(src.manifold, T0), "deboss")])
    assert slab.volume() - thin.volume() < 2.0


def test_the_sag_on_a_wall_is_the_nearest_contact_along_the_mount_normal():
    """A back standing on the rim: over a recess wider than itself the wall
    is the recess's depth away, and the sink covers it; across a notch
    narrower than itself its ends touch, and it sinks no further (the two
    faces are read by vertical ray, the largest drop; the rim and a pick by
    a ray along the normal, the nearest)."""
    from shapely.geometry import box
    slab = Manifold.cube([40, 20, 10]).translate([-20, -10, 0])
    recess = Manifold.cube([10, 2, 10]).translate([-5, 8, 0])    # 2 mm in, wider than the back
    host = to_trimesh(Manifold.batch_boolean([slab, recess], OpType.Subtract))
    src = load_sculpt(_stl(_dome()), "dome.stl")
    back = flat_back(src.mesh)[0]
    target = snap_target(host, "rim", (0.0, 12.0, 5.0), outline=box(-20, -10, 20, 10))
    assert np.allclose(target.point, [0.0, 10.0, 5.0]) and np.allclose(target.normal, [0, 1, 0])
    T0 = mount_transform(back, target, overlap_mm=0.0)
    assert sag_under(host, back, src.mesh, T0, target) == pytest.approx(2.0, abs=1e-6)
    notch = Manifold.cube([4, 2, 10]).translate([-2, 8, 0])       # narrower: the ends touch
    notched = to_trimesh(Manifold.batch_boolean([slab, notch], OpType.Subtract))
    assert sag_under(notched, back, src.mesh, T0, target) == 0.0
    plain = snap_target(to_trimesh(slab), "rim", (0.0, 12.0, 5.0), outline=box(-20, -10, 20, 10))
    assert sag_under(to_trimesh(slab), back, src.mesh,
                     mount_transform(back, plain, overlap_mm=0.0), plain) == 0.0
    # a back taller than the wall still reads the recess: the samples are
    # held within the host's height
    tall = Manifold.cube([40, 20, 3]).translate([-20, -10, 0])
    tall_recessed = to_trimesh(Manifold.batch_boolean(
        [tall, Manifold.cube([10, 2, 3]).translate([-5, 8, 0])], OpType.Subtract))
    t_tall = snap_target(tall_recessed, "rim", (0.0, 12.0, 1.5), outline=box(-20, -10, 20, 10))
    assert sag_under(tall_recessed, back, src.mesh, mount_transform(back, t_tall, overlap_mm=0.0),
                     t_tall) == pytest.approx(2.0, abs=1e-6)
    # a pick with a leaning normal reads the same way
    pick = snap_target(host, "pick", (0.0, 10.0, 5.0), pick_normal=(0.0, 1.0, 0.0))
    assert sag_under(host, back, src.mesh, mount_transform(back, pick, overlap_mm=0.0),
                     pick) == pytest.approx(2.0, abs=1e-6)


# ------------------------------------------------------------- the CAM

@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["COMPONENT"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def test_a_flipped_deboss_on_the_back_is_a_cavity_in_the_relief(demo):
    """The stamp reaches the CAM as the model's own upper envelope: under
    the sculpt the relief is lower than the plain terrace by the depth, and
    the footprint joins the feature band."""
    from guildmodel.core.model import build_castle_model
    from guildmodel.core.zmap import castle_relief
    partition, hinges = demo
    castle = CastleParams()
    host = to_trimesh(build_castle_model(partition, castle, hinges))
    data = _stl(_dome(radius=2.5))
    src = load_sculpt(data, "dome.stl")
    back = flat_back(src.mesh)[0]
    zone = next(z for z in partition.zones if z.name.startswith("eyewire_superior"))
    c = zone.polygon.representative_point()
    target = snap_target(host, "posterior", (c.x, c.y))
    depth = 0.8
    h = relief_height(src.mesh, back)
    T = mount_transform(back, target, overlap_mm=depth, flip=True, height_mm=h)
    feature = SculptFeature(
        id="stamp", source_name="dome.stl", source_sha256=src.sha256, op="deboss",
        height_mm=h, extent_mm=src.extent_mm,
        mount=SculptMount(face="posterior", point=[float(v) for v in target.point],
                          normal=[float(v) for v in target.normal], overlap_mm=depth,
                          flip=True)).with_transform(T)
    castle.sculpts = [feature]
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3,
                           sculpt_sources={src.sha256: data})
    plain = castle_relief(partition, CastleParams(), hinges, kernel="mesh", resolution=0.3)
    f = relief.field
    r = int(round((c.y - f.origin[1]) / f.resolution))
    col = int(round((c.x + 0.3 - f.origin[0]) / f.resolution))
    assert f.z[r, col] < plain.field.z[r, col] - 0.5 * depth
    assert f.z[r, col] > plain.field.z[r, col] - depth - 0.1
    assert len(relief.sculpt_footprints) == 1
    assert relief.feature_band is not None and relief.feature_band[r, col]


# ------------------------------------------------------------- the maker's elements

@pytest.mark.skipif(_elements_dir() is None, reason="the maker's elements are not on this machine")
def test_the_makers_elements_import_whole_and_quickly():
    import time
    for path in sorted(_elements_dir().glob("*.stl")):
        data = path.read_bytes()
        raw = trimesh.load(io.BytesIO(data), file_type="stl", process=True, force="mesh")
        t0 = time.perf_counter()
        src = load_sculpt(data, path.name)
        took = time.perf_counter() - t0
        assert took < 20.0, (path.name, took)
        assert src.hulled == 0
        # the whole of it: the box the file spans, and more than the fixer kept
        b = np.asarray(src.mesh.bounds)
        assert np.allclose(b[1] - b[0], raw.extents, rtol=0.02, atol=0.1), path.name
        assert src.mesh.is_watertight
        src.back = flat_back(src.mesh)[0]
        assert src.back.exact and src.height_mm > 0.5
        assert src.height_mm < src.extent_mm


# ------------------------------------------------------------- the panel

@pytest.fixture
def qapp(monkeypatch, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _feature(**kw):
    base = dict(id="sculpt_1", label="Crest", source_name="crest.stl", source_sha256="a" * 64,
                triangles=100, height_mm=4.0, extent_mm=50.0, scale=0.3,
                mount=SculptMount(face="posterior", point=[1.0, 2.0, 4.0],
                                  normal=[0.0, 0.0, 1.0], overlap_mm=0.05))
    base.update(kw)
    return SculptFeature(**base)


def test_the_panel_reads_size_in_mm_and_ranges_sink_to_the_relief(qapp):
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    heard = []
    p.sculpt_mount_changed.connect(lambda row, moved: heard.append((row, moved)))
    p.add_sculpt(_feature())
    assert p.sc_size.value() == pytest.approx(15.0)             # 50 mm × 0.3
    assert p.sc_scale.value() == pytest.approx(0.3)
    assert p.sc_overlap.hard_range()[1] == pytest.approx(3.0)   # 1.2 mm relief: the floor of 3
    assert not p.sc_flip.isChecked()
    # Size edits Scale
    p.sc_size.setValue(10.0)
    assert p.sculpts()[0].scale == pytest.approx(0.2)
    assert p.sc_scale.value() == pytest.approx(0.2)
    assert heard[-1] == (0, False)
    # Scale edits Size
    p.sc_scale.setValue(1.0)
    assert p.sc_size.value() == pytest.approx(50.0)
    assert p.sc_overlap.hard_range()[1] == pytest.approx(5.0)   # a 4 mm relief: height + 1
    # Flip is a mount edit and shows in the list
    p.sc_flip.setChecked(True)
    assert p.sculpts()[0].mount.flip and heard[-1] == (0, False)
    assert "flipped" in p.sculpt_list.item(0).text()
    # a record with no extent recorded (a 2.0.0 file) keeps Size off
    p.add_sculpt(_feature(id="old", extent_mm=0.0, height_mm=0.0, scale=1.0))
    assert not p.sc_size.isEnabled()


def test_switching_to_deboss_flips_the_sculpt_and_sinks_it_halfway(qapp):
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    p = ParamsPanel()
    heard = []
    p.sculpt_mount_changed.connect(lambda row, moved: heard.append((row, moved)))
    p.add_sculpt(_feature())                                   # 4 mm × 0.3 = 1.2 mm relief
    p.sc_op.setCurrentIndex(1)
    f = p.sculpts()[0]
    assert f.op == "deboss" and f.mount.flip
    assert f.mount.overlap_mm == pytest.approx(0.6)
    assert p.sc_flip.isChecked() and p.sc_overlap.value() == pytest.approx(0.6)
    assert heard[-1] == (0, False)
    # back to emboss: the back goes on the surface and the sag is read again
    p.sc_op.setCurrentIndex(0)
    f = p.sculpts()[0]
    assert f.op == "emboss" and not f.mount.flip and f.mount.overlap_mm == pytest.approx(0.05)
    assert heard[-1] == (0, True)
    assert heard[-1] == (0, True)
    # a deboss the maker un-flips stays un-flipped on the next op change round trip
    p.sc_op.setCurrentIndex(1)
    p.sc_flip.setChecked(False)
    assert p.sculpts()[0].op == "deboss" and not p.sculpts()[0].mount.flip


# ------------------------------------------------------------- the window

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _gdraw(path):
    """A front the window builds: an outline, two lenses, two section cuts."""
    import json
    import xml.etree.ElementTree as ET
    import zipfile
    ns = "http://www.w3.org/2000/svg"
    front = {"mirror": {"enabled": False}, "curves": [
        _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
        _line("SCULPT", [(0, -20), (0, 20)]),
        _line("SCULPT", [(30, -20), (30, 20)]),
    ]}
    states = {"front": front, "temple_r": {"curves": []}, "temple_l": {"curves": []},
              "hinge": {"curves": []}}
    ET.register_namespace("", ns)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            root = ET.Element(f"{{{ns}}}svg")
            ET.SubElement(root, f"{{{ns}}}metadata").text = json.dumps(st)
            zf.writestr(f"{tab}.svg", ET.tostring(root, xml_declaration=True, encoding="utf-8"))
    return path


def _new_window():
    from guildmodel.gui.app import MainWindow
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


@pytest.mark.gui
def test_a_drop_lands_under_the_cursor_and_a_drag_reseats_on_the_face(qapp, tmp_path, monkeypatch):
    """The window's side: a dome dropped at a surface point is seated there
    on the face its normal names, scaled to 15 mm when wider; a drag commit
    moves it by the grab offset and reads the host under the new point."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)
    from guildmodel.core.model import build_castle_model
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win._activate_workspace(0)
    assert win._castle_ready()
    host = to_trimesh(build_castle_model(win._partition, win.params.castle_params(), []))
    win._stage_cache[win._stage] = host                       # a built model, as a snap reads it
    big = _dome(radius=20.0)                                   # 40 mm across: scaled to 15
    path = tmp_path / "crest.stl"
    path.write_bytes(_stl(big))
    z0 = surface_z_at(host, [(-10.0, 16.0)], face="top")[0]
    at = (np.array([-10.0, 16.0, z0]), np.array([0.0, 0.0, 1.0]))
    win._add_sculpt_from_path(str(path), at=at)
    f = win.params.sculpts()[0]
    assert f.mount.face == "posterior"
    assert f.mount.point[:2] == pytest.approx([-10.0, 16.0], abs=1e-6)
    assert f.size_mm == pytest.approx(15.0) and f.scale == pytest.approx(0.375)
    assert f.height_mm == pytest.approx(20.0, abs=1e-6) and f.extent_mm == pytest.approx(40.0, abs=1e-6)
    # the face from the normal
    assert win._face_of_normal([0, 0, 1]) == "posterior"
    assert win._face_of_normal([0, 0, -1]) == "anterior"
    assert win._face_of_normal([1, 0, 0]) == "rim"
    # a drag that let go 3 mm over, grabbed 1 mm off the anchor; the built
    # model carries the sculpt-free surface the drag reads, and that host
    # is kept through the rebuild the drop starts
    baked = host.copy()
    baked.metadata["sculpt_host"] = host
    win._stage_cache[win._stage] = baked
    assert win._sculpt_host_mesh() is host
    win._stage_cache.clear()
    assert win._sculpt_host_mesh() is host                    # kept through a rebuild
    win._on_sculpt_dropped(0, np.array([-7.0, 16.0, z0]), np.array([0.0, 0.0, 1.0]),
                           np.array([1.0, 0.0, 0.0]))
    g = win.params.sculpts()[0]
    assert g.mount.point[:2] == pytest.approx([-6.0, 16.0], abs=1e-6)
    z = surface_z_at(host, [(-6.0, 16.0)], face="top")[0]
    assert g.mount.point[2] == pytest.approx(z, abs=1e-6)
    assert g.mount.face == "posterior"
    # a leaning normal on the back face is seated level; a wall is the rim
    t = win._picked_target([0.0, 0.0, 3.0], [0.3, 0.0, 0.954])
    assert t.face == "posterior" and np.allclose(t.normal, [0, 0, 1])
    # on a wall the hit itself is the target
    win._on_sculpt_dropped(0, np.array([60.0, 0.0, 2.0]), np.array([1.0, 0.0, 0.0]),
                           np.array([1.0, 0.0, 0.0]))
    assert win.params.sculpts()[0].mount.face == "rim"
    assert win.params.sculpts()[0].mount.point == pytest.approx([60.0, 0.0, 2.0])
