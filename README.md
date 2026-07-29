# GuildModel

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildModel takes a GuildDraw frame-front DXF and builds the posterior relief the
way a maker models it — the **castle**: tower zones (endpieces, bridge,
nosepads), eyewire walls, and rolling-ball footing fillets — then generates
the five-operation single-tool GRBL program (hinge pockets → rough relief →
fine relief → eyewires → perimeter, released by a hand-finished onion skin)
for the Guild CNC fixture.

## Status

**v1.1.0.** GuildModel builds the posterior castle relief and the
five-operation single-tool GRBL program for a frame front, its temples, and
per-lens base-curve forming blocks — with worktable nesting, cut simulation, a
maker's guide (`docs/USER-GUIDE.md`), and an optional lens bevel groove
(drageoir V-groove in each eyewire wall, off by default).

> **Upgrading from v1.0.0:** worktable programs built their relief on the
> 3D-preview grid rather than the cutting grid, which put a lot of unnecessary Z
> motion into the toolpath. Re-nest and re-post any `worktable.nc` you still have
> before running it — the fix is in the generator, not the file. Single-component
> programs were unaffected.

The **whole-bed workflow is now hardware-proven**: a complete nested worktable —
frame front, both temples, and both base-curve forming blocks — has been cut on
real stock in one program on the Guild CNC (LUNYEE 3020 Nova), on top of the
existing end-to-end frame-front proof (GuildDraw DXF → castle relief → five-op
GRBL program → cut on a Carbide 3D Nomad).

Still **beta**: the **lens bevel groove** (built and verified in cut-simulation,
off by default, not yet cut on real stock) — treat its first real cuts as you
would any new program (air-cut, then a test piece). The two-sided (cut-and-flip)
workflow is planned for a later release.

See `BUILDPLAN.md` for the full milestone history and roadmap.

## Requirements

Python 3.12 or newer (the packaged Windows installer bundles its own runtime —
no Python needed to run it).

## Install (Windows)

Download `GuildModel-<version>-setup.exe` from the release and run it. It is a
per-user install (no admin prompt) and registers the `.gmodel` project type. It
is not code-signed, so SmartScreen warns on first run — **More info ▸ Run
anyway**.

To build it yourself on Windows: `scripts\build_release.ps1` (needs
[Inno Setup](https://jrsoftware.org/isdl.php) for the installer; it produces the
portable `.zip` without it).

## Building releases without that platform

Neither release build needs a machine of its own. Both workflows are manual —
**Actions ▸ (workflow) ▸ Run workflow** — and upload their artifacts for you to
attach to a GitHub release:

| Workflow | Runner | Artifacts |
|---|---|---|
| `.github/workflows/windows-build.yml` | `windows-latest` | portable `.zip` + `setup.exe` |
| `.github/workflows/macos-build.yml` | `macos-14` (arm64), `macos-15-intel` (x86_64) | `.zip` + `.dmg` per architecture |

Each runs the same release script a maker would run locally
(`scripts\build_release.ps1` / `scripts/build_release_macos.sh`), so a CI build
and a hand build cannot drift apart. Both gate on the full test suite first.
PyInstaller does not cross-compile, which is why this is a matter of borrowing a
runner rather than building everything in one place.

## Installation (development)

```
pip install -e ".[dev]"
```

## Running the app

The install registers a `guildmodel` entry point:

```
guildmodel
```

or, without activating the venv:

```
.venv\Scripts\guildmodel.exe          # Windows
.venv\Scripts\python -m guildmodel.gui.app
```

The app opens with an empty workspace; use **File ▸ Open Drawing** (a GuildDraw
`.gdraw`) or **File ▸ Open DXF** to load a design. A reference frame front that
exercises the full castle pipeline (9 zones, hinge pockets, five-op G-code) is
vendored under `tests/fixtures/demo/`.

### Linux: Wayland crashes "Build 3D Model" — run under XWayland

On a native Wayland session, **Build 3D Model** builds the mesh successfully
(that part is pure Python/CPU) but then crashes the app when it tries to
display it. PyVista/VTK's Linux renderer (`vtkXOpenGLRenderWindow`) is X11-only
— under Qt's native `wayland` platform plugin it can't embed its render window
(`BadWindow` / `X_ConfigureWindow` errors, then a segfault). Force Qt onto
XWayland instead:

```
QT_QPA_PLATFORM=xcb guildmodel
```

If you're launching from a `.desktop` file, set it there:

```
Exec=env QT_QPA_PLATFORM=xcb /path/to/.venv/bin/guildmodel
```

## Running tests

```
pytest
```

## License

GPLv3 or later. See `LICENSE`.
