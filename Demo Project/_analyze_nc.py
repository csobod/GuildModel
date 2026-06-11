"""Inspect Demo Program.nc: header comments, tools, ops, Z range, feeds."""
import re
from pathlib import Path

NC = Path(__file__).parent / "Demo Program.nc"
lines = NC.read_text(errors="replace").splitlines()
print("total lines:", len(lines))

print("\n-- comments / op markers --")
for i, ln in enumerate(lines):
    if "(" in ln or ln.startswith("%") or ln.startswith("O"):
        print(f"{i+1:6d}: {ln.strip()}")
    if i > len(lines):
        break

print("\n-- tool changes --")
for i, ln in enumerate(lines):
    if re.search(r"\bT\d+|M0?6\b", ln):
        print(f"{i+1:6d}: {ln.strip()}")

zs = [float(m) for m in re.findall(r"Z(-?[\d.]+)", "\n".join(lines))]
fs = sorted({float(m) for m in re.findall(r"F(-?[\d.]+)", "\n".join(lines))})
ss = sorted({float(m) for m in re.findall(r"S(\d+)", "\n".join(lines))})
print(f"\nZ range: {min(zs):.3f} .. {max(zs):.3f}")
print("feeds:", fs)
print("spindle:", ss)

print("\n-- first 30 lines --")
for ln in lines[:30]:
    print(ln)
