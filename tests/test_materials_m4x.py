"""Material store: shipped defaults + user overrides + write-back (BUILDPLAN M4.x).

The CAM tab populates feeds/speeds/stepover/stepdown from the selected material;
edits can be written back as per-user overrides (~/.guildmodel/materials.yaml),
merged over the shipped baseline, and reset to shipped.
"""
import pytest

from guildmodel.gui import material_store


@pytest.fixture
def tmp_user(tmp_path, monkeypatch):
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    return tmp_path / "materials.yaml"


def test_shipped_has_cam_defaults():
    eff = material_store.effective()
    assert "acetate" in eff and "horn" in eff
    for key in material_store.CAM_KEYS:
        assert key in eff["acetate"], f"acetate missing {key}"
    assert eff["acetate"]["relief_stepover_mm"] == 0.9
    assert eff["horn"]["contour_stepdown_mm"] == 0.8


def test_cam_values_subset():
    vals = material_store.cam_values("acetate")
    assert set(vals) == set(material_store.CAM_KEYS)


def test_changed_keys_detects_edits():
    base = material_store.cam_values("acetate")
    assert material_store.changed_keys("acetate", base) == []
    edited = dict(base, feed_rate_mmpm=base["feed_rate_mmpm"] + 100)
    assert material_store.changed_keys("acetate", edited) == ["feed_rate_mmpm"]


def test_override_roundtrip_and_reset(tmp_user):
    base = material_store.cam_values("acetate")
    edited = dict(base, feed_rate_mmpm=999.0, relief_stepover_mm=1.3)
    material_store.save_override("acetate", edited)

    eff = material_store.effective()
    assert eff["acetate"]["feed_rate_mmpm"] == 999.0
    assert eff["acetate"]["relief_stepover_mm"] == 1.3
    # shipped baseline is untouched
    assert material_store.shipped_material("acetate")["feed_rate_mmpm"] == 750
    # a now-matching value is no longer "changed"
    assert material_store.changed_keys("acetate", eff["acetate"]) == []

    material_store.reset_material("acetate")
    assert material_store.effective()["acetate"]["feed_rate_mmpm"] == 750


def test_reset_all(tmp_user):
    material_store.save_override("horn", {"feed_rate_mmpm": 123.0})
    assert material_store.effective()["horn"]["feed_rate_mmpm"] == 123.0
    material_store.reset_all()
    assert material_store.effective()["horn"]["feed_rate_mmpm"] == 400
