"""Per-operation stats: cutting Z range, XY extents, feed usage, move counts."""
import re
from pathlib import Path

NC = Path(__file__).parent / "Demo Program.nc"
lines = NC.read_text(errors="replace").splitlines()

ops = []  # (name, start_idx)
for i, ln in enumerate(lines):
    m = re.fullmatch(r"\((Hinge Pockets|Rough Scallop|Fine Scallop|Eyewires|Perimeter)\)", ln.strip())
    if m:
        ops.append((m.group(1), i))
ops.append(("END", len(lines)))

coord = re.compile(r"([XYZF])(-?[\d.]+)")
for (name, start), (_, end) in zip(ops, ops[1:]):
    xs, ys, cut_z = [], [], []
    g1_count = g0_count = 0
    cur = {"X": None, "Y": None, "Z": None}
    for ln in lines[start:end]:
        s = ln.strip()
        is_g0 = s.startswith("G0 ") or s == "G0"
        is_move = bool(coord.search(s)) and not s.startswith("(")
        for ax, val in coord.findall(s):
            if ax in cur:
                cur[ax] = float(val)
        if not is_move:
            continue
        if is_g0:
            g0_count += 1
            continue
        g1_count += 1
        if cur["X"] is not None:
            xs.append(cur["X"])
        if cur["Y"] is not None:
            ys.append(cur["Y"])
        if cur["Z"] is not None:
            cut_z.append(cur["Z"])
    print(f"\n== {name} ==  (lines {start+1}-{end})")
    print(f"  feed moves: {g1_count}, rapids: {g0_count}")
    if xs:
        print(f"  X {min(xs):8.3f} .. {max(xs):8.3f}")
        print(f"  Y {min(ys):8.3f} .. {max(ys):8.3f}")
    if cut_z:
        print(f"  cutting Z {min(cut_z):.3f} .. {max(cut_z):.3f}")
        # distinct Z plateau histogram (rounded 0.1)
        from collections import Counter
        zc = Counter(round(z, 1) for z in cut_z)
        top = sorted(zc.items(), key=lambda kv: -kv[1])[:10]
        print("  common Z:", ", ".join(f"{v}({n})" for v, n in top))
