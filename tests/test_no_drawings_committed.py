"""No maker's drawing is ever committed to this repository.

The frame designs are the maker's product line — access to them is sold — so a
drawing is not sample data and does not belong in a public history, in any
folder and in any form. Testing against real ones is still the right thing to
do; `tests/test_frame_corpus.py` does it by reading a corpus off disk, which
ships nothing.

Two forms to catch, because the first rule only ever covered one of them:

* **the archive** — a `.gdraw` or `.gmodel` file. `.gitignore` carried
  `/*.gdraw`, root-anchored, which silently permitted every subdirectory.
* **the unpacked archive** — a folder of `front.svg` + `manifest.json` +
  temples, which is exactly what a `.gdraw` *is* and which no extension rule
  can see. Three drawings reached `tests/fixtures/` in this form in 2026-09
  before anyone noticed, and two older ones are still there.

So this reads the git index rather than the working tree: what matters is what
would be published, not what happens to be on this disk.
"""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]

#: Unpacked drawings that are **already in the published history**, kept listed
#: rather than quietly excluded. Both are the maker's own designs (one under its
#: own name, one renamed), committed before the rule above existed, and ~23 test
#: modules build on them. Removing them from the working tree is easy; removing
#: them from a public history is a rewrite, and that is the maker's call to make
#: — see the note this list points at. Until then they are known debt, and this
#: test still fails for anything *new*, which is its whole job.
KNOWN_EXPOSED = {"tests/fixtures/gabriel", "tests/fixtures/aviator"}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=False)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in out.stdout.splitlines() if line]


def test_no_drawing_archive_is_tracked():
    """The plain form: a `.gdraw` or `.gmodel` anywhere in the index."""
    bad = [p for p in _tracked() if p.endswith((".gdraw", ".gmodel"))]
    assert not bad, (
        "a maker's drawing is staged for publication:\n  " + "\n  ".join(bad)
        + "\n\nThe designs are sold, not sample data. Test against a corpus on "
          "disk instead — see tests/test_frame_corpus.py.")


def test_no_unpacked_drawing_is_tracked():
    """The form an extension rule cannot see: a `.gdraw` with the zip taken off.

    A GuildDraw archive is a folder of SVG layers plus a `manifest.json`, so a
    directory holding both is a drawing whatever it has been named — which is
    how three of them were nearly published as `front.svg` and friends.
    """
    tracked = set(_tracked())
    dirs = {str(Path(p).parent) for p in tracked}
    bad = sorted(d for d in dirs
                 if d not in KNOWN_EXPOSED
                 and f"{d}/manifest.json" in tracked
                 and f"{d}/front.svg" in tracked)
    assert not bad, (
        "an unpacked drawing is staged for publication:\n  " + "\n  ".join(bad)
        + "\n\nA folder of front.svg + manifest.json is a .gdraw with the zip "
          "taken off. Point tests/test_frame_corpus.py at it instead.")
