"""Read/write the ``.gmodel`` project container (BUILDPLAN M5.1).

A ``.gmodel`` file is a ZIP archive holding everything needed to **(a)** reopen the
whole project in GuildModel with no external files and **(b)** hand the job to a
gSender fork. Layout:

    manifest.json      format / app / version, timestamps, run mode, SHA-256 inventory
    project.json       the full ProjectSchema (boxing / castle / cam_params / components / …)
    source.dxf         the imported GuildDraw DXF (single frame-front reopen)
    source.gdraw       OR a whole-model GuildDraw drawing (multi-component reopen)
    program/*.nc       generated G-code (posterior_cut.nc [, anterior_cut.nc], or two_sided_cut.nc)
    machine.yaml       snapshot of the active MachineProfile
    setup.json         setup sheet (tool, feeds, op order, cut lengths, est. time)
    cut_report.json    cut-simulation verification (completeness / gouge + time)
    model.stl          (optional) cut-piece mesh for inspection
    preview.png        (optional) render thumbnail
    features/<id>.stl  the sculpts' source meshes (M22), one per SculptFeature

The **gSender-fork hand-off subset** is ``program/*.nc`` + ``machine.yaml`` +
``setup.json`` (+ ``manifest.json`` for the two-file flip). See
``docs/GMODEL-FORMAT.md``. Everything but the manifest and project is optional, so a
``.gmodel`` can be saved at any stage (after import; after generation) — which is
what drives the readiness traffic-light (M5.2).
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .schema import MachineProfile, ProjectSchema

#: 2 since M22: a `features/` folder may hold the sculpts' STL bytes. A reader
#: tolerates its absence, so a version-1 file loads with no sculpts.
FORMAT_VERSION = 2

_MANIFEST = "manifest.json"
_PROJECT = "project.json"
_SOURCE = "source.dxf"
_SOURCE_GDRAW = "source.gdraw"   # a whole-model GuildDraw drawing (multi-component)
_MACHINE = "machine.yaml"
_SETUP = "setup.json"
_REPORT = "cut_report.json"
_STL = "model.stl"
_PREVIEW = "preview.png"
_PROGRAM_DIR = "program"
_FEATURES_DIR = "features"
# Every component's own program set, so a whole-model project keeps the
# temple programs as well as the front's: ``components/<id>/program/*.nc``
# plus that component's setup / machine / cut report. The worktable program
# has a slot of its own under the same tree (`WORKTABLE_ID`, M20). The
# top-level set is the job GuildSend streams: the bed program when the
# project has one, else the active component's.
_COMPONENTS_DIR = "components"
WORKTABLE_ID = "worktable"

#: files (besides ``program/*.nc``) that a gSender fork consumes
HANDOFF_FILES = (_MANIFEST, _MACHINE, _SETUP)


class GModelError(Exception):
    """Raised on a malformed or corrupted .gmodel container."""


def _guildmodel_version() -> str:
    """Best-effort package version for the manifest (in-source __version__ first,
    since an editable install's metadata can lag the source)."""
    try:
        import guildmodel
        v = getattr(guildmodel, "__version__", None)
        if v:
            return v
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("guildmodel")
    except Exception:
        return "0"


@dataclass
class GModelBundle:
    """The parsed contents of a ``.gmodel`` file."""
    project: ProjectSchema
    manifest: dict
    dxf_bytes: bytes | None = None
    gdraw_bytes: bytes | None = None
    programs: dict[str, str] = field(default_factory=dict)
    #: Per component id: {"programs", "setup", "machine", "report"} — see
    #: `_COMPONENTS_DIR`. Empty for a bundle saved before v1.8.0.
    component_artifacts: dict[str, dict] = field(default_factory=dict)
    machine: dict | None = None
    setup: dict | None = None
    report: dict | None = None
    stl_bytes: bytes | None = None
    preview_bytes: bytes | None = None
    #: ``features/<id>.stl`` by feature id: the sculpts' sources (M22).
    features: dict[str, bytes] = field(default_factory=dict)
    #: What the load changed to read an older file as it was cut, a line each.
    migrated: list[str] = field(default_factory=list)

    @property
    def run_mode(self) -> str:
        return self.manifest.get("run_mode", "two_file")

    def has_program(self) -> bool:
        return bool(self.programs)


def component_key(component_id: str) -> str:
    """A component id as a zip directory name: one path segment, whatever
    GuildDraw called the workspace."""
    return str(component_id).replace("/", "_").replace("\\", "_") or "component"


def save_gmodel(
    path,
    *,
    project: ProjectSchema,
    dxf_bytes: bytes | None = None,
    gdraw_bytes: bytes | None = None,
    programs: dict[str, str] | None = None,
    machine: "MachineProfile | dict | None" = None,
    setup: dict | None = None,
    report: dict | None = None,
    stl_bytes: bytes | None = None,
    preview_bytes: bytes | None = None,
    run_mode: str = "two_file",
    created: str | None = None,
    component_artifacts: dict[str, dict] | None = None,
    features: dict[str, bytes] | None = None,
) -> None:
    """Write a ``.gmodel`` container. Only ``project`` is required; pass whatever of
    the rest exists at this stage. Written atomically (temp file + replace)."""
    path = Path(path)
    files: dict[str, bytes] = {
        _PROJECT: project.model_dump_json(indent=2).encode("utf-8"),
    }
    if dxf_bytes is not None:
        files[_SOURCE] = bytes(dxf_bytes)
    if gdraw_bytes is not None:
        files[_SOURCE_GDRAW] = bytes(gdraw_bytes)
    for name, text in (programs or {}).items():
        files[f"{_PROGRAM_DIR}/{name}"] = text.encode("utf-8")
    if machine is not None:
        md = machine.model_dump() if isinstance(machine, MachineProfile) else dict(machine)
        files[_MACHINE] = yaml.safe_dump(md, sort_keys=False).encode("utf-8")
    if setup is not None:
        files[_SETUP] = json.dumps(setup, indent=2, default=str).encode("utf-8")
    if report is not None:
        files[_REPORT] = json.dumps(report, indent=2, default=str).encode("utf-8")
    for cid, art in (component_artifacts or {}).items():
        base = f"{_COMPONENTS_DIR}/{component_key(cid)}"
        for name, text in (art.get("programs") or {}).items():
            files[f"{base}/{_PROGRAM_DIR}/{name}"] = text.encode("utf-8")
        if art.get("machine") is not None:
            m = art["machine"]
            md = m.model_dump() if isinstance(m, MachineProfile) else dict(m)
            files[f"{base}/{_MACHINE}"] = yaml.safe_dump(md, sort_keys=False).encode("utf-8")
        if art.get("setup") is not None:
            files[f"{base}/{_SETUP}"] = json.dumps(art["setup"], indent=2, default=str).encode("utf-8")
        if art.get("report") is not None:
            files[f"{base}/{_REPORT}"] = json.dumps(art["report"], indent=2, default=str).encode("utf-8")
    if stl_bytes is not None:
        files[_STL] = bytes(stl_bytes)
    if preview_bytes is not None:
        files[_PREVIEW] = bytes(preview_bytes)
    for fid, data in (features or {}).items():
        files[f"{_FEATURES_DIR}/{component_key(fid)}.stl"] = bytes(data)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "format": "gmodel",
        "format_version": FORMAT_VERSION,
        "app": "GuildModel",
        "app_version": _guildmodel_version(),
        "created": created or now,
        "modified": now,
        "run_mode": run_mode,
        "contents": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(files.items())
        },
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_MANIFEST, json.dumps(manifest, indent=2))
        for name, data in sorted(files.items()):
            zf.writestr(name, data)
    tmp.replace(path)


def load_gmodel(path, verify: bool = True) -> GModelBundle:
    """Read a ``.gmodel`` container into a :class:`GModelBundle`. Verifies the
    manifest's SHA-256 inventory unless ``verify=False``.

    Every failure is a `GModelError`: a damaged file raised whatever the part
    it broke raised, a JSON or a CRC or a UTF-8 error, past the window's
    handler, and a damaged file opened from the desktop closed the app at
    launch (the 2.0 bug hunt)."""
    path = Path(path)
    try:
        return _load_gmodel(path, verify)
    except GModelError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise GModelError(f"{path.name} could not be read: {exc}") from exc


def _load_gmodel(path: Path, verify: bool) -> GModelBundle:
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        raise GModelError(f"{path.name} is not a valid .gmodel (not a zip): {exc}") from exc
    with zf:
        names = set(zf.namelist())
        if _MANIFEST not in names or _PROJECT not in names:
            raise GModelError(
                f"{path.name} is not a valid .gmodel (missing manifest/project)")
        manifest = json.loads(zf.read(_MANIFEST))
        if verify:
            for name, meta in manifest.get("contents", {}).items():
                if name not in names:
                    raise GModelError(f"manifest lists a missing file: {name}")
                if hashlib.sha256(zf.read(name)).hexdigest() != meta.get("sha256"):
                    raise GModelError(f"checksum mismatch on {name} — file corrupted")
        from .schema import collect_corrections
        try:
            text = zf.read(_PROJECT).decode("utf-8")
            with collect_corrections() as corrected:
                project = ProjectSchema.model_validate_json(text)
        except Exception as exc:
            raise GModelError(f"invalid project.json: {exc}") from exc
        # A legacy single-component .gmodel (M5.1–M6.5) has no `components`; migrate
        # it to a one-component (frame_front) project on load (BUILDPLAN M7.1).
        project.ensure_components()
        # a value out of range was replaced as the file was read (`schema._sane`)
        migrated: list[str] = [f"{line}, out of range" for line in corrected]
        if "two_sided" not in (json.loads(text).get("cam_params") or {}):
            # A file from before two-sided machining (M24) was cut from the
            # back alone, an anterior feature modeled and never posted. Read
            # as Auto, it became a two-setup job on its first Generate (the
            # 2.0 bug hunt); it opens Off, as it was cut.
            project.cam_params.two_sided = "off"
            migrated.append("Two-sided is Off, as the file was cut before two-sided "
                            "machining; set it on the Cut tab to cut the front's features")

        programs = {
            n[len(_PROGRAM_DIR) + 1:]: zf.read(n).decode("utf-8")
            for n in names if n.startswith(_PROGRAM_DIR + "/") and not n.endswith("/")
        }
        features = {
            n[len(_FEATURES_DIR) + 1:-4]: zf.read(n)
            for n in names if n.startswith(_FEATURES_DIR + "/") and n.endswith(".stl")
        }
        component_artifacts: dict[str, dict] = {}
        for n in sorted(names):
            if not n.startswith(_COMPONENTS_DIR + "/") or n.endswith("/"):
                continue
            parts = n.split("/")
            if len(parts) < 3:
                continue
            art = component_artifacts.setdefault(
                parts[1], {"programs": {}, "setup": None, "machine": None, "report": None})
            rest = "/".join(parts[2:])
            if rest.startswith(_PROGRAM_DIR + "/"):
                art["programs"][rest[len(_PROGRAM_DIR) + 1:]] = zf.read(n).decode("utf-8")
            elif rest == _MACHINE:
                art["machine"] = yaml.safe_load(zf.read(n))
            elif rest == _SETUP:
                art["setup"] = json.loads(zf.read(n))
            elif rest == _REPORT:
                art["report"] = json.loads(zf.read(n))
        return GModelBundle(
            project=project,
            manifest=manifest,
            migrated=migrated,
            dxf_bytes=zf.read(_SOURCE) if _SOURCE in names else None,
            gdraw_bytes=zf.read(_SOURCE_GDRAW) if _SOURCE_GDRAW in names else None,
            programs=programs,
            component_artifacts=component_artifacts,
            machine=yaml.safe_load(zf.read(_MACHINE)) if _MACHINE in names else None,
            setup=json.loads(zf.read(_SETUP)) if _SETUP in names else None,
            report=json.loads(zf.read(_REPORT)) if _REPORT in names else None,
            stl_bytes=zf.read(_STL) if _STL in names else None,
            preview_bytes=zf.read(_PREVIEW) if _PREVIEW in names else None,
            features=features,
        )


def extract_handoff(path, dest_dir) -> list[Path]:
    """Extract the gSender-fork subset (``program/*.nc`` + machine + setup +
    manifest) to ``dest_dir``. Returns the written paths."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            keep = name in HANDOFF_FILES or (
                name.startswith(_PROGRAM_DIR + "/") and not name.endswith("/"))
            if not keep:
                continue
            out = dest / name
            # A member named `program/../../x.nc` wrote outside the destination
            # (the 2.0 bug hunt): only what resolves inside it is written.
            if not out.resolve().is_relative_to(dest.resolve()):
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(name))
            written.append(out)
    return written
