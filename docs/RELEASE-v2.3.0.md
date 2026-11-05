**GuildModel 2.3** draws the frame as it will be worn. *View ▸ Draft* assembles the formed front with its temples bent at their tip bend and opened to the angle of side and the splay you set, fills the hinge in from the drawn pocket, cuts the butt where the temples meet the endpiece, and runs the bench checks. *Export Blueprint…* writes the dimensioned drawing for the factory and the bench: the front, top and side views after forming, the hinge detail, the tolerances and the ISO 7200 title block on sheet 1; the 1:1 alignment template on sheet 2; as PDF, SVG, DXF or to a printer, with your paper, views and title-block cells kept as defaults. GuildDraw 2.3 stores the front's forming and each temple's tip bend in the drawing, and GuildModel reads them. The held 2.1 round ships inside this release: a temple's second side, the temples' link, Embossing, and Program Zero's shift.

**Re-post temple programs.** A temple with anything on its outer face posts two setups now, and its anterior is mirrored for the flip over its length; a temple with nothing there posts as it did. Projects from 2.0 open with their settings; generate their programs again before cutting. The draft view and the blueprint change no program.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## New in 2.3

- **The draft view.** *View ▸ Draft (D)*: the formed front with the temples bent and opened, in the 3D view; the panel under it sets the **angle of side** and the **splay** the temples hang at, and reads what the hinge alone would give beside each (the pocket floor's angle, the endpiece's lean and turn on the formed front, the hinge's slant and stop) and the panto and splay cut into the butt. *Match pocket angle* sets the front's component pocket angle so the hinge agrees. The hinge is **rivet**, **heat-set cleat** or **spring**, with its barrels, screw thread, slant and stop; the drawn pocket gives the plate and the width along the axis. Seven bench checks: the angle of side and the splay left against right, the four-point touch, the tips on a common plane, no X-ing, each folded temple crossing the center and clearing the back.
- **The blueprint.** *File ▸ Export Blueprint…*, or the panel's button. Sheet 1, laid out as eyewear sheets are: the plan with the temples curving in, the front view, and the side view with the temple horizontal and the front tilted by the angle of side, drawn to the frame's major lines and stacked down a portrait page at the largest standard scale that fits (1:1 on A3 and tabloid, 1:2 on letter and A4), every dimension tagged locked, target, open or reference; the hinge detail, reference only; the notes with the marking, the rim widths, the forming, the bench numbers, the hinge, the editable tolerance table, the checks and the temples as cut; the ISO 7200 title block with the projection symbol. Sheet 2: the 1:1 alignment template with the tips and ear points in ±2 mm targets, the side view and a ruler. PDF, SVG, DXF or print. **Preferences ▸ Blueprint** holds the defaults: the paper, the orientation, the projection, the views, the scale, the line weight, the owner and author, the document type, the tolerances, and the angle of side, splay and hinge a new project starts from.
- **The temple bends as a bar.** The drop and a new **inward angle**, the turn toward the head seen from above, are composed along the temple's core, so the tips sit closer together than the hinges; 15° is assumed until you set it. The butt is cut by the endpiece's back face at the panto and the splay, and the temple's solid in the 3D view shows the cut.
- **The drawing's forming and tip bend.** A GuildDraw 2.3 front seeds the project's forming (the base curve and its radius, the face form, the bridge projection, the press row, the neutral surface); a saved project's own forming wins. Each temple's tip bend reaches the Temple tab's new **Forming** section (*Length to bend*, *Downward angle*, *Bend radius*) and the draft. The library folder a component came from is read, so a bridge is not taken for a hinge.
- **The Forming panel, as GuildDraw's group.** *Preset*; the face form per side in low degrees, the included angle beside it; the tooling index, the sheet thickness and the neutral surface in **Preferences ▸ General ▸ Forming**, which every design uses.
- **From the held 2.1 round.** A temple's second side, cut first in G55 and flipped over its length; the simulation plays both setups; two-sided is each part's own; Embossing on a temple; the temples' link; meshes placed by hand and imported whole; Program Zero's *Fixture* mode replaced by Shift X, Y and Z; the sidebar's housekeeping; two fronts refused as GuildDraw 2.0.1 refuses them. The 2.1 entries in `CHANGELOG.md` have the detail.

## Known issues

- **The draft view is a rough assembly.** The hinge axis sits at the endpiece's back corner, on the library entry's datum; a hinge whose barrel stands off the corner is set by the hinge's axis offsets in the project file only. The drop itself is drawn straight down; the curl a bent drop takes toward the head is not drawn. The far temple shows in the side view only where it differs from the near one.
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
| `GuildModel-2.3.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gmodel` association; upgrades in place. |
| `GuildModel-2.3.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildModel-2.3.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildModel-2.3.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

The Mac builds need **macOS 13 Ventura or later** (the Qt they are built on sets that floor); Windows builds need Windows 10 or later, 64-bit.

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once.

Pair it with [GuildDraw 2.3](https://github.com/csobod/GuildDraw/releases/tag/v2.3.0), which shows the front formed and the temple bent, stores the forming and the tip bend in the drawing, draws the INLAY and COMPONENT layers, keeps your components in a library of your own folders, and fills the inlays with a color or an image.

## Learning GuildModel

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each part, two-sided jobs, the Forming view, the draft view and the blueprint, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
