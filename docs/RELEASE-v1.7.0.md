# Release v1.7.0: every component you can build, you can export

GuildModel has built temples and base-curve forming templates since v1.5.0; it
has drawn them in 3D, simulated them, and posted their programs. It could not
write an STL of either one. Export STL was wired to the frame front alone, and
a maker who asked for a base-curve template got a dialog telling them to draw
five SCULPT section cuts, which is advice that component can never take. This
release closes that, and fixes the three silent faults found while chasing it.

**No program changes.** The toolpath generator reads the relief heightfield
directly and never touches the mesher this release rewrote; programs posted
with v1.6.0 remain valid, and nothing needs re-posting.

## Version -> 1.7.0

The five stamped places: `src/guildmodel/__init__.py`, `pyproject.toml`,
`installer/GuildModel.iss`, `README.md`, `docs/USER-GUIDE.md`. `__init__.py` is
the one that matters; both release scripts read `from guildmodel import
__version__` and pass it to Inno as `/DMyAppVersion`, so the `.iss` values are
the hand-compile fallback.

## What a maker will notice

**Export STL now offers whatever is on screen.** A frame front, a temple, or a
base-curve template; if the component builds, it exports. **Export All STL**
(Ctrl+Shift+E) asks for one folder and writes every buildable component into
it, named for the component. A drawing carrying more than two lens curves
produces more than two templates, and those are numbered rather than silently
overwriting one another.

**Exports are now the model's own triangles.** Export previously rasterized the
selected kernel back into a heightfield before writing, so an exact model
reached the file as a raster remesh of itself; the Inspector could report
"Model verified" over a build the maker never received. The exact kernels now
write what they built. On a frame front this is 34,000 triangles and 1.71 MB in
place of 262,000 and 13.10 MB.

**Every export is measured, and says what is wrong without refusing.** Triangle
count, volume and verdict go to the log per component, followed by any problem
found. A mounting hole that will not fit its lens is reported here and in the
block program; the maker still gets the file.

## The base-curve template could not be exported, for two reasons

The rim conform projects grid vertices onto a polyline, so three corners of one
quad landing on a single straight segment come out exactly collinear. Those are
real triangles of zero area, and both halves of the pipeline mishandled them.

**The validity check was wrong.** It dropped zero-area faces before counting
open edges. A face with no area carries no surface, but it does carry the seam
between its neighbours; dropping one unpairs three edges that were never open.
On a base-curve template that turned 86 collinear faces into a report of 258
gaps, in a solid that trimesh, an STL round-trip and the Euler characteristic
all agreed was closed. `welded_surfaces` now returns both surfaces, and gaps
are counted on the full one while self-contacts are counted on the live one.

**The mesher should not have produced them.** A grid quad now splits on its
other diagonal where the default choice collapses. This is a re-triangulation
and not a re-shaping; the collapse happens only when three corners are
collinear, and three collinear points plus a fourth are always coplanar, so
both splits cover the same region. Volume and triangle count are unchanged, and
229 builds across a real drawing corpus now emit zero degenerate faces.

## Three faults that passed every gate

**A boolean switch was removing material silently.** `SetUseOBB(True)` rejects
face pairs using oriented bounding boxes, and on some geometry it rejected
pairs that do intersect. Two drawings failed loudly with gaps and self-touching
edges. A third passed every check while 29.1 mm3 of material went missing; the
raster and Manifold kernels both disagreed with it by 0.26%, and nothing in the
application would have said so. The switch is gone, at a cost of 2.4% build
time in the worst case and 0.0% across a full corpus sweep.

**A footing blend that will not close.** On one drawing of forty, the
nosepad-to-bridge blend leaves a 0.08 mm hole where it meets the bridge
terrace; it is one of a mirrored pair whose two fills differ by 0.0009 mm3, and
`BRepCheck_Analyzer` calls it valid. No targeted remedy closes it. The solid
builder now checks closure with the application's own tessellation oracle and
rebuilds once from flattened terraces when the check fails. The rebuild costs
0.017% of the part, is faster than the build it replaces, and is paid only by
the drawings that need it.

**Mounting holes that do not fit the lens.** The three-hole M4 pattern is fixed
at a 10 mm pitch and nothing compared it against the lens being cut. Across 96
templates in a real corpus, 10 fail: the hole breaks the rim and comes out as a
notch, which leaves the mesh watertight and every existing check satisfied. On
the smallest eye, two of three break out and the template arrives with one
usable mounting point. The Euler characteristic is the tell; a good template is
-4 and those come out at 0. Three severities are now reported by name: off the
block entirely, breaching the rim, or leaving a wall thinner than the blank.

## Release engineering

**The release gate no longer runs the tests that hang it.** 32 tests build a
real application window, and on the hosted Windows and Intel macOS runners one
of them parks the main thread; the per-test timeout then kills the interpreter,
so a single hang ends the run and no artifact is produced. That cost 80 minutes
of a Windows runner and 79 of a macOS one during v1.5.0. Both workflows now
gate on `-m "not gui"` and run the window tests afterwards in a step that
reports without blocking, placed after the artifact upload so a hang cannot
delay the build. This split had been described in `pyproject.toml` since v1.5.0
and was never implemented; it is now implemented and pinned by a test.

**Test corpus without vendored drawings.** Every fault above needed a real
drawing to reproduce, and those drawings are not ours to publish.
`tests/test_frame_corpus.py` reads a corpus from `GUILDMODEL_FRAME_CORPUS` and
checks the properties those faults violated; it names no drawing and skips when
the variable is unset.

## Corrections carried in the history

Export All shipped in this branch naming its files by component kind, which
gave several base-curve templates from one drawing the same filename; ten
components built and four files were written, with the six overwrites logged as
successes. It is the same class of fault as the boolean above, found the same
way, and the fix is pinned by its own test. Two tests written for this release
asserted less than their names claimed and were rewritten rather than removed.
