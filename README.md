# GuildModel

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildModel takes a GuildDraw frame-front DXF and builds the posterior relief the
way a maker models it — the **castle**: tower zones (endpieces, bridge,
nosepads), eyewire walls, and rolling-ball footing fillets — then generates
the five-operation single-tool GRBL program (hinge pockets → rough relief →
fine relief → eyewires → perimeter, released by a hand-finished onion skin)
for the Guild CNC fixture.

## Status

**v1.0.0-rc1** — release candidate, plus the posterior finishing features
(pad splay chamfer, bezeled eyewire, bridge projection relief — all optional,
off by default).

The **frame-front workflow is hardware-proven**: a frame front has been cut on
real acetate end-to-end (GuildDraw DXF → castle relief → five-op GRBL program →
cut on a Carbide 3D Nomad). This is the core of the tool and the focus of RC1.

The **temple, base-curve-block, and worktable-nesting paths are beta** — fully
built and verified in cut-simulation, but not yet hardware-validated on real
stock. They work; treat their first real cuts as you would any new program
(air-cut, then a test piece). The two-sided (cut-and-flip) workflow is planned
for a later release.

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

In a development checkout the app auto-loads
`Demo Project/GuildDraw DXF Export.dxf`, which exercises the full castle
pipeline (9 zones, hinge pockets, five-op G-code).

## Running tests

```
pytest
```

## License

GPLv3 or later. See `LICENSE`.
