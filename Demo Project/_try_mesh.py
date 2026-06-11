"""Manual smoke: build the castle mesh and verify watertightness + volume."""
from pathlib import Path
import time

from guildcam.core.geometry.regions import partition_zones
from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.project.schema import CastleParams
from guildcam.core.relief.castle import build_castle_relief, build_castle_mesh

HERE = Path(__file__).parent
raw = import_dxf(HERE / "GuildDraw DXF Export.dxf")
outline = points_to_polygon(raw["OUTLINE"][0])
lenses = [points_to_polygon(c) for c in raw["LENS"]]
hinges = [points_to_polygon(c) for c in raw["HINGE"]]
part = partition_zones(outline, lenses, raw["SCULPT"])

t0 = time.perf_counter()
relief = build_castle_relief(part, CastleParams(), hinges, resolution=0.3)
mesh = build_castle_mesh(relief)
print(f"build+mesh: {time.perf_counter() - t0:.2f}s")
print(f"verts {len(mesh.vertices)}  faces {len(mesh.faces)}")
print(f"watertight: {mesh.is_watertight}  volume: {mesh.volume:.0f} mm^3")
print(f"bounds Z {mesh.bounds[0][2]:.3f}..{mesh.bounds[1][2]:.3f}")
