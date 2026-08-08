"""The maker's own drawing, and the failure only it reveals.

Two real drawings were not enough. M-N0's tangency existed on the aviator and
not the demo; this one carries a third, worse failure that neither shows: with
the pad splay on, **the frame came out in two halves**.

    piece 0  vol 3647.531  x[-67.65, -1.38]
    piece 1  vol 3647.306  x[  1.38, 67.65]

Watertight. Zero holes. Zero non-manifold edges. `BRepCheck_Analyzer` valid. A
clean cut straight down the centreline, and the only check that noticed was the
body count — which the app did not have until UI-0.

**Two independent causes, both real:**

1. `anterior_clamp_mm` has been in `PadSplayParams` since M13.1, carrying the
   comment "cut floor above the anterior face (no knife edge)". The B-Rep
   `splay_cutter` never read it. The cut reached 3.464 mm *below* the front
   face with 19 of 41 stations over less material than that.

2. The deeper one. Inward from the outline is not into the body: at the bottom
   centre the frame has the nose notch, and the default 6 mm crest offset steps
   out through it. `surface_z_at` reports its `missing` value for a ray that
   hits nothing — 0.0, indistinguishable from "the surface is at the anterior
   face" — and the chamfer spans from the cut surface *up* to `top`, so the
   station removed the full thickness. Fixing (1) alone left the frame severed;
   it took `_crest_inside` to close it.

Both fixes are no-ops where the crest stays in material: aviator and demo
volumes are unchanged to the last digit (8064.704 / 8302.741 / 7605.804 /
7923.353 before and after).
"""
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def gabriel(tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / "gabriel.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


def _built(front, mutate):
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import build_castle_solid, clear_base_cache
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    mutate(castle)
    clear_base_cache()
    return tessellate(
        build_castle_solid(front.partition, castle, front.hinge_polys)
    ).to_trimesh()


def test_the_drawing_imports_as_the_maker_drew_it(gabriel):
    partition = gabriel.partition
    assert partition.classified, "zone classification failed on a real drawing"
    assert len(partition.zones) == 9
    assert sum(1 for r in partition.body.interiors
               if not partition.is_hole(r)) == 2, "two lens apertures"
    assert len(gabriel.hinge_polys) == 2


def test_the_pad_splay_does_not_cut_the_frame_in_half(gabriel):
    """The headline. A frame component is one connected body; two means a
    feature severed it, and no other check in the app would have said so."""
    from guildmodel.core.mesh_check import verify_mesh

    mesh = _built(gabriel, lambda c: setattr(c.pad_splay, "enabled", True))
    assert mesh.body_count == 1, "the splay severed the frame"
    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict.problems


def test_the_splay_cut_stays_above_the_anterior_face(gabriel):
    """`anterior_clamp_mm` is a promise the maker can see in the UI: the cut
    floors this far above the front face. It was not being kept."""
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.solid import castle_base, clear_base_cache
    from guildmodel.core.solid.features import splay_cutter
    from guildmodel.core.solid.tessellate import tessellate

    castle = CastleParams()
    castle.pad_splay.enabled = True
    clear_base_cache()
    _p, _h, _top, base = castle_base(gabriel.partition, castle)
    cutter = tessellate(
        splay_cutter(base, gabriel.partition.body, castle.pad_splay)).to_trimesh()

    assert cutter.bounds[0][2] >= -1e-6, (
        f"the splay cutter reaches z={cutter.bounds[0][2]:.3f}, below the "
        "anterior face")


def test_every_feature_together_verifies(gabriel):
    """What the maker actually clicks. This is the build behind the screenshot
    that started the whole investigation."""
    from guildmodel.core.mesh_check import verify_mesh

    def everything(castle):
        castle.pad_splay.enabled = True
        castle.bridge_relief.enabled = True
        castle.lens_groove.enabled = True
        castle.eyewire_bezel.enabled = True

    verdict = verify_mesh(_built(gabriel, everything))
    assert verdict.ok, verdict.problems
