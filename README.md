# GuildModel

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildModel takes a GuildDraw frame-front DXF and builds the posterior relief the
way a maker models it — the **castle**: tower zones (endpieces, bridge,
nosepads), eyewire walls, and rolling-ball footing fillets — then generates
the five-operation single-tool GRBL program (hinge pockets → rough relief →
fine relief → eyewires → perimeter, released by a hand-finished onion skin)
for the Guild CNC fixture.

## Status

**v1.0.0.** GuildModel builds the posterior castle relief and the
five-operation single-tool GRBL program for a frame front, its temples, and
per-lens base-curve forming blocks — with worktable nesting, cut simulation, a
maker's guide (`docs/USER-GUIDE.md`), and an optional lens bevel groove
(drageoir V-groove in each eyewire wall, off by default).

The **frame-front workflow is hardware-proven**: a frame front has been cut on
real acetate end-to-end (GuildDraw DXF → castle relief → five-op GRBL program →
cut on a Carbide 3D Nomad). This is the core of the tool.

The **temple, base-curve-block, worktable-nesting, and lens-groove paths are
beta** — fully built and verified in cut-simulation, but not yet
hardware-validated on real stock. They work; treat their first real cuts as
you would any new program (air-cut, then a test piece). The two-sided
(cut-and-flip) workflow is planned for a later release.

See `BUILDPLAN.md` for the full milestone history and roadmap.

## Requirements

Python 3.12 or newer (the packaged Windows installer bundles its own runtime —
no Python needed to run it).

## Install (Windows)

Download `GuildModel-<version>-setup.exe` from the release and run it. It is a
per-user install (no admin prompt) and registers the `.gmodel` project type. To
build the installer yourself, see `scripts/build_release.ps1`.

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
