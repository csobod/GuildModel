"""Job & validation diagnostics (BUILDPLAN M7.14).

Aggregate every check the engine already produces — tool reach (width + depth),
bed / worktable clearance, machine lint, and cut completeness / gouge — into one
uniform, severity-tagged list the inspector panel renders and the readiness dot
summarizes. Pure: the GUI hands in the already-computed warnings, this maps them to
`Issue`s, so the collection is unit-testable apart from any rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

# Lower sorts first → errors above warnings above info.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    """One validation finding, ready for a navigable inspector row.

    `target` is an optional navigation hint the GUI interprets, e.g. ``("op", "Hinge
    Pockets")`` to highlight that toolpath, ``("view", "sim")`` to open the cut sim,
    or ``("view", "worktable")`` for the bed. None means "no place to jump to".
    """
    severity: str          # "error" | "warning" | "info"
    category: str          # short group label, e.g. "Tool reach"
    message: str           # full human-readable text
    target: Optional[tuple] = None

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)


def collect_issues(
    *,
    reach_warnings: Iterable[Any] = (),
    depth_warnings: Iterable[Any] = (),
    clearance_violations: Sequence[str] = (),
    machine_lint: Sequence[str] = (),
    collisions: Sequence[str] = (),
    cut_report: Any = None,
) -> list[Issue]:
    """Fold the engine's checks into one severity-sorted issue list.

    Every argument is optional and duck-typed (reach/depth warnings need a
    ``.message()`` + ``.op_name``; the cut report needs ``.completeness`` / ``.gouge``
    / ``.status()``), so this module imports none of the producers and can't loop a
    dependency. A clean job yields ``[]``.
    """
    issues: list[Issue] = []

    for w in reach_warnings:                       # width reach (tool too wide)
        issues.append(Issue("warning", "Tool reach", w.message(),
                             ("op", getattr(w, "op_name", None))))

    for w in depth_warnings:                       # depth reach (cut deeper than flute)
        issues.append(Issue("warning", "Tool reach", w.message(),
                             ("op", getattr(w, "op_name", None))))

    for msg in clearance_violations:               # static bed / worktable fouling
        issues.append(Issue("error", "Clearance", str(msg), ("view", "worktable")))

    for msg in collisions:                          # dynamic hold-down fouling (cut sim)
        issues.append(Issue("error", "Collision", str(msg), ("collision", None)))

    for msg in machine_lint:                        # posted-program lint
        issues.append(Issue("warning", "Machine lint", str(msg), None))

    if cut_report is not None:
        fail = cut_report.status() == "fail"
        c = cut_report.completeness
        g = cut_report.gouge
        if getattr(c, "uncut_cells", 0) > 0:
            issues.append(Issue(
                "error" if fail else "warning", "Cut quality",
                f"{c.uncut_cells} of {c.body_cells} cells under-cut "
                f"({100 * (1 - c.uncut_fraction):.1f}% reached, worst "
                f"{c.max_excess_mm:.2f} mm proud)",
                ("view", "sim")))
        if getattr(g, "gouge_cells", 0) > 0:
            issues.append(Issue(
                "error" if g.max_depth_mm > 0.5 else "warning", "Cut quality",
                f"Gouge: {g.gouge_cells} cells below target "
                f"(worst {g.max_depth_mm:.2f} mm)",
                ("view", "sim")))

    issues.sort(key=lambda i: (i.rank, i.category))
    return issues


def severity_counts(issues: Sequence[Issue]) -> dict[str, int]:
    """Tally issues by severity (always returns all three keys)."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    return counts
