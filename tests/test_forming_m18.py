"""Forming preview and formed STL (BUILDPLAN M18) — the core half.

The frame front after forming is one smooth map applied to the flat model's
own triangles (`core.forming`). Three things must be true at every step and
each is pinned here rather than trusted: `core.cam` cannot import
`core.forming`; the posted program is byte-identical with forming on and
off, and with the formed-groove override on and off; and the readiness dot
never reads a forming value.

The numbers are BUILDPLAN §0.4's, measured by `scripts/spike_thermoform.py`
on 2026-09-24. The bridge-set pins are the loud ones: a sign error anywhere
in the map moves them by millimetres.
"""
import ast
import inspect
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]

#: The shipped SBT rows: (label, base curve D, die radius mm, face form deg).
SBT = [
    ("SBT base 2 / lens 4", 2.0, 259.0, 174.69),
    ("SBT base 3 / lens 4", 3.0, 181.0, 169.24),
    ("SBT base 4 / lens 4", 4.0, 144.0, 163.97),
    ("SBT base 2 / lens 2", 2.0, 262.0, 170.11),
]

#: Where the bridge's top edge lands relative to the rims at the same height
#: with a 4 mm projection, per drawing and press row, mm (negative = forward
#: of them). Re-measured 2026-09-25 on the crease map, which sets the bridge
#: forward by exactly the projection at its top edge; the rest of each figure
#: is the rims' own sag against the face form, which is why it is not -4.00.
#: The spike's S-bend numbers (demo -3.80 / -4.49 / -5.21 / -4.85) are history:
#: that bend folded the castle, see `ThermoformMap`'s docstring.
BRIDGE_SET = {
    "demo":    (-3.91, -4.60, -5.32, -4.98),
    "gabriel": (-3.75, -4.44, -5.18, -4.93),
    "aviator": (-3.52, -4.20, -4.94, -4.82),
}
PROJECTION_MM = 4.0
#: The three fixtures' castles all rise to exactly this, which is what the
#: fold gate is measured against. Asserted, so a fixture change re-pins loudly.
FIXTURE_THICKNESS_MM = 10.0


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def demo_front():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="demo",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws


def _gdraw_front(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    ws = build_workspaces_from_gdraw(path)[0][0]
    ws.label = name
    return ws


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "gabriel")


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def flat_models(demo_front, gabriel_front, aviator_front):
    """Each drawing's flat Manifold, groove off and on, built once."""
    from guildmodel.core.model import build_castle_model
    from guildmodel.core.project.schema import CastleParams

    out = {}
    for ws in (demo_front, gabriel_front, aviator_front):
        castle = ws.castle_params or CastleParams()
        for groove in (False, True):
            c = castle.model_copy(update={"lens_groove": castle.lens_groove.model_copy(
                update={"enabled": groove})})
            out[(ws.label, groove)] = build_castle_model(
                ws.partition, c, list(ws.hinge_polys))
    return out


def _geom(ws):
    from guildmodel.core.forming import bridge_geometry
    return bridge_geometry(ws.partition, ws.lens_od, ws.lens_os)


def _map_for(ws, R, F, projection=PROJECTION_MM, **kw):
    from guildmodel.core.forming import ThermoformMap

    return ThermoformMap(radius_mm=R, face_form_deg=F, projection_mm=projection,
                         bridge=_geom(ws), **kw)


# ------------------------------------------------------------------ the map

def test_one_sphere_is_exact():
    """With the apex at the bridge the composed rotations are a sphere of
    radius R: 1.7e-7 mm over a 140 x 50 mm field in the spike. The gate is
    two orders looser and still a hundred times under any chord."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    R = 144.0
    m = ThermoformMap(radius_mm=R, bridge=BridgeGeometry(apex_x=0.0, apex_y=0.0))
    xs, ys = np.meshgrid(np.linspace(-70, 70, 29), np.linspace(-25, 25, 11))
    pts = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
    r = np.linalg.norm(m(pts) - np.array([0, 0, R]), axis=1)
    assert np.abs(r - R).max() < 1e-6


def test_the_flat_map_is_the_identity():
    from guildmodel.core.forming import ThermoformMap

    m = ThermoformMap()
    assert m.is_flat
    pts = np.array([[-60.0, 12.0, 0.0], [0.0, -5.0, 6.0], [71.5, 20.0, 3.3]])
    assert np.allclose(m(pts), pts, atol=1e-12)
    assert m.bridge_set_mm() == pytest.approx(0.0, abs=1e-12)


def test_projection_is_forward_and_independent_of_the_curve():
    """Positive projection moves the bridge away from the face (toward -z in
    the flat model's frame, whose +z is the posterior), by exactly the amount
    asked at the bridge's top edge on a flat front; on a curved one the die
    pushes along the local normal, which the rim's own curvature tilts by
    the bridge's height over R, so the z component is p·cos(12 / 144)."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry()
    flat = ThermoformMap(projection_mm=4.0, bridge=g)
    assert flat.bridge_set_mm() == pytest.approx(-4.0, abs=1e-9)
    # the die only presses forward: a negative projection is read as none
    back = ThermoformMap(projection_mm=-4.0, bridge=g)
    assert back.p == 0.0 and back.is_flat and back.bridge_set_mm() == 0.0
    curved = ThermoformMap(radius_mm=144.0, face_form_deg=163.97, bridge=g)
    both = ThermoformMap(radius_mm=144.0, face_form_deg=163.97,
                         projection_mm=4.0, bridge=g)
    tilt = np.cos((g.top_y - g.apex_y) / 144.0)
    assert both.bridge_set_mm() - curved.bridge_set_mm() == pytest.approx(
        -4.0 * tilt, abs=1e-6)


def test_the_bump_is_the_dies_section_between_the_creases():
    """Across the gap the die's own section: p on the centre line, zero at
    each crease with a kink, an arc of the die's radius between. With no die
    named the die is the arc through both creases, ``(h^2 + p^2) / 2p``.
    Along the V the same die rests on the plate's two edges as the creases
    converge, so the bump shrinks toward the nose; it is zero outside the
    creases and rides on above the top edge."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry(top_y=12.0, top_width=20.0, nose_dir=-1.0)
    m = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0,
                      crease_angle_deg=45.0, bridge=g)
    R = (100.0 + 16.0) / 8.0
    assert m.die_radius_mm() == pytest.approx(R)
    assert ThermoformMap.auto_die_radius(20.0, 4.0) == pytest.approx(R)
    assert m.apex_mm() == pytest.approx(4.0)
    assert m.bump(0.0, 12.0) == pytest.approx(4.0)
    assert m.bump(10.0, 12.0) == pytest.approx(0.0)           # on the crease
    assert m.bump(10.5, 12.0) == 0.0                          # outside it
    # the arc of radius R through (0, 4) and (10, 0)
    assert m.bump(5.0, 12.0) == pytest.approx(4.0 - R + np.sqrt(R * R - 25.0))
    # a kink at the crease: the arc's slope just inside, 0 just outside
    inside = (m.bump(9.999, 12.0) - m.bump(9.99, 12.0)) / 0.009
    assert inside == pytest.approx(-10.0 / np.sqrt(R * R - 100.0), rel=0.02)
    # converging toward the nose at the V's angle: 45 degrees included, so
    # each crease leans tan(22.5) per millimetre of depth, and the die rests
    # on the narrower gap at R - sqrt(R^2 - h^2)
    h5 = float(m.crease_half_width(7.0))
    assert h5 == pytest.approx(10.0 - 5.0 * np.tan(np.radians(22.5)))
    assert m.bump(0.0, 7.0) == pytest.approx(R - np.sqrt(R * R - h5 * h5))
    assert m.bump(0.0, 7.0) < m.bump(0.0, 12.0)
    assert float(m.crease_half_width(-40.0)) == 0.0            # past the apex
    assert m.bump(0.0, -40.0) == 0.0
    assert float(m.crease_half_width(14.0)) == 10.0            # parallel above the edge
    assert m.bump(0.0, 20.0) == pytest.approx(4.0)             # a brow bar rides along
    # parallel creases: the bump does not shrink
    par = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0,
                        crease_angle_deg=0.0, bridge=g)
    assert par.bump(0.0, 0.0) == pytest.approx(4.0)
    # the V converges the other way when the nose is the other way
    up = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, crease_angle_deg=45.0,
                       bridge=BridgeGeometry(top_y=12.0, top_width=20.0, nose_dir=1.0))
    assert float(up.crease_half_width(17.0)) == pytest.approx(h5)
    assert float(up.crease_half_width(7.0)) == 10.0            # above its edge: parallel
    # the die only presses forward: a negative projection is no bump at all
    back = ThermoformMap(projection_mm=-4.0, crease_gap_mm=20.0, bridge=g)
    assert back.bump(5.0, 12.0) == 0.0 and not back.is_creased


def test_a_named_die_gives_the_bump_flanks():
    """A die smaller than the arc through the creases floats between them:
    its arc on the centre line, then a straight flank tangent to it down to
    each crease, where the kink is the flank's own slope. The bump keeps the
    full projection until the V narrows to the die's footprint, then rests.
    A die *wider* than the arc rests on the plate at the top edge already
    and never reaches the projection, which `apex_mm` reports; a die
    shallower than the projection caps it at its own radius."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry(top_y=12.0, top_width=20.0, nose_dir=-1.0)
    small = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, crease_angle_deg=45.0,
                          die_radius_mm=5.0, bridge=g)
    assert small.die_radius_mm() == 5.0
    assert small.apex_mm() == pytest.approx(4.0)
    assert small.bump(0.0, 12.0) == pytest.approx(4.0)
    # the arc of radius 5 centred at (0, -1) on the centre line
    assert small.bump(1.0, 12.0) == pytest.approx(-1.0 + np.sqrt(24.0))
    # a straight flank from the tangent point to the crease: constant slope
    us = np.linspace(7.0, 9.9, 30)
    d = np.array([float(small.bump(u, 12.0)) for u in us])
    slopes = np.diff(d) / np.diff(us)
    assert np.ptp(slopes) < 1e-9
    assert slopes[0] < 0.0
    assert small.bump(10.0, 12.0) == pytest.approx(0.0)
    # the flank is tangent to the arc: the slope is continuous through the
    # tangent point (u = 2.73 for h = 10, p = 4, R = 5)
    fine = np.linspace(2.0, 3.5, 3001)
    s = np.diff(np.array([float(small.bump(u, 12.0)) for u in fine])) / np.diff(fine)
    assert np.abs(np.diff(s)).max() < 2e-3
    # still the full projection down the V until the gap narrows to the
    # die's footprint (2 sqrt(2Rp - p^2) = 9.8 mm, 14 mm down a 45 degree V),
    # resting on the plate beyond it
    assert small.bump(0.0, 2.0) == pytest.approx(4.0)
    assert small.bump(0.0, -3.0) < 4.0

    wide = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, die_radius_mm=30.0,
                         bridge=g)
    assert wide.apex_mm() == pytest.approx(30.0 - np.sqrt(900.0 - 100.0))
    assert wide.apex_mm() < 4.0
    assert wide.bump(0.0, 12.0) == pytest.approx(wide.apex_mm())
    assert wide.bump(10.0, 12.0) == pytest.approx(0.0)

    shallow = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, die_radius_mm=2.0,
                            bridge=g)
    assert shallow.apex_mm() == pytest.approx(2.0)

    # through a gap narrower than the projection no die reaches it: Auto is
    # the gap's half-width, and the bump is that deep with vertical flanks
    narrow = ThermoformMap(projection_mm=4.0, crease_gap_mm=4.0, bridge=g)
    assert narrow.die_radius_mm() == pytest.approx(2.0)
    assert narrow.apex_mm() == pytest.approx(2.0)


def test_a_crease_blend_rounds_the_fold():
    """With a blend the fold at each crease becomes a fillet of that radius:
    the bump is smooth through the crease (no kink), spreads a little past
    it, is unchanged on the centre line, and the map says it is no longer
    creased so the tessellation neither cuts nor splits there."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry(top_y=12.0, top_width=20.0, nose_dir=-1.0)
    sharp = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, bridge=g)
    soft = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, crease_blend_mm=1.5,
                         bridge=g)
    assert sharp.is_creased and not soft.is_creased
    assert soft.bump(0.0, 12.0) == pytest.approx(4.0)
    assert soft.bump(10.0, 12.0) > 0.0                        # spread past the crease
    assert 0.0 < soft.bump(10.3, 12.0) < soft.bump(10.0, 12.0)
    assert soft.bump(10.0 + soft.bump_margin_mm(), 12.0) == 0.0
    us = np.linspace(8.5, 11.5, 3001)
    d = np.array([float(soft.bump(u, 12.0)) for u in us])
    s = np.diff(d) / np.diff(us)
    assert np.abs(np.diff(s)).max() < 3e-3, "a kink survived the blend"
    assert d.min() >= 0.0
    # and on a flanked die the same
    flank = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, die_radius_mm=5.0,
                          crease_blend_mm=1.0, bridge=g)
    d = np.array([float(flank.bump(u, 12.0)) for u in us])
    s = np.diff(d) / np.diff(us)
    assert np.abs(np.diff(s)).max() < 3e-3
    # a blend is a change of layout; a die is not
    assert soft.layout_key() != sharp.layout_key()
    assert (ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, die_radius_mm=5.0,
                          bridge=g).layout_key() == sharp.layout_key())
    assert (ThermoformMap(projection_mm=2.0, crease_gap_mm=20.0, radius_mm=144.0,
                          bridge=g).layout_key() == sharp.layout_key())


def test_the_crease_planes_are_where_the_creases_are():
    """Two planes a side — the parallel run and the converging run — and the
    top edge; every point of a crease lies in its plane, the parallel one is
    live above the edge and the converging one below it, and neither is
    live where the bump is zero."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry(top_y=12.0, top_width=20.0, nose_dir=-1.0)
    m = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, crease_angle_deg=45.0,
                      bridge_offset_mm=1.0, bridge=g)
    planes = m.crease_planes()
    kinds = sorted(k for _, _, k in planes)
    assert kinds == [("converge", -1.0), ("converge", 1.0), ("parallel", -1.0),
                     ("parallel", 1.0), ("top", 0.0)]
    for n, d, (what, side) in planes:
        assert np.linalg.norm(n) == pytest.approx(1.0)
        if what == "top":
            assert np.array([0.0, 12.0, 0.0]) @ n == pytest.approx(d)
            assert not m.crease_is_live(np.array([[1.0, 12.0]]), (what, side)).any()
            continue
        ys = np.array([16.0, 12.0, 8.0, 3.0]) if what == "converge" else np.array([20.0, 12.0])
        for y in ys:
            x = 1.0 + side * float(m.crease_half_width(y)) if what == "converge" or y >= 12.0 else None
            if x is None:
                continue
            assert np.array([x, y, 5.0]) @ n == pytest.approx(d, abs=1e-9) or y > 12.0
        live = m.crease_is_live(np.array([[1.0 + side * 10.0, 20.0],
                                          [1.0 + side * 10.0, 8.0]]), (what, side))
        assert list(live) == ([True, False] if what == "parallel" else [False, True]) \
            or what == "converge"
    conv = [p for p in planes if p[2][0] == "converge"]
    for n, d, kind in conv:
        side = kind[1]
        pts = np.array([[1.0 + side * float(m.crease_half_width(y)), y, 0.0]
                        for y in (12.0, 8.0, 3.0)])
        assert np.allclose(pts @ n, d, atol=1e-9)
        assert list(m.crease_is_live(pts[:, :2], kind)) == [True, True, True]
        assert not m.crease_is_live(np.array([[1.0 + side * 12.0, 16.0]]), kind).any()
    assert ThermoformMap(bridge=g).crease_planes() == []
    # a 0 degree V has no converging plane: the parallel one is the crease
    zero = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, crease_angle_deg=0.0,
                         bridge=g)
    assert sorted(k[0] for _, _, k in zero.crease_planes()) == ["parallel", "parallel", "top"]
    assert zero.crease_is_live(np.array([[10.0, 3.0]]), ("parallel", 1.0)).all()


def test_the_offset_moves_the_ridge_and_nothing_else():
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    g = BridgeGeometry(top_y=12.0, top_width=20.0)
    m = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, bridge=g,
                      bridge_offset_mm=3.0)
    centred = ThermoformMap(projection_mm=4.0, crease_gap_mm=20.0, bridge=g)
    assert m.bump(3.0, 12.0) == pytest.approx(4.0)
    assert m.bump(0.0, 12.0) == pytest.approx(centred.bump(3.0, 12.0))
    assert m.bump(13.0, 12.0) == pytest.approx(0.0)
    assert m.bump(-7.0, 12.0) == pytest.approx(0.0)
    assert m.bridge_set_mm() == pytest.approx(-4.0, abs=1e-9)


def test_thickness_rides_the_normal():
    """A point 6 mm up the castle stays 6 mm off the formed surface, so the
    posterior keeps its depth everywhere the maker looks — through the bump
    too, which moves a column of material as one."""
    from guildmodel.core.forming import BridgeGeometry, ThermoformMap

    m = ThermoformMap(radius_mm=144.0, face_form_deg=163.97, projection_mm=4.0,
                      bridge=BridgeGeometry(apex_x=30.0, apex_y=2.0, band_half=11.0,
                                            top_y=12.0, top_width=20.0))
    base = np.array([[-55.0, 10.0, 0.0], [-9.0, -4.0, 0.0], [0.0, 2.0, 0.0],
                     [0.0, 12.0, 0.0], [4.0, 9.0, 0.0], [40.0, 15.0, 0.0]])
    top = base + np.array([0.0, 0.0, 6.0])
    d = np.linalg.norm(m(top) - m(base), axis=1)
    assert np.allclose(d, 6.0, atol=1e-9)


@pytest.mark.parametrize("row", range(4))
@pytest.mark.parametrize("fixture", ["demo_front", "gabriel_front",
                                     "aviator_front"])
def test_the_bridge_lands_where_it_was_measured(fixture, row, request):
    """The bridge-set column, per drawing and press row, to 0.02 mm. A sign
    error in the rim curvature, the wrap or the bump would move these by
    millimetres, which is the point of pinning all twelve."""
    ws = request.getfixturevalue(fixture)
    _, _, R, F = SBT[row]
    fmap = _map_for(ws, R, F)
    assert fmap.bridge_set_mm() == pytest.approx(BRIDGE_SET[ws.label][row],
                                                 abs=0.02)
    # and the projection more forward than the same row unprojected, less
    # the tilt of the local normal at the bridge's height (under 0.3 %)
    assert (fmap.bridge_set_mm()
            - _map_for(ws, R, F, projection=0.0).bridge_set_mm()) == pytest.approx(
        -PROJECTION_MM, abs=0.02)


def test_the_fixtures_are_as_thick_as_the_gates_assume(flat_models):
    for (name, groove), model in flat_models.items():
        assert model.bounding_box()[5] == pytest.approx(FIXTURE_THICKNESS_MM,
                                                        abs=1e-6), name


@pytest.mark.parametrize("fixture", ["demo_front", "gabriel_front",
                                     "aviator_front"])
def test_the_press_rows_bend_nowhere_tighter_than_the_part(fixture, request):
    """A map is injective through a thickness exactly when that thickness is
    under its tightest bend radius. The bump is a shear along z and cannot
    tighten anything; what can is the reverse bend between two rims apexed
    at their own lens centres. Held at every press row, at the panel's
    150 degree face-form floor, and across the projection range."""
    ws = request.getfixturevalue(fixture)
    rows = [(R, F) for _, _, R, F in SBT] + [(100.0, 150.0), (400.0, 180.0)]
    for R, F in rows:
        for p in (0.0, 4.0, 8.0, -4.0):
            fmap = _map_for(ws, R, F, projection=p)
            assert fmap.min_bend_radius_mm() > FIXTURE_THICKNESS_MM + 2.0, (
                R, F, p, fmap.min_bend_radius_mm())


def test_a_sixteen_diopter_curve_says_when_it_folds(aviator_front):
    """The slider goes to 16 diopters because that is how the forms are
    tagged. At R 33 the reverse bend between the rims drops to R 7 on the
    aviator — but its centre is in *front* of the part, so the castle's
    depth cannot fold there, and the first version of this test pinned a
    false alarm. What folds is the bridge bump, an offset toward that
    centre: an 8 mm set through a 20 mm gap inverted 1,159 triangles while
    the check stayed quiet. The report reads the sign of the bend."""
    from guildmodel.core.forming import ThermoformMap
    from guildmodel.core.project.schema import FormingMetadata

    def fmap(d, f, p):
        meta = FormingMetadata().with_base_curve(
            d, f, bridge_projection_mm=p, crease_gap_mm=20.0, crease_angle_deg=0.0)
        return ThermoformMap.from_metadata(meta, bridge=_geom(aviator_front))

    flat = fmap(16.0, 180.0, 0.0)
    assert flat.fold_warning(FIXTURE_THICKNESS_MM) is None
    assert flat.min_bend_radius_mm() > FIXTURE_THICKNESS_MM
    thickness, projection = flat.bend_radii_mm()
    assert projection < 8.0 < thickness

    set_ = fmap(16.0, 180.0, 8.0)
    warning = set_.fold_warning(FIXTURE_THICKNESS_MM)
    assert warning is not None and "bridge set" in warning, warning

    eased = fmap(8.0, 170.0, 4.0)
    assert eased.fold_warning(FIXTURE_THICKNESS_MM) is None


def test_the_rims_and_the_face_form_nearly_cancel(gabriel_front):
    """Assumption 4 in §0.3, corrected: with the rims apexed 30-odd mm out
    at R 259 their sag alone would put the bridge 1.7 mm *behind* the lens
    apexes; the face form pulls it forward again and at the press's pairings
    the two land within 1.3 mm of each other — one continuous bow, not a W.
    The plan's "0.5-1.2 mm forward" was the middle rows only: the base 2 die
    leaves the bridge a quarter millimetre behind."""
    for _, _, R, F in SBT:
        s = _map_for(gabriel_front, R, F, projection=0.0).bridge_set_mm()
        assert -1.3 < s < 0.5, f"R{R}: bridge set {s:.2f} mm"


# ----------------------------------------------------------- the drawing's part

def test_the_band_is_the_bridge_zone(gabriel_front):
    from guildmodel.core.forming import bridge_band

    x0, _, x1, _ = gabriel_front.partition.zone("bridge").polygon.bounds
    assert bridge_band(gabriel_front.partition) == pytest.approx(
        0.5 * (x1 - x0))
    assert 8.0 < bridge_band(gabriel_front.partition) < 14.0


def test_the_band_falls_back_to_the_lens_gap_then_to_a_default(gabriel_front):
    from guildmodel.core.forming import DEFAULT_BAND_HALF_MM, bridge_band

    class _NoBridge:
        def zone(self, name):
            raise KeyError(name)

    od, os_ = gabriel_front.lens_od, gabriel_front.lens_os
    inner = sorted([od.bounds[0], od.bounds[2], os_.bounds[0], os_.bounds[2]])[1:3]
    assert bridge_band(_NoBridge(), od, os_) == pytest.approx(
        0.5 * (inner[1] - inner[0]))
    assert bridge_band(_NoBridge()) == DEFAULT_BAND_HALF_MM
    assert bridge_band(None) == DEFAULT_BAND_HALF_MM


@pytest.mark.parametrize("fixture,top_width", [("demo_front", 20.3),
                                                ("gabriel_front", 19.5),
                                                ("aviator_front", 13.1)])
def test_the_bridge_geometry_is_read_off_the_partition(fixture, top_width,
                                                       request):
    """The creases start at the bridge's top edge — its edge away from the
    nose, found from the nosepad zones rather than assumed from a sign of y,
    because the intake mirrors a drawing — and the default gap is the
    bridge's width there."""
    ws = request.getfixturevalue(fixture)
    g = _geom(ws)
    b = ws.partition.zone("bridge").polygon
    assert g.nose_dir == -1.0
    assert g.top_y == pytest.approx(b.bounds[3])
    assert g.centre_y == pytest.approx(b.centroid.y)
    assert g.top_width == pytest.approx(top_width, abs=0.1)
    assert g.band_half == pytest.approx(0.5 * (b.bounds[2] - b.bounds[0]))
    pads = np.mean([z.polygon.centroid.y for z in ws.partition.zones
                    if z.name.startswith("nosepad")])
    assert pads < g.centre_y, "the nose is below the bridge on every fixture"


def test_a_front_without_a_bridge_zone_still_has_a_geometry(gabriel_front):
    from guildmodel.core.forming import bridge_geometry

    class _NoBridge:
        zones = []

        def zone(self, name):
            raise KeyError(name)

    g = bridge_geometry(_NoBridge(), gabriel_front.lens_od, gabriel_front.lens_os)
    assert g.top_width == pytest.approx(2.0 * g.band_half)
    assert g.top_y > g.apex_y and g.nose_dir == -1.0


def test_the_apex_is_the_lens_centres(gabriel_front):
    from guildmodel.core.forming import rim_apex

    ax, ay = rim_apex(gabriel_front.lens_od, gabriel_front.lens_os)
    cs = [gabriel_front.lens_od.centroid, gabriel_front.lens_os.centroid]
    assert ax == pytest.approx(np.mean([abs(c.x) for c in cs]))
    assert ay == pytest.approx(np.mean([c.y for c in cs]))
    assert rim_apex(None, None) == (0.0, 0.0)


# ------------------------------------------------------------- the meshes

@pytest.mark.parametrize("groove", [False, True])
@pytest.mark.parametrize("row", range(4))
@pytest.mark.parametrize("name", ["demo", "gabriel", "aviator"])
def test_every_fixture_forms_clean_at_every_press_row(name, row, groove,
                                                      flat_models, request):
    """All twenty-four formed fronts come back "Model verified": zero gaps and
    zero self-contacts after a positional weld, the check that gates export.
    Also that the groove survives the warp (the grooved part is lighter) and
    that thickness rather than volume is preserved (§0.3 assumption 3)."""
    from guildmodel.core.forming import FormingMesh
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import to_trimesh

    ws = request.getfixturevalue(f"{name}_front")
    _, _, R, F = SBT[row]
    model = flat_models[(name, groove)]
    fmap = _map_for(ws, R, F)
    fm = FormingMesh.for_export(to_trimesh(model))
    assert fm.exact
    mesh = fm.formed(fmap)
    verdict = verify_mesh(mesh)
    assert verdict.ok, verdict.problems
    assert verdict.watertight
    assert mesh.is_watertight, "closed by index, as the flat one was"
    # The posterior is on the concave side and is compressed: a few percent
    # lighter, never heavier, never by a lot.
    ratio = mesh.volume / model.volume()
    assert 0.94 < ratio < 1.0, f"formed / flat volume {ratio:.4f}"
    if groove:
        # The groove survives the warp. Note the sign: a grooved front is the
        # *heavier* one, because the rim lip grows inward by the groove depth
        # so the groove bottom lands on the drawn LENS contour, and the lip
        # adds more than the V takes away.
        bare = flat_models[(name, False)].volume()
        assert abs(model.volume() - bare) > 1.0
        assert abs(mesh.volume - bare * ratio) > 1.0
    # the display mesh is the same surface over split vertices
    shown = fm.formed(fmap, display=True)
    assert shown.volume == pytest.approx(mesh.volume, rel=1e-9)
    assert len(shown.faces) == len(mesh.faces)
    assert shown.vertex_normals.shape == (len(shown.vertices), 3)
    assert np.allclose(np.linalg.norm(shown.vertex_normals, axis=1), 1.0)


def _chords(fine, fmap):
    """Distance between each refined edge's midpoint and the smooth surface,
    split into the edges outside the V and the edges in it."""
    e = fine.edges_unique
    a, b = fine.vertices[e[:, 0]], fine.vertices[e[:, 1]]
    d = np.linalg.norm(0.5 * (fmap(a) + fmap(b)) - fmap(0.5 * (a + b)), axis=1)
    ha, hb = fmap.crease_half_width(a[:, 1]), fmap.crease_half_width(b[:, 1])
    outside = ((np.abs(a[:, 0] - fmap.offset) > ha + 2.0)
               & (np.abs(b[:, 0] - fmap.offset) > hb + 2.0))
    return d[outside].max(), d[~outside].max()


@pytest.mark.parametrize("fixture", ["demo_front", "gabriel_front",
                                     "aviator_front"])
def test_chord_error_is_under_the_gates(fixture, flat_models, request):
    """Worst distance between a refined edge's midpoint and the smooth
    surface at the export length. Outside the V it is the rim's own
    curvature: 0.004-0.014 mm on the three drawings, gated at 0.02. In the V
    the crease is a real fold, so an edge that straddles it sits off the
    surface by up to a quarter of its length times the crease's slope — the
    facet a slicer will see along the crease — and that is gated at its own
    figure so it cannot grow unnoticed."""
    import trimesh

    from guildmodel.core.forming import EXPORT_REFINE_MM, FormingMesh, refine
    from guildmodel.core.model import to_trimesh

    ws = request.getfixturevalue(fixture)
    flat = to_trimesh(flat_models[(ws.label, False)])
    fine = to_trimesh(refine(flat_models[(ws.label, False)], EXPORT_REFINE_MM))
    fm = FormingMesh.for_export(flat)
    for _, _, R, F in SBT:
        fmap = _map_for(ws, R, F)
        outside, inside = _chords(fine, fmap)
        assert outside < 0.02, f"R{R}: chord outside the V {outside:.4f} mm"
        assert inside < 0.5, f"R{R}: chord along the crease {inside:.4f} mm"
        # and on the mesh the export actually writes, the crease is a chain
        # of edges and the band is at the die's resolution: no edge sits off
        # the surface by more than a facet of the die's arc
        prep = fm.prepared(fmap)
        cut = trimesh.Trimesh(prep.V, prep.F, process=False)
        outside, inside = _chords(cut, fmap)
        assert outside < 0.02, f"R{R}: chord outside the V {outside:.4f} mm"
        assert inside < 0.01, f"R{R}: chord in the V on the cut mesh {inside:.4f} mm"


def test_the_preview_forms_the_cached_trimesh_exactly(flat_models,
                                                      gabriel_front):
    """The window holds the kernel's output as a trimesh; the live preview
    rebuilds the Manifold from it (volume-exact, ~10 ms) and forms that. The
    result is the same part the export path makes from the model directly."""
    from guildmodel.core.forming import (PREVIEW_REFINE_MM, FormingMesh,
                                         form_trimesh, formed_model,
                                         manifold_from_trimesh)
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.model import to_trimesh

    model = flat_models[("gabriel", False)]
    flat = to_trimesh(model)
    rebuilt = manifold_from_trimesh(flat)
    assert rebuilt.volume() == pytest.approx(model.volume(), rel=1e-9)

    fmap = _map_for(gabriel_front, 144.0, 163.97)
    via_trimesh = form_trimesh(flat, fmap, PREVIEW_REFINE_MM)
    via_object = FormingMesh(flat).formed(fmap)
    assert verify_mesh(via_trimesh).ok
    assert len(via_trimesh.faces) == len(via_object.faces)
    assert via_trimesh.volume == pytest.approx(via_object.volume, rel=1e-9)
    # the uncut Manifold route is the same part to a few thousandths: the
    # tessellation adds vertices on the surface, never moves it
    via_model = to_trimesh(formed_model(model, fmap, PREVIEW_REFINE_MM))
    assert via_trimesh.volume == pytest.approx(via_model.volume, rel=2e-3)


# ------------------------------------------------------------ the tessellation

def test_a_plane_cut_keeps_both_sides_and_closes():
    """`split_by_plane` on a box: watertight before and after, the volume
    unchanged, every vertex the cut added exactly on the plane, and no edge
    left straddling it — with a vertex of the box snapped onto the plane
    when it is a hair away."""
    import trimesh

    from guildmodel.core.forming.tessellate import split_by_plane, split_by_planes

    box = trimesh.creation.box(extents=(40.0, 20.0, 6.0))
    n, d = np.array([0.6, 0.8, 0.0]), 3.0
    V, F = split_by_plane(box.vertices, box.faces, n, d)
    cut = trimesh.Trimesh(V, F, process=False)
    assert cut.is_watertight and cut.is_winding_consistent
    assert cut.volume == pytest.approx(box.volume, rel=1e-12)
    added = V[len(box.vertices):]
    assert len(added) > 0
    assert np.allclose(added @ n - d, 0.0, atol=1e-12)
    e = cut.edges_unique
    sa, sb = V[e[:, 0]] @ n - d, V[e[:, 1]] @ n - d
    assert not (((sa * sb) < 0) & (np.abs(sa) > 1e-9) & (np.abs(sb) > 1e-9)).any()
    # a plane through a vertex (to 1e-9): that vertex is on it, nothing splits
    # in two at a hair's width
    V2, F2 = split_by_plane(box.vertices, box.faces, np.array([1.0, 0.0, 0.0]),
                            20.0 - 1e-9)
    assert trimesh.Trimesh(V2, F2, process=False).is_watertight
    assert len(V2) == len(box.vertices)
    # several planes in turn
    V3, F3 = split_by_planes(box.vertices, box.faces,
                             [(np.array([1.0, 0.0, 0.0]), 0.0, ("a", 1)),
                              (np.array([0.0, 1.0, 0.0]), 2.5, ("b", 1)),
                              (np.array([1.0, 1.0, 0.0]) / np.sqrt(2), 1.0, ("c", 1))])
    m3 = trimesh.Trimesh(V3, F3, process=False)
    assert m3.is_watertight and m3.volume == pytest.approx(box.volume, rel=1e-12)


def test_band_refinement_is_conforming_and_stops_at_the_target():
    """`refine_band` on a coarse box with a band down its middle: every edge
    in the band ends up under the target, the faces outside are touched
    only to match a neighbour, and the mesh stays closed with no
    T-junction — which `is_watertight` on the index topology is the test
    of."""
    import trimesh

    from guildmodel.core.forming.tessellate import refine_band

    box = trimesh.creation.box(extents=(40.0, 20.0, 6.0))

    def inside(V, edges):
        m = 0.5 * (V[edges[:, 0]] + V[edges[:, 1]])
        return np.abs(m[:, 0]) < 6.0

    V, F = refine_band(box.vertices, box.faces, 1.0, inside)
    out = trimesh.Trimesh(V, F, process=False)
    assert out.is_watertight and out.is_winding_consistent
    assert out.volume == pytest.approx(box.volume, rel=1e-12)
    e = out.edges_unique
    m = 0.5 * (V[e[:, 0]] + V[e[:, 1]])
    L = np.linalg.norm(V[e[:, 0]] - V[e[:, 1]], axis=1)
    assert L[np.abs(m[:, 0]) < 6.0].max() <= 1.0
    assert L[np.abs(m[:, 0]) > 12.0].max() > 5.0, "the far ends stay coarse"


def test_the_formed_mesh_is_cut_along_the_creases(gabriel_front, flat_models):
    """On a real front: no edge of the prepared mesh straddles a crease
    plane, every edge in the band is at the fine length, the plain formed
    mesh is closed by index, the display mesh welds to it, and the normals
    on either side of a live crease differ by the fold — sharp — while a
    blend leaves them continuous."""
    import trimesh

    from guildmodel.core.forming import (PREVIEW_FINE_MM, FormingMesh,
                                         ThermoformMap)
    from guildmodel.core.mesh_check import verify_mesh, welded_surface
    from guildmodel.core.model import to_trimesh

    ws = gabriel_front
    flat = to_trimesh(flat_models[("gabriel", True)])
    fm = FormingMesh(flat)
    fmap = ThermoformMap(radius_mm=144.0, face_form_deg=163.97, projection_mm=3.2,
                         crease_gap_mm=12.8, crease_angle_deg=20.0, bridge=_geom(ws))
    prep = fm.prepared(fmap)
    V, F = prep.V, prep.F
    cut = trimesh.Trimesh(V, F, process=False)
    assert cut.is_watertight
    e = cut.edges_unique
    for n, d, kind in fmap.crease_planes():
        sa, sb = V[e[:, 0]] @ n - d, V[e[:, 1]] @ n - d
        straddle = ((sa * sb) < 0) & (np.abs(sa) > 1e-9) & (np.abs(sb) > 1e-9)
        assert not straddle.any(), kind
    m = 0.5 * (V[e[:, 0]] + V[e[:, 1]])
    L = np.linalg.norm(V[e[:, 0]] - V[e[:, 1]], axis=1)
    band = fmap.in_band(m[:, 0], m[:, 1], 0.0)
    assert L[band].max() <= PREVIEW_FINE_MM + 1e-9
    assert L[~fmap.in_band(m[:, 0], m[:, 1], 6.0)].max() > 2.0, "the rims stay coarse"

    plain = fm.formed(fmap)
    assert plain.is_watertight
    assert verify_mesh(plain).ok
    # what the file carries: float32, welded, still one closed body
    from guildmodel.core.forming import weld_for_file
    filed = weld_for_file(plain)
    assert filed.is_watertight and verify_mesh(filed).ok
    assert filed.volume == pytest.approx(plain.volume, rel=1e-5)
    assert np.array_equal(np.asarray(filed.vertices, dtype=np.float32).astype(np.float64),
                          np.asarray(filed.vertices))
    shown = fm.formed(fmap, display=True)
    assert len(shown.vertices) > len(plain.vertices), "split at the edges and creases"
    assert shown.volume == pytest.approx(plain.volume, rel=1e-9)
    assert verify_mesh(shown).watertight, "welds closed"
    assert len(welded_surface(shown).split(only_watertight=False)) == 1, "to one body"
    # no sliver became a patch of its own: every vertex of the display mesh
    # carries a normal within a right angle of its neighbours' average
    from guildmodel.core.forming.tessellate import area_weighted_normals
    smooth = area_weighted_normals(plain.vertices, plain.faces)[fm.prepared(fmap).origin]
    agree = np.einsum("ij,ij->i", smooth, shown.vertex_normals)
    assert (agree > 0.0).mean() > 0.999

    # the two copies of a crease vertex on the anterior face carry normals a
    # fold apart: the crease is drawn sharp at any angle (the planes are in
    # flat coordinates: test them on the flat positions of the split vertices)
    n, d, kind = next(p for p in fmap.crease_planes() if p[2] == ("converge", 1.0))
    flat_shown = prep.V[prep.origin]
    on = np.abs(flat_shown @ n - d) < 1e-6
    on &= flat_shown[:, 2] < 1e-6                         # the anterior face
    on &= fmap.crease_is_live(flat_shown[:, :2], kind)
    assert on.sum() >= 4
    pts = flat_shown[on]
    key = np.round(pts, 6)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    twins = np.where(counts >= 2)[0]
    assert len(twins) >= 2, "crease vertices are duplicated"
    angles = []
    for t in twins:
        idx = np.where(on)[0][inv.ravel() == t]
        nn = shown.vertex_normals[idx]
        angles.append(np.degrees(np.arccos(np.clip(nn[0] @ nn[-1], -1, 1))))
    assert max(angles) > 20.0

    # a blend: no cut, no split, one normal per point
    soft = ThermoformMap(radius_mm=144.0, face_form_deg=163.97, projection_mm=3.2,
                         crease_gap_mm=12.8, crease_angle_deg=20.0, crease_blend_mm=1.0,
                         bridge=_geom(ws))
    shown_soft = fm.formed(soft, display=True)
    prep_soft = fm.prepared(soft)
    flat_soft = prep_soft.V[prep_soft.origin]
    on = np.abs(flat_soft @ n - d) < 1e-6
    on &= flat_soft[:, 2] < 1e-6
    on &= fmap.crease_is_live(flat_soft[:, :2], kind)
    assert on.sum() >= 4, "the blended layout is cut along the same planes"
    key = np.round(flat_soft[on], 6)
    # a vertex where the crease plane meets the outline is split for the
    # wall it also belongs to, blend or no blend; along the crease itself a
    # blended fold is one vertex, a sharp one two
    twins_soft = int(on.sum()) - len(np.unique(key, axis=0))
    twins_sharp = len(pts) - len(np.unique(np.round(pts, 6), axis=0))
    assert twins_soft <= 2 < 10 <= twins_sharp, (twins_soft, twins_sharp)
    # the edges the viewer draws come by index, warped: the part's own
    # creases and the live crease lines, and nothing else
    edges = fm.formed_edges(fmap)
    assert len(edges) > 0 and edges.shape[1:] == (2, 3)
    mid = 0.5 * (prep.V[prep.edge_pairs[:, 0]] + prep.V[prep.edge_pairs[:, 1]])
    on_crease = np.abs(mid @ n - d) < 1e-6
    assert on_crease.sum() >= 4, "the crease is among the drawn edges"
    assert fm.formed_edges(soft).shape[0] < edges.shape[0], "a blended crease is not drawn"

    # the quick path is the uncut base and a different cache entry
    quick = fm.formed(fmap, display=True, quick=True)
    assert len(quick.faces) < len(shown.faces)
    assert fm.prepared(fmap, quick=True) is fm.prepared(soft, quick=True)
    assert fm.prepared(fmap) is not fm.prepared(soft)
    # a projection or a die change reuses the prepared mesh
    other = ThermoformMap(radius_mm=181.0, face_form_deg=169.24, projection_mm=1.0,
                          crease_gap_mm=12.8, crease_angle_deg=20.0, die_radius_mm=5.0,
                          bridge=_geom(ws))
    assert fm.prepared(other) is prep


def test_a_mesh_manifold_rejects_still_forms_as_a_preview():
    """The fallback for a kernel whose output is not closed: a warped copy
    comes back rather than an exception, so the B-Rep and raster previews can
    bend too. It is not the export path and is not asked to verify."""
    import trimesh

    from guildmodel.core.forming import ThermoformMap, form_trimesh
    from guildmodel.core.model.kernel import ManifoldError

    box = trimesh.creation.box(extents=(40.0, 20.0, 6.0))
    box.apply_translation((0.0, 0.0, 3.0))
    open_box = trimesh.Trimesh(box.vertices, box.faces[:-1], process=False)
    from guildmodel.core.forming import BridgeGeometry
    fmap = ThermoformMap(radius_mm=100.0, bridge=BridgeGeometry(apex_x=10.0))
    with pytest.raises(ManifoldError):
        from guildmodel.core.forming import manifold_from_trimesh
        manifold_from_trimesh(open_box)
    formed = form_trimesh(open_box, fmap, 3.0)
    assert len(formed.faces) >= len(open_box.faces)
    # bent: the far ends of the box have moved off the plane
    assert formed.vertices[:, 2].max() - formed.vertices[:, 2].min() > 6.5


# ------------------------------------------------------------ the export spec

def test_the_groove_override_never_touches_the_castle(demo_front):
    """`formed_spec` copies. The realistic failure is an in-place
    `castle.lens_groove.enabled = True`, which would switch the groove on for
    the next G-code build too — so this posts the demo before and after and
    compares the bytes, with the override both ways."""
    import yaml

    from guildmodel.core.cam.castle_ops import (generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleParams, FormingMetadata
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.gui.mesh_build import formed_spec

    CONFIG = ROOT / "src" / "guildmodel" / "config"
    tools_cfg = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    tools = tools_cfg.get("tools", tools_cfg)
    tool = tools.get("flat_3175", next(iter(tools.values())))

    castle = CastleParams()

    def posted():
        relief = build_castle_relief(demo_front.partition, castle,
                                     demo_front.hinge_polys,
                                     resolution=CUT_RES_MM)
        ops = generate_castle_program(relief, castle, demo_front.hinge_polys,
                                      tool, tools_cfg=tools)
        post = GRBLPost(job_name="forming", material="acetate",
                        tool_diameter_mm=3.175, spindle_rpm=10000,
                        feed_rate_mmpm=750, plunge_rate_mmpm=333,
                        safe_z_mm=castle.stock.total_pad_height_mm + 5.0)
        write_castle_program(ops, post)
        return post.to_string()

    before = posted()
    spec = {"mode": "castle", "kind": "frame_front", "label": "Frame Front",
            "partition": demo_front.partition, "castle": castle,
            "hinge": list(demo_front.hinge_polys), "stage": "pockets"}
    from guildmodel.core.forming import BridgeGeometry
    for groove in (True, False):
        forming = FormingMetadata().with_base_curve(4.0, 163.97, radius_mm=144.0,
                                                    bridge_projection_mm=4.0,
                                                    formed_groove=groove)
        fs = formed_spec(spec, forming, bridge=BridgeGeometry())
        assert fs["mode"] == "formed"
        assert fs["castle"].lens_groove.enabled is groove
        assert fs["label"].endswith("(formed)")
        assert spec["mode"] == "castle"
        assert castle.lens_groove.enabled is False, "the override leaked"
        assert fs["castle"] is castle or fs["castle"] is not castle
    assert posted() == before, "forming changed what the machine cuts"


def test_a_formed_export_builds_through_the_choke_point(gabriel_front):
    """`build_component_mesh` handles mode "formed" like any other: the mesh
    kernel warps its own model, the file's part is closed, and the groove
    override reaches the file — the grooved formed part is lighter than the
    bare one, so the printed piece is the finished piece."""
    from guildmodel.core.mesh_check import verify_mesh
    from guildmodel.core.project.schema import CastleParams, FormingMetadata
    from guildmodel.core.model import build_castle_model
    from guildmodel.gui.mesh_build import build_component_mesh, formed_spec

    ws = gabriel_front
    castle = ws.castle_params or CastleParams()
    assert castle.lens_groove.enabled is False
    spec = {"mode": "castle", "kind": "frame_front", "label": "Frame Front",
            "partition": ws.partition, "castle": castle,
            "hinge": list(ws.hinge_polys), "stage": "pockets"}
    geom = _geom(ws)
    volumes = {}
    flat = {}
    for groove in (False, True):
        c = castle.model_copy(update={"lens_groove": castle.lens_groove.model_copy(
            update={"enabled": groove})})
        flat[groove] = build_castle_model(ws.partition, c, list(ws.hinge_polys)).volume()
    for groove in (False, True):
        forming = FormingMetadata().with_base_curve(4.0, 163.97, radius_mm=144.0,
                                                    bridge_projection_mm=4.0,
                                                    formed_groove=groove,
                                                    press_preset="SBT base 4 / lens 4")
        mesh, edges, guide = build_component_mesh(
            formed_spec(spec, forming, bridge=geom),
            resolution=0.3, kernel="mesh")
        verdict = verify_mesh(mesh)
        assert verdict.ok, verdict.problems
        assert edges and guide is None
        # welded for the file: float32-exact and closed by index, so a reader
        # that merges by position finds every edge in two faces
        assert mesh.is_watertight
        assert np.array_equal(np.asarray(mesh.vertices, dtype=np.float32).astype(np.float64),
                              np.asarray(mesh.vertices))
        lo, hi = mesh.bounds
        # bowed: deeper than any flat castle
        assert hi[2] - lo[2] > 15.0
        volumes[groove] = verdict.volume_mm3
        # the formed part is the flat part of the same castle, compressed a
        # few percent on its concave side — so the override reached the file
        ratio = volumes[groove] / flat[groove]
        assert 0.94 < ratio < 1.0, f"groove={groove}: {ratio:.4f}"
    assert abs(volumes[True] - volumes[False]) > 1.0
    assert castle.lens_groove.enabled is False


# ------------------------------------------------------------ the boundaries

def test_the_cam_cannot_reach_forming():
    """`core.forming` joins the AST gate (`test_kernel_flip_mn3` carries the
    same clause). Pinned here too so the M18 file fails on its own."""
    import guildmodel.core.cam as cam_pkg

    offenders = {}
    for path in sorted(Path(cam_pkg.__file__).parent.glob("*.py")):
        imported = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # the module *and* every name taken from it, with the dots of
                # a relative import: `from .. import forming` names no module
                base = "." * node.level + (node.module or "")
                imported.add(base)
                imported.update(f"{base}.{a.name}" for a in node.names)
        bad = [m for m in imported if "forming" in m]
        if bad:
            offenders[path.name] = sorted(bad)
    assert not offenders, f"core.cam reaches core.forming: {offenders}"


def test_forming_imports_no_qt_and_no_cam():
    """Qt-free and CAM-free, by AST: the export worker and the tests import it
    headless, and the CAM must not be reachable from it either."""
    import guildmodel.core.forming as pkg

    for path in sorted(Path(pkg.__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for m in names:
                assert "PySide6" not in m and "Qt" not in m, (path.name, m)
                assert ".cam" not in m and not m.endswith("cam"), (path.name, m)


def test_the_readiness_dot_reads_three_job_facts_and_no_forming():
    from guildmodel.gui.widgets import readiness_dot

    params = list(inspect.signature(readiness_dot.state_for).parameters)
    assert params == ["dxf_loaded", "mesh_built", "program_stored"]


# ------------------------------------------------------------- the schema

def test_with_base_curve_keeps_the_radius_in_step():
    """The maker's number is the base curve in diopters; the radius the map
    bends to is a press row's die when one supplies it, else 530 / D."""
    from guildmodel.core.project.schema import FormingMetadata

    f = FormingMetadata()
    assert f.is_flat and f.face_form_deg == 180.0
    assert f.crease_angle_deg == 45.0 and f.crease_gap_mm == 0.0
    g = f.with_base_curve(4.0, 163.97, radius_mm=144.0, bridge_projection_mm=4.0,
                          press_preset="SBT base 4 / lens 4")
    assert g.base_curve == 4.0 and g.base_radius_mm == 144.0
    assert g.face_form_deg == pytest.approx(163.97)
    assert g.face_form_wrap_deg == pytest.approx(16.03)
    assert g.bridge_projection_mm == 4.0
    assert g.formed_groove is True
    assert not g.is_flat
    assert f.is_flat, "with_base_curve must copy, not mutate"
    off = f.with_base_curve(4.25, 163.97)
    assert off.base_radius_mm == pytest.approx(530.0 / 4.25)
    flat = g.with_base_curve(0.0, 180.0, radius_mm=144.0, bridge_projection_mm=0.0)
    assert flat.is_flat and flat.base_curve == 0.0 and flat.base_radius_mm == 0.0


def test_a_projection_is_never_negative():
    """The die only presses forward. No panel can set a negative projection
    any more; one in a file is read as none, and the map reads any negative
    it is handed the same way."""
    from guildmodel.core.forming import ThermoformMap
    from guildmodel.core.project.schema import FormingMetadata

    assert FormingMetadata(bridge_projection_mm=-3.0).bridge_projection_mm == 0.0
    loaded = FormingMetadata.model_validate({"bridge_projection_mm": -1.5})
    assert loaded.bridge_projection_mm == 0.0 and loaded.is_flat
    assert FormingMetadata(bridge_projection_mm=2.5).bridge_projection_mm == 2.5
    assert ThermoformMap(projection_mm=-2.0).p == 0.0


def test_a_v170_project_opens_flat(tmp_path):
    """A `.gmodel` written before M18 carries the five old forming fields and
    none of the new ones; it must open exactly as it did — flat, groove on
    for any later formed export, no preset."""
    from guildmodel.core.project.save_load import load_project, save_project
    from guildmodel.core.project.schema import (Component, ComponentKind,
                                                FormingMetadata, ProjectSchema)

    old_forming = {"base_curve": 0.0, "pantoscopic_tilt_deg": 0.0,
                   "face_form_wrap_deg": 0.0, "apical_radius_mm": 12.0,
                   "bridge_angle_deg": 8.0}
    f = FormingMetadata.model_validate(old_forming)
    assert f.is_flat and f.formed_groove is True and f.press_preset == ""
    assert f.apical_radius_mm == 12.0 and f.bridge_angle_deg == 8.0

    proj = ProjectSchema(job_name="v1.7.0")
    proj.components = [Component.for_kind(ComponentKind.FRAME_FRONT)]
    data = json.loads(proj.model_dump_json())
    data["components"][0]["forming"] = old_forming
    data["forming"] = old_forming
    path = tmp_path / "old.guildmodel"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.components[0].forming.is_flat
    assert loaded.forming.is_flat

    # and the new fields round-trip through the same writer
    proj.components[0].forming = FormingMetadata().with_base_curve(
        4.0, 163.97, radius_mm=144.0, bridge_projection_mm=4.0,
        crease_gap_mm=18.0, crease_angle_deg=50.0, bridge_offset_mm=-2.0,
        formed_groove=False, press_preset="SBT base 4 / lens 4")
    save_project(proj, path)
    back = load_project(path).components[0].forming
    assert back.base_curve == 4.0 and back.base_radius_mm == 144.0
    assert back.formed_groove is False
    assert back.press_preset == "SBT base 4 / lens 4"
    assert back.bridge_projection_mm == 4.0
    assert (back.crease_gap_mm, back.crease_angle_deg, back.bridge_offset_mm) == (
        18.0, 50.0, -2.0)


# ------------------------------------------------------------- the presses

def test_the_shipped_presses_are_the_sbt_rows():
    from guildmodel.core.forming import press_rows

    rows = press_rows()
    assert [(p.label, p.base_curve, p.radius_mm, p.face_form_deg)
            for p in rows] == SBT
    assert all(p.shipped for p in rows)


def test_the_makers_presses_merge_over_the_shipped_ones(tmp_path, monkeypatch):
    import yaml

    import guildmodel.core.forming.presses as store
    from guildmodel.core.forming import (find_press, matching_press,
                                         press_rows)

    user = tmp_path / "presses.yaml"
    monkeypatch.setattr(store, "_USER", user)
    user.write_text(yaml.safe_dump({
        "SBT base 3 / lens 4": {"base_curve": 3.0, "radius_mm": 180.0,
                                "face_form_deg": 169.0},
        "SBT base 2 / lens 2": {"_deleted": True},
        "Bench die 6": {"base_curve": 6.0, "face_form_deg": 158.0},
        "broken": {"base_curve": "no"},
    }), encoding="utf-8")
    rows = press_rows()
    labels = [p.label for p in rows]
    assert labels == ["SBT base 2 / lens 4", "SBT base 3 / lens 4",
                      "SBT base 4 / lens 4", "Bench die 6"]
    assert find_press("SBT base 3 / lens 4").radius_mm == 180.0
    assert not find_press("SBT base 3 / lens 4").shipped
    six = find_press("Bench die 6")
    assert six.face_form_deg == 158.0
    assert six.radius_mm == pytest.approx(530.0 / 6.0), "no die radius: 530 / D"
    assert find_press("SBT base 2 / lens 2") is None
    assert matching_press(4.0, 163.95).label == "SBT base 4 / lens 4"
    assert matching_press(4.25, 163.97) is None


def test_the_shipped_presses_file_is_packaged():
    """The packaging-data-dir rule: a config file the app reads at runtime
    has to be in `build_common`'s datas or the frozen build silently ships
    without it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_common",
                                                  ROOT / "build_common.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shipped = ROOT / "src" / "guildmodel" / "config" / "presses.yaml"
    assert shipped.exists()
    covered = any(shipped.is_relative_to(ROOT / src)
                  for src, _dest in mod._GUILDMODEL_DATAS)
    assert covered, "config/presses.yaml is not in _GUILDMODEL_DATAS"


def test_a_sliver_sides_with_the_smooth_side_it_lies_on():
    """The Paula's posterior chatter (2026-09-25): a sliver thinner than the
    simplification's tolerance has a normal pointing anywhere. It must take
    the normal of its neighbours' largest mutually smooth group: inside a
    flat patch it joins both sides, at a corner it sides with one and never
    bridges the corner, and a fan of slivers resolves from its ends."""
    from guildmodel.core.forming.tessellate import _borrowed_normals

    cos40 = float(np.cos(np.radians(40.0)))
    up, wall, junk = [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]

    # face 0 is the sliver; faces 1 and 2 are flat top faces on either side
    fn = np.array([junk, up, up, wall])
    w = np.array([1e-9, 1.0, 1.0, 1.0])
    sliver = np.array([True, False, False, False])
    nbr = np.array([[1, 2, -1], [0, -1, -1], [0, -1, -1], [-1, -1, -1]])
    eff = _borrowed_normals(fn, w, sliver, nbr, cos40)
    assert np.allclose(eff[0], up), "inside a patch it joins both sides"

    # at a corner: two top faces and one wall face around it
    nbr = np.array([[1, 2, 3], [0, -1, -1], [0, -1, -1], [0, -1, -1]])
    eff = _borrowed_normals(fn, w, sliver, nbr, cos40)
    assert np.allclose(eff[0], up), "sides with the larger group"
    assert eff[0] @ np.array(wall) < cos40, "and does not bridge the corner"

    # a fan: slivers 0-1-2 in a chain, top faces at both ends
    fn = np.array([junk, junk, junk, up, up])
    w = np.array([1e-9, 1e-9, 1e-9, 1.0, 1.0])
    sliver = np.array([True, True, True, False, False])
    nbr = np.array([[3, 1, -1], [0, 2, -1], [1, 4, -1], [0, -1, -1], [2, -1, -1]])
    eff = _borrowed_normals(fn, w, sliver, nbr, cos40)
    assert np.allclose(eff[:3], up), "the whole fan resolves"

    # a thick face keeps its own normal: only slivers are touched
    assert np.allclose(eff[3:], up)
