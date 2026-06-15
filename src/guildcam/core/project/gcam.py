"""Read/write the ``.gcam`` project container (BUILDPLAN M5.1).

A ``.gcam`` file is a ZIP archive holding everything needed to **(a)** reopen the
whole project in GuildCAM with no external files and **(b)** hand the job to a
gSender fork. Layout:

    manifest.json      format / app / version, timestamps, run mode, SHA-256 inventory
    project.json       the full ProjectSchema (boxing / castle / cam_params / …)
    source.dxf         the imported GuildDraw DXF (self-contained reopen)
    program/*.nc       generated G-code (posterior_cut.nc [, back_cut.nc])
    machine.yaml       snapshot of the active MachineProfile
    setup.json         setup sheet (tool, feeds, op order, cut lengths, est. time)
    cut_report.json    cut-simulation verification (completeness / gouge + time)
    model.stl          (optional) cut-piece mesh for inspection
    preview.png        (optional) render thumbnail

The **gSender-fork hand-off subset** is ``program/*.nc`` + ``machine.yaml`` +
``setup.json`` (+ ``manifest.json`` for the two-file flip). See
``docs/GCAM-FORMAT.md``. Everything but the manifest and project is optional, so a
``.gcam`` can be saved at any stage (after import; after generation) — which is
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

FORMAT_VERSION = 1

_MANIFEST = "manifest.json"
_PROJECT = "project.json"
_SOURCE = "source.dxf"
_MACHINE = "machine.yaml"
_SETUP = "setup.json"
_REPORT = "cut_report.json"
_STL = "model.stl"
_PREVIEW = "preview.png"
_PROGRAM_DIR = "program"

#: files (besides ``program/*.nc``) that a gSender fork consumes
HANDOFF_FILES = (_MANIFEST, _MACHINE, _SETUP)


class GcamError(Exception):
    """Raised on a malformed or corrupted .gcam container."""


def _guildcam_version() -> str:
    """Best-effort package version for the manifest (in-source __version__ first,
    since an editable install's metadata can lag the source)."""
    try:
        import guildcam
        v = getattr(guildcam, "__version__", None)
        if v:
            return v
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("guildcam")
    except Exception:
        return "0"


@dataclass
class GcamBundle:
    """The parsed contents of a ``.gcam`` file."""
    project: ProjectSchema
    manifest: dict
    dxf_bytes: bytes | None = None
    programs: dict[str, str] = field(default_factory=dict)
    machine: dict | None = None
    setup: dict | None = None
    report: dict | None = None
    stl_bytes: bytes | None = None
    preview_bytes: bytes | None = None

    @property
    def run_mode(self) -> str:
        return self.manifest.get("run_mode", "two_file")

    def has_program(self) -> bool:
        return bool(self.programs)


def save_gcam(
    path,
    *,
    project: ProjectSchema,
    dxf_bytes: bytes | None = None,
    programs: dict[str, str] | None = None,
    machine: "MachineProfile | dict | None" = None,
    setup: dict | None = None,
    report: dict | None = None,
    stl_bytes: bytes | None = None,
    preview_bytes: bytes | None = None,
    run_mode: str = "two_file",
    created: str | None = None,
) -> None:
    """Write a ``.gcam`` container. Only ``project`` is required; pass whatever of
    the rest exists at this stage. Written atomically (temp file + replace)."""
    path = Path(path)
    files: dict[str, bytes] = {
        _PROJECT: project.model_dump_json(indent=2).encode("utf-8"),
    }
    if dxf_bytes is not None:
        files[_SOURCE] = bytes(dxf_bytes)
    for name, text in (programs or {}).items():
        files[f"{_PROGRAM_DIR}/{name}"] = text.encode("utf-8")
    if machine is not None:
        md = machine.model_dump() if isinstance(machine, MachineProfile) else dict(machine)
        files[_MACHINE] = yaml.safe_dump(md, sort_keys=False).encode("utf-8")
    if setup is not None:
        files[_SETUP] = json.dumps(setup, indent=2, default=str).encode("utf-8")
    if report is not None:
        files[_REPORT] = json.dumps(report, indent=2, default=str).encode("utf-8")
    if stl_bytes is not None:
        files[_STL] = bytes(stl_bytes)
    if preview_bytes is not None:
        files[_PREVIEW] = bytes(preview_bytes)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "format": "gcam",
        "format_version": FORMAT_VERSION,
        "app": "GuildCAM",
        "app_version": _guildcam_version(),
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


def load_gcam(path, verify: bool = True) -> GcamBundle:
    """Read a ``.gcam`` container into a :class:`GcamBundle`. Verifies the
    manifest's SHA-256 inventory unless ``verify=False``."""
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        raise GcamError(f"{path.name} is not a valid .gcam (not a zip): {exc}") from exc
    with zf:
        names = set(zf.namelist())
        if _MANIFEST not in names or _PROJECT not in names:
            raise GcamError(
                f"{path.name} is not a valid .gcam (missing manifest/project)")
        manifest = json.loads(zf.read(_MANIFEST))
        if verify:
            for name, meta in manifest.get("contents", {}).items():
                if name not in names:
                    raise GcamError(f"manifest lists a missing file: {name}")
                if hashlib.sha256(zf.read(name)).hexdigest() != meta.get("sha256"):
                    raise GcamError(f"checksum mismatch on {name} — file corrupted")
        try:
            project = ProjectSchema.model_validate_json(zf.read(_PROJECT).decode("utf-8"))
        except Exception as exc:
            raise GcamError(f"invalid project.json: {exc}") from exc

        programs = {
            n[len(_PROGRAM_DIR) + 1:]: zf.read(n).decode("utf-8")
            for n in names if n.startswith(_PROGRAM_DIR + "/") and not n.endswith("/")
        }
        return GcamBundle(
            project=project,
            manifest=manifest,
            dxf_bytes=zf.read(_SOURCE) if _SOURCE in names else None,
            programs=programs,
            machine=yaml.safe_load(zf.read(_MACHINE)) if _MACHINE in names else None,
            setup=json.loads(zf.read(_SETUP)) if _SETUP in names else None,
            report=json.loads(zf.read(_REPORT)) if _REPORT in names else None,
            stl_bytes=zf.read(_STL) if _STL in names else None,
            preview_bytes=zf.read(_PREVIEW) if _PREVIEW in names else None,
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
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(name))
            written.append(out)
    return written
