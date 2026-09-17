"""The release workflows really do quarantine the window tests.

`pyproject.toml` and `tests/test_gui_marker.py` both describe a split: the gate
runs `-m "not gui"`, and the window tests run afterwards in a separate step that
is allowed to fail. `test_gui_marker.py` works hard to keep the `gui` mark
complete and accurate on that basis.

**The split was described for months and never implemented.** Both workflows ran
the whole suite in one step; `git log -S'not gui' -- .github/` was empty. So the
mark was maintained, and enforced, and consumed by nothing — while the failure it
exists to contain stayed live: one window test parks the main thread on the
hosted Windows and macos-15-intel runners, `--timeout-method=thread` cannot
interrupt that and kills the interpreter, and the run dies with no artifact. That
cost 80 minutes of a Windows runner and 79 of a macOS one across v1.5.0's first
two attempts.

A comment cannot check itself, which is the whole lesson. This reads the
workflows.
"""
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _jobs():
    yaml = pytest.importorskip("yaml")
    if not WORKFLOWS.is_dir():
        pytest.skip("no .github/workflows in this checkout")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, spec in (doc.get("jobs") or {}).items():
            yield path.name, name, spec.get("steps") or []


def _pytest_steps(steps):
    """Steps that *invoke* pytest.

    Matched on `-m pytest`, the invocation, rather than on the bare word: the
    dependency step installs `pytest-timeout`, and a substring match counts that
    as an unguarded release gate.
    """
    return [s for s in steps if "-m pytest" in str(s.get("run", ""))]


def test_the_blocking_gate_excludes_the_window_tests():
    """A gate that can be killed by a quarantined test is not a quarantine."""
    seen = 0
    for wf, job, steps in _jobs():
        for step in _pytest_steps(steps):
            if step.get("continue-on-error"):
                continue                      # that is the reporting half
            seen += 1
            assert '-m "not gui"' in step["run"], (
                f"{wf} :: {job} :: {step.get('name')} runs the whole suite as a "
                "blocking gate. One window test hangs on the hosted runners and "
                "--timeout-method=thread kills the interpreter, so that step "
                'cannot produce an artifact. Add -m "not gui".')
    assert seen, "no blocking pytest step found in any workflow"


def test_the_window_tests_still_run_somewhere():
    """Excluding them from the gate must not mean never running them.

    They are 32 real tests over the windows, docks and session guards. The point
    is that they cannot hold back a release, not that nobody looks at them.
    """
    for wf, job, steps in _jobs():
        runs = _pytest_steps(steps)
        if not runs:
            continue
        gui = [s for s in runs if "-m gui" in s["run"]]
        assert gui, (f"{wf} :: {job} excludes the gui tests from its gate and "
                     "never runs them anywhere — they are silently dropped")
        for step in gui:
            assert step.get("continue-on-error") is True, (
                f"{wf} :: {step.get('name')} runs the quarantined tests without "
                "continue-on-error, so a hang there fails the release anyway")


def test_the_window_tests_run_after_the_artifact_is_uploaded():
    """Placement is load-bearing, not tidiness.

    `continue-on-error` stops a hang from *failing* the job; it does not stop it
    from spending its whole 20-minute timeout. Scheduled before the build, that
    is 20 minutes out of a budget the heavy step still needs — macOS allows 140
    minutes and the gate alone may take 90. Scheduled after the upload, the
    artifact already exists and a hang can only make the run look slow.
    """
    for wf, job, steps in _jobs():
        names = [s.get("name", "") for s in steps]
        gui = [i for i, s in enumerate(steps)
               if "-m pytest" in str(s.get("run", ""))
               and "-m gui" in str(s.get("run", ""))]
        uploads = [i for i, s in enumerate(steps)
                   if "upload-artifact" in str(s.get("uses", ""))]
        if not gui or not uploads:
            continue
        assert min(gui) > max(uploads), (
            f"{wf} :: {job} runs the window tests at step {min(gui)} "
            f"({names[min(gui)]}) but uploads at {max(uploads)} — a 20-minute "
            "hang there delays the artifact it is supposed to be independent of")
