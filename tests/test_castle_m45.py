"""M4.5 Part B gates: the boundary-conforming rim (BUILDPLAN § M4.5).

The masked-grid mesher used to emit an axis-aligned staircase silhouette
(98.9 % of sharp edges axis-aligned at any resolution). With the conforming
rim, every silhouette vertex — outline rim, lens-hole rims, hinge-pocket
walls — is projected onto the true ring it belongs to.

Gates:
  * axis-aligned fraction of sharp silhouette edges < 20 %
  * max XY deviation of sharp-edge vertices from the true rings <= 0.02 mm
  * mesh watertight; volume matches the Fusion reference (and is
    resolution-independent), unlike the pre-fix half-pixel underestimate
  * prefs module round-trips and always exposes the M4.5 keys
"""
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).parents[1] / "tests" / "fixtures" / "demo"

PREVIEW_RES = 0.3   # the coarsest mesh anyone sees — must already pass


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    return part, CastleParams(), hinges


@pytest.fixture(scope="module")
def demo_relief(demo):
    from guildmodel.core.relief.castle import build_castle_relief

    part, castle, hinges = demo
    return build_castle_relief(part, castle, hinges, resolution=PREVIEW_RES)


@pytest.fixture(scope="module")
def demo_mesh(demo_relief):
    from guildmodel.core.relief.castle import build_castle_mesh

    return build_castle_mesh(demo_relief)


def _sharp_silhouette(mesh, angle_deg: float = 60.0):
    """(edges, vertex_ids) of edges whose adjacent faces disagree > angle."""
    sharp = mesh.face_adjacency_angles > np.radians(angle_deg)
    edges = mesh.face_adjacency_edges[sharp]
    return edges, np.unique(edges)


def _true_rings(relief):
    body = relief.partition.body
    return ([body.exterior] + list(body.interiors)
            + [p.exterior for p in relief.pocket_polys])


# ------------------------------------------------------------------ gates

def test_silhouette_not_axis_aligned(demo_mesh):
    """< 20 % of sharp silhouette edges axis-aligned (was 98.9 %)."""
    edges, _ = _sharp_silhouette(demo_mesh)
    assert len(edges) > 1000
    vec = (demo_mesh.vertices[edges[:, 1]] - demo_mesh.vertices[edges[:, 0]])[:, :2]
    norm = np.linalg.norm(vec, axis=1)
    vec = vec[norm > 1e-9] / norm[norm > 1e-9, None]
    axis_aligned = (np.abs(vec[:, 0]) > 0.999) | (np.abs(vec[:, 1]) > 0.999)
    assert axis_aligned.mean() < 0.20


def test_rim_vertices_on_true_rings(demo_relief, demo_mesh):
    """Every sharp-edge vertex sits on an outline / lens / pocket ring."""
    import shapely

    _, vids = _sharp_silhouette(demo_mesh)
    pts = shapely.points(
        demo_mesh.vertices[vids, 0], demo_mesh.vertices[vids, 1]
    )
    d = np.full(len(vids), np.inf)
    for ring in _true_rings(demo_relief):
        d = np.minimum(d, shapely.distance(pts, ring))
    assert d.max() <= 0.02


def test_watertight_and_volume_matches_reference(demo, demo_mesh):
    """Conforming rim recovers the true silhouette volume (ref: Model.stl,
    7826 mm^3); the staircase mesh underestimated by a half-pixel band."""
    import trimesh

    assert demo_mesh.is_watertight
    ref = trimesh.load(DEMO / "Model.stl")
    assert demo_mesh.volume == pytest.approx(ref.volume, rel=0.005)


def test_volume_resolution_independent(demo, demo_mesh):
    """The silhouette no longer depends on the grid resolution."""
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_relief

    part, castle, hinges = demo
    fine = build_castle_mesh(
        build_castle_relief(part, castle, hinges, resolution=0.15)
    )
    assert fine.is_watertight
    assert fine.volume == pytest.approx(demo_mesh.volume, rel=0.005)


def test_stage_meshes_still_watertight(demo):
    """The teaching stepper builds (towers/walls) survive the conform pass."""
    from guildmodel.core.relief.castle import build_castle_mesh, build_castle_stage

    part, castle, hinges = demo
    for stage in ("towers", "footing"):
        relief = build_castle_stage(part, castle, hinges, stage=stage,
                                    resolution=0.5)
        mesh = build_castle_mesh(relief)
        assert mesh.is_watertight, stage


def test_unconformed_path_unchanged(demo_relief):
    """conform=False keeps the legacy masked-grid mesh (probe baseline)."""
    from guildmodel.core.relief.castle import build_castle_mesh

    mesh = build_castle_mesh(demo_relief, conform=False)
    edges, _ = _sharp_silhouette(mesh)
    vec = (mesh.vertices[edges[:, 1]] - mesh.vertices[edges[:, 0]])[:, :2]
    norm = np.linalg.norm(vec, axis=1)
    vec = vec[norm > 1e-9] / norm[norm > 1e-9, None]
    axis_aligned = (np.abs(vec[:, 0]) > 0.999) | (np.abs(vec[:, 1]) > 0.999)
    assert axis_aligned.mean() > 0.9          # the staircase, preserved
    assert mesh.is_watertight


# ------------------------------------------------------------------ prefs

def test_prefs_defaults_and_roundtrip(tmp_path, monkeypatch):
    from guildmodel.gui import prefs

    monkeypatch.setattr(prefs, "_DIR", tmp_path)
    monkeypatch.setattr(prefs, "_FILE", tmp_path / "prefs.json")

    p = prefs.load()
    for key in ("dark_mode", "recent_files", "preview_resolution_mm",
                "export_resolution_mm", "last_output_dir"):
        assert key in p

    p["dark_mode"] = True
    p["export_resolution_mm"] = 0.1
    prefs.save(p)
    q = prefs.load()
    assert q["dark_mode"] is True
    assert q["export_resolution_mm"] == 0.1

    # unknown/missing keys merge over defaults (future-version safety)
    (tmp_path / "prefs.json").write_text('{"dark_mode": true}', encoding="utf-8")
    r = prefs.load()
    assert r["dark_mode"] is True
    assert r["preview_resolution_mm"] == prefs.DEFAULTS["preview_resolution_mm"]
