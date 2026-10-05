**GuildModel 1.8.1** engraves a drawn logo as a filled shape. A closed curve drawn on a temple's ENGRAVING layer, a logo or a mark, was treated as text and reduced to the center line of its strokes, which turned a six-armed logo into a forked stick figure in the 3D model, the cut simulation and the posted program. Text is still engraved as stroke centerlines; a closed curve you drew is now cut out as a filled shape to the engraving depth, a closed curve inside it is left standing, and an open curve you drew is traced as a stroke. Nothing else changes: projects from 1.8.0 open as they did, and the frame front, the base-curve blocks and the worktable post the same programs.

**Re-post a temple that carries a drawn closed curve on ENGRAVING.** Every other program is byte-identical to 1.8.0.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## Fixed in 1.8.1

- **A drawn ENGRAVING curve is cut as drawn, closed shapes filled.** When a drawing comes from a `.gdraw`, GuildModel now tells the text objects from the curves on the ENGRAVING layer from the moment the file opens. Text is outlined and, with *Engrave text as stroke centerlines* on, engraved as one line down each stroke. A drawn closed curve is a filled shape, cleared to the engraving depth with the engraving bit in rings 40 % of its diameter apart; a closed curve drawn inside another is an island and keeps its material, so an O is two circles and a filled disc is one. A drawn open curve is a stroke, traced as drawn. All of it is cut with the same bit at the same depth in the same Engraving operation, whatever the option says, and the model, the simulation, the nest and the program follow the same rule. A shape too small for the bit to enter is left, and the simulation reports it as uncut; a small flat end mill set as the engrave tool fills a logo more cleanly than a V-bit.
- **Over a DXF, the option applies to every closed curve, as before.** A DXF cannot tell text from drawing; GuildDraw outlines its text into plain closed splines at export. Turn the option off for a DXF temple that carries a logo, or hand the drawing over as a `.gdraw`.
- **The Temple tab says what the option does.** *Engrave stroke centerlines* is now *Engrave text as stroke centerlines*, and its tooltip states the rule.

The full account is in [CHANGELOG.md](CHANGELOG.md).

## Known issues

- **An edge feature can fold at a very sharp corner.** This is still true from 1.5. After a rebuild, read the log, not the readiness dot. To clear it, move the run's **Trim start** or **Trim end** past the corner.
- **A formed STL is a little lighter than the flat part.** Forming compresses the concave side a few percent. This is expected.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildModel-1.8.1-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gmodel` association; upgrades in place. |
| `GuildModel-1.8.1-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildModel-1.8.1-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildModel-1.8.1-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once.

Pair it with [GuildDraw 1.3.1](https://github.com/csobod/GuildDraw/releases/tag/v1.3.1), which now imports SVG, so a logo can be drawn in any editor and placed on the temple at the size you choose.

## Learning GuildModel

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each component, the Forming view, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
