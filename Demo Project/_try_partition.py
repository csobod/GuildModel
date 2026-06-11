"""Manual smoke: partition the demo DXF and print the zone table."""
from pathlib import Path

from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.geometry.regions import partition_zones

raw = import_dxf(Path(__file__).parent / "GuildDraw DXF Export.dxf")
outline = points_to_polygon(raw["OUTLINE"][0])
lenses = [points_to_polygon(c) for c in raw["LENS"]]

part = partition_zones(outline, lenses, raw["SCULPT"])
print("matched:", part.matched, " zones:", len(part.zones))
for z in sorted(part.zones, key=lambda z: z.name):
    c = z.polygon.centroid
    print(f"  {z.name:22s} kind={z.kind:18s} area={z.polygon.area:8.2f}  centroid=({c.x:7.2f},{c.y:7.2f})")
print("edges:")
for e in part.edges:
    print(f"  {e.name:24s} canonical={e.canonical or '-':20s} adj={e.zone_names}")
