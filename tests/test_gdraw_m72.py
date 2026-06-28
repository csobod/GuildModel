"""GuildDraw `.gdraw` direct intake (BUILDPLAN M7.2).

One `.gdraw` (front + temple_r + temple_l + hinge SVGs, each with a JSON metadata
blob) imports as a multi-component project. These tests cover the curve flatteners
+ the scene→posterior (x,y)→(-x,-y) transform, the per-workspace read, the
multi-component assembly (frame front + both temples + a base-curve template per
lens), the base-curve right/left split, the forming carry, and the security guard.
"""
import json
import math
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.project.schema import ComponentKind
from guildmodel.core.io_import.gdraw import (
    GdrawError,
    TABS,
    build_project_from_gdraw,
    read_gdraw,
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
    # posterior centre is (-5, 0); every sample is ~r from it
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
