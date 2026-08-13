"""GuildDraw `.gdraw` direct intake (BUILDPLAN M7.2).

One `.gdraw` (front + temple_r + temple_l + hinge SVGs, each with a JSON metadata
blob) imports as a multi-component project. These tests cover the curve flatteners
+ the scene→posterior (x,y)→(-x,-y) transform, the per-workspace read, the
multi-component assembly (frame front + both temples + a base-curve template per
lens), the base-curve right/left split, the forming carry, and the security guard.

The last section covers the *exact* curves (2026-08-07). A ``.gdraw`` stores its
splines as cubic Bezier nodes; those are now carried through as B-splines instead
of being flattened away, so the primary intake reaches the B-Rep kernel as the
curve GuildDraw drew rather than as a polygon approximating it.
"""
import json
import math
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from guildmodel.core.project.schema import ComponentKind
from guildmodel.core.io_import.gdraw import (
    GdrawError,
    TABS,
    build_project_from_gdraw,
    read_gdraw,
    read_workspace_curves,
    read_workspace_geometry,
)

_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ builders

def _node(x, y, cp_in=None, cp_out=None):
    d = {"x": x, "y": y}
    if cp_in:
        d["cp_in"] = {"x": cp_in[0], "y": cp_in[1]}
    if cp_out:
        d["cp_out"] = {"x": cp_out[0], "y": cp_out[1]}
    return d


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [_node(x, y) for x, y in pts]}


def _svg_bytes(state: dict) -> bytes:
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    root.set("version", "1.1")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path, states: dict, active="front"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json",
                    json.dumps({"version": 1, "tabs": list(TABS), "active_tab": active}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))


def _front_state():
    return {
        "forming": {"apical_radius_mm": 88.0, "bridge_angle_deg": 5.0},
        "mirror": {"x": 0.0, "enabled": True},
        "curves": [
            _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
            _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),     # scene +x → posterior -x (OS/left)
            _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),  # scene -x → posterior +x (OD/right)
            _line("SCULPT", [(0, -20), (0, 20)]),
            _line("SCULPT", [(30, -20), (30, 20)]),
            _line("HINGE", [(50, -5), (58, -5), (58, 5), (50, 5)], closed=True),
        ],
    }


def _temple_r_state():
    return {
        "forming": {"apical_radius_mm": 0.0, "bridge_angle_deg": 0.0},
        "mirror": {},
        "curves": [
            _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
            _line("ENGRAVING", [(-40, 0), (0, 0), (40, 0)]),
        ],
    }


def _full_states():
    return {
        "front": _front_state(),
        "temple_r": _temple_r_state(),
        "temple_l": {"curves": []},                                   # no temple drawn
        "hinge": {"curves": [_line("HINGE", [(0, 0), (8, 0), (8, 8), (0, 8)], closed=True)]},
    }


# ------------------------------------------------------------------ flatten / transform

def test_line_flatten_and_posterior_transform():
    state = {"curves": [_line("OUTLINE", [(10, 5), (30, 5)])]}
    geom = read_workspace_geometry(state, posterior=True)
    assert geom["OUTLINE"] == [[(-10, -5), (-30, -5)]]                # (x,y) → (-x,-y)
    raw = read_workspace_geometry(state, posterior=False)
    assert raw["OUTLINE"] == [[(10, 5), (30, 5)]]


def test_circle_flatten_samples_the_ring():
    state = {"curves": [{"kind": "circle", "layer": "LENS",
                         "nodes": [_node(5, 0)], "radius": 10.0}]}
    ring = read_workspace_geometry(state)["LENS"][0]
    assert len(ring) >= 16
    # posterior center is (-5, 0); every sample is ~r from it
    for x, y in ring:
        assert math.hypot(x - (-5), y - 0) == pytest.approx(10.0, abs=1e-6)


def test_spline_flatten_keeps_endpoints():
    curve = {"kind": "spline", "layer": "OUTLINE", "closed": False,
             "nodes": [_node(0, 0, cp_out=(10, 10)), _node(20, 0, cp_in=(10, -10))]}
    pts = read_workspace_geometry({"curves": [curve]})["OUTLINE"][0]
    assert len(pts) > 2                                               # curved, subdivided
    assert pts[0] == (0.0, 0.0) and pts[-1] == (-20.0, 0.0)           # endpoints, transformed


def test_unknown_layer_skipped():
    state = {"curves": [_line("FOO", [(0, 0), (1, 1)]), _line("OUTLINE", [(0, 0), (1, 0)])]}
    geom = read_workspace_geometry(state)
    assert "FOO" not in geom and len(geom["OUTLINE"]) == 1


# ------------------------------------------------------------------ read_gdraw

def test_read_gdraw_workspaces(tmp_path):
    path = tmp_path / "model.gdraw"
    _make_gdraw(path, _full_states(), active="temple_r")
    doc = read_gdraw(path)

    assert set(doc.workspaces) == set(TABS)
    assert doc.active_tab == "temple_r"
    front = doc.workspaces["front"]
    assert len(front.layers["OUTLINE"]) == 1
    assert len(front.layers["LENS"]) == 2
    assert len(front.layers["SCULPT"]) == 2
    assert front.apical_radius_mm == pytest.approx(88.0)
    assert front.bridge_angle_deg == pytest.approx(5.0)
    assert doc.workspaces["temple_l"].is_empty()


def test_plain_svg_is_single_front(tmp_path):
    path = tmp_path / "front.svg"
    path.write_bytes(_svg_bytes(_front_state()))
    doc = read_gdraw(path)
    assert set(doc.workspaces) == {"front"}
    assert len(doc.workspaces["front"].layers["LENS"]) == 2


def test_doctype_is_rejected(tmp_path):
    path = tmp_path / "evil.svg"
    path.write_bytes(b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "x">]>'
                     b'<svg xmlns="http://www.w3.org/2000/svg"><metadata>{}</metadata></svg>')
    with pytest.raises(GdrawError):
        read_gdraw(path)


def test_missing_metadata_raises(tmp_path):
    path = tmp_path / "bare.gdraw"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        zf.writestr("front.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    with pytest.raises(GdrawError):
        read_gdraw(path)


# ------------------------------------------------------------------ project assembly

def test_build_project_is_multi_component(tmp_path):
    path = tmp_path / "model.gdraw"
    _make_gdraw(path, _full_states())
    gp = build_project_from_gdraw(path)

    kinds = [c.component.kind for c in gp.components]
    assert kinds[:3] == [ComponentKind.FRAME_FRONT,
                         ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT]
    assert {kinds[3], kinds[4]} == {ComponentKind.BASE_CURVE_RIGHT,
                                    ComponentKind.BASE_CURVE_LEFT}
    assert gp.project.job_name == "model"
    # the front's base curve is carried onto the project + the frame component
    assert gp.project.forming.apical_radius_mm == pytest.approx(88.0)
    assert gp.project.frame_front().forming.apical_radius_mm == pytest.approx(88.0)


def test_empty_temple_is_disabled(tmp_path):
    path = tmp_path / "model.gdraw"
    _make_gdraw(path, _full_states())
    gp = build_project_from_gdraw(path)
    by_kind = {c.component.kind: c.component for c in gp.components}
    assert by_kind[ComponentKind.TEMPLE_RIGHT].enabled is True        # has an OUTLINE
    assert by_kind[ComponentKind.TEMPLE_LEFT].enabled is False        # empty workspace


def test_base_curve_components_carry_the_right_lens(tmp_path):
    path = tmp_path / "model.gdraw"
    _make_gdraw(path, _full_states())
    gp = build_project_from_gdraw(path)

    for gc in gp.components:
        kind = gc.component.kind
        if kind not in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            continue
        lenses = gc.layers["LENS"]
        assert len(lenses) == 1                                       # exactly its own lens
        cx = sum(x for x, _ in lenses[0]) / len(lenses[0])
        if kind == ComponentKind.BASE_CURVE_RIGHT:
            assert cx > 0                                             # OD on +x (posterior)
        else:
            assert cx < 0


def test_temple_geometry_has_outline_and_engraving(tmp_path):
    path = tmp_path / "model.gdraw"
    _make_gdraw(path, _full_states())
    gp = build_project_from_gdraw(path)
    tr = next(c for c in gp.components if c.component.kind == ComponentKind.TEMPLE_RIGHT)
    assert len(tr.layers["OUTLINE"]) == 1
    assert len(tr.layers["ENGRAVING"]) == 1


# ------------------------------------------------------------------ exact curves

def _spline(layer, nodes, closed=False):
    """A GuildDraw spline curve: `nodes` is [(x, y, cp_in|None, cp_out|None), ...]."""
    return {"kind": "spline", "layer": layer, "closed": closed,
            "nodes": [_node(x, y, cp_in, cp_out) for x, y, cp_in, cp_out in nodes]}


def _curved_ring(layer):
    """A closed four-node spline — a rounded square, genuinely not a polygon."""
    return _spline(layer, [
        (-20.0, -20.0, (-30.0, -10.0), (-10.0, -30.0)),
        (20.0, -20.0, (10.0, -30.0), (30.0, -10.0)),
        (20.0, 20.0, (30.0, 10.0), (10.0, 30.0)),
        (-20.0, 20.0, (-10.0, 30.0), (-30.0, 10.0)),
    ], closed=True)


def test_a_gdraw_spline_keeps_its_exact_definition():
    """The point of the whole exercise: a `.gdraw` spline reaches the kernel as a
    curve, not as the polyline it happens to flatten to."""
    pts, curves = read_workspace_curves({"curves": [_curved_ring("OUTLINE")]})
    curve = curves["OUTLINE"][0]
    assert curve is not None
    assert curve.degree == 3 and curve.closed and curve.is_consistent()
    # four Bezier segments -> 3*4 + 1 poles, and far fewer than the flattening.
    assert len(curve.control_points) == 13
    assert len(pts["OUTLINE"][0]) > 40


def test_the_exact_curve_and_the_polyline_describe_the_same_boundary():
    """Not a fit. Every flattened point must lie *on* the rebuilt curve — if the
    two ever drift apart, `_ring_key` lookups start silently missing."""
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.gp import gp_Pnt
    from guildmodel.core.solid.occ import nurbs_edge

    pts, curves = read_workspace_curves({"curves": [_curved_ring("OUTLINE")]})
    geom = BRep_Tool.Curve_s(nurbs_edge(curves["OUTLINE"][0], 0.0), 0.0, 1.0)
    worst = max(GeomAPI_ProjectPointOnCurve(gp_Pnt(x, y, 0.0), geom).LowerDistance()
                for x, y in pts["OUTLINE"][0])
    assert worst < 1e-9, f"{worst} mm — a transcription must be exact"


def test_the_posterior_flip_moves_the_curve_too():
    """Scene -> posterior is (x, y) -> (-x, -y). Miss the curve and the two
    representations describe different frames (BUILDPLAN M1.2)."""
    state = {"curves": [_curved_ring("OUTLINE")]}
    _, raw = read_workspace_curves(state, posterior=False)
    _, flipped = read_workspace_curves(state, posterior=True)
    a = raw["OUTLINE"][0].control_points
    b = flipped["OUTLINE"][0].control_points
    assert np.allclose(b, -a)


def test_a_gdraw_circle_is_exact_not_sampled():
    """A circle is a rational quadratic; no polyline reproduces one."""
    import math
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.gp import gp_Pnt
    from guildmodel.core.solid.occ import nurbs_edge

    state = {"curves": [{"kind": "circle", "layer": "LENS",
                         "nodes": [_node(5, 0)], "radius": 10.0}]}
    _, curves = read_workspace_curves(state, posterior=False)
    curve = curves["LENS"][0]
    assert curve is not None and curve.rational and curve.degree == 2

    geom = BRep_Tool.Curve_s(nurbs_edge(curve, 0.0), 0.0, 1.0)
    worst = 0.0
    for i in range(360):
        a = 2.0 * math.pi * i / 360.0
        p = gp_Pnt(5.0 + 10.0 * math.cos(a), 10.0 * math.sin(a), 0.0)
        worst = max(worst, GeomAPI_ProjectPointOnCurve(p, geom).LowerDistance())
    assert worst < 1e-9


def test_circle_flattening_is_sagitta_based():
    """`tol` is how far a chord may sag, not a divisor of the circumference.

    The original read `circumference / tol`, which is dimensionally wrong and
    turned a 20 mm hole into ~12,600 points — every one of which then went
    through Shapely and the mesher.
    """
    state = {"curves": [{"kind": "circle", "layer": "LENS",
                         "nodes": [_node(0, 0)], "radius": 20.0}]}
    ring = read_workspace_geometry(state)["LENS"][0]
    assert 50 < len(ring) < 200
    # and it really is within tolerance of the circle
    worst = max(abs(math.hypot(x, y) - 20.0) for x, y in ring)
    assert worst < 0.01


def test_lines_and_arcs_report_no_curve():
    """A polyline already *is* its points, and an open arc is never a ring, so
    neither needs an exact form — and claiming one would be noise."""
    state = {"curves": [
        _line("SCULPT", [(0, 0), (10, 10)]),
        {"kind": "arc", "layer": "OUTLINE", "nodes": [_node(0, 0)],
         "radius": 5.0, "start_angle": 0.0, "end_angle": 90.0},
    ]}
    _, curves = read_workspace_curves(state)
    assert curves["SCULPT"] == [None]
    assert curves["OUTLINE"] == [None]


def test_points_and_curves_stay_index_aligned(tmp_path):
    """The contract every consumer relies on, across a whole file."""
    path = tmp_path / "model.gdraw"
    states = _full_states()
    states["front"]["curves"].append(_curved_ring("OUTLINE"))
    _make_gdraw(path, states)
    doc = read_gdraw(path)
    for ws in doc.workspaces.values():
        for layer, pts in ws.layers.items():
            assert len(pts) == len(ws.curves[layer]), f"{ws.name}/{layer}"


def test_components_carry_their_curves(tmp_path):
    """Including a base-curve template, which gets exactly its own lens."""
    path = tmp_path / "model.gdraw"
    states = _full_states()
    states["front"]["curves"].append(_curved_ring("LENS"))
    _make_gdraw(path, states)
    gp = build_project_from_gdraw(path)
    for gc in gp.components:
        for layer, pts in gc.layers.items():
            assert len(pts) == len(gc.curves.get(layer, [])), gc.component.kind
    front = next(c for c in gp.components
                 if c.component.kind == ComponentKind.FRAME_FRONT)
    assert sum(c is not None for c in front.curves["LENS"]) == 1
