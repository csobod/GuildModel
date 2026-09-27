**GuildModel 1.8** shows the frame front as it will be worn. The new **Forming** view bends the front the way the press and the bench do, and you can export the formed front as an STL to print and try on before you cut. This release also adds a **hinge pocket angle** and fixes a set of faults found in a full review of the program.

**Re-post your programs before you cut.** Most single-part programs are unchanged, but this release changes worktable programs, tabbed release passes and some fallback paths. The safe choice is to post everything again with 1.8.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## New in 1.8

- **View ▸ Forming (`F`).** On the Frame Front tab, press `F` to see the formed front. A panel under the 3D view sets the base curve (in diopters), the face form, and the bridge projection with its creases and die. The sliders are live.
- **Press presets.** The SBT base-curve press ships as presets. Add your own presses in `~/.guildmodel/presses.yaml`.
- **Export Formed STL.** Writes the formed front, with the lens bevel groove, as one closed solid for SLA printing. **Export All STL** includes it when the front is formed.
- **Hinge pocket angle.** Tilts the floor of each hinge pocket: on the front to set the pantoscopic angle at the hinge, on a temple to offset built-in splay. A tilted pocket gets a finishing pass. At 0°, nothing changes.
- **Hinge pocket depth on the Temple tab.** Temples now cut at the depth you set; before, they always cut at 1.0 mm.

Forming never changes a program. The forming settings are saved with the project, and older projects open flat.

## Fixes

**Toolpaths**
- Each part on a worktable now cuts at its own material's feeds and depth per pass.
- Worktable rapids now clear the tallest part on the bed.
- GuildModel refuses to post a program whose rapid height is not above every cut.
- A tabbed release pass now ramps in instead of plunging.
- A frame with no SCULPT cuts now gets its whole profile cut.
- A hole too small for the tool is now reported instead of skipped silently.

**Projects**
- A reopened project keeps its stored program.
- Each component's program is saved, not only the open tab's.
- Invalid values in a hand-edited project are refused with a reason.

**Interface**
- Cancel now stops a build, export, simulation or nest.
- Failures now show a message with a button that opens the log.
- Quit and Preferences shortcuts can no longer be taken by another action.
- Number fields in the Cut tab apply when you press Enter, not on every keystroke.
- Closing the window during a build no longer crashes.
- The user guide's shortcut table is corrected.

The full list is in [CHANGELOG.md](CHANGELOG.md).

## Known issues

- **An edge feature can fold at a very sharp corner.** This is still true from 1.5. After a rebuild, read the log, not the readiness dot. To clear it, move the run's **Trim start** or **Trim end** past the corner.
- **A formed STL is a little lighter than the flat part.** Forming compresses the concave side a few percent. This is expected.

## Downloads: which file do I want?

| File | For |
|---|---|
| `GuildModel-1.8.0-setup.exe` | **Windows, recommended.** Per-user installer (no admin), Start Menu shortcut, `.gmodel` association; upgrades in place. |
| `GuildModel-1.8.0-win64.zip` | Windows portable folder. Unzip and run. |
| `GuildModel-1.8.0-macos-arm64.dmg` / `.zip` | **Mac (Apple Silicon, M1 and later).** Drag to Applications. |
| `GuildModel-1.8.0-macos-x86_64.dmg` / `.zip` | Mac (Intel). |

**First launch** (the builds are not signed): on Windows, SmartScreen asks once; click *More info ▸ Run anyway*. On macOS, **right-click the app ▸ Open ▸ Open** once.

Pair it with [GuildDraw 1.2.0](https://github.com/csobod/GuildDraw/releases/tag/v1.2.0) to draw the frame in the first place.

## Learning GuildModel

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each component, the Forming view, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
