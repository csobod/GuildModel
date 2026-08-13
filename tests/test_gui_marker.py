"""Every test that builds a MainWindow has to say so.

The release workflows gate on `-m "not gui"` and run `-m gui` as a separate,
non-blocking step. That split is only worth anything if the marker is complete:
an unmarked MainWindow test lands back in the gating run, and the failure it
causes there is not a red assertion — it is a 300 s per-test timeout that
`--timeout-method=thread` turns into a killed process, so the whole gate dies
and the build produces no artifact. That cost 80 minutes of a Windows runner
and 79 of a macOS one before this file existed, on v1.5.0's first two attempts.

It is a real fault and it is not fixed; it is quarantined. What is known: two
different tests on two unrelated platforms parked at the *same* frame — the
first GIL-releasing call inside `MainWindow.__init__`, `read_text` on a camera
icon — which is the signature of the main thread waiting on a GIL something
else is holding, not of a slow file read. It does not reproduce on Linux or on
the macos-14 runner, both of which run the whole suite green.

So the marker is checked here rather than trusted. The scan is deliberately
syntactic — a test qualifies if it names `MainWindow` itself or calls a
module-level helper that does, which is how all 41 of the current ones reach
one. A test that gets there some other way (a fixture in `conftest`, say) would
slip past, and the cost of that is a wedged CI run, so put the mark on by hand
if you write one.
"""
import ast
from pathlib import Path

TESTS = Path(__file__).parent


def _builds_window(node):
    """True if this function *calls* `MainWindow(...)`.

    Calling it is the thing that costs — `test_model_kernel_mn2` reaches a
    method through `MainWindow.__new__(MainWindow)`, which never runs
    `__init__`, builds no widgets, and belongs in the gating run. So this looks
    for a call whose callee is the bare name, not for the name anywhere.
    """
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "MainWindow" for n in ast.walk(node))


def _reaching_tests(tree):
    """Names of top-level tests that build a MainWindow, and their marks."""
    funcs = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def calls(node):
        return {n.func.id for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    helpers = {name for name, n in funcs.items()
               if not name.startswith("test_") and _builds_window(n)}
    for _ in range(3):                      # helper calling helper
        for name, n in funcs.items():
            if not name.startswith("test_") and calls(n) & helpers:
                helpers.add(name)

    for name, n in funcs.items():
        if not name.startswith("test_"):
            continue
        if _builds_window(n) or calls(n) & helpers:
            marked = any(isinstance(d, ast.Attribute) and d.attr == "gui"
                         for d in n.decorator_list)
            yield name, marked


def test_every_mainwindow_test_carries_the_gui_marker():
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name, marked in _reaching_tests(tree):
            if not marked:
                missing.append(f"{path.name}::{name}")

    assert missing == [], (
        "these build a MainWindow but are not marked `gui`, so they would run "
        "in the gating job and can hang it:\n  " + "\n  ".join(missing))


def test_the_marker_is_not_over_applied():
    """The other half: a `gui` mark on a test that never builds a window quietly
    drops it out of the gate. 31 tests need it, out of a suite of ~1085 — if
    that count climbs on a change that added no window tests, something is being
    excused rather than marked."""
    marked = 0
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reaching = dict(_reaching_tests(tree))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if any(isinstance(d, ast.Attribute) and d.attr == "gui"
                   for d in node.decorator_list):
                marked += 1
                assert node.name in reaching, (
                    f"{path.name}::{node.name} is marked `gui` but does not "
                    "build a MainWindow — it belongs in the gating run")
    assert marked == 31, f"{marked} tests marked `gui`, expected 31"
