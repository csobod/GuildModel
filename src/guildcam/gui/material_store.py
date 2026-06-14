"""Material presets with user overrides (BUILDPLAN M4.x).

The shipped baseline lives in ``config/materials.yaml`` and is never written.
User edits to a material's CAM defaults (feeds / speeds / stepover / stepdown)
are stored as overrides in ``~/.guildcam/materials.yaml`` and merged over the
baseline at load — the same DEFAULTS-merge pattern as prefs. This lets the CAM
tab populate from the selected material, the user override per material, and
"Reset to shipped" restore the baseline by dropping the override.
"""
from __future__ import annotations

import pathlib

import yaml

_SHIPPED = pathlib.Path(__file__).resolve().parents[1] / "config" / "materials.yaml"
_USER = pathlib.Path.home() / ".guildcam" / "materials.yaml"

# The per-material CAM fields the CAM tab drives and can write back.
CAM_KEYS = [
    "spindle_rpm", "feed_rate_mmpm", "plunge_rate_mmpm",
    "relief_stepover_mm", "contour_stepdown_mm", "rough_axial_stock_mm",
]


def _read(path: pathlib.Path) -> dict:
    try:
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def shipped() -> dict:
    return _read(_SHIPPED)


def _user() -> dict:
    return _read(_USER)


def _write_user(data: dict) -> None:
    try:
        _USER.parent.mkdir(parents=True, exist_ok=True)
        _USER.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except Exception:
        pass


def effective() -> dict:
    """Shipped materials with user overrides merged per material/per key."""
    base = shipped()
    over = _user()
    merged = {name: dict(vals) for name, vals in base.items()}
    for name, vals in over.items():
        if not isinstance(vals, dict):
            continue
        merged.setdefault(name, {}).update(vals)
    return merged


def names() -> list[str]:
    return list(effective().keys())


def material(name: str) -> dict:
    return effective().get(name, {})


def shipped_material(name: str) -> dict:
    return shipped().get(name, {})


def cam_values(name: str) -> dict:
    """Just the CAM_KEYS for a material (effective), missing keys omitted."""
    m = material(name)
    return {k: m[k] for k in CAM_KEYS if k in m}


def changed_keys(name: str, values: dict, tol: float = 1e-6) -> list[str]:
    """CAM_KEYS in `values` that differ from the material's effective default."""
    base = material(name)
    out = []
    for k in CAM_KEYS:
        if k not in values or k not in base:
            continue
        if abs(float(values[k]) - float(base[k])) > tol:
            out.append(k)
    return out


def save_override(name: str, values: dict) -> None:
    """Merge the given CAM values into this material's user override and persist."""
    data = _user()
    entry = dict(data.get(name, {}))
    for k in CAM_KEYS:
        if k in values:
            entry[k] = values[k]
    data[name] = entry
    _write_user(data)


def reset_material(name: str) -> None:
    """Drop the user override for one material (revert to shipped)."""
    data = _user()
    if name in data:
        del data[name]
        _write_user(data)


def reset_all() -> None:
    _write_user({})
