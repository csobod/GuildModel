# `.gcam` — GuildCAM project container

A `.gcam` file is a **ZIP archive** (same container idea as GuildDraw's `.gdraw`)
that holds everything needed to **(a)** reopen a complete job in GuildCAM with no
external files and **(b)** hand the job to a [gSender](https://sienci.com/gsender/)
fork adapted to the Guild two-sided acetate workflow.

Reader/writer: `guildcam.core.project.gcam` (`save_gcam`, `load_gcam`,
`extract_handoff`). Format version: **1**.

## Layout

```
job.gcam  (zip)
├── manifest.json      # format/app/version, timestamps, run mode, SHA-256 inventory
├── project.json       # the full ProjectSchema (boxing / castle / cam_params / stock / …)
├── source.dxf         # the imported GuildDraw DXF — self-contained reopen
├── program/
│   ├── posterior_cut.nc   # generated G-code (the posterior one-setup program)
│   └── back_cut.nc        # (M8) back-side program for the two-sided flip
├── machine.yaml       # snapshot of the active MachineProfile
├── setup.json         # setup sheet (tool, feeds/speeds, op order, cut lengths, est. time, flip axis)
├── cut_report.json    # cut-simulation verification (completeness / gouge + cut-time)
├── model.stl          # (optional) watertight cut-piece mesh for inspection
└── preview.png        # (optional) render thumbnail
```

Only `manifest.json` and `project.json` are guaranteed present. Everything else
is written when it exists, so a `.gcam` is valid at any stage — saved right after
import (project + `source.dxf`) or after generation (adds `program/`,
`machine.yaml`, `setup.json`, `cut_report.json`). This staging is what drives the
GuildCAM readiness traffic-light.

**The generated program lives in the `.gcam` by default.** Generating G-code
stores the program in the project (folded into the open `.gcam`, or written on
the next Save Project); it no longer writes a loose `.nc`. A standalone `.nc` is
an explicit, optional export — **File ▸ Export G-code** (`Ctrl+Shift+G`), the
G-code counterpart of **Export STL**.

## `manifest.json`

```jsonc
{
  "format": "gcam",
  "format_version": 1,
  "app": "GuildCAM",
  "app_version": "0.5.1",
  "created":  "2026-06-14T18:00:00+00:00",
  "modified": "2026-06-14T18:05:00+00:00",
  "run_mode": "two_file",          // "two_file" | "single_m0"
  "contents": {                     // every member except manifest.json itself
    "project.json":            { "sha256": "…", "bytes": 1234 },
    "source.dxf":              { "sha256": "…", "bytes": 56789 },
    "program/posterior_cut.nc":{ "sha256": "…", "bytes": 9012 }
    // …
  }
}
```

`load_gcam` verifies every `contents` entry's SHA-256 by default
(`verify=False` to skip). A mismatch raises `GcamError` (corrupted file).

## gSender-fork hand-off contract

A fork consumes a **frozen subset** — it must not need to parse `project.json`,
the DXF, or the STL:

| File | Purpose for the fork |
|---|---|
| `program/*.nc` | the G-code to stream to the controller |
| `machine.yaml` | work area, max feed/spindle, accel, arc support — clamp / sanity-check before streaming |
| `setup.json` | operator setup sheet: tool, feeds/speeds, op order, est. cycle time, stock/fixture, **flip axis** for two-sided |
| `manifest.json` | `run_mode` (two-file flip vs single `M0`), app version, integrity |

`extract_handoff(path, dest)` writes exactly this subset (`program/*.nc` +
`machine.yaml` + `setup.json` + `manifest.json`) to a directory for the fork to
read. `cut_report.json`, `source.dxf`, `model.stl`, and `preview.png` are
**GuildCAM-only** and never required to run the job.

### Two-sided run modes

- `two_file` — `program/posterior_cut.nc` then `program/back_cut.nc`, with a
  manual re-fixture (flip about `setup.json.flip_axis_x_mm`, re-register on the
  dowel pins) between them.
- `single_m0` — one program with an `M0` pause at the flip point.

## Stability

`format_version` is bumped on any breaking change to the layout or the hand-off
contract. Readers should tolerate unknown extra members (forward-compatible) and
must check `format_version` before trusting the layout.
