**GuildModel 1.8** shows the frame front as it will be worn. The new **Forming** view bends the front the way the press and the bench do: the base curve in each rim, the face form at the bridge, and the bridge set forward between two creases. You can export that formed front as an STL and print it to try on before you cut. This release also adds a **hinge pocket angle**, and it fixes a set of faults found in a full review of the program before release.

**Most programs you posted with 1.7 are still good.** A frame front on the default onion skin, a temple and a base-curve template post the same program, byte for byte. Some programs do change; the next section lists them.

Thank you to everyone filing issues and keeping the conversation going. For continued support and conversation, please visit our [RootApp Server](https://guild.vision/community) and follow me on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

## What to re-post

I posted the Gabriel front, a temple and a base-curve template through 1.7.0 and through 1.8.0 and compared the files. The front on the onion skin, the temple and the template are identical. Forming never changes a program; the Forming view reads the model and writes an STL, and the CAM cannot load the forming code.

Re-post these:

- **A frame front held by tabs.** The release pass now ramps in; before, it plunged straight to the floor. Only the entry of that pass changes.
- **Every worktable (bed) program.** Each part on the bed now cuts at its own feeds and depth per pass, and the rapid height now clears the tallest part's stock. Both are described below.
- **A frame with no SCULPT section cuts.** Its profile-only program now cuts the whole ring. Before, the last segment of each pass was not cut.
- **A tilted hinge pocket.** This is new, so it applies only if you set an angle.

**If you upgrade from 1.5 or earlier, re-post everything.** 1.6 changed the default relief stepover and fixed the sawtooth pattern in the posterior feature finish. Read the [1.6 notes](https://github.com/csobod/GuildModel/releases/tag/v1.6.0) before you cut.

## New in 1.8

- **View ▸ Forming (`F`).** On the Frame Front tab, after you build the model, press `F`. A panel opens under the 3D view, and the front in the view is replaced by the formed front. Press `F` again to go back to the flat model; it comes back at once, from cache.
  - **Base curve** is in diopters, from 0 to 16 in quarter steps, as the forms are tagged.
  - **Face form** is the angle between the two rims at the bridge.
  - **Bridge projection** sets the bridge forward, from 0 to 8 mm. The die presses the bridge away from the face only.
  - **Crease gap**, **crease angle** and **bridge offset** place the two creases that the V plate leaves. **Die radius** is the radius of the die's face; *Auto* is the largest die that reaches the projection through the gap. **Crease blend** rounds each crease; *Sharp* is the plate's own edge.
  - The sliders are live. On the Gabriel drawing, the view redraws about nine times a second while you drag.
  - The strip over the view shows the settings, for example `FORMED · SBT base 4 · 4.00 D · 164° · +4 mm`. When a bend is too tight for the part, the readout says so.
- **Press presets.** The SBT base-curve press ships as four rows: base 2, 3 and 4 with lens curve 4, and base 2 with lens curve 2. A row sets the base curve and the face form together, and the model bends to that die's own radius. To add your own presses, write them in `~/.guildmodel/presses.yaml`.
- **Export Formed STL.** **File ▸ Export Formed STL** writes `frame_front_formed.stl`: the formed front, with the lens bevel groove in the rims, as one closed solid in millimeters, ready for an SLA printer. **Export All STL** adds this file when the front's forming is not flat.
- **The forming is saved with the project.** A project from 1.7 or earlier opens flat.
- **Hinge pocket angle.** This new setting tilts the floor of each hinge pocket. At 0°, the default, the pocket is flat, as before.
  - On the **Frame Front** (Model tab), the superior edge of the pocket keeps the set depth, and the angle moves the inferior edge. This changes the pantoscopic angle at which the temple leaves the endpiece.
  - On a **Temple** (Temple tab), the anterior edge keeps the set depth, and the angle moves the posterior edge. This offsets splay that is built into a hinge.
  - The slider goes only as far as the drawing allows. Both edges of the longest pocket stay between the surface and 0.5 mm above the anterior face.
  - A tilted pocket gets a finishing pass with the same tool. At 5°, the pass takes the highest ridge on the floor from about 0.1 mm down to 0.022 mm.
  - A flat end mill cannot reach a narrow strip against the downhill wall: 0.27 mm at 5° with the 3.175 mm cutter. Clean it up by hand, or let the hinge leaf's edge radius take it.
- **The Temple tab has a Hinge pocket depth control.** Before, a temple always cut its pockets at 1.0 mm, because the tab did not keep the depth that a project saved.

## Fixed

Before this release, the whole program was reviewed, not only the new work. These are the faults a maker could meet.

- **A reopened project keeps its program.** When you opened a `.gmodel`, the stored program was restored and then lost. The readiness dot came up red, Export G-code was disabled, and the next save removed the program from the file. This was true in every release since 1.0.
- **Every component's program is saved.** A project saved only the program of the tab that was open. Now each component's program is in the file. GuildSend still streams the program of the tab you had open, as before.
- **Cancel works.** The Cancel button on a progress dialog did nothing until the job was complete. Now it stops Build 3D, Export STL, G-code, Simulation and Nest at the next step.
- **Each part on the bed cuts at its own settings.** A worktable program cut every part at the project's feeds and depth per pass. A base-curve template in acetal, nested with an acetate front, was cut at acetate's feeds. Now each part cuts at its own material's feeds and depth per pass, and at its own overrides. A tool with its own feeds in the tool library keeps them, as it does for a single part. When you nest, the log shows the material and the feeds for each part.
- **The bed program's rapids clear the stock.** The rapid height of a worktable program came from the fixture's nominal stock thickness, not from the parts. With an 8 mm blank on a 6 mm pad block, every rapid ran 1 mm inside the pad block. Now the rapid height clears the tallest part on the bed. Also, GuildModel now refuses to post any program whose rapid height is not above every cut; the simulation cannot see a rapid, so the post checks it.
- **The profile-only program cuts the whole ring.** For a frame with no SCULPT section cuts, the perimeter, the tabbed release pass and each decorative hole were left open at their seam: 1.3 mm of material on the aviator, and a full side of a rectangular hole.
- **A tabbed release pass ramps in.** It plunged straight to the floor because it rises over its tabs, and the ramped entry accepted only a level pass.
- **A hole that the tool cannot enter is reported.** A decorative hole narrower than the tool plus its allowance was skipped, and nothing said so. Now the log shows a warning with the hole's size and the tool.
- **Failures show a message.** When a build, G-code, export, simulation or nest failed, the status bar said "see log", and the log panel is hidden by default. Now a message names the failure, and its **Show Log** button opens the log.
- **The shortcuts in the user guide are correct.** The guide had `Ctrl+O` and `Ctrl+Shift+O` the wrong way round. `Ctrl+O` opens a drawing (`.gdraw`); `Ctrl+Shift+O` opens a DXF. The table in section 10 now lists every default shortcut.
- **You cannot rebind Quit or Preferences.** If you put an action on `Ctrl+Q` or `Ctrl+,`, both actions stopped working. Preferences ▸ Hotkeys now shows this as a conflict and keeps OK disabled until you change it.
- **Typing a number in the Cut tab is fast.** Each keystroke in a feed or speed field was applied as a new value. Now the value is applied when you press Enter or Tab, or click away.
- **Closing during a build no longer crashes.** GuildModel now stops its work before the window closes.

## Under the hood

- **A saved project carries a folder for each component.** The file has `components/<id>/` with that component's programs, setup sheet, machine profile and cut report. The top-level `program/` folder is the same as before, so GuildSend and GuildModel 1.7 read the file as they always did. GuildModel 1.7 ignores the forming and pocket angle settings; if you save the project again in 1.7, they are removed.
- **Values that a machine must never see are refused.** A hand-edited project with a rapid clearance of 0, a feed rate of 0, a pocket angle beyond the slider or a `NaN` in the forming settings now gives an error with the reason. Before, some of these reached the program.
- **Preferences are written safely.** GuildModel writes a new file and then replaces the old one. Before, a crash during the write could leave an empty file, and your recent files, shortcuts and toolbar reverted to the defaults.
- **More regression tests.** The suite has 1,315 tests. The new tests hold each fault above closed.
- **The Intel Mac build has more time.** At 1.7, the test gate on the Intel Mac runner used 76 of its 90 minutes. The limit is now 110 minutes.

## Known issues

- **An edge feature can fold at a very sharp corner.** This is still true from 1.5. A near-cusp is a corner that turns tighter than the feature is deep, for example an aviator endpiece at 58° in a quarter of a millimeter. Where a run passes one, the swept cut can cross itself. The log and the Inspector then show "the model overlaps itself along N edges", and GuildModel does not count the model as built. **After a rebuild, read the log, not the readiness dot.** A program that you stored before keeps the dot green. To clear the fault, move the run's **Trim start** or **Trim end** past the corner, or ease the corner in the drawing.
- **The formed volume is not the flat volume.** Forming bends the front; it does not stretch it. The posterior is on the concave side and is compressed a few percent. This is expected.
- **A crease can be up to 0.3 mm off in the formed STL.** Where a 1.5 mm edge of the file crosses a crease, it can sit up to 0.3 mm off the true surface. This is less than a printer's usual tolerance.
- **A grooved STL can show four-face edges in a slicer.** A file with the lens bevel groove, flat or formed, has eight coincident edges from the groove. A slicer that merges vertices can report them. The file is one closed body, and it was the same in 1.7.

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

The [user guide](docs/USER-GUIDE.md) covers opening a drawing, tuning each component, the Forming view, simulation, export and the GuildSend handoff. The full list of changes is in [CHANGELOG.md](CHANGELOG.md). Video tutorials are on [my YouTube channel](https://www.youtube.com/@spectacle-maker).

Made by the Guild of American Spectacle Makers. GPL-3.0.
