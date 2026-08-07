"""Time the B-Rep castle build, feature by feature, on the demo frame.

The Stage 2 handover's timing table (BUILDPLAN 2026-08-07) was measured by hand;
this reproduces it so every later claim about the perf work is against the same
stopwatch. Run it before and after a change:

    python scripts/bench_solid.py              # the full table
    python scripts/bench_solid.py --only all   # just ALL FEATURES ON

Each row is one feature alone on top of the bare castle, so the rows are
*increments*, not a decomposition of the total — the ALL row is measured
separately and is deliberately larger than their sum (each boolean pays for
whatever came before it).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "demo"


def demo_inputs():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    return partition_zones(outline, lenses, raw["SCULPT"]), hinges


def _brow_chamfer():
    from guildmodel.core.project.schema import EdgeFeature

    return EdgeFeature(
        id="brow", label="Brow chamfer", face="posterior", edge="outline",
        zones=["eyewire_superior_od"], blend_mm=4.0, profile="chamfer",
        width_mm=2.0, angle_deg=45.0, mirror=True)


def variants():
    """(label, mutate) pairs — each mutate turns exactly one feature on."""
    def bare(_c):
        pass

    def bridge(c):
        c.bridge_relief.enabled = True

    def splay(c):
        c.pad_splay.enabled = True

    def groove(c):
        c.lens_groove.enabled = True

    def chamfer(c):
        c.edge_features = [_brow_chamfer()]

    def bezel(c):
        c.eyewire_bezel.enabled = True
        c.eyewire_bezel.face = "posterior"

    def everything(c):
        for fn in (bridge, splay, groove, chamfer, bezel):
            fn(c)

    return [
        ("bare castle + hinge pockets", bare),
        ("+ bridge relief", bridge),
        ("+ pad splay", splay),
        ("+ lens groove", groove),
        ("+ brow chamfer (mirrored pair)", chamfer),
        ("+ eyewire bezel (posterior)", bezel),
        ("ALL FEATURES ON", everything),
    ]


def time_build(partition, hinges, mutate) -> tuple[float, float, float]:
    """(cold, warm, volume) for one row.

    Cold clears the `castle_base` cache first, so it pays for the terraces and
    the ten footing blends. Warm is the same build with that cache primed, which
    is what a slider drag actually costs — the maker is changing a feature
    parameter, and no feature parameter touches the base.
    """
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache, volume

    castle = CastleParams()
    mutate(castle)

    clear_base_cache()
    t0 = time.perf_counter()
    solid = build_castle_solid(partition, castle, hinges)
    cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    build_castle_solid(partition, castle, hinges)
    warm = time.perf_counter() - t0
    return cold, warm, volume(solid)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                    help="substring of a row label; 'all' runs ALL FEATURES ON only")
    args = ap.parse_args()

    partition, hinges = demo_inputs()
    rows = variants()
    if args.only:
        needle = "ALL FEATURES" if args.only == "all" else args.only
        rows = [r for r in rows if needle.lower() in r[0].lower()]
        if not rows:
            raise SystemExit(f"no benchmark row matches {args.only!r}")

    print(f"{'Build':<34} {'Cold':>8} {'Warm':>8} {'Volume':>14}")
    print("-" * 68)
    for label, mutate in rows:
        cold, warm, vol = time_build(partition, hinges, mutate)
        print(f"{label:<34} {cold:>7.1f}s {warm:>7.1f}s {vol:>12.1f} mm3")


if __name__ == "__main__":
    main()
