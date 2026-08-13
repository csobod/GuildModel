"""The batched rasterizer, and the anterior surface that falls out of it.

`triangle_envelopes` replaced a loop over triangles with one vectorised pass
over (triangle, cell) pairs, and split the two envelopes across the two
facings. Both are optimizations of an answer that must not move, so the first
test here is a reference implementation of the old loop, compared cell for cell
— not a tolerance.

The rest pin the things the speedup rests on:

* the facing split assumes outward winding, and falls back when it is wrong
* the pair array is batched, so a triangle spanning the whole grid is fine
* the lower envelope is flat zero on a frame that does not cut its front, which
  is what lets `CastleRelief.anterior` stay `None` and keep the M17 fast path
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _reference_zmap(vertices, faces, origin, rows, cols, resolution,
                    background=0.0):
    """The per-triangle loop, kept as the thing the fast path must reproduce.

    A copy on purpose. The point of a reference implementation is that it does
    not change when the implementation does, so it is not shared with it.
    """
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if len(f) == 0:
        return np.full((rows, cols), background, dtype=np.float64)

    z = np.full((rows, cols), -np.inf, dtype=np.float64)
    ox, oy = origin
    tri = v[f]
    gx = (tri[:, :, 0] - ox) / resolution
    gy = (tri[:, :, 1] - oy) / resolution
    tz = tri[:, :, 2]

    lo_c = np.maximum(np.floor(gx.min(axis=1)).astype(np.int64), 0)
    hi_c = np.minimum(np.ceil(gx.max(axis=1)).astype(np.int64) + 1, cols)
    lo_r = np.maximum(np.floor(gy.min(axis=1)).astype(np.int64), 0)
    hi_r = np.minimum(np.ceil(gy.max(axis=1)).astype(np.int64) + 1, rows)
    x0, x1, x2 = gx[:, 0], gx[:, 1], gx[:, 2]
    y0, y1, y2 = gy[:, 0], gy[:, 1], gy[:, 2]
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

    for t in range(len(f)):
        c0, c1, r0, r1 = lo_c[t], hi_c[t], lo_r[t], hi_r[t]
        if c1 <= c0 or r1 <= r0 or abs(denom[t]) < 1e-12:
            continue
        px, py = np.meshgrid(np.arange(c0, c1, dtype=np.float64),
                             np.arange(r0, r1, dtype=np.float64))
        d = denom[t]
        w0 = ((y1[t] - y2[t]) * (px - x2[t]) + (x2[t] - x1[t]) * (py - y2[t])) / d
        w1 = ((y2[t] - y0[t]) * (px - x2[t]) + (x0[t] - x2[t]) * (py - y2[t])) / d
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not hit.any():
            continue
        zt = w0 * tz[t, 0] + w1 * tz[t, 1] + w2 * tz[t, 2]
        sub = z[r0:r1, c0:c1]
        np.maximum(sub, np.where(hit, zt, -np.inf), out=sub)

    z[~np.isfinite(z)] = background
    return z


def _front_from_gdraw(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def demo_front():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    return _front_from_gdraw(tmp_path_factory, "gabriel")


def _featured_mesh(front):
    from guildmodel.core.model import build_castle_model, to_trimesh
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.pad_splay.enabled = True
    castle.eyewire_bezel.enabled = True
    castle.bridge_relief.enabled = True
    return castle, to_trimesh(build_castle_model(front.partition, castle,
                                                 front.hinge_polys))


@pytest.mark.parametrize("fixture", ["gabriel_front", "demo_front"])
def test_the_batched_pass_reproduces_the_loop_cell_for_cell(fixture, request):
    """Equality, not a tolerance — this is the same arithmetic reordered."""
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.zmap import grid_for, groove_body, triangle_envelopes

    front = request.getfixturevalue(fixture)
    castle, mesh = _featured_mesh(front)
    body, _ = groove_body(front.partition, castle)
    origin, rows, cols = grid_for(body, CUT_RES_MM)

    up, _ = triangle_envelopes(mesh.vertices, mesh.faces, origin, rows, cols,
                               CUT_RES_MM)
    ref = _reference_zmap(mesh.vertices, mesh.faces, origin, rows, cols,
                          CUT_RES_MM)
    assert np.array_equal(up, ref), (
        f"worst cell differs by {np.abs(up - ref).max():.3e} mm on "
        f"{int((up != ref).sum())} of {rows * cols} cells")


def test_a_frame_that_does_not_cut_its_front_has_a_flat_anterior(gabriel_front):
    """The lower envelope is the anterior face, and it is the blank's datum
    until something cuts it. This is what keeps `CastleRelief.anterior` at
    `None` and every pre-M17 project on the single-surface fast path."""
    from guildmodel.core.relief.castle import CUT_RES_MM
    from guildmodel.core.zmap import grid_for, groove_body, triangle_envelopes

    castle, mesh = _featured_mesh(gabriel_front)
    body, _ = groove_body(gabriel_front.partition, castle)
    origin, rows, cols = grid_for(body, CUT_RES_MM)

    up, dn = triangle_envelopes(mesh.vertices, mesh.faces, origin, rows, cols,
                                CUT_RES_MM)
    assert np.count_nonzero(np.abs(dn) > 1e-9) == 0, (
        "the posterior features are cutting through to the front face")
    assert (up >= dn - 1e-9).all(), "a cell of the body has negative thickness"
    assert up.max() > 9.0, "nothing was sampled at all; the test proves nothing"


def _wedge():
    """A closed wedge: 4 mm x 4 mm footprint, 1 mm floor, sloping 1 -> 3 mm."""
    v = np.array([[0., 0., 1.], [4., 0., 1.], [4., 4., 1.], [0., 4., 1.],
                  [0., 0., 3.], [4., 0., 3.], [4., 4., 1.], [0., 4., 1.]])
    f = np.array([[0, 2, 1], [0, 3, 2],          # floor, facing down
                  [4, 5, 6], [4, 6, 7],          # roof, facing up
                  [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5],
                  [2, 3, 7], [2, 7, 6],
                  [3, 0, 4], [3, 4, 7]])
    return v, f


def test_inverted_winding_falls_back_instead_of_swapping_the_envelopes():
    """Flip every triangle and the split would hand back the floor as the
    posterior surface. The negative-thickness check catches that."""
    from guildmodel.core.zmap import triangle_envelopes

    v, f = _wedge()
    grid = ((0.0, 0.0), 9, 9, 0.5)
    up, dn = triangle_envelopes(v, f, *grid)
    up_flipped, dn_flipped = triangle_envelopes(v, f[:, ::-1], *grid)

    assert up.max() == pytest.approx(3.0)
    assert np.array_equal(up, up_flipped), "winding changed the roof"
    assert np.array_equal(dn, dn_flipped), "winding changed the floor"


def test_a_triangle_bigger_than_the_pair_budget_still_rasterizes(monkeypatch):
    """The batcher must let an oversized triangle through on its own rather
    than loop forever or drop it — the blank's underside is exactly that."""
    from guildmodel.core import zmap

    monkeypatch.setattr(zmap, "_MAX_PAIRS", 4)
    v, f = _wedge()
    up, dn = zmap.triangle_envelopes(v, f, (0.0, 0.0), 9, 9, 0.5)

    assert up.max() == pytest.approx(3.0)
    assert dn[up > 0].max() == pytest.approx(1.0)
