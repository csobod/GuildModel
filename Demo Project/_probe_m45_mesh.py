"""M4.5 diagnosis: why does the castle mesh look jagged vs the Fusion STL?

Builds the demo relief at preview (0.3) and validation (0.15) resolution,
renders both next to Model.stl (flat-shaded closeups so faceting is honest),
and prints the numbers that matter: rim-edge direction histogram (Manhattan
staircase?), plateau z purity, footing-band facet normal spread.

Run:  .venv\\Scripts\\python "Demo Project\\_probe_m45_mesh.py"
Writes _m45_*.png next to this script.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).parent


def build(resolution: float):
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.project.schema import CastleParams
    from guildcam.core.relief.castle import build_castle_mesh, build_castle_relief

    raw = import_dxf(HERE / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    relief = build_castle_relief(part, CastleParams(), hinges, resolution=resolution)
    return relief, build_castle_mesh(relief)


def rim_stats(mesh: trimesh.Trimesh) -> dict:
    """Boundary (rim) edge orientation: how much Manhattan staircase?"""
    # Rim verticals connect top boundary to the anterior; instead inspect the
    # top-surface boundary ring: edges referenced by exactly one face among
    # near-horizontal faces is fiddly post-merge, so use the full mesh's
    # sharp silhouette: edges whose adjacent face normals differ > 60 deg.
    adj = mesh.face_adjacency
    angles = mesh.face_adjacency_angles
    sharp = adj[angles > np.radians(60)]
    edges = mesh.face_adjacency_edges[angles > np.radians(60)]
    if len(edges) == 0:
        return {"sharp_edges": 0}
    vec = mesh.vertices[edges[:, 1]] - mesh.vertices[edges[:, 0]]
    vec2d = vec[:, :2]
    norm = np.linalg.norm(vec2d, axis=1)
    keep = norm > 1e-9
    vec2d = vec2d[keep] / norm[keep, None]
    axis_aligned = (np.abs(vec2d[:, 0]) > 0.999) | (np.abs(vec2d[:, 1]) > 0.999)
    lengths = np.linalg.norm(vec[keep], axis=1)
    return {
        "sharp_edges": int(keep.sum()),
        "axis_aligned_frac": float(axis_aligned.mean()),
        "mean_edge_len_mm": float(lengths.mean()),
    }


def plateau_purity(relief) -> dict:
    """Are the terraces flat? (they should be exactly so by construction)"""
    z = relief.field.z
    out = {}
    for name in ("endpiece_od", "nosepad_od", "eyewire_inferior_od"):
        idx = [zo.name for zo in relief.partition.zones].index(name)
        mask = (relief.zone_index == idx) & relief.inside
        vals = z[mask]
        out[name] = (float(vals.min()), float(vals.max()),
                     int(len(np.unique(vals))))
    return out


def render(meshes: list[tuple[str, trimesh.Trimesh]], out: Path,
           zoom_window: tuple | None = None, flat: bool = True) -> None:
    import pyvista as pv
    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, shape=(1, len(meshes)),
                    window_size=(900 * len(meshes), 900))
    for i, (title, m) in enumerate(meshes):
        pl.subplot(0, i)
        faces = np.column_stack([np.full(len(m.faces), 3), m.faces]).ravel()
        poly = pv.PolyData(np.asarray(m.vertices, dtype=float), faces)
        pl.add_mesh(poly, color="#d4a84b", smooth_shading=not flat,
                    specular=0.3, specular_power=15)
        pl.add_text(title, font_size=11)
        pl.set_background("white")
        pl.view_isometric()
        if zoom_window is not None:
            cx, cy, cz, dist = zoom_window
            pl.camera.focal_point = (cx, cy, cz)
            pl.camera.position = (cx + dist, cy - dist, cz + dist)
    pl.screenshot(str(out))
    pl.close()
    print(f"wrote {out.name}")


def main() -> None:
    ref = trimesh.load(HERE / "Model.stl")
    print(f"reference: {len(ref.vertices):,} verts, {len(ref.faces):,} faces, "
          f"mean edge {ref.edges_unique_length.mean():.3f} mm")

    for res in (0.3, 0.15):
        relief, mesh = build(res)
        print(f"\n--- castle mesh @ {res} mm ---")
        print(f"{len(mesh.vertices):,} verts, {len(mesh.faces):,} faces, "
              f"watertight={mesh.is_watertight}")
        print("rim:", rim_stats(mesh))
        print("plateaus:", plateau_purity(relief))
        if res == 0.3:
            mesh03 = mesh
        else:
            mesh015 = mesh

    # Reference is y-mirrored / translated relative to ours; render side by
    # side without registration (shape comparison only).
    render([("GuildCAM 0.3 mm (preview/export)", mesh03),
            ("GuildCAM 0.15 mm", mesh015),
            ("Fusion Model.stl (reference)", ref)],
           HERE / "_m45_overview_flat.png", flat=True)

    # Closeup near the OD endpiece / superior eyewire footing + outline rim.
    b = mesh03.bounds
    cx, cy = b[1][0] - 8.0, (b[0][1] + b[1][1]) / 2 + 8.0
    rb = ref.bounds
    rcx, rcy = rb[1][0] - 8.0, (rb[0][1] + rb[1][1]) / 2 + 8.0
    render([("GuildCAM 0.3 mm closeup", mesh03)],
           HERE / "_m45_closeup_guildcam.png", zoom_window=(cx, cy, 5.0, 18.0))
    render([("Reference closeup", ref)],
           HERE / "_m45_closeup_reference.png", zoom_window=(rcx, rcy, 5.0, 18.0))


if __name__ == "__main__":
    main()
