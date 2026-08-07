# GuildModel

Free, open-source CAM tool for spectacle frame cutting on GRBL CNC machines.

GuildModel takes a GuildDraw frame-front DXF and builds the posterior relief the
way a maker models it — the **castle**: tower zones (endpieces, bridge,
nosepads), eyewire walls, and rolling-ball footing fillets — then generates
the five-operation single-tool GRBL program (hinge pockets → rough relief →
fine relief → eyewires → perimeter, released by a hand-finished onion skin)
for the Guild CNC fixture.

## Status

**v1.4.0.** GuildModel builds the posterior castle relief and the
five-operation single-tool GRBL program for a frame front, its temples, and
per-lens base-curve forming blocks — with worktable nesting, cut simulation, a
maker's guide (`docs/USER-GUIDE.md`), and an optional lens bevel groove
(drageoir V-groove in each eyewire wall, off by default).

> **New in v1.4.0 — the frame has a front (first V2 instalment).** The model now
> carries an **anterior surface** as well as the posterior castle, and a new
> **Edge Features** list on the Model tab cuts partial-span chamfers and fillets
> into either face — the anterior brow chamfer over each eyewire, stopping short
> of the bridge, that thick modern frames want. A run's span is chosen by castle
> zone, tapers to nothing at each end, can vary in width along its length, and
> mirrors to the other side as one feature. The eyewire bezel can now be cut into
> the front face instead of, or as well as, the back. **This is modelling and 3D
> preview only** — machining the front needs the flip setup, which is the next
> milestone. Posterior programs are unchanged.

> **New in v1.3.0 — toolpath control.** The Cut tab now decides how the part is
> held (onion skin or hold-down tabs), which operations run at all (uncheck one to
> cut a job in stages), and what any single component overrides from the project's
> CAM settings — most usefully its material, so acetal forming blocks stop
> inheriting the acetate frame's depth per pass. The Machine tab adds climb /
> conventional milling and a ramp-or-plunge lead-in. Defaults are unchanged, so an
> existing project posts exactly as it did in v1.2.0. **Hold-down tabs are new and
> have not been cut on real stock** — air-cut the first one.

> **Upgrading from v1.1.0 — this changes how deep your programs cut.** Depth per
> pass was set on a frame-only panel that was hidden whenever a temple or
> base-curve block was the active component, and the shipped default asked for a
> 4 mm bite: a stock 4 mm temple blank came out as **one full-depth pass**, with no
> control to change it. Depth per pass now lives on the **Cut** tab for every
> component kind, with a read-out of the resulting pass count, and the shipped
> acetate default drops from 4.0 mm to 1.5 mm. Blind pockets and deep engraving
> step down too, and temple/base-curve programs finally honour the machine's and
> material's depth-of-cut ceiling. **Re-post any program you still have**, and
> treat the new pass structure as you would any new program — air-cut, then a test
> piece.

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

### Linux / Wayland — handled automatically

**You should not have to do anything here.** Both of the workarounds this
section used to ask for are now applied by the app at startup; the detail below
is for anyone who wants to override them or is debugging.

PyVista/VTK's Linux renderer (`vtkXOpenGLRenderWindow`) is X11-only. Under Qt's
native `wayland` plugin it cannot embed its render window — `BadWindow` on
`X_ConfigureWindow`, then a segfault the moment you build a 3D model. So on a
Wayland session GuildModel selects the `xcb` plugin (XWayland) for itself before
Qt starts. Re-tested 2026-08-07 on VTK 9.6.2 / PySide6 6.11.1 / KDE Plasma:
still required, not a stale workaround.

Running under XWayland means Qt is told the screen is 96 DPI whatever the panel
actually is, and there is no compositor scale to fall back on, so the UI comes
out small — about 68% of intended size on a 141 DPI laptop panel. GuildModel
measures the panel's true DPI and scales both the application font *and* the
stylesheet to match. (Scaling the stylesheet is the part `QT_FONT_DPI` cannot
do: Qt stylesheet `px` is a device-independent unit that ignores font DPI, and
this app pins every font size in `px`. That is why the old `QT_FONT_DPI` advice
only half-worked.)

To override, set any of these and the app will leave the scale alone:

```
QT_SCALE_FACTOR=1.25 guildmodel      # or QT_FONT_DPI, QT_SCREEN_SCALE_FACTORS
QT_QPA_PLATFORM=wayland guildmodel   # force the native plugin (3D will crash)
```

Or pin it in **Preferences** — the `ui_scale` setting takes `"auto"` (the
default), or a number; `1.0` turns scaling off entirely.

## Running tests

```
pytest
```

## License

GPLv3 or later. See `LICENSE`.
