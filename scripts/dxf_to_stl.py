"""GuildDraw DXF → solid 3D model (STL + rendered PNG).

Exercises GuildCAM's existing core pipeline end-to-end on real GuildDraw
output, as a planning aid for the GuildCAM redevelopment:

    io_import.dxf.import_dxf      SPLINE tessellation @ 0.01 mm
    io_import.normalize           point lists → Shapely polygons, auto-close
    io_import.validate            strict layer rules (OUTLINE ×1, LENS ×2)
    geometry.boxing               recover A / B / DBL from the lens pair
    relief.builder                front relief (nosepad, lens grooves) +
                                  back scallop on a shared heightfield grid
    mesh (trimesh)                watertight solid masked to the outline
    mesh.stl_export               binary STL

Run:  .venv\\Scripts\\python scripts\\dxf_to_stl.py demo\\guilddraw_front.dxf
"""
from __future__ import annotations
import sys
from pathlib import Path

from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import normalize
from guildcam.core.io_import.validate import validate
from guildcam.core.geometry.boxing import measure_from_polygon
from guildcam.core.relief.builder import ReliefBuildParams, build_preview_mesh
from guildcam.core.mesh.stl_export import export_stl


def main(dxf_path: Path, stl_path: Path, png_path: Path) -> int:
    raw = import_dxf(dxf_path)
    layers = normalize(raw)
    print(f"imported: { {k: len(v) for k, v in layers.items() if v} }")

    result = validate(layers)
    for w in getattr(result, "warnings", []):
        print(f"  warning: {w}")
    if not result.ok:
        for e in result.errors:
            print(f"  error: {e}")
        return 1

    outline = layers["OUTLINE"][0]
    lenses = sorted(layers["LENS"], key=lambda p: p.centroid.x)
    lens_od, lens_os = lenses[0], lenses[1]   # OD on viewer's left (neg x)

    bd = measure_from_polygon(lens_od, lens_os)
    print(f"boxing from DXF: A={bd.a:.1f}  B={bd.b:.1f}  DBL={bd.dbl:.1f}  "
          f"ED={bd.ed:.1f}  frame width={bd.derived_frame_width():.1f} mm")

    params = ReliefBuildParams(stock_thickness_mm=6.0, resolution=0.2)
    mesh = build_preview_mesh(outline, lens_od, lens_os, params)
    print(f"mesh: {len(mesh.vertices)} verts, {len(mesh.faces)} faces, "
          f"watertight={mesh.is_watertight}, "
          f"extents={[round(e, 1) for e in mesh.extents]} mm")

    export_stl(mesh, stl_path)
    print(f"wrote {stl_path} ({stl_path.stat().st_size // 1024} KiB)")

    try:
        _render_png(mesh, png_path)
        print(f"wrote {png_path}")
    except Exception as e:                       # rendering is best-effort
        print(f"pyvista render failed ({e}); trying matplotlib")
        _render_png_mpl(mesh, png_path)
        print(f"wrote {png_path} (matplotlib)")
    return 0


def _render_png(mesh, png_path: Path) -> None:
    import numpy as np
    import pyvista as pv

    pv.OFF_SCREEN = True
    faces = np.column_stack(
        [np.full(len(mesh.faces), 3), mesh.faces]).ravel()
    poly = pv.PolyData(mesh.vertices, faces)
    pl = pv.Plotter(off_screen=True, window_size=(1600, 900))
    pl.set_background("white")
    pl.add_mesh(poly, color="#8a5a2b", smooth_shading=True,
                specular=0.4, specular_power=12)
    pl.camera_position = "xy"
    pl.camera.elevation = -55
    pl.camera.zoom(1.25)
    pl.screenshot(str(png_path))
    pl.close()


def _render_png_mpl(mesh, png_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(16, 9), dpi=100)
    ax = fig.add_subplot(projection="3d")
    v, f = mesh.vertices, mesh.faces
    ax.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2],
                    color="#8a5a2b", edgecolor="none")
    ax.view_init(elev=35, azim=-90)
    ax.set_box_aspect((mesh.extents[0], mesh.extents[1],
                       mesh.extents[2] * 3))
    ax.set_axis_off()
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    dxf = Path(sys.argv[1] if len(sys.argv) > 1 else "demo/guilddraw_front.dxf")
    stl = Path(sys.argv[2]) if len(sys.argv) > 2 else dxf.with_suffix(".stl")
    png = Path(sys.argv[3]) if len(sys.argv) > 3 else dxf.with_suffix(".png")
    raise SystemExit(main(dxf, stl, png))
