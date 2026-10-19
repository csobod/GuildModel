**GuildModel 2.0** cuts both faces of a frame front. A front that carries anything on its anterior, a brow chamfer, an anterior bezel, a round-over or an inlay seat, is cut in two setups: the anterior first, front face up while the blank is still a flat slab, cutting only what its features need; then the flip onto the dowel pins, and the posterior as a one-sided job cuts it, through-cuts and onion skin and all. The program is two files, or one that pauses for the flip, and the simulation plays the whole job with the flip in it. 2.0 also brings inlay seats for plaques, laminates and plates; sculpts, your own meshes on the frame; press dies for the formed front; a new stock engine under the simulation, with a stricter verdict; the Worktable redone; separated rims and the monocle; and the COMPONENT layer, which carries hinges, bridges, endpieces and bridge bars alike.

**Re-post every program.** 2.0 changes how much of each job is cut: the contours cut only where there is material, a pocket's middle takes one more pass where the passes would not overlap, the features take the 2 mm ball by default, and the hops between passes keep clear of the fixture's screws. Projects from 1.8 open with their settings; generate their programs again before cutting.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## New in 2.0

- **Two-sided jobs, the anterior first.** The anterior program, in G55, cuts the Fine Relief and the Features pass over the anterior's chamfers, bezels and round-overs, and the anterior seats; it cuts the Rough Relief only where the front is cut deeper than one stepdown, and never a pocket or a through-cut. Past the part's edge the stock still stands, so the anterior reaches a tool's width beyond the edge and finishes each feature there. The posterior program, in G54, is the one-sided program, byte for byte. *Output* on the Cut tab writes `anterior_cut.nc` and `posterior_cut.nc`, or `two_sided_cut.nc` with the flip's `M0`. A blank with the pad block lies on a spacer for the anterior, the pad in its cut-out.
- **The flip, simulated.** Simulate cuts the anterior from the blank turned front face up, turns the result back over and cuts the posterior from it. The 3D playback stops at the flip, and ▶ turns the block over and goes on. The log names the rings where the anterior takes the onion skin's hold away, and warns when it takes it off a whole ring, so tabs are needed only where they are.
- **Inlays.** Draw a seat on the INLAY layer in GuildDraw: a plaque, a laminate, a plate. Each is pocketed flat, parents first; a seat drawn inside another is a step down from it, one inside a component pocket steps that pocket's floor, and the program checks the material each floor leaves against the other face.
- **The COMPONENT layer.** HINGE is now COMPONENT, for anything mounted on the back that needs a classic pocket. Drawings, library entries and DXFs that say HINGE read as COMPONENT, and the pockets are cut by *Component Pockets*; a project saved before keeps its settings.
- **Sculpts.** Import your own mesh and emboss or deboss it on the frame's back, placed, scaled and turned on the model; the *Sculpt Finish* operation cuts its detail with a small ball. Sculpts are built and cut by the mesh kernel.
- **The stock engine.** The simulation cuts a true solid, so a side-cutting tool such as the lens groove's leaves the rim above its slot, and a rapid through stock or a shank in it fails the verdict. The verdict judges the largest piece left standing by its volume, catches a gouge into a wall, and asks whether the part is released.
- **The Worktable, redone.** Placements are saved; the parts are placed before anything is generated; one Generate posts the bed and *Simulate Bed* cuts it once. Each part has a checkbox to put it on the bed or leave it off, and a part is placed by its drawing's origin.
- **Separated rims and the monocle.** A combination frame's two rims on a metal bridge are one front with a body per rim, the bridge's mount one shape across the gap. A front with one rim and one lens is a monocle.
- **Press dies and the pre-formed blank.** *Export Dies…* writes the press's molds for the formed front, and *Export Nest…* the fixture a pressed blank is cut in. Cutting after pressing is in, for a niche: its known issues are below.
- **The fourth axis.** A machine profile may carry a rotary for an indexed flip; the shipped profile's figures are placeholders for the bench.
- **Smaller things.** Every sidebar section folds; a control the chosen kernel ignores is hidden; the pad splay is cut the way it is finished by hand, with a *Seam blend* radius; a pocket's middle always takes an overlapping pass.

GuildModel reads only the curves you drew, never GuildDraw's Ghost: bake the mirror (*Mirror (bake)*) before you open a front drawn as a half, or it opens as a monocle.

The full account is in [CHANGELOG.md](CHANGELOG.md).

## Known issues

- **The simulation can list a pocket's wall as uncut.** It places each tool position at its nearest cell, so where a tool's edge lies exactly on a pocket's wall, a column of cells along that wall may be listed under its zone as uncut. The verdict itself sets cells beside a step aside.
- **GuildSend's guided two-file sequence does not know 2.0's names yet.** It offers the two programs to choose from: run `anterior_cut.nc` first. The one file, pausing for the flip, runs in GuildSend as it is.
- **The pre-formed blank's nest was shaped for a carved back.** A two-sided job now cuts the anterior first, so the nest's dome bears on the slab's uncut back only where it is not cut away. Work on pressed blanks is paused.
- **The fourth axis has not met the bench.** Measure the spindle nose to the table, and the rotary's centerline and sign, before an indexed flip.
- **An edge feature can fold at a very sharp corner.** This is still true from 1.5. After a rebuild, read the log, not the readiness dot. To clear it, move the run's **Trim start** or **Trim end** past the corner.
- **A formed STL is a little lighter than the flat part.** Forming compresses the concave side a few percent. This is expected.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildModel-2.0.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gmodel` association; upgrades in place. |
| `GuildModel-2.0.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildModel-2.0.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildModel-2.0.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once.

Pair it with [GuildDraw 2.0](https://github.com/csobod/GuildDraw/releases/tag/v2.0.0), which draws the INLAY and COMPONENT layers, keeps your components in a library of your own folders, fills the inlays with a color or an image, and shows the drawing from either face.

## Learning GuildModel

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each part, two-sided jobs, the Forming view, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
