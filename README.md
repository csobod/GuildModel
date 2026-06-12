# GuildCAM

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildCAM takes a GuildDraw frame-front DXF and builds the posterior relief the
way a maker models it — the **castle**: tower zones (endpieces, bridge,
nosepads), eyewire walls, and rolling-ball footing fillets — then generates
the five-operation single-tool GRBL program (hinge pockets → rough relief →
fine relief → eyewires → perimeter, released by a hand-finished onion skin)
for the Guild CNC fixture.

## Status

v0.4.0 — M4 complete (parametric castle UI). See `BUILDPLAN.md` for the
milestone roadmap to 1.0.

## Requirements

Python 3.12 or newer.

## Installation (development)

```
pip install -e ".[dev]"
```

## Running the app

The install registers a `guildcam` entry point:

```
guildcam
```

or, without activating the venv:

```
.venv\Scripts\guildcam.exe          # Windows
.venv\Scripts\python -m guildcam.gui.app
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
