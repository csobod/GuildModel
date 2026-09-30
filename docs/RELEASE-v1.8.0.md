**GuildModel 1.8** shows the frame front as it will be worn. The new **Forming** view bends the front the way the press and the bench do, and you can export the formed front as an STL to print and try on before you cut. This release also keeps your shop's defaults for each kind of part, sets feeds and speeds per tool, and fixes a set of faults found in a full review of the program.

**Re-post your programs before you cut.** Worktable programs, the order of a temple's operations, tabbed release passes and some fallback paths have changed. Most single-part programs are unchanged, but the safe choice is to post everything again with 1.8.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## New in 1.8

**Forming**
- **View ▸ Forming (`F`).** On the Frame Front tab, press `F` to see the front formed to a base curve (in diopters), a face form and a bridge projection, on live sliders. The SBT press ships as presets; add your own in `~/.guildmodel/presses.yaml`.
- **Export Formed STL.** Writes the formed front, lens groove included, as one closed solid for SLA printing.

Forming never changes a program, and older projects open flat.

**Hinge pockets**
- **Hinge pocket angle.** Tilts each pocket's floor: on the front for the pantoscopic angle at the hinge, on a temple to offset built-in splay. At 0°, nothing changes.
- **Temples cut at the pocket depth you set.** Before, they always cut at 1.0 mm.

**Your shop's defaults**
- **Preferences ▸ Parts** sets what a new drawing starts from, per kind of part: program zero, stock, temple alignment, the block's hole pattern and tools. When a saved project differs, GuildModel lists the differences once; check the ones to keep.
- **Apply to both temples** copies the Temple tab onto the other temple.
- **Every offer has a *Don't ask again*;** *Preferences ▸ General ▸ Prompts* turns it back on.

**Cutting**
- **Feeds and speeds per tool.** The Cut tab shows a row per tool, with its feed, plunge, spindle, chip load and where each comes from. Type into a row to set it for this project; Generate offers to save it to your tool library.
- **The briefest tool first.** A temple's program runs the tool with the least work first, so the operator swaps once; the profile still releases the part last.

## Fixes

**Toolpaths**
- Each part on a worktable cuts at its own material's feeds and depth per pass, and the rapids clear the tallest part on the bed.
- GuildModel refuses to post a program whose rapid height is not above every cut.
- A tabbed release pass ramps in instead of plunging.
- A frame with no SCULPT cuts gets its whole profile cut.
- A hole too small for the tool is reported instead of skipped silently.
- The cut simulation works in batches, so a long path at a fine resolution no longer needs gigabytes of memory.

**Projects**
- A reopened project keeps its stored program, and Save keeps every component's program, not only the open tab's.
- Invalid values in a hand-edited project are refused with a reason.

**Interface**
- Cancel stops a build, export, simulation or nest, and closing the window during a build no longer crashes.
- A failure shows a message with a button that opens the log.
- A typed number applies when you press Enter or click away, not on every keystroke.
- Quit and Preferences shortcuts can no longer be taken by another action.
- The Preferences window fits the screen and remembers its size.
- Tooltips wrap to a readable width, and the **?** button at the end of the toolbar turns them off and on.
- Checkboxes are drawn in the app's own colors, so an unchecked box is clear in dark mode.
- A slider clicked into place, rather than dragged, settles like any other edit. Before, the Forming view could keep a drag's rough preview on screen until the next rebuild, and a changed Model slider could leave a stale program marked ready. (Fixed in the downloads rebuilt on 2026-09-30.)

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

Pair it with [GuildDraw 1.3.0](https://github.com/csobod/GuildDraw/releases/tag/v1.3.0) to draw the frame in the first place.

## Learning GuildModel

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each component, the Forming view, simulation, export and the GuildSend handoff. Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
