# GuildCAM

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildCAM takes a 2D vector drawing of a spectacle frame (DXF or SVG) and produces
GRBL-ready G-code for two-sided cutting on the Guild CNC fixture — back relief,
front relief, lens groove, hinge pockets, and profile cut with tabs.

## Status

Early development. See `BUILDPLAN.md` for the milestone roadmap.

## Requirements

Python 3.12 or newer.

## Installation (development)

```
pip install -e ".[dev]"
```

## Running tests

```
pytest
```

## License

GPLv3 or later. See `LICENSE`.
