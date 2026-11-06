**GuildModel 2.3.1** sorts out the worktable and brings STEPCRAFT machines in. Pick **STEPCRAFT (UCCNC, tool changer)** in the Machine list and GuildModel writes your programs in UCCNC's G-code, tool changer and all. A bed whose zero is anywhere but its lower-left now simulates where it really cuts, and a bed drawn in Fusion 360 imports every zone. 2.3.1 is also the first time we are announcing 2.3, so everything new in 2.3 is below as well.

**GuildModel 2.3** is the result of a massive undertaking to likewise bring 2D drafting features into the modeling program. *View ▸ Draft* assembles the formed front with its temples bent at their tip bend and opened to the angle of side and the splay you set, fills the hinge in from the drawn pocket, cuts the butt where the temples meet the endpiece, and runs a series of checks and stats for the model completion.

*Export Blueprint…* writes the dimensioned drawing for either OEM factory production or bench alignment use. The front, top and side views after forming, the hinge detail, the tolerances and the ISO 7200 title block on sheet 1; the 1:1 alignment template on sheet 2; all can be exported to PDF, SVG, DXF or sent to a printer, with your choice of paper size, views, lettering, colors and the shop's title-block cells kept as defaults. GuildDraw 2.3 stores the front's forming and each temple's tip bend in the drawing, and GuildModel is able to read this, in the efforts of saving time within a given workflow.

**Re-post temple programs.** A temple with anything on its outer face posts two setups now, and its anterior is mirrored for the flip over its length; a temple with nothing there posts as it did. Projects from 2.0 open with their settings; generate their programs again before cutting. The draft view and the blueprint change no program.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## New in 2.3.1

- **STEPCRAFT machines on UCCNC, with the tool changer.** *Machine ▸ STEPCRAFT (UCCNC, tool changer)* writes every program, a part's or the whole worktable's, in UCCNC's G-code, modeled on Autodesk's own STEPCRAFT UCCNC post: `T… M6` for the changer and `G43 H…` for that tool's length, comments in parentheses, a pause after the spindle starts, and every retract that leaves the work to the top of Z travel. The toolpaths are the same as on any other machine.
  - **Give every tool its pocket.** The number after `T` is the pocket the changer fetches, so set each tool's **Tool number** to its pocket in *Preferences ▸ Tools*. A program with a tool on *0 = auto*, or two tools on one number, is refused, and the message names every tool to fix.
  - **Home the machine before you run,** since the retracts are in machine coordinates, and air-cut your first program.
- **A bed zeroed anywhere but its lower-left simulates where it cuts.** Simulate Bed read the worktable program with the bed zero still in it, so on a bed zeroed at its center every cut landed beside its blank. The G-code was always right for the zero you chose; only the simulation was wrong. The Bed group now shows the exact point the program touches off, any shift included, and the setup sheet records it.
- **A bed drawn in CAD keeps every zone.** A zone whose corner the CAD wrote two slightly different ways, as Fusion 360 does, never closed and was left off the bed; so was a screw hole drawn as three arcs. Corners within 0.01 mm now close.
- **The tool library keeps what its form does not show.** Editing the lens groove cutter in *Preferences ▸ Tools*, even just its Tool number, flattened its V and its neck, in the drawing and, once you pressed OK, in your library. **If you edited that cutter before,** pick it, choose *Reset to shipped*, and set your number or feeds again.
- **A tool's own number is never taken by another.** A tool without a number that cut first could take T1 from a later tool whose number is 1.

## New in 2.3

- **The draft view.** *View ▸ Draft (D)*: the formed front with the temples bent and opened, in the 3D view; the panel under it sets the **angle of side** and the **splay** the temples hang at, and reads what the hinge alone would give beside each (the pocket floor's angle, the endpiece's lean and turn on the formed front, the hinge's slant and stop) and the panto and splay cut into the butt. *Match pocket angle* sets the front's component pocket angle so the hinge agrees. The hinge is **rivet**, **heat-set cleat** or **spring**, with its barrels, screw thread, slant and stop; the drawn pocket gives the plate and the width along the axis. Seven bench checks: the angle of side and the splay left against right, the four-point touch, the tips on a common plane, no X-ing, each folded temple crossing the center and clearing the back.
- **The blueprint.** *File ▸ Export Blueprint…*, or the panel's button. Sheet 1, laid out as eyewear sheets are: the plan with the temples curving in, the front view, and the side view with the temple horizontal and the front tilted by the angle of side, each an edge rendering of the formed solid with hidden lines removed, stacked down a portrait page at the largest standard scale that fits (1:1 on A3 and tabloid, 1:2 on letter and A4), every dimension tagged locked, target, open or reference; the hinge detail, reference only; the notes with the marking, the rim widths, the forming, the bench numbers, the hinge, the editable tolerance table, the checks and the temples as cut; the ISO 7200 title block with the projection symbol. Sheet 2: the 1:1 alignment template with the tips and ear points in ±2 mm targets, the side view and a ruler. PDF, SVG, DXF or print. The lettering is any font the machine has; a dimension's value sits in a break in its line, or above it on request; the hinge detail is drawn from the pockets as drawn, the front's and the temple's shapes joined by the barrel, with the joint from above beside it; and the ink and the paper are yours: black on white, a true blueprint of white lines on Prussian blue, or any two colors. **Preferences ▸ Blueprint** holds the defaults: the paper, the orientation, the projection, the views, the scale, the line weight, the font, the dimension text, the colors, the owner and author, the document type, the tolerances, and the angle of side, splay and hinge a new project starts from.
- **The temple bends as a bar.** The drop and a new **inward angle**, the turn toward the head seen from above, are composed along the temple's core, so the tips sit closer together than the hinges; 15° is assumed until you set it. The butt is cut by the endpiece's back face at the panto and the splay, and the temple's solid in the 3D view shows the cut.
- **The drawing's forming and tip bend.** A GuildDraw 2.3 front seeds the project's forming (the base curve and its radius, the face form, the bridge projection, the press row, the neutral surface); a saved project's own forming wins. Each temple's tip bend reaches the Temple tab's new **Forming** section (*Length to bend*, *Downward angle*, *Bend radius*) and the draft. The library folder a component came from is read, so a bridge is not taken for a hinge.
- **The Forming panel, as GuildDraw's group.** *Preset*; the face form per side in low degrees, the included angle beside it; the tooling index, the sheet thickness and the neutral surface in **Preferences ▸ General ▸ Forming**, which every design uses.
- **From the held 2.1 round.** A temple's second side, cut first in G55 and flipped over its length; the simulation plays both setups; two-sided is each part's own; Embossing on a temple; the temples' link; meshes placed by hand and imported whole; Program Zero's *Fixture* mode replaced by Shift X, Y and Z; the sidebar's housekeeping; two fronts refused as GuildDraw 2.0.1 refuses them. The 2.1 entries in `CHANGELOG.md` have the detail.

## Known issues

- **STEPCRAFT on UCCNC is new.** Its programs are checked against Autodesk's own post and in our simulation; air-cut your first one. The profile's work area and spindle range are a D.600's; set yours in `stepcraft_uccnc.yaml`. `G43 H…` expects UCCNC's tool table to hold each tool's length. Re-probing Z after a flip is not written for UCCNC yet; re-zero by hand at the flip's pause.
- **GuildSend draws a shifted bed zero in the wrong place.** Its bed view reads the bed zero's corner but not its shift; the program itself is right.
- **The draft view is a rough assembly.** The hinge axis sits on the endpiece's back face a temple's thickness inside its end face, on the library entry's datum; the panel's *Inset* and *Butt gap* move it. The drop itself is drawn straight down; the curl a bent drop takes toward the head is not drawn. The far temple shows in the side view only where it differs from the near one.
- **The hinge detail is a reference, not the hinge.** It is drawn from the drawn pockets, the barrel count and the screw; a hinge whose plates differ from its pockets, or whose barrel stands off the corner, is not what it shows.
- **The blueprint's DXF carries its dimensions as lines and text,** not as dimension entities; a CAD reads them as drawn.
- **A letter or A4 sheet holds the views at 1:2;** A3 or tabloid gives 1:1, the bench's scale.
- **GuildSend reads the front's flip only.** Its guided sequence and its setup sheet describe a temple's flip as the front's, about a machine X line, and its two-file sequence does not know the temple's names: run `temple_anterior_cut.nc` first, then `temple_cut.nc`, and turn the blank over its length. The one file, pausing for the flip, runs in GuildSend as it is.
- **GuildSend infers Z0 from the program zero's words.** A program zero with a Z shift is not read by GuildSend's bed inference; touch off Z by hand after a shift, or leave *Shift Z* at 0 for a job GuildSend sets up.
- **The simulation can list a pocket's wall as uncut.** It places each tool position at its nearest cell, so where a tool's edge lies exactly on a pocket's wall, a column of cells along that wall may be listed under its zone as uncut. The verdict itself sets cells beside a step aside.
- **An emboss on a temple is modeled only.** A mesh that stands above the blank's face needs a blank thicker than the part, which is a later release.
- **The pre-formed blank's nest was shaped for a carved back.** Work on pressed blanks is paused.
- **The fourth axis has not met the bench.** Measure the spindle nose to the table, and the rotary's centerline and sign, before an indexed flip.
- **An edge feature can fold at a very sharp corner.** This is still true from 1.5. After a rebuild, read the log, not the readiness dot. To clear it, move the run's **Trim start** or **Trim end** past the corner.
- **A formed STL is a little lighter than the flat part.** Forming compresses the concave side a few percent. This is expected.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildModel-2.3.1-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gmodel` association; upgrades in place. |
| `GuildModel-2.3.1-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildModel-2.3.1-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildModel-2.3.1-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once.

Pair it with [GuildDraw 2.3](https://github.com/csobod/GuildDraw/releases/tag/v2.3.0), which shows the front formed and the temple bent, stores the forming and the tip bend in the drawing, draws the INLAY and COMPONENT layers, keeps your components in a library of your own folders, and fills the inlays with a color or an image.

## Learning GuildModel

The [user guide](https://github.com/csobod/GuildModel/blob/main/docs/USER-GUIDE.md) covers opening a drawing, tuning each part, two-sided jobs, the Forming view, the draft view and the blueprint, the worktable and its machines, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
