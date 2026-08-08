"""Build a frame front both ways and diff it — ``guildmodel --diag-kernels``.

BUILDPLAN-NEW M-N2's A/B. The migration's whole claim is that the mesh kernel
produces the same part as the B-Rep one, and the way that claim stays true is by
being cheap to re-check on a drawing nobody wrote a fixture for.

The parity suite covers three drawings. This covers the maker's, whichever it is
this week, in one command:

    guildmodel --diag-kernels "Gabriel 49x18-138.gdraw"

Deliberately Qt-free and importable headless, like `gui/diag.py`. It reports
rather than asserts — the numbers are the point, and a tolerance belongs in a
test where it can be argued about, not in a diagnostic where it would just hide
the figure.

**Volume and silhouette, not volume alone.** Volume is one number and two very
different parts can share it; the silhouette is what the part looks like from
the front, and between them they catch both a feature in the wrong place and a
feature of the wrong size. That pairing is the M-N3 gate, and running it here
first means M-N3 finds no surprises.
"""
from __future__ import annotations

import time

__all__ = ["compare_kernels", "format_report"]


def _silhouette_area(mesh) -> float:
    """Area of the part's shadow on the XY plane, mm2.

    Summed from the triangles' signed XY projections: for a closed mesh the
    downward-facing faces cancel the upward-facing ones everywhere except where
    there is material, so the total is the outline area including holes, without
    needing a 2D boolean.
    """
    import numpy as np

    tris = mesh.vertices[mesh.faces]
    ab = tris[:, 1, :2] - tris[:, 0, :2]
    ac = tris[:, 2, :2] - tris[:, 0, :2]
    return float(np.abs(0.5 * (ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0])).sum()) / 2.0


def compare_kernels(partition, castle, hinges) -> dict:
    """Build both kernels' models and measure them. Returns a plain dict."""
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    out: dict = {}

    start = time.perf_counter()
    mesh = to_trimesh(build_castle_model(partition, castle, hinges))
    out["mesh"] = _measure(mesh, time.perf_counter() - start, verify_mesh)

    clear_base_cache()
    start = time.perf_counter()
    try:
        tess = tessellate(build_castle_solid(partition, castle, hinges))
        brep = tess.to_trimesh()
        out["brep"] = _measure(brep, time.perf_counter() - start, verify_mesh)
        out["brep"]["edges"] = len(tess.edges)
    except Exception as exc:                                 # noqa: BLE001
        # The B-Rep path failing is a *result*, not an error in this tool —
        # BUILDPLAN-NEW §3 is a catalogue of it doing exactly that, and a
        # diagnostic that dies alongside it reports nothing.
        out["brep"] = {"error": f"{type(exc).__name__}: {exc}",
                       "seconds": time.perf_counter() - start}
    return out


def _measure(mesh, seconds: float, verify) -> dict:
    verdict = verify(mesh)
    return {
        "volume": float(mesh.volume),
        "silhouette": _silhouette_area(mesh),
        "triangles": int(len(mesh.faces)),
        "bodies": int(mesh.body_count),
        "watertight": bool(mesh.is_watertight),
        "ok": bool(verdict.ok),
        "problems": list(verdict.problems),
        "seconds": float(seconds),
    }


def format_report(result: dict) -> str:
    """The comparison as a table, for a terminal or the log dock."""
    mesh, brep = result.get("mesh", {}), result.get("brep", {})
    lines = ["GuildModel kernel comparison", "=" * 52]

    if "error" in brep:
        lines.append(f"  B-Rep FAILED after {brep['seconds']:.1f}s: "
                     f"{brep['error']}")
        lines.append("")

    lines.append(f"  {'':<14}{'mesh':>14}{'B-Rep':>14}{'delta':>10}")
    for key, label, fmt in (("volume", "volume mm3", "{:.4f}"),
                            ("silhouette", "silhouette mm2", "{:.4f}"),
                            ("triangles", "triangles", "{:,}"),
                            ("bodies", "bodies", "{}"),
                            ("seconds", "build s", "{:.2f}")):
        m, b = mesh.get(key), brep.get(key)
        if m is None:
            continue
        delta = ""
        if isinstance(b, (int, float)) and b:
            delta = f"{100.0 * (m - b) / b:+.4f}%"
        lines.append(f"  {label:<14}{fmt.format(m):>14}"
                     f"{(fmt.format(b) if b is not None else '-'):>14}"
                     f"{delta:>10}")

    if "edges" in brep:
        lines.append(f"  {'B-Rep edges':<14}{brep['edges']:>28,}")
    lines.append("")
    # Said out loud because otherwise it reads as a defect. The B-Rep path
    # extrudes the authored splines; this one extrudes the partition's
    # flattened polygons, which are inscribed in them. So the mesh silhouette
    # is expected to come out a chord deficit SMALLER, a few tenths of a
    # percent, and the sign is the tell: mesh larger would mean something else
    # is going on.
    lines.append("  A small negative silhouette delta is the chord deficit of "
                 "the flattened")
    lines.append("  outline, and is expected. A positive one is not.")
    lines.append("")
    for name, side in (("mesh", mesh), ("B-Rep", brep)):
        if "ok" not in side:
            continue
        state = "verified" if side["ok"] else "FAILED"
        lines.append(f"  {name}: {state}")
        for problem in side.get("problems", ()):
            lines.append(f"      {problem}")
    return "\n".join(lines)


def run_diag(path: str) -> int:
    """`--diag-kernels <drawing>`: compare both kernels on every frame front."""
    from pathlib import Path

    from guildmodel.core.project.schema import CastleParams, ComponentKind
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    source = Path(path)
    if not source.exists():
        print(f"no such file: {source}")
        return 2

    workspaces, _active = build_workspaces_from_gdraw(source)
    fronts = [ws for ws in workspaces if ws.kind == ComponentKind.FRAME_FRONT]
    if not fronts:
        print(f"{source.name} has no frame front to compare")
        return 2

    for front in fronts:
        print(f"\n{source.name}: {front.label or 'frame front'}")
        # The drawing's own castle parameters where it carries them, so the
        # comparison is of the part the maker is actually building.
        castle = front.castle_params or CastleParams()
        print(format_report(compare_kernels(front.partition, castle,
                                            front.hinge_polys)))
    return 0
