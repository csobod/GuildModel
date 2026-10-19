"""HINGE became COMPONENT (2.0, the maker's decision).

The layer carries anything mounted on the posterior that needs a classic
pocket: hinges, bridges, endpieces, bridge bars. Every drawing, library entry
and DXF made before 2.0 says HINGE, so HINGE is read as COMPONENT for good,
and GuildDraw's component tab, `hinge.svg` before 2.0, is read under either
name. The op that cuts the pockets is Component Pockets; a project or a CAM
preference saved before keeps its per-op settings under the new name, and a
program stored before still has its pockets timed.
"""
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

from guildmodel.core.layers import ALL_LAYERS, LAYER_ALIASES, canonical_layer

_SVG_NS = "http://www.w3.org/2000/svg"


def _rect(layer, x0, y0, x1, y1):
    return {"kind": "line", "layer": layer, "closed": True,
            "nodes": [{"x": x, "y": y} for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]}


def _svg(state) -> bytes:
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    ET.SubElement(root, f"{{{_SVG_NS}}}metadata").text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _gdraw(path, layer: str, tab: str, active: str = "front"):
    front = {"curves": [_rect("OUTLINE", -60, -20, 60, 20), _rect(layer, 50, -5, 58, 5)]}
    tabs = {"front": front, "temple_r": {"curves": []}, "temple_l": {"curves": []},
            tab: {"curves": [_rect(layer, -4, -2, 4, 2)]}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": active}))
        for name, st in tabs.items():
            zf.writestr(f"{name}.svg", _svg(st))
    return path


def test_the_layer_is_component_and_hinge_reads_as_it():
    assert "COMPONENT" in ALL_LAYERS and "HINGE" not in ALL_LAYERS
    assert LAYER_ALIASES == {"HINGE": "COMPONENT"}
    assert canonical_layer("HINGE") == canonical_layer("hinge") == "COMPONENT"
    assert canonical_layer("Component") == "COMPONENT"
    assert canonical_layer("LENS") == "LENS" and canonical_layer(None) is None


@pytest.mark.parametrize("layer", ["HINGE", "COMPONENT"])
def test_a_dxf_drawn_on_either_name_reads_as_component(tmp_path, layer):
    ezdxf = pytest.importorskip("ezdxf")
    from guildmodel.core.io_import.dxf import import_dxf
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (8, 0), (8, 10), (0, 10)], close=True,
                                    dxfattribs={"layer": layer})
    path = tmp_path / "pocket.dxf"
    doc.saveas(path)
    raw = import_dxf(path)
    assert len(raw["COMPONENT"]) == 1 and "HINGE" not in raw


@pytest.mark.parametrize("layer,tab,active", [("HINGE", "hinge", "hinge"),
                                              ("COMPONENT", "component", "component")])
def test_a_gdraw_from_before_or_after_the_rename_reads_alike(tmp_path, layer, tab, active):
    from guildmodel.core.io_import.gdraw import TABS, read_gdraw
    doc = read_gdraw(_gdraw(tmp_path / "frame.gdraw", layer, tab, active))
    assert "component" in TABS and "hinge" not in TABS
    assert len(doc.workspaces["front"].layers["COMPONENT"]) == 1
    assert len(doc.workspaces["component"].layers["COMPONENT"]) == 1
    assert doc.active_tab == ("component" if active != "front" else "front")


def test_the_front_cuts_a_pocket_drawn_on_hinge(tmp_path):
    """Through to the part: a pocket on an old drawing's HINGE layer is a
    component pocket on the front."""
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    front = build_workspaces_from_gdraw(_gdraw(tmp_path / "old.gdraw", "HINGE", "hinge"))[0][0]
    assert len(front.hinge_polys) == 1


def test_an_old_projects_op_settings_carry_to_component_pockets():
    from guildmodel.core.project.schema import CastleCamParams
    cam = CastleCamParams.model_validate({
        "op_enabled": {"Hinge Pockets": False, "Perimeter": True},
        "op_tools": {"Hinge Pockets": "flat_1mm"}})
    assert cam.op_enabled == {"Component Pockets": False, "Perimeter": True}
    assert cam.op_tools == {"Component Pockets": "flat_1mm"}
    assert not cam.is_op_enabled("Component Pockets")
    assert cam.tool_for_op("Component Pockets") == "flat_1mm"
    # the CAM preference is restored the same way
    assert CastleCamParams(**{"op_enabled": {"Hinge Pockets": False}}).op_enabled == {
        "Component Pockets": False}


def test_a_stored_program_has_its_pockets_timed_under_either_name():
    from guildmodel.core.cam.cuttime import _canon_op
    assert _canon_op("--- Hinge Pockets ---") == "Component Pockets"
    assert _canon_op("--- Component Pockets ---") == "Component Pockets"
