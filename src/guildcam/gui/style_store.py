"""Frame-style presets — named CastleParams snapshots (BUILDPLAN M7.16).

The third use of the store pattern (materials M4.9, tools M7.8): a shipped baseline
('Guild demo' = the reference `CastleParams`, computed from the schema default so it
never drifts) merged with the maker's own presets in ``~/.guildcam/frame_styles.yaml``
— the same DEFAULTS-merge with add / override / ``_deleted`` tombstone semantics.

A preset captures a frame's *style* (zone heights, footing schedule, stock, onion
skin, allowance). It **seeds** a new frame; the ``.gcam`` still stores the frame's
actual params, so presets are project-independent.
"""
from __future__ import annotations

import pathlib

import yaml

from guildcam.core.project.schema import CastleParams

_USER = pathlib.Path.home() / ".guildcam" / "frame_styles.yaml"
_SHIPPED_NAME = "Guild demo"


def _read(path: pathlib.Path) -> dict:
    try:
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def shipped() -> dict:
    """The built-in presets, computed from the schema default (never written)."""
    return {_SHIPPED_NAME: CastleParams().model_dump()}


def _user() -> dict:
    return _read(_USER)


def _write_user(data: dict) -> None:
    try:
        _USER.parent.mkdir(parents=True, exist_ok=True)
        _USER.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except Exception:
        pass


def effective() -> dict:
    """Shipped presets with the user's additions/overrides merged and deletes removed."""
    merged = {name: dict(vals) for name, vals in shipped().items()}
    for name, vals in _user().items():
        if not isinstance(vals, dict):
            continue
        if vals.get("_deleted"):
            merged.pop(name, None)
            continue
        merged[name] = dict(vals)
    return merged


def names() -> list[str]:
    return list(effective().keys())


def is_shipped(name: str) -> bool:
    return name in shipped()


def style(name: str) -> CastleParams | None:
    """The named preset as a `CastleParams`, or None if it doesn't exist."""
    d = effective().get(name)
    if not d:
        return None
    return CastleParams(**d)


def save_style(name: str, params) -> None:
    """Persist a preset as a user entry (a full CastleParams snapshot)."""
    d = params.model_dump() if isinstance(params, CastleParams) else dict(params)
    data = _user()
    data[name] = d
    _write_user(data)


def delete_style(name: str) -> None:
    """Remove a preset: tombstone a shipped one, drop a user-added one."""
    data = _user()
    if is_shipped(name):
        data[name] = {"_deleted": True}
    else:
        data.pop(name, None)
    _write_user(data)


def reset_style(name: str) -> None:
    """Drop a preset's user entry — reverts to shipped / un-hides a tombstoned one."""
    data = _user()
    if name in data:
        del data[name]
        _write_user(data)


def reset_all() -> None:
    _write_user({})
