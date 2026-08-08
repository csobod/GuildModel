# BUILDPLAN-NEW — The Model Kernel, Re-examined

*2026-08-07. Written after the Stage 2 curve work hit a wall: user-visible
breakage (a spike of material off the nosepad, features that corrupt the model)
on a real drawing, with every automated check green. This document is the deep
audit that was asked for: what our chosen method actually is, what the evidence
says about it, what the alternatives are, and what to do. Every number in it was
measured on this machine, this week, on this codebase — the probe scripts are in
`scripts/` and the session history is in BUILDPLAN.md's Stage 2 log.*

---

## 1. The one-paragraph verdict

The project's goals are right and most of the codebase is sound. The failure is
localized and structural: **general-purpose B-Rep boolean modeling (OpenCASCADE)
is the wrong tool for this workload**, and no amount of hardening fixes it,
because its failure modes are data-dependent, order-dependent, session-history-
dependent, and — decisively — **invisible to the kernel's own validity checker**.
This was not a mistake of language ("solids within Python"): the kernel is C++;
a C++ rewrite inherits every failure documented below, byte for byte. The
recommendation is a **staged replacement of the construction layer only** —
mesh-domain CSG via the Manifold library, driven by the same exact curves,
parameters, and partition we already have — keeping the intake, the GUI, the
CAM, and the test suite. A feasibility spike already runs the full failing
workload **220× faster with a guaranteed-closed result**. No new codebase. The
foundations were never the problem.

---

## 2. What we are actually building (the requirements, distilled)

Stated plainly, because the choice of tool has to be judged against the actual
job and not against "CAD" in the abstract:

1. **Input**: GuildDraw drawings — closed NURBS outlines, lens curves, straight
   SCULPT cuts, hinge rings — via `.gdraw` (primary) and DXF. This part is
   *done and exact*: both intakes now carry the authored curves with 0.0000 nm
   deviation (BUILDPLAN Stage 2).
2. **A fixed, small vocabulary of parametric features.** Terraces at per-zone
   heights, footing blends, hinge pockets, the lens-groove V (an undercut), the
   eyewire bezel, edge chamfers/fillets, pad splay, bridge relief, engraving.
   There is no user-driven freeform modeling. **We know every face of the
   result analytically before we build it.** This is the single most important
   fact in this document.
3. **Outputs**: a crisp interactive preview with real feature edges; a
   watertight STL; measurements (volume, sections, boxing); and G-code. **The
   CAM does not consume the solid** — it posts from the 2D curves plus the
   parameters. The solid exists for preview, export, and verification.
4. **Qualities**: Fusion-360-like feel — change a number, the model updates,
   *every time*, identically, fast. GPL-3. Linux-first. One person maintains
   this.
5. **Tolerance regime**: machining. The chord tolerance everywhere in the
   pipeline — importer flattening, raster, CAM — is **0.01 mm**. Nothing
   downstream ever consumes surfaces more exactly than that except the B-Rep
   itself.

Point 2 + point 3 together are the indictment of the current approach: we are
using machinery built to intersect *arbitrary analytic surfaces exactly* — a
research-grade problem — to assemble a known family of shapes whose every face
we can already write down, for consumers that need 0.01 mm.

---

## 3. The evidence against the current method

### 3.1 This week's user-visible bugs, reproduced and traced

The reported symptoms — a spike of material off the nosepad, features breaking
the model — were reproduced on the **aviator fixture** (the second real drawing
we own; the demo frame is clean under every probe, which is itself the lesson:
*fixture-based testing cannot protect users from this kernel*).

Measured, same code, same drawing (`scripts/probe_occt_history.py`):

| build | result |
| --- | --- |
| groove, fresh process, cache cleared | watertight ✓ |
| the GUI sequence: bare → splay → bridge → groove, caches warm (i.e. a user clicking checkboxes) | **splay leaks, bridge leaks, groove leaks — and "groove again" still leaks** |
| one-pass cut, tools ordered `groove+hinges` | watertight ✓ |
| the same call with the same tools ordered `hinges+groove` | **leaks** |
| every sequential-cut variant of the same operations | leaks |
| one full-pipeline run produced 2,485 vertices of junk **10.2 mm outside the body**; the same nominal pipeline in a fresh process produced none | the on-screen spike class |

**`BRepCheck_Analyzer` reports `IsValid = True` for every row of that table.**
Volumes agree to 0.001 mm³ between the leaking and non-leaking variants — the
geometry is "right" while the topology is corrupt.

The obvious mechanism — OCCT booleans are destructive by default and our base
cache re-feeds the same mutated shape — was tested: `SetNonDestructive(True)`
**does not fix it** (groove builds watertight once, then the *identical* build
leaks on the next call). There is no switch for this one. We looked; we have
found four off-by-default switches this week alone (`SetRunParallel`,
`SetUseOBB`, `SetToFillHistory`, `SetNonDestructive`) and the fifth does not
exist.

### 3.2 The season's full catalog

Each of these cost real time this week, each is recorded with numbers in
BUILDPLAN.md, and each was **silent** — no exception, no invalid flag:

| # | failure | detection |
| --- | --- | --- |
| 1 | **Empty-but-valid**: booleans returning zero-volume/zero-face shapes that pass `IsValid()` — four separate occurrences | volume guards we wrote |
| 2 | **`BRepGProp` disagrees with itself**: two *disjoint* prisms whose fused "volume" ≠ the sum, at every `Eps` setting (1550–2413 mm³ for a true 2008) | our mesh oracle |
| 3 | **Silent vertex-tolerance rejection**: `MakeEdge` refusing arc junctions 0.19–0.54 µm off (default tol 1e-7 mm), quietly leaving *two ninths of every frame polygonal* while classification, verification, volume, and watertightness all read correct | counting edges by hand |
| 4 | **`MakePipeShell`**: refuses offset-curve spines outright; 401 s + invalid on a polyline spine; the multi-section bezel sweep yields a beautiful valid 4-face cutter whose *cut* takes 260 s and returns an invalid solid with **negative volume** | trying it |
| 5 | **`BRepFilletAPI_MakeChamfer`**: chamfers a box, chamfers our own extrusions — and 0/30 rim edges on the real part at every width; non-monotonic in width on bare terraces (2.5 mm succeeds where 1.0 mm fails) | trying it |
| 6 | **Order/history dependence** (§3.1) | the user's screenshot |
| 7 | **Cost**: all-features build 20.5 s cold / 15.2 s warm polygonal, 35.0 s / 21.7 s curved — after a week of optimization that already took it down from 82.8 s | benchmark |

The pattern across all seven: the kernel fails *sideways*. Not an error, not an
invalid flag — a wrong shape, a leak, a hang, delivered with a clean bill of
health. **The only oracle that has ever caught any of these is the
tessellation**: watertightness of the mesh and volume of the mesh. Our ground
truth is already the mesh. The kernel is a 70 MB middleman between us and the
representation we actually trust.

### 3.3 What OCCT genuinely delivered (fairness)

The Stage 2 *goals* were correct and most were achieved: exact curve carriage
end-to-end (0.0000 nm), real feature edges instead of dihedral guessing, the
undercut groove as first-class geometry, sectioning and measurement, watertight
export *when it works*. The move from raster to a real model was right. The
error was equating "a real model" with "a general B-Rep kernel."

### 3.4 Why "rewrite it in C++ / another language" is a red herring

Every failure in §3.1–3.2 happens inside compiled C++ (OCCT itself). Python
orchestrates; the GIL costs us thread-level parallelism of *our* calls, but the
82 s → 35 s history shows the time is in the kernel's own algorithms, not in the
interpreter. A C++ port of this codebase would reproduce the catalog exactly,
after a rewrite measured in months. Likewise CadQuery/build123d (same kernel
underneath) change the ergonomics, not the math.

---

## 4. What is sound and must survive any redesign

These are assets, most of them new this week, all of them kernel-neutral:

- **The intake.** `.gdraw` and DXF both deliver exact authored curves
  (`core/geometry/curves.py` — deliberately kernel-free) alongside the same
  0.01 mm flattened points. Verified to 0.0000 nm on both fixtures. *This is
  the "reliable standard of intake file format" the mandate asks for, and it
  already exists.*
- **The 2D layer.** Partition/zones/edges (Shapely), the boxing measurements,
  `OffsetCurve` ("that curve, d inward" — exact by definition).
- **The parameter schema** (`project/schema.py`) — the entire feature
  vocabulary, typed and versioned. This *is* the parametric model; the solid
  was only ever its evaluation.
- **The CAM.** Posts from curves + parameters; never consumed the B-Rep.
  Untouched by any of this.
- **The GUI shell** (PySide6, component workspaces, the dock, the viewer).
- **The test suite as a behavioral spec** — 768 tests, including the oracles
  that actually work: ray-crossing V-profile spec (5 µm), raster-agreement
  gates, watertightness, mesh volume. These tests define what "the castle" is
  independently of who builds it.

Note what this list amounts to: **everything except `core/solid`'s construction
calls.** The seam already exists — `build_castle_solid(partition, castle,
hinges) → solid → tessellate() → mesh` — and the GUI consumes the mesh, not the
solid.

---

## 5. The alternatives, examined

### A. Harden OCCT in place — **rejected**

This week *was* that strategy, executed aggressively: four kernel switches
found, three construction rewrites (segmented arcs, swept groove, junction
tolerances), 60× on the original build time. The reward was a new
data-dependent failure on the second drawing we own, unfixable by the fifth
switch. §3.1 is the measured proof that the next trap is always input-shaped,
which means users find it before tests do. A one-maintainer GPL project cannot
staff a permanent OCCT-pathology department.

### B. Same kernel, different host (C++, CadQuery, build123d) — **rejected**

§3.4. Same math, same catalog, plus a rewrite.

### C. Commercial kernels (Parasolid, ACIS) — **rejected**

License-incompatible with GPL-3 and with the project's premise.

### D. Young Rust B-Rep kernels (Fornjot, truck) — **rejected for now**

Philosophically aligned, years from the maturity this needs; we would trade
documented pathologies for undocumented ones.

### E. Implicit/SDF modeling (libfive et al.) — **rejected as the core**

Robust CSG by construction, but surfacing via marching cubes fights exactly
what we need most: crisp feature edges and exact dimensional control at
machining tolerance. Worth revisiting someday for cosmetic preview effects;
not for the model of record.

### F. Mesh-domain CSG — Manifold — **recommended**

[Manifold](https://github.com/elalish/manifold) (Apache-2.0 → GPL-compatible;
`manifold3d` 3.5.2 on PyPI; the boolean engine OpenSCAD adopted; actively
maintained). Its entire premise is the property we keep discovering we need:
**the output of every operation is guaranteed manifold** — the halfedge
representation cannot *express* a leak — and failures are loud (`status()`
errors), deterministic, and input-side.

**The feasibility spike** (`scripts/spike_manifold.py`), run on the aviator —
the drawing that breaks OCCT — building the same workload from the same
partition at the same 0.01 mm flattening: 8 terraces unioned, 2 hinge pockets
subtracted, and the lens-groove V — *the undercut that justified the solid
rewrite* — swept as 360 per-segment convex hulls per aperture:

| | OCCT (this branch, after all optimization) | Manifold spike |
| --- | --- | --- |
| same build, cold | 8,600 ms | **39 ms** (220×) |
| watertight | **depends on click order** (§3.1) | closed: **0 boundary edges of 33,036**, counted directly |
| topology | `IsValid` regardless of correctness | genus 3 — exactly the aviator's two lenses + keyhole |
| undercut V | works (when the build survives) | present at **40/40** ray stations |
| volume | 9,152.4 mm³ | 9,237.4 mm³ (delta = the footing blends, not yet ported in the spike) |
| determinism | history- and order-dependent | identical every run |

Two honest notes from the spike, both instructive. First, my hand-rolled tube
mesh was initially wound inside-out and then self-intersecting near the
aviator's teardrow corner — **my** input bugs, caught immediately (negative
volume; visible boundary edges), fixed by construction (per-segment hulls).
That is what failure looks like in this domain: *your* bug, *detectable*,
*deterministic*. Second, `trimesh.is_watertight` under-reports on Manifold's
raw output because MeshGL splits vertices along property boundaries and carries
its own weld map (`merge_from_vert`); the direct combinatorial count (every
directed edge paired) is the correct check and comes back perfect. The export
path must apply the weld map — a footnote, now known.

**What about exactness?** The curves stay exact — they remain the source of
truth for CAM (toolpaths follow the NURBS and its offsets, as they already do)
and for measurement of record. The mesh is evaluated *from* those curves at
whatever density the purpose needs: 0.01 mm for display parity with today,
finer for export if ever wanted, coarser for live dragging. One geometry, one
tolerance knob, no second representation fighting the first. This is also
exactly how Fusion actually feels interactive: display meshes over an exact
definition.

**What about feature edges?** Better than today, not worse. We *know* every
edge analytically — ring curves at terrace heights, groove lips, chamfer
boundaries — because we authored them; they can be drawn from the curve data
directly. (Today's B-Rep hands us 23,088 topological edges, most of which are
boolean scars we then have to filter.) Manifold's face provenance
(`originalID`) additionally labels which input produced every output triangle,
for free.

**2D synergy**: `CrossSection.offset` gives robust polygon offsetting inside
the same library (today: Shapely buffer + our `OffsetCurve` + a comparative
guard), and `project`/`slice` cover sectioning.

---

## 6. Recommendation

**Replace the construction layer; keep everything else. In this codebase, not a
new one.**

Concretely: a new `core/model/` package whose public function is the same shape
as today's seam — *(partition, castle params, hinges) → watertight mesh +
feature edges* — built on Manifold primitives:

| feature | construction (all robust primitives) |
| --- | --- |
| terraces | `CrossSection` → `extrude`, one per zone, `batch_boolean` union |
| hinge pockets | extrude → subtract |
| lens groove V | per-segment convex hulls along the ring (spiked, 40/40) |
| bezel / edge chamfers | same station machinery as today, sections → per-segment hulls (no `ThruSections`, no `MakePipeShell`, no chamfer engine) |
| pad splay / bridge relief scoop | ditto — they are swept sections today already |
| footing blends | ditto — the S-profile sections already exist (`_blend_section`); swept as hull chains |
| rim lip | `CrossSection.offset` (with the existing `OffsetCurve` staying the CAM-side truth) |

Anchoring rays (`surface_z_at`) become mesh raycasts (trimesh + rtree are
already dependencies; Manifold has its own ray API).

Nothing about the GUI, intake, schema, CAM, or file formats changes. The raster
path and the OCCT path both eventually retire, taking roughly 4,500 duplicated
lines with them — the codebase *shrinks*.

**Why this is not another bandaid** (the mandate's phrase): it aligns the
construction domain with the verification domain. Every reliability incident
this season reduced to "the construction layer and the truth layer disagreed,
silently." After this change they are the same layer, and the closed-mesh
property is enforced by the data structure, not by hope. That is the structural
fix; everything else in this document is bookkeeping around it.

---

## 7. Migration plan

Staged so that at every point the app still works and the old path can referee.

**M-N0 — stop the bleeding (immediately, on the current branch).**
The §3.1 history-dependence is a shipping bug today. Mitigation candidates, in
order: (a) copy the cached base (`BRepBuilderAPI_Copy`) before each feature
pass; (b) failing that, drop `_BASE_CACHE` (costs the 0.6 s warm win; honesty:
measure first). Gate every GUI-facing build on the *mesh* oracle (closed +
volume sane), not `IsValid` — on failure, rebuild once from cold before
surfacing an error. Also: obtain the Gabriel drawing from the screenshot as a
third fixture. ~1 session.

**M-N1 — the mesh feature kernel.** `core/model/` with terraces, pockets,
groove, bezel, edge features, splay, scoop. Port the per-feature parity tests
to run against *both* kernels: the ray-crossing V spec (5 µm), the
raster-agreement chamfer gate, mesh volumes to a stated tolerance, watertight
always. The footing blends are the real work item (the S-sections exist; the
sweep is new). ~2–3 sessions. **Kill switch**: if footing parity cannot meet
the existing gates, fall back to hybrid — OCCT builds the (cacheable, rarely
failing) base, Manifold applies every feature to its tessellation; §3.1 shows
the features, not the terraces, are where the kernel dies.

**M-N2 — into the app behind a flag.** `MultiMeshWorker` gains the Manifold
path; readiness dot = Manifold `status()` + our own boundary-edge count (the
direct check from the spike, it costs microseconds). A/B command in the debug
menu: build both, diff volumes and silhouettes. ~1 session.

**M-N3 — parity and the flip.** Demo + aviator + Gabriel: volume, silhouette,
V-profile, chamfer gates, **posted G-code byte-equivalence** (it posts from
curves, so this should be exactly equal — any diff is a bug found cheap).
Flip the default. OCCT demoted to an optional cross-check behind a debug flag.
~1 session.

**M-N4 — the payoff.** Retire the raster relief path (its only remaining role
is being the third opinion) and then the OCCT path; `cadquery-ocp` becomes an
optional dev dependency and 70 MB leaves the install. Slider dragging goes
live-continuous: the spike's 39 ms full build is faster than one frame of the
current progress dialog. Update BUILDPLAN.md to point here.

Total estimate: **5–7 working sessions** at this codebase's demonstrated pace,
with the app never broken in between. Compare: staying the course spent one
session this week producing two correct features and one new class of silent
corruption.

---

## 8. Risks, stated plainly

1. **The footing blends are unproven in the new kernel** — the spike's volume
   delta (85 mm³) is exactly the unported footings. They are ruled sections
   swept along measured stations, i.e. the same per-segment-hull pattern as the
   groove, but until built this is the schedule risk. Mitigated by the M-N1
   kill switch (hybrid mode), which is itself a fully acceptable end state.
2. **Mesh density becomes a quality knob.** Chord 0.01 mm matches today's
   contract everywhere, but edge crispness in the *viewer* now depends on our
   analytic edge overlay landing exactly on the mesh — needs one careful test.
3. **A second geometry dependency.** Manifold is small (~MBs vs OCCT's 70),
   Apache-2.0, and load-bearing for OpenSCAD; risk accepted. It was installed
   into the venv for the spike but is *not* yet in `pyproject.toml` — M-N1
   adds it.
4. **Measurement of record.** `mesh_volume` is already the referee (BUILDPLAN,
   GProp table); Manifold's `volume()` agreed with the welded trimesh to the
   third decimal in the spike. Sectioning via `slice` needs porting from the
   OCCT sectioner — small, testable.
5. **Sunk cost, honestly faced.** The exact-curve work is *not* lost — it feeds
   the mesh evaluation and the CAM. The OCCT-specific work (arc segmentation,
   junction tolerances, boolean switches) becomes archaeology. That is the
   price of the week that also produced the evidence in §3; it was not
   knowable in advance, and it is cheaper than the next such week.

---

## 9. The decision being asked for

Approve the direction (§6) and M-N0/M-N1 as the next work. The first visible
deliverables: the in-session corruption bug mitigated on the current branch,
the Gabriel drawing as a fixture, and the mesh kernel building the bare castle
+ groove with the full parity suite green — at which point the 39 ms number
stops being a spike and starts being the product.
