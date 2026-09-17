"""Sweep a maker's own drawings, when a maker points us at some.

Three defects reached production because the three fixtures this repo ships
build bit-identically under all of them. Each needed a real drawing:

* a boolean switch (`SetUseOBB`) that rejected face pairs which do intersect.
  On two drawings it was loud — gaps, self-touching edges, no export. On a
  third it was **silent**: 29.1 mm3 of material gone with every gate green.
* mounting holes breaking out of a small eye, leaving a base-curve template
  with one usable hole instead of three and a watertight mesh either way.
* a nosepad-to-bridge blend that will not close, on one side of a mirrored
  pair whose two fills differ by 0.0009 mm3.

None of them is reproducible from anything in this repository, and the
drawings that do reproduce them are a maker's own product designs — not ours
to vendor, and deliberately absent from this history. So this module asks for
a corpus instead of carrying one, and checks the *properties* those three
defects violated rather than the drawings that happened to expose them.

Point it at a folder of `.gdraw` files::

    GUILDMODEL_FRAME_CORPUS="/path/to/drawings" pytest tests/test_frame_corpus.py

Skipped, and silent, when that is unset. Nothing here names a drawing: the
names in a failure message come off the filesystem at the moment it fails.

**It is slow** — a B-Rep front is ~20 s and a corpus is typically dozens, so
budget accordingly and use `GUILDMODEL_FRAME_CORPUS_MAX` to bound a smoke run.
Slow is the point: this is the pass you make before a release, not on a commit.
"""
import os
from pathlib import Path

import pytest

#: Where the drawings are. Unset (the normal case, and every CI run) skips.
_CORPUS_ENV = "GUILDMODEL_FRAME_CORPUS"
#: Optional cap, for a smoke run over a large corpus.
_MAX_ENV = "GUILDMODEL_FRAME_CORPUS_MAX"

#: The kernels agreed to 0.006% once the boolean switch was gone; the parity
#: gate elsewhere in the suite allows 0.1%. Same bound here, for the same
#: reason — anything looser cannot see the 0.26% that went missing silently.
VOLUME_REL = 0.001


def _drawings():
    """Every live `.gdraw` under the corpus root.

    Syncthing keeps version history in `.stversions/`, which on a real corpus
    is the majority of what `rglob` finds — a sweep that includes it measures
    the same drawing many times over and reports failures against files the
    maker cannot open. `.bak` siblings go for the same reason.
    """
    root = os.environ.get(_CORPUS_ENV)
    if not root or not Path(root).is_dir():
        return []
    out = [p for p in sorted(Path(root).rglob("*.gdraw"))
           if ".stversions" not in p.parts and not p.name.endswith(".bak")]
    cap = os.environ.get(_MAX_ENV)
    return out[:int(cap)] if cap and cap.isdigit() else out


pytestmark = pytest.mark.skipif(
    not _drawings(),
    reason=f"no corpus: set {_CORPUS_ENV} to a folder of .gdraw drawings")


def _fronts():
    """`(path, workspace)` for every drawing with a buildable frame front.

    A corpus is working material, so plenty of it will not build — a drawing
    with no SCULPT zones, or fewer than two LENS curves, or no OUTLINE at all.
    That is the maker's business and not a fault here, so those are passed over
    rather than failed.
    """
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    out = []
    for path in _drawings():
        try:
            workspaces = build_workspaces_from_gdraw(path)[0]
        except Exception:                                     # noqa: BLE001
            continue          # an unreadable drawing is not this test's claim
        for ws in workspaces:
            if ws.enabled and ws.castle_ready:
                out.append((path, ws))
                break
    return out


@pytest.fixture(scope="module")
def fronts():
    got = _fronts()
    if not got:
        pytest.skip("corpus has no drawing with a buildable frame front")
    return got


@pytest.fixture(scope="module")
def built(fronts):
    """Build each front **once** on both kernels: `(path, verdict, brep, raster)`.

    Module-scoped because the two sweeps below want the same builds and a B-Rep
    front is ~20 s — asking for them per test doubles a corpus pass from about
    25 minutes to about 40 for no new information.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.mesh_check import verify_mesh

    out = []
    for path, ws in fronts:
        brep = _brep_mesh(ws)
        out.append((path, verify_mesh(brep), brep.volume, _raster_mesh(ws).volume))
    return out


def _brep_mesh(ws):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    clear_base_cache()
    solid = build_castle_solid(ws.partition, ws.castle_params or CastleParams(),
                               ws.hinge_polys)
    return tessellate(solid).to_trimesh()


def _raster_mesh(ws, resolution=0.30):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_mesh
    from guildmodel.core.zmap import castle_relief

    relief = castle_relief(ws.partition, ws.castle_params or CastleParams(),
                           ws.hinge_polys, kernel="raster", resolution=resolution)
    return build_castle_mesh(relief)


def test_every_corpus_front_builds_a_closed_solid(built):
    """The loud half of the boolean defect, and the blend that will not close.

    Reported in one batch rather than failing on the first, because the useful
    output of a corpus sweep is *which* drawings are affected — one name tells
    you much less than the shape of the set.
    """
    bad = [f"{path.name}: {'; '.join(v.problems)}"
           for path, v, _brep, _raster in built if not v.ok]
    assert not bad, "fronts that did not build a closed solid:\n  " + "\n  ".join(bad)


def test_the_kernels_agree_on_how_much_material_there_is(built):
    """The silent half, and the only thing that catches it.

    A boolean that eats material leaves a mesh that is still closed, still one
    body, still correctly wound, and still passes every gate this app has. The
    build that lost 29.1 mm3 reported "Model verified". Nothing derived from a
    single kernel can see that, so this asks a second one: the raster shares no
    code with the B-Rep path below the partition.
    """
    bad = []
    for path, _v, brep, raster in built:
        if abs(brep - raster) > VOLUME_REL * max(abs(raster), 1.0):
            bad.append(f"{path.name}: brep {brep:.2f} vs raster {raster:.2f} mm3 "
                       f"({(brep - raster) / raster:+.3%})")
    assert not bad, (
        "a boolean is eating material that no closure check can see:\n  "
        + "\n  ".join(bad))


def test_the_flat_fallback_is_still_earning_its_place(fronts):
    """A tripwire on the defect, not on the workaround.

    `build_castle_solid` builds with curved terraces, checks the result closes,
    and rebuilds from the flattened partition when it does not. That costs a
    little accuracy (the chord deficit) on any drawing that needs it, and it is
    only worth carrying while some drawing still does.

    So this fails when **every** front in the corpus closes unaided: at that
    point the fallback is dead weight and should be deleted, which is a better
    thing to be told than to keep paying for quietly. It stops at the first
    drawing that needs it, since one is enough to justify the code.
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid.build import (castle_base, clear_base_cache,
                                             closes)

    for path, ws in fronts:
        clear_base_cache()
        base = castle_base(ws.partition, ws.castle_params or CastleParams(),
                           None, curved=True)[3]
        if not closes(base):
            clear_base_cache()
            flat = castle_base(ws.partition, ws.castle_params or CastleParams(),
                               None, curved=False)[3]
            assert closes(flat), (
                f"{path.name} closes on neither curved nor flat terraces — the "
                "fallback cannot rescue it and it will reach the maker broken")
            return                        # one is enough: the fallback is live

    if os.environ.get(_MAX_ENV):
        # A capped run is a sample, and "no drawing needed it" is a claim about
        # the whole corpus. Concluding it from a sample would retire live code
        # on the strength of whichever files sorted first.
        pytest.skip(f"{_MAX_ENV} is set — a bounded sample cannot show the "
                    "fallback is unused")
    pytest.fail(
        "every front in this corpus closes with curved terraces — the flat "
        "fallback in build_castle_solid is dead weight and should be removed, "
        "along with the `curved` parameter threaded through castle_base()")
