"""The `model_kernel` preference now reaches the spindle, and must reach all of it.

Through M-N3 the setting governed the 3D viewer and nothing a machine cut,
because every posting path called `relief.castle.build_castle_relief` directly.
They now go through `core.zmap.castle_relief`, and the new failure mode is one
path that does not: a G-code program cut from a surface the maker is not
looking at, with nothing on screen to say so.

These are structural checks by AST rather than behavioural ones, because the
thing to prevent is a *call site* rather than a wrong answer — a future edit
that adds a sixth posting path and forgets the keyword. They are cheap and they
run without Qt.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "guildmodel"

#: Modules that legitimately build a raster relief directly. The raster builder
#: is not deprecated — it is one of the three kernels `castle_relief` chooses
#: between, and it is still the reference the parity gates measure against.
_RASTER_IS_THE_POINT = {
    SRC / "core" / "relief" / "castle.py",      # it *is* the raster builder
    SRC / "core" / "relief" / "__init__.py",    # re-export
    SRC / "core" / "zmap.py",                   # the dispatcher's raster branch
}


def _sources(*parts):
    return sorted((SRC.joinpath(*parts)).rglob("*.py"))


def test_no_production_path_builds_a_raster_relief_behind_the_dispatcher():
    """`build_castle_relief` outside `core.relief` and the dispatcher means a
    path that cannot see the preference."""
    offenders = []
    for path in _sources():
        if path in _RASTER_IS_THE_POINT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            called = (isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name)
                      and node.func.id == "build_castle_relief")
            if called:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, (
        "these call the raster builder directly and so ignore `model_kernel`: "
        + ", ".join(offenders))


def test_every_dispatcher_call_names_its_kernel():
    """`castle_relief` defaults to "mesh", which is the right default and the
    wrong thing to inherit silently at a call site. Every caller says which."""
    bare = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "castle_relief"):
                continue
            if not any(kw.arg == "kernel" for kw in node.keywords):
                bare.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not bare, (
        "these take whichever kernel the default happens to be: "
        + ", ".join(bare))


def test_every_worker_that_reaches_the_cam_is_told_which_kernel():
    """A worker left at `_ProgressWorker.kernel`'s "raster" default would post
    from a different surface than the viewer draws, and quietly.

    Counted rather than named: the assertion is that the number of workers the
    window launches onto a CAM path equals the number it tags. If a seventh
    appears, this fails until it is tagged too.
    """
    app = (SRC / "gui" / "app.py").read_text(encoding="utf-8")
    tagged = app.count("kernel = self._model_kernel()")

    tree = ast.parse(app)
    cam_workers = {"GCodeWorker", "SimWorker", "NestWorker", "BedSimWorker",
                   "ExportWorker"}
    built = sum(1 for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in cam_workers)
    assert built == tagged, (
        f"{built} workers on a CAM path are constructed but {tagged} are given "
        "a kernel — one of them will post from the raster while the viewer "
        "shows something else")


def test_the_dispatcher_falls_back_rather_than_raising_on_a_strange_name():
    """A prefs file is not a contract. An unrecognised kernel must behave as
    the app always did, not stop a maker posting a job."""
    import inspect

    from guildmodel.core import zmap

    src = inspect.getsource(zmap.castle_relief)
    assert "build_castle_relief" in src, "there is no raster fallback branch"
    assert "raise" not in src, "an unknown kernel name must not raise"
