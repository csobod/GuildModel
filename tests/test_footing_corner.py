"""The sharp fin at the inferior nosepad, and the gate that would have caught it.

A footing band is a ribbon swept along a zone seam, so it has square ends and
never carves the corner just off one. The raster has no such notion — it carves
by Euclidean distance to the seam, which rounds the corner for free. So the
raster and *both* solid kernels disagreed exactly there, and the two solid
kernels agreed with each other perfectly, which is why every parity gate passed.

It survived from before UI-0 ("a visibly corrupt model — a spike of material off
the nosepad") until 2026-08-08, and nothing automated ever saw it: the part is
watertight, one body, one connected piece, and correct to 0.04% on volume with a
9 mm wedge of uncarved material standing on it. It took a maker looking at the
render.

**What makes it appear.** A fillet large against the seam it runs along. On the
gabriel, `nosepad_inferior` is a **5.19 mm** seam carrying **9.0 / 10.0 mm**
radii, so the blend reaches nearly twice as far as the seam is long and the
uncarved corner comes out as a long wedge tapering to a point. The demo's same
seam is 10.14 mm and shows nothing — which is the lesson about fixture choice,
not about the demo.

`geometry.footings.CUT_LEAD_MM` runs the stations past both ends.

These compare against the **raster**, deliberately. The two solid kernels agreeing
with each other is exactly the condition that hid this, so a mesh-vs-B-Rep gate
would not have caught it and will not catch the next one.
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
from shapely import contains_xy, prepare

FIXTURES = Path(__file__).parent / "fixtures"

#: How far the lowest full-height cell in a nosepad zone may sit below the
#: raster's answer, mm. One 0.15 mm CAM cell of slack, doubled: the three paths
#: land within a cell of each other and the defect this guards against was
#: 1.95 mm — a hundred times this — so there is no need to sit on the noise.
TONGUE_TOL_MM = 0.3


def _demo_front():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws


def _gdraw_front(tmp_path_factory, name):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp("gdraw") / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def demo_front():
    return _demo_front()


@pytest.fixture(scope="module")
def aviator_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "aviator")


@pytest.fixture(scope="module")
def gabriel_front(tmp_path_factory):
    return _gdraw_front(tmp_path_factory, "gabriel")


def _tongue(relief, partition):
    """Lowest y still standing at full nosepad height, per nosepad zone."""
    f = relief.field
    rows, cols = f.z.shape
    xs = f.origin[0] + np.arange(cols) * f.resolution
    ys = f.origin[1] + np.arange(rows) * f.resolution
    grid_x, grid_y = np.meshgrid(xs, ys)

    out = {}
    for zone in partition.zones:
        if "nosepad" not in zone.name:
            continue
        prepare(zone.polygon)
        inside = contains_xy(zone.polygon, grid_x.ravel(),
                             grid_y.ravel()).reshape(rows, cols)
        tall = inside & (f.z > 9.5)
        out[zone.name] = float(grid_y[tall].min()) if tall.any() else None
    return out


@pytest.mark.parametrize("fixture",
                         ["gabriel_front", "aviator_front", "demo_front"])
def test_no_uncarved_wedge_survives_at_the_nosepad_corner(fixture, request):
    """Both solid kernels must stop full-height material where the raster does.

    Measured before the fix, lowest full-height cell: gabriel **-6.697** against
    the raster's -4.747, aviator -8.366 against -7.016. After: -4.597 / -4.747
    and -7.016 / -7.016. The demo's nosepads do not move at all — its seams are
    long enough that the corner was never visible — though the part as a whole
    loses 0.674 mm3 of uncarved corner elsewhere (`test_bridge_tangency_mn0`).
    """
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.model import build_castle_model, mesh_to_relief
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import CUT_RES_MM, build_castle_relief
    from guildmodel.core.solid import (build_castle_solid, clear_base_cache,
                                       solid_to_relief)

    front = request.getfixturevalue(fixture)
    part, hinges = front.partition, front.hinge_polys
    castle = CastleParams()

    raster = _tongue(build_castle_relief(part, castle, hinges,
                                         resolution=CUT_RES_MM), part)
    mesh = _tongue(mesh_to_relief(build_castle_model(part, castle, hinges),
                                  part, castle, resolution=CUT_RES_MM), part)
    clear_base_cache()
    brep = _tongue(solid_to_relief(build_castle_solid(part, castle, hinges),
                                   part, castle, resolution=CUT_RES_MM), part)

    assert raster, "no nosepad zones on this drawing; the test proves nothing"
    for zone, reference in raster.items():
        for label, table in (("mesh", mesh), ("brep", brep)):
            got = table[zone]
            assert got is not None, f"{label} carved the whole {zone} away"
            assert got >= reference - TONGUE_TOL_MM, (
                f"{label} leaves full-height material down to y={got:.3f} in "
                f"{zone}, where the raster stops at {reference:.3f} — an "
                "uncarved wedge off the end of a footing band")


def test_the_stations_run_past_both_ends_of_the_cut():
    """The mechanism, checked directly rather than through a build.

    This used to sample 2%..98% of the cut, and on a short seam that trim is a
    tenth of a millimetre — which under a 9 mm blend is a 9 mm wedge. The
    stations now cover the whole cut and `CUT_LEAD_MM` past each end.
    """
    from shapely.geometry import LineString

    from guildmodel.core.geometry.footings import CUT_LEAD_MM, cut_stations

    line = LineString([(0.0, 0.0), (10.0, 0.0)])
    pts, perps = cut_stations(line, 12)

    assert pts[0][0] == pytest.approx(-CUT_LEAD_MM)
    assert pts[-1][0] == pytest.approx(10.0 + CUT_LEAD_MM)
    assert 0.0 < CUT_LEAD_MM <= 1.0, (
        "past ~1 mm the lead buys nothing the tongue test can see and starts "
        "costing OpenCASCADE its booleans — see the constant's own note")
    assert len(pts) == len(perps) == 12
    # Left-normals of a +x cut point at +y, and stay unit length.
    assert np.allclose(np.linalg.norm(perps, axis=1), 1.0)
    assert perps[0][1] == pytest.approx(1.0)

    # A lead of zero still spans the cut exactly — the old behaviour minus its
    # trim, which is what the parametrisation is for.
    plain, _ = cut_stations(line, 5, lead_mm=0.0)
    assert plain[0][0] == pytest.approx(0.0)
    assert plain[-1][0] == pytest.approx(10.0)


def test_a_curved_cut_is_extrapolated_along_its_end_tangents():
    """The lead is a straight extension of the end segment, so a gently curved
    SCULPT line does not get a kink. Short by design: 2 mm on a spline whose
    curvature is measured in tens of millimetres."""
    from shapely.geometry import LineString

    from guildmodel.core.geometry.footings import CUT_LEAD_MM, cut_stations

    arc = LineString([(np.cos(t), np.sin(t)) for t in
                      np.linspace(0.0, np.pi / 2, 24)])
    pts, _ = cut_stations(arc, 30)

    start_seg = np.asarray(arc.coords[0]) - np.asarray(arc.coords[1])
    start_seg /= np.linalg.norm(start_seg)
    expected = np.asarray(arc.coords[0]) + start_seg * CUT_LEAD_MM
    assert np.allclose(pts[0], expected, atol=1e-9)
