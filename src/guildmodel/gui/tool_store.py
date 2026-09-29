"""Tool library with user overrides (BUILDPLAN M7.8).

The shipped baseline lives in ``config/tools.yaml`` and is never written. User
edits, additions, and deletions live in ``~/.guildmodel/tools.yaml`` and are merged
over the baseline at load — the same DEFAULTS-merge pattern as `material_store`,
extended so the user can also **add** a tool (a new key) and **delete** a shipped
tool (a ``{"_deleted": true}`` tombstone). This is what frees the maker from
hand-editing ``tools.yaml``: the Preferences ▸ Tools editor reads/writes here.

`effective()` returns the same ``{name: tool_dict}`` shape `yaml.safe_load`
returned before, so every existing consumer (the CAM combos, generation, the post,
the sim) is unchanged — only the *source* of the tools widens. User entries are
written through `ToolSpec`, so a merged dict is always consumer-complete (carries
the derived ``radius_mm`` etc.).
"""
from __future__ import annotations

import pathlib

import yaml

from guildmodel.core.cam.tooling import ToolSpec

_SHIPPED = pathlib.Path(__file__).resolve().parents[1] / "config" / "tools.yaml"
_USER = pathlib.Path.home() / ".guildmodel" / "tools.yaml"


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



#: The merged table, keyed on the files' (mtime, size): the Cut tab and the
#: workers ask for a tool or a material per change, and re-reading two YAML
#: files each time was most of a keystroke's cost.
_cache: tuple | None = None


def _stamp(path: pathlib.Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)

def effective() -> dict:
    """Shipped tools with user overrides/additions merged and deletions removed."""
    global _cache
    key = (str(_SHIPPED), _stamp(_SHIPPED), str(_USER), _stamp(_USER))
    if _cache is None or _cache[0] != key:
        _cache = (key, _merge())
    return {name: dict(vals) for name, vals in _cache[1].items()}


def _merge() -> dict:
    merged = {name: dict(vals) for name, vals in shipped().items()}
    for name, vals in _user().items():
        if not isinstance(vals, dict):
            continue
        if vals.get("_deleted"):
            merged.pop(name, None)
            continue
        merged[name] = dict(vals)           # user entry is a complete tool (ToolSpec)
    return merged


# alias for call sites that read the tool table (e.g. the CAM workers)
def tools_cfg() -> dict:
    return effective()


def names() -> list[str]:
    return list(effective().keys())


def tool(name: str) -> dict:
    return effective().get(name, {})


def shipped_tool(name: str) -> dict:
    return shipped().get(name, {})


def is_shipped(name: str) -> bool:
    return name in shipped()


def spec(name: str) -> ToolSpec:
    """The typed view of a tool (for the editor / visualizer)."""
    return ToolSpec.from_dict(effective().get(name, {}))


def save_tool(name: str, spec_or_dict) -> None:
    """Persist a tool as a user override/addition (the full normalized entry)."""
    s = spec_or_dict if isinstance(spec_or_dict, ToolSpec) else ToolSpec.from_dict(spec_or_dict)
    data = _user()
    data[name] = s.to_yaml()
    _write_user(data)


_FEED_KEYS = ("feed_rate_mmpm", "plunge_rate_mmpm", "spindle_rpm")


def feed_departures(name: str, feeds) -> dict:
    """Which of a project's per-tool feeds (a `ToolFeeds` or a dict) differ from
    the library's entry for `name`: field -> the project's value. A field the
    library does not carry counts as different; a tool the library does not
    know, or nothing set, gives {} (2026-09-27, the write-back offer)."""
    t = tool(name)
    if not t:
        return {}
    out: dict = {}
    for key in _FEED_KEYS:
        v = feeds.get(key) if isinstance(feeds, dict) else getattr(feeds, key, None)
        if v is None:
            continue
        lib = t.get(key)
        if lib is None or abs(float(lib) - float(v)) > 1e-6:
            out[key] = float(v)
    return out


def save_feeds(name: str, feeds: dict) -> None:
    """Write feed / plunge / spindle onto the tool's library entry, keeping the
    rest of the tool as it is (the write-back of a project's per-tool feeds)."""
    s = spec(name)
    for key in _FEED_KEYS:
        v = feeds.get(key)
        if v is not None:
            setattr(s, key, float(v))
    save_tool(name, s)


def delete_tool(name: str) -> None:
    """Hide a tool: tombstone a shipped one, drop a user-added one."""
    data = _user()
    if is_shipped(name):
        data[name] = {"_deleted": True}
    else:
        data.pop(name, None)
    _write_user(data)


def reset_tool(name: str) -> None:
    """Drop a tool's user entry — reverts to shipped, or un-hides a tombstoned one."""
    data = _user()
    if name in data:
        del data[name]
        _write_user(data)


def reset_all() -> None:
    _write_user({})


def replace_user(data: dict) -> None:
    """Overwrite the whole user library file (the Preferences ▸ Tools editor commits
    its staged state at once: overrides, additions, and ``_deleted`` tombstones)."""
    _write_user(dict(data))


def export_library(path) -> None:
    """Write the whole effective library to a shareable ``.tools`` YAML file."""
    pathlib.Path(path).write_text(
        yaml.safe_dump(effective(), sort_keys=False), encoding="utf-8")


def import_library(path, *, replace: bool = False) -> int:
    """Merge tools from a library file into the user overrides (non-destructive by
    default; ``replace=True`` first clears existing user entries). Returns the count
    imported."""
    incoming = _read(pathlib.Path(path))
    if not isinstance(incoming, dict):
        return 0
    data = {} if replace else _user()
    n = 0
    for name, vals in incoming.items():
        if not isinstance(vals, dict) or vals.get("_deleted"):
            continue
        data[name] = ToolSpec.from_dict(vals).to_yaml()
        n += 1
    _write_user(data)
    return n
