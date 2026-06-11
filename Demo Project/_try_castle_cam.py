"""M3 diagnostic: generate the five-op program from the demo DXF and compare
per-op envelopes against Demo Program.nc expectations (teardown §6)."""
from pathlib import Path
import time

import yaml

from guildcam.core.cam.castle_ops import (
    CastleCamParams, fixture_clearance_violations, generate_castle_program,
    write_castle_program,
)
from guildcam.core.geometry.regions import partition_zones
from guildcam.core.io_import.dxf import import_dxf
from guildcam.core.io_import.normalize import points_to_polygon
from guildcam.core.post.grbl import GRBLPost
from guildcam.core.project.schema import CastleParams
from guildcam.core.relief.castle import build_castle_relief

HERE = Path(__file__).parent
CONFIG = HERE.parent / "src" / "guildcam" / "config"

raw = import_dxf(HERE / "GuildDraw DXF Export.dxf")
outline = points_to_polygon(raw["OUTLINE"][0])
lenses = [points_to_polygon(c) for c in raw["LENS"]]
hinges = [points_to_polygon(c) for c in raw["HINGE"]]
part = partition_zones(outline, lenses, raw["SCULPT"])
castle = CastleParams()

t0 = time.perf_counter()
relief = build_castle_relief(part, castle, hinges, resolution=0.15)
print(f"relief: {time.perf_counter() - t0:.2f}s  grid {relief.field.z.shape}")

tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
tool = tools["flat_3175"]

t0 = time.perf_counter()
ops = generate_castle_program(relief, castle, hinges, tool)
print(f"cam: {time.perf_counter() - t0:.2f}s\n")

for op in ops:
    zmin, zmax = op.z_range()
    bx = op.xy_bounds()
    npts = sum(len(p) for p in op.paths)
    print(f"{op.name:14s} paths {len(op.paths):4d}  pts {npts:6d}  "
          f"Z {zmin:6.3f}..{zmax:6.3f}  X {bx[0]:7.2f}..{bx[2]:7.2f}  Y {bx[1]:7.2f}..{bx[3]:7.2f}")

print("\nreference (Demo Program.nc, our frame = demo XY via registration):")
print("  Hinge Pockets  floor 4.5, ramped")
print("  Rough Scallop  Z 6.2..7.5 (full-coverage air variant; ours stock-aware)")
print("  Fine Scallop   Z 4.2..10.0")
print("  Eyewires       passes 7.5/5.0/2.5/0.4")
print("  Perimeter      passes 7.5/5.0/2.5/0.4")

# contour pass listing
from guildcam.core.cam.castle_ops import contour_passes
print("\ncontour passes:", contour_passes(10.0, 0.4, 2.5))

# fixture check
fixture = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text(encoding="utf-8"))
v = fixture_clearance_violations(ops, fixture, tool["radius_mm"])
print("fixture violations:", v if v else "none")

# write a program and lint basics
mats = yaml.safe_load((CONFIG / "materials.yaml").read_text(encoding="utf-8"))
m = mats["acetate"]
post = GRBLPost(
    job_name="demo_castle", material="acetate",
    tool_diameter_mm=tool["diameter_mm"], spindle_rpm=m["spindle_rpm"],
    feed_rate_mmpm=m["feed_rate_mmpm"], plunge_rate_mmpm=m["plunge_rate_mmpm"],
    safe_z_mm=castle.stock.total_pad_height_mm + 5.0,
)
write_castle_program(ops, post)
out = HERE / "_generated_posterior_cut.nc"
post.write(out)
text = post.to_string()
print(f"\nprogram: {len(text.splitlines())} lines -> {out.name}")
print("has G21/G90/M3/M30:", all(t in text for t in ("G21", "G90", "M3 S", "M30")))
