"""The parameter dock's sections fold under their headers (2026-10-15), and
GuildModel remembers which — with the Inlays section tidied to what a seat
needs every time, the rest under *Cut details*.

The Worktable panel's sections have folded since M20; the maker asked for the
same on the Model tab once the Inlays section joined Model Properties,
Posterior Finishing, Edge Features and Zones there. Every section on every tab
took it, through one helper, so a section hidden for a component kind hides
header and all.
"""
import pytest

from guildmodel.core.project.schema import CastleParams, ComponentKind, InlayFeature


def _panel(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


MODEL_TAB = ("Frame style", "Model Properties", "Posterior Finishing",
             "Lens Bevel Groove", "Edge Features  (chamfers && fillets)",
             "Inlays  (seats for plaques && plates)", "Zones")


def test_every_section_of_the_dock_is_a_fold(tmp_path, monkeypatch):
    from guildmodel.gui.widgets.collapsible import CollapsibleBox
    p = _panel(tmp_path, monkeypatch)
    for title in MODEL_TAB:
        assert title in p._folds, title
    for title in ("Stock", "Temple", "Inlays  (seats on this temple)",
                  "Base-Curve Holding Block", "Material && Allowances",
                  "Operations  (uncheck to skip)", "Program Zero  (G54 work datum)"):
        assert title in p._folds, title
    assert all(isinstance(b, CollapsibleBox) for b in p._folds.values())
    assert all(b.is_expanded() for t, b in p._folds.items() if "cut details" not in t)


def test_a_fold_hides_its_body_and_is_remembered_by_title(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    assert p.fold_state() == {}
    heard = []
    p.fold_changed.connect(lambda: heard.append(1))
    p._folds["Zones"].header.click()
    assert heard and not p._folds["Zones"].body.isVisibleTo(p)
    assert p.fold_state() == {"Zones": False}
    # a second dock, restored from that: Zones folded, the rest open
    q = _panel(tmp_path, monkeypatch)
    q.set_fold_state({"Zones": False, "A section that no longer exists": False})
    assert not q._folds["Zones"].is_expanded()
    assert q._folds["Model Properties"].is_expanded()
    q.set_fold_state({})
    assert q._folds["Zones"].is_expanded()


def test_a_section_hidden_for_a_kind_hides_its_header_too(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    box = p._folds["Per-operation tools  (multi-tool jobs)"]
    assert box.header.parentWidget() is box          # hiding the box hides its header
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    assert box.isHidden() and not box.body.isHidden()   # the whole fold, not just the body
    p.set_component_kind(ComponentKind.FRAME_FRONT)
    assert not box.isHidden()


def test_the_inlays_section_keeps_its_explanation_on_the_header(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel
    from guildmodel.gui.widgets.inlays_group import InlaysGroup
    p = _panel(tmp_path, monkeypatch)
    box = p._folds["Inlays  (seats for plaques && plates)"]
    assert box.header.toolTip() == InlaysGroup.TIP
    paragraphs = [w for w in p.inlays_front.findChildren(QLabel)
                  if w.objectName() == "hintLabel"]
    assert paragraphs == []
    assert p.inlays_front.rows.height() < 100
    # the rarer numbers are folded away, and remembered as their own section
    assert not p.inlays_front.details.is_expanded()
    assert p._folds["Inlays  (seats for plaques && plates) · cut details"] is p.inlays_front.details
    # built closed, so closed is not written down and open is
    assert p.fold_state() == {}
    p.inlays_front.details.header.click()
    assert p.fold_state() == {"Inlays  (seats for plaques && plates) · cut details": True}
    p.inlays_front.details.header.click()
    assert p.fold_state() == {}


def test_the_folded_details_still_round_trip_the_seat(tmp_path, monkeypatch):
    p = _panel(tmp_path, monkeypatch)
    castle = CastleParams(inlays=[InlayFeature(
        id="inlay_1", label="Plaque", flush_mm=0.15, tool="ball_1mm",
        stepdown_mm=0.3, min_thickness_mm=1.4, centroid=(0.0, 5.0), area_mm2=24.0)])
    p.set_castle_params(castle)
    assert p.castle_params().inlays[0].model_dump() == castle.inlays[0].model_dump()
    p.inlays_front.flush.setValue(-0.2)
    assert p.castle_params().inlays[0].flush_mm == pytest.approx(-0.2)


def test_the_prefs_carry_the_fold_key():
    from guildmodel.gui import prefs as prefs_mod
    assert prefs_mod.DEFAULTS["dock_folds"] == {}


def test_the_stock_tab_does_not_hold_the_sidebar_open(tmp_path, monkeypatch):
    """A checkbox does not wrap, and the pre-formed blank's long label made
    the Stock tab's least width 478 px when the next widest tab's was 370:
    narrowing the sidebar scrolled the Stock tab sideways and no other (2.0)."""
    from PySide6.QtWidgets import QApplication, QScrollArea
    p = _panel(tmp_path, monkeypatch)
    p.resize(380, 900)
    p.show()
    QApplication.processEvents()
    widths = {}
    for i in range(p.count()):
        page = p.widget(i)
        inner = page.widget() if isinstance(page, QScrollArea) else page
        widths[p.tabText(i)] = inner.minimumSizeHint().width()
    assert widths["Stock"] <= max(w for name, w in widths.items() if name != "Stock"), widths
