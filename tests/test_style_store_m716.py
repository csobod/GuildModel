"""M7.16 — frame-style preset store: save/list/load round-trip, shipped untouched."""
import pytest

from guildmodel.gui import style_store
from guildmodel.core.project.schema import CastleParams


@pytest.fixture
def tmp_user(tmp_path, monkeypatch):
    monkeypatch.setattr(style_store, "_USER", tmp_path / "frame_styles.yaml")
    return tmp_path / "frame_styles.yaml"


def test_shipped_is_the_schema_default():
    s = style_store.style("Guild demo")
    assert s == CastleParams()
    assert style_store.is_shipped("Guild demo")


def test_effective_equals_shipped_without_user(tmp_user):
    assert style_store.names() == ["Guild demo"]


def test_save_list_load_roundtrips_full_params(tmp_user):
    c = CastleParams()
    c.zones.endpiece_mm = 7.25
    c.footing.endpiece_superior.exterior_mm = 40.0
    c.stock.blank_thickness_mm = 6.0
    c.onion_skin_mm = 0.55
    style_store.save_style("House bold", c)

    assert "House bold" in style_store.names()
    loaded = style_store.style("House bold")
    assert loaded == c                          # full nested CastleParams round-trips
    assert loaded.zones.endpiece_mm == 7.25
    assert loaded.stock.blank_thickness_mm == 6.0


def test_save_accepts_a_plain_dict(tmp_user):
    style_store.save_style("from dict", CastleParams().model_dump())
    assert isinstance(style_store.style("from dict"), CastleParams)


def test_shipped_baseline_is_never_written(tmp_user):
    # saving + deleting only ever touches the user file
    style_store.save_style("mine", CastleParams())
    style_store.delete_style("Guild demo")      # tombstone, not a baseline edit
    assert not style_store._SHIPPED_NAME == ""  # sanity
    # shipped() still returns the pristine default regardless of user file state
    assert style_store.shipped() == {"Guild demo": CastleParams().model_dump()}


def test_delete_user_added_removes(tmp_user):
    style_store.save_style("temp", CastleParams())
    assert "temp" in style_store.names()
    style_store.delete_style("temp")
    assert "temp" not in style_store.names()


def test_delete_shipped_tombstones_then_resets(tmp_user):
    style_store.delete_style("Guild demo")
    assert "Guild demo" not in style_store.names()
    style_store.reset_style("Guild demo")       # un-hide
    assert "Guild demo" in style_store.names()


def test_unknown_style_is_none(tmp_user):
    assert style_store.style("nope") is None


def test_reset_all_clears_user(tmp_user):
    style_store.save_style("a", CastleParams())
    style_store.save_style("b", CastleParams())
    style_store.reset_all()
    assert style_store.names() == ["Guild demo"]


def test_panel_preset_drives_the_dock(tmp_user, monkeypatch):
    """The Castle/Stock dock: save the current params as a style, edit them, then
    selecting the style restores them (the live-rebuild signal path)."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    p = ParamsPanel()
    # the combo seeds with the placeholder + the shipped preset
    items = [p.style_combo.itemText(i) for i in range(p.style_combo.count())]
    assert items == ["— Frame style —", "Guild demo"]

    p.zone_endpiece.setValue(7.7)
    p.blank_thickness.setValue(6.5)
    rebuilt = []
    p.castle_changed.connect(lambda: rebuilt.append(True))   # the live-preview trigger
    style_store.save_style("Bold rim", p.castle_params())
    p._refresh_style_combo(select="Bold rim")

    p.zone_endpiece.setValue(5.0)                # drift away
    p._on_style_selected(p.style_combo.findText("Bold rim"))
    assert abs(p.zone_endpiece.value() - 7.7) < 1e-6
    assert abs(p.blank_thickness.value() - 6.5) < 1e-6
    assert rebuilt, "loading a preset must emit castle_changed (drives the preview)"

    style_store.delete_style("Bold rim")
    p._refresh_style_combo()
    assert "Bold rim" not in [p.style_combo.itemText(i)
                              for i in range(p.style_combo.count())]
