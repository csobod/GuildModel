"""The OCCT boolean switches, and why one of them is not set.

`SetUseOBB(True)` was set in `occ._run` from Stage 2 until 2026-09-16, on a
measured 8% speedup. It rejects face pairs that cannot intersect using oriented
bounding boxes — and on some frames it rejects pairs that **do** intersect, so
faces that should have been cut are left touching.

Swept over the 40 buildable frame fronts in a maker's own corpus:

===========================  ==========  ===========  ====================
drawing                      OBB on      OBB off      what it meant
===========================  ==========  ===========  ====================
one 54 mm front              6 gaps,     clean        unexportable
                             154 touch
another holding the same     6 gaps,     clean        same geometry
geometry                     154 touch
one 55 mm front              **passes**  passes       29.1 mm3 missing
the other 37                 identical   identical    nothing
===========================  ==========  ===========  ====================

The third is the one that settled it. It never failed a gate; it was just
29.1 mm3
short (11,123.39 against 11,152.52), and the raster (11,151.80) and Manifold
(11,152.18) agree with the no-OBB build to 0.006%. Two independent kernels
against one, on a part a machine would have cut.

Cost of removing it, on the fully-featured builds it was tuned against: demo
29.56 s -> 30.25 s, gabriel 35.67 -> 36.45, aviator 31.49 -> 31.58. Worst case
+2.4%, identical volumes. Across the library sweep, +0.0%.

**Why this test is structural rather than geometric.** None of the three shipped
fixtures reproduces it — demo, gabriel and aviator build bit-identical volumes
either way, which is exactly why it survived Stage 2 and the whole M-N series.
Reproducing it needs one of the maker's own drawings, and those are deliberately
not in this history (see the 2026-08 removal of a maker's program). So this pins
the decision where the decision lives, and the geometry is pinned by the sweep
recorded above.
"""
import ast
import inspect
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "guildmodel"


def test_the_boolean_runner_does_not_enable_obb():
    """`SetUseOBB` must stay off until someone has a fixture proving it is safe.

    Asserted on the source rather than by running a boolean, because the failure
    it guards against is invisible on every drawing this repository ships.
    """
    # The whole module, through the AST: the explanation above `_run` names
    # `SetUseOBB` in prose, and a comment is not a call.
    tree = ast.parse((SRC / "core" / "solid" / "occ.py").read_text(encoding="utf-8"))
    calls = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "SetUseOBB"]
    assert not calls, (
        f"SetUseOBB is set again (line {calls}) — it silently removed 29.1 mm3 "
        "from one frame while passing every gate, and corrupted two others "
        "outright. See this module's docstring for the sweep.")


def test_the_switches_that_remain_are_still_set():
    """The other two are real and measured: parallel is worth 82.0 s -> 62.2 s
    bit-identically, and history stays off because nothing asks for it. A change
    that dropped them while removing OBB would be a silent regression."""
    from guildmodel.core.solid import occ

    src = inspect.getsource(occ._run)
    assert "SetRunParallel(True)" in src
    assert "SetToFillHistory(False)" in src


def test_every_boolean_goes_through_the_one_runner():
    """The switches only mean something if nothing bypasses them.

    `_run` is where the policy lives; a `BRepAlgoAPI_*` built and `.Build()`-ed
    somewhere else would carry OCCT's defaults instead — including OBB off, so
    this is not the direction that broke anything, but it is how the next
    setting would fail to apply.
    """
    tree = ast.parse((SRC / "core" / "solid" / "occ.py").read_text(encoding="utf-8"))
    builds = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Build"):
            builds.append(node.lineno)
    run_src = inspect.getsource(
        __import__("guildmodel.core.solid.occ", fromlist=["_run"])._run)
    assert run_src.count(".Build()") == 1
    assert len(builds) == 1, (
        f"a boolean is built outside _run (lines {builds}) — it will not get "
        "the parallel/history settings")
