"""OpenCASCADE is optional now, and the app has to work without it.

264 MB installed — 163 MB of `OCP` plus 101 MB of `cadquery_ocp.libs`, measured;
the buildplan's long-standing "70 MB" was wrong and too kind — for a kernel that
since M-N4 is not the default, does not post G-code, and is not needed by any
feature: every posterior feature loads zero OCP modules on the mesh path.

**Demoted, not deleted.** It is still the third opinion every parity gate
measures the mesh against, and building the same part two ways is what caught
this season's silent defects — the nosepad spike, the whole-ring bezel, the
swept groove that only broke when the exact rim lip went away. So `dev` still
installs it and these tests still find it; what changed is that a *maker* does
not get it, and does not get offered a kernel they have no reason to choose.

The interesting tests here are the ones that run with OCP hidden. `find_spec`
answers without importing, so absence can be simulated honestly in-process:
a meta-path finder that refuses `OCP` is exactly what a machine without it has.
"""
import importlib
import importlib.abc
import sys

import pytest


class _NoOCP(importlib.abc.MetaPathFinder):
    """A machine without `cadquery-ocp`.

    Raises rather than returning None on purpose: a half-removed package makes
    `find_spec` raise, and that is the case `brep_installed` has to swallow —
    the question is "can this install build a B-Rep", and every failure to
    answer means no.
    """

    def find_spec(self, name, path=None, target=None):
        if name == "OCP" or name.startswith("OCP."):
            raise ImportError("OCP hidden for this test")
        return None


@pytest.fixture
def without_ocp(monkeypatch):
    finder = _NoOCP()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    for name in [m for m in sys.modules if m.startswith("OCP")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    return finder


def test_the_kernel_list_drops_the_brep_when_it_is_not_installed(without_ocp):
    from guildmodel.core import kernels

    assert kernels.brep_installed() is False
    assert kernels.brep_offered() is False
    assert kernels.available_kernels() == ("raster", "mesh")


def test_a_saved_brep_preference_still_opens_on_a_machine_without_it(without_ocp):
    """The migration case. A maker who chose the B-Rep once, on a machine that
    had it, must not be unable to open their project on one that does not — and
    must not be silently dropped to the raster either, having asked for an exact
    solid. The mesh is one, and agrees with the B-Rep to a mean of 0.0025 mm.
    """
    from guildmodel.core import kernels

    assert kernels.resolve_kernel("brep") == "mesh"
    assert kernels.resolve_kernel("mesh") == "mesh"
    assert kernels.resolve_kernel("raster") == "raster"
    assert kernels.resolve_kernel("nonsense") == "mesh"


def test_the_flag_alone_does_not_conjure_a_kernel(monkeypatch, without_ocp):
    """`GUILDMODEL_BREP` governs whether an installed B-Rep is *offered*. It
    cannot offer one that is not there."""
    from guildmodel.core import kernels

    monkeypatch.setenv(kernels.BREP_ENV, "1")
    assert kernels.brep_offered() is False
    assert "brep" not in kernels.available_kernels()


def test_installed_but_unasked_is_the_developer_case(monkeypatch):
    """The default on a dev machine: OCCT present for the gates, absent from
    Preferences. Without this the demotion would be a no-op for everyone who
    can actually see it."""
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core import kernels

    monkeypatch.delenv(kernels.BREP_ENV, raising=False)
    assert kernels.brep_installed() is True
    assert kernels.brep_offered() is False
    assert kernels.available_kernels() == ("raster", "mesh")

    monkeypatch.setenv(kernels.BREP_ENV, "1")
    assert kernels.brep_offered() is True
    assert kernels.available_kernels() == ("raster", "brep", "mesh")
    # An explicit choice is still honoured whether or not it is offered — the
    # flag is about the menu, not about what the app can build.
    assert kernels.resolve_kernel("brep") == "brep"


def test_nothing_a_maker_touches_imports_the_kernel(without_ocp):
    """The whole app, with OCP hidden: the GUI, the CAM bridge, the mesh kernel.

    An import error anywhere here is a crash on startup for every user who does
    not install the extra, which is now the default install.
    """
    for name in ("guildmodel.core.kernels", "guildmodel.core.zmap",
                 "guildmodel.core.model", "guildmodel.core.geometry.rings",
                 "guildmodel.core.geometry.curves", "guildmodel.gui.app",
                 "guildmodel.gui.mesh_build"):
        importlib.import_module(name)
    assert not [m for m in sys.modules if m.startswith("OCP")]


def test_cadquery_ocp_is_an_extra_rather_than_a_dependency():
    """Read off `pyproject.toml`, because that is what a user's `pip install`
    obeys — the code being able to run without OCCT is only half of it."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    with open(root / "pyproject.toml", "rb") as fh:
        cfg = tomllib.load(fh)

    required = " ".join(cfg["project"]["dependencies"])
    assert "cadquery-ocp" not in required, (
        "cadquery-ocp is back in the required dependencies — 264 MB for a "
        "kernel a maker does not use")

    extras = cfg["project"]["optional-dependencies"]
    assert any("cadquery-ocp" in dep for dep in extras["brep"])
    assert any("brep" in dep for dep in extras["dev"]), (
        "the parity gates need the third opinion; dev must still pull it in")
