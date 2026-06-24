"""M7.14 — job/validation diagnostics aggregation."""
from dataclasses import dataclass

from guildcam.core.diagnostics import Issue, collect_issues, severity_counts


@dataclass
class _Reach:
    op_name: str
    def message(self):
        return f"{self.op_name}: tool too wide"


@dataclass
class _Depth:
    op_name: str
    def message(self):
        return f"{self.op_name}: cut deeper than flute"


class _Comp:
    def __init__(self, uncut_cells, body_cells, uncut_fraction, max_excess_mm):
        self.uncut_cells = uncut_cells
        self.body_cells = body_cells
        self.uncut_fraction = uncut_fraction
        self.max_excess_mm = max_excess_mm


class _Gouge:
    def __init__(self, gouge_cells, max_depth_mm):
        self.gouge_cells = gouge_cells
        self.max_depth_mm = max_depth_mm


class _Report:
    def __init__(self, status, comp, gouge):
        self._status = status
        self.completeness = comp
        self.gouge = gouge
    def status(self):
        return self._status


def test_clean_job_is_empty():
    assert collect_issues() == []
    assert collect_issues(
        reach_warnings=[], depth_warnings=[], clearance_violations=[],
        machine_lint=[],
        cut_report=_Report("ok", _Comp(0, 1000, 0.0, 0.0), _Gouge(0, 0.0)),
    ) == []


def test_collects_every_category_from_a_bad_job():
    issues = collect_issues(
        reach_warnings=[_Reach("Hinge Pockets")],
        depth_warnings=[_Depth("Profile")],
        clearance_violations=["frame_front fouls a screw at (10, 20)"],
        machine_lint=["arc without an explicit center"],
        cut_report=_Report("fail", _Comp(120, 1000, 0.12, 1.4), _Gouge(8, 0.7)),
    )
    cats = {i.category for i in issues}
    assert cats == {"Tool reach", "Clearance", "Machine lint", "Cut quality"}
    # reach (2) + clearance (1) + lint (1) + cut quality (2: uncut + gouge)
    assert len(issues) == 6


def test_collisions_are_errors_to_the_sim():
    issues = collect_issues(
        collisions=["the tool fouls a hold-down at 12 points"])
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].category == "Collision"
    assert issues[0].target == ("view", "sim")


def test_sorted_errors_before_warnings():
    issues = collect_issues(
        reach_warnings=[_Reach("A")],                       # warning
        clearance_violations=["collision"],                  # error
    )
    assert issues[0].severity == "error"
    assert issues[-1].severity == "warning"


def test_targets_for_navigation():
    issues = collect_issues(
        reach_warnings=[_Reach("Hinge Pockets")],
        clearance_violations=["c"],
        cut_report=_Report("warn", _Comp(50, 1000, 0.05, 0.6), _Gouge(0, 0.0)),
    )
    by_cat = {i.category: i for i in issues}
    assert by_cat["Tool reach"].target == ("op", "Hinge Pockets")
    assert by_cat["Clearance"].target == ("view", "worktable")
    assert by_cat["Cut quality"].target == ("view", "sim")


def test_cut_report_severity_depends_on_status():
    warn = collect_issues(
        cut_report=_Report("warn", _Comp(50, 1000, 0.05, 0.6), _Gouge(0, 0.0)))
    assert warn[0].severity == "warning"
    fail = collect_issues(
        cut_report=_Report("fail", _Comp(200, 1000, 0.20, 2.0), _Gouge(0, 0.0)))
    assert fail[0].severity == "error"


def test_gouge_severity_by_depth():
    shallow = collect_issues(
        cut_report=_Report("warn", _Comp(0, 1000, 0.0, 0.0), _Gouge(5, 0.3)))
    assert shallow[0].severity == "warning"
    deep = collect_issues(
        cut_report=_Report("fail", _Comp(0, 1000, 0.0, 0.0), _Gouge(5, 0.9)))
    assert deep[0].severity == "error"


def test_severity_counts():
    issues = collect_issues(
        reach_warnings=[_Reach("A"), _Reach("B")],
        clearance_violations=["c"],
    )
    counts = severity_counts(issues)
    assert counts == {"error": 1, "warning": 2, "info": 0}
