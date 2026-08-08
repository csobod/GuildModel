"""Does copying the cached base fix the in-session corruption, and what does it cost?

BUILDPLAN-NEW M-N0 offers two mitigations in order: (a) deep-copy the cached
base before handing it out, (b) failing that, drop `_BASE_CACHE` and eat the
rebuild. `probe_stale_mesh.py` established that every failure lands on a
*reused* base and no cold build has ever failed, and that stale triangulation is
not the mechanism (`BRepTools.Clean_s` changed nothing, bit for bit).

Three modes over the same GUI-like sequence:

    shared   the old behaviour — one TopoDS_Shape handed to every build
    copied   (a), the shipped fix — the cache keeps a private deep copy
    cold     (b), the fallback — no cache at all

Reports watertightness, volume and wall time, so "which is correct" and "what
does correct cost" are answered by the same run.
"""
import tempfile
import time
import zipfile
from pathlib import Path

from guildmodel.core.project.schema import CastleParams
from guildmodel.core.solid import build_castle_solid, clear_base_cache
from guildmodel.core.solid.tessellate import tessellate
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

import guildmodel.core.solid.build as build_mod

src = Path("tests/fixtures/aviator")
tmp = Path(tempfile.mkdtemp()) / "aviator.gdraw"
with zipfile.ZipFile(tmp, "w") as zf:
    for f in sorted(src.iterdir()):
        zf.write(f, f.name)
front = build_workspaces_from_gdraw(tmp)[0][0]
part = front.partition

_REAL_COPY = build_mod.copy_shape


def splay(c): c.pad_splay.enabled = True
def bridge(c): c.bridge_relief.enabled = True
def groove(c): c.lens_groove.enabled = True
def bare(c): pass


#: bare/splay/bridge share one `_base_key` (neither feature is in it), so the
#: base is built once and reused twice — which is where it broke.
SEQ = ((bare, "bare"), (splay, "splay"), (bridge, "bridge"),
       (groove, "groove"), (groove, "groove again"))


def run(mode):
    build_mod.copy_shape = (lambda s: s) if mode == "shared" else _REAL_COPY
    clear_base_cache()
    print(f"\n{mode}:")
    total = 0.0
    failures = 0
    for mutate, label in SEQ:
        if mode == "cold":
            clear_base_cache()
        c = CastleParams()
        mutate(c)
        t0 = time.perf_counter()
        solid = build_castle_solid(part, c, front.hinge_polys)
        tm = tessellate(solid).to_trimesh()
        dt = time.perf_counter() - t0
        total += dt
        failures += not tm.is_watertight
        print(f"  {label:<14} wt={tm.is_watertight!s:<5} "
              f"vol={tm.volume:9.3f}  {dt:6.2f}s")
    print(f"  {'total':<14} {'BROKEN ' + str(failures) if failures else 'all clean':<12} "
          f"{total:19.2f}s")
    return failures, total


results = {mode: run(mode) for mode in ("shared", "copied", "cold")}

print("\nsummary")
for mode, (failures, total) in results.items():
    print(f"  {mode:<8} {failures} corrupt   {total:6.2f}s")
