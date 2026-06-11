# OLGA Suite Teardown → GuildCAM Design Reference

**Status:** reference document (informs `BUILDPLAN.md` and the M0–M3 milestones)
**Date:** 2026-06-03
**Source material:** decompiled CamBam plugins from `D:\CamBam plus 0.9.8\plugins\`
(olgaV5, OLGA V1, CHA, BR, courbes2, SVGStAlone) authored by *Julien Bonnemay /
"Clément Lunetier" / lesopticiens.fr*.

> **Why this exists.** The OLGA suite is a working, in-production toolchain for
> CNC-milling eyeglass frames. We reverse-engineered it not to copy code (it is
> proprietary, obfuscated only lightly, and carries machine-fingerprint DRM we
> explicitly do **not** reproduce) but to recover the **domain workflow, the
> geometry algorithms, the parameter vocabulary, and the real-world numbers** that
> a frame-cutting CAM tool must get right. Everything below is a behavioural /
> algorithmic description. GuildCAM remains a clean-room, GPLv3 reimplementation.

---

## 1. What OLGA actually is (the ground truth)

OLGA is **not** a standalone CAM engine. It is a set of CamBam plugins + a
standalone "ID Conception OLGA" front-end (`OLGA V1.dll`, ~10k lines) that:

1. Lets an optician lay out a frame **face** and **temples** ("branches") as 2D
   polylines inside CamBam's CAD canvas.
2. Captures machining parameters through WinForms dialogs (cutter diameter,
   precision, bevel offsets, hinge pocket geometry, lab thickness…).
3. Prepares 3D toolpath geometry as CamBam `Polyline` entities on dedicated
   **layers** ("ID chanfrein Face Avant/Arriere" = chamfer, front/back face).
4. Hands off to **CamBam's own CAM pipeline** (`CAMUtils.GenerateGCodeOutput`) and a
   **swappable VBS post-processor** (selected via a `GCODE,` config entry) to emit
   the final NC code.

**Architectural consequence for us:** the DLLs are *UI + parameter capture +
geometry preparation*. The actual cut recipe (which machine ops, depths, tool
order, feeds) lives in **embedded VBS post-processor scripts** and CamBam MOP
definitions, not in compiled code. GuildCAM collapses all four layers above into
one headless Python core + its own GRBL post — which is the right call and makes
us controller-portable instead of CamBam-bound.

### 1.1 Module map (OLGA → GuildCAM)

| OLGA component | French term | Does | GuildCAM home |
|---|---|---|---|
| `olgaV5`, `courbes2`, `CHA-chamfer` | *chanfrein* | Lens-rim **bevel / groove** flank | `core/relief/groove.py`, `core/cam/profile.py` |
| `CHA.dll` (OLGA_SaveBr) | *charnière* | **Hinge** pocket + ramp geometry, hinge catalog | **new** `core/relief/hinge.py` + `config/hinges/*.yaml` |
| `BR.dll` | *branche* | **Temple** arm geometry + hinge tab | v2 backlog (temples) |
| `OLGA V1.dll` | — | Full front-end: boxing dims, layout, NC export orchestration | `core/geometry/boxing.py`, `gui/`, `core/post/grbl.py` |
| `SVGStAlone.dll` | — | SVG import helper | `core/io_import/svg.py` |
| `CookieAwareWebClient` + `wmic UUID` | — | **Machine-fingerprint DRM phone-home** | **deliberately omitted** (see §6) |

---

## 2. The core algorithm: bevel / groove generation

This is the single most valuable thing recovered. `olgaV5`, `courbes2`, and the
chamfer path of `CHA` all implement the **same** recipe. Reconstructed from
`button1_Click` / `button5_Click` / `decal1()` / `decal2()`:

### 2.1 Inputs (with OLGA's real defaults)

| OLGA field | Meaning | Default | GuildCAM mapping |
|---|---|---|---|
| `DiaOutil` | cutter diameter (mm) | **3.0** | `tool.diameter_mm` |
| `textBox4` "Precision" | **resample point count** per contour | **500** | `resample_n` |
| `textBox5` "décalage entre les lignes" | offset distance between the two flank contours (mm) | **3.0** | `groove_width_mm` / flank spacing |
| `RBinterne` / `RBExterne` | offset **direction** (− = inside, + = outside) | — | `side: inner/outer` |
| `RBAvant` / `RBArriere` | which **face** (front/back) → target layer | Arriere | front/back relief pass |
| InputBox "hauteur de la polyligne" | per-contour **Z height** (mm) | "6" (front), "4" (back) | flank top/bottom Z |

### 2.2 Procedure

```
for each selected closed contour C (the lens rim):
    1. Offset:  C' = CreateOffsetPolyline(C, sign * diameter/2, miter=1e6)
                  sign = -1 (Interne) or +1 (Externe)        # cutter-radius comp
    2. Resample: P = resample_uniform(C', N=500)             # even point spacing
    3. Winding:  if direction(P) == CCW: reverse(P)          # force CW
    4. Align:    s = nearest_segment(P, firstPoint_of_other_contour)
                 P = split_at_segment(P, s)                  # both contours start
                                                             # at the same place
    5. Record P with its prompted Z height.

# Build the bevel as a RULED surface between the two aligned contours:
bevel = empty 3D polyline
for i in range(N):
    bevel.add( innerContour[i].x,  innerContour[i].y,  Z_inner )   # e.g. Z=6
    bevel.add( outerContour[i].x,  outerContour[i].y,  Z_outer )   # e.g. Z=4
# -> the zig-zag between the two offset rings at two Z levels IS the chamfer wall.
emit bevel on layer "ID chanfrein Face Avant" | "Face Arriere"
```

**Key insights:**

- The "chamfer" is a **ruled bevel between two cutter-radius-compensated offset
  contours at two different Z heights** — *not* a single-depth contour. GuildCAM's
  current `groove.py` returns a single ring at `-depth`; it should be upgraded to
  this two-flank ruled form (it already stubs `profile="vee"|"radius"`).
- **`split_at_segment` start-point alignment** is essential: without it the ruled
  surface twists. Port this as "rotate both rings so index 0 is the nearest pair."
- The `1e6` miter/round parameter on the offset = "keep corners sharp, never round
  them off." In `pyclipper` this is `JT_MITER` with a high `miter_limit`.
- `button5` ("sans modification du Z") keeps each point's **original Z** instead of
  a flat prompted height — i.e. it drapes the bevel over a non-planar (already
  3D / curved) rim. This is the **base-curve-aware** variant and maps directly to
  GuildCAM's heightfield/relief story for curved front faces.
- `courbes2.Addsin()` adds a **sinusoid** along the contour — a decorative/serration
  option; low priority, note for v2.

### 2.3 Recommended GuildCAM form

```python
def bevel_flank(contour, tool_dia, n=500, side="inner",
                z_top=6.0, z_bottom=4.0, flank_offset=3.0) -> list[Pt3]:
    ring_a = resample(offset(contour, sign(side)*tool_dia/2), n)
    ring_b = resample(offset(contour, sign(side)*(tool_dia/2 + flank_offset)), n)
    ring_a, ring_b = force_cw(ring_a), force_cw(ring_b)
    ring_b = align_start(ring_b, ring_a)        # nearest-segment rotation
    out = []
    for pa, pb in zip(ring_a, ring_b):
        out += [(pa.x, pa.y, z_top), (pb.x, pb.y, z_bottom)]
    return out
```

---

## 3. Hinge pockets (`CHA.dll`)

`CHA` (assembly `OLGA_SaveBr`, namespace `Clement_Lunetier`) is the **hinge**
("charnière") tool. It does **not** machine directly; it writes hinge parameters
into `system/XML/cha-doc.xml` and runs one of two embedded VBS scripts that drive
CamBam to cut the pocket. Two modes: **Face** (front frame) vs **Branches**
(temples), selected by buttons. There is a hinge **catalog** ("Ajouter la
charnière au catalogue").

### 3.1 Hinge parameter vocabulary (use these names in `hinge.py` + YAML)

| OLGA XML node | Translation | Likely meaning |
|---|---|---|
| `RotationCharniere` | hinge rotation | yaw of the hinge box about Z |
| `EncombrementCharniere` | hinge footprint / bulk | overall pocket size envelope |
| `ProfondeurPocheCharniere` | pocket depth | flat pocket depth into the material |
| `InclinaisonPocheCharniere` | pocket inclination | tilt of the pocket floor |
| `InclinaisonPente` | slope inclination | ramp angle leading into the pocket |
| `RotationPenteCharniere` | slope rotation | orientation of that ramp |
| `ProfondeurPenteCharniere` | slope depth | depth at the deep end of the ramp |

These define a **tilted, ramped rectangular pocket** that seats a metal hinge.
GuildCAM should model a hinge as: a placement (point + `RotationCharniere`), a
footprint (`EncombrementCharniere`), and a pocket profile (depth + optional
inclination + lead-in ramp). The catalog → `config/hinges/<part>.yaml`.

### 3.2 Recommendation
Add `core/relief/hinge.py` (front + temple variants) and a hinge catalog. The
machining is a **pocket** (already have `pocket.py`) constrained to the hinge
footprint, plus an optional ramped lead-in. This satisfies the README's
"hinge pockets" v1 scope.

---

## 4. Temples / boxing / front-end (`OLGA V1.dll`, `BR.dll`)

- **Temples ("branches")** are built as explicit polylines. Observed hard-coded
  tab geometry (mm): a `60`-long tab at the temple end with slots at `±26.5/±30.5`
  in Y at a Z derived from **lab thickness** `EpLaboBr` (default 4 mm) minus an
  offset. This is the **hinge tab** where the temple meets the front. → v2, but the
  numbers are a useful sanity reference for tab/箱 dimensions.
- **Boxing / sizing** in `OLGA V1` is crude: frame width ≈ `max.X − min.X` of the
  selected polylines, with `profdrag` (drag/bevel allowance) folded in, formatted
  into a label like `A□B  length  C E`. **Do better:** GuildCAM's `boxing.py` should
  implement the proper optical **boxing system** (A = lens box width, B = lens box
  height, DBL = distance between lenses, ED = effective diameter, temple length),
  which is fixed API vocabulary per the brief. OLGA's max−min is only a fallback.
- **NC export** (`creafichiergcode_Click` → `CAMUtils.GenerateGCodeOutput`) is
  delegated to CamBam + a VBS post chosen by a `GCODE,<file>` config line; settings
  persisted to `configuration/DefautConfig.idcnc`. GuildCAM's own `grbl.py` replaces
  this entirely (see §5).
- Multi-language via `Langue2.txt` (`name;text` pairs). GuildCAM can defer i18n.

---

## 5. NC / post-processor: OLGA vs GuildCAM

| Aspect | OLGA | GuildCAM (current/target) |
|---|---|---|
| Engine | CamBam MOPs (profile/pocket/engrave) | own `core/cam/*` (pyclipper + drop-cutter) |
| Post | swappable **VBS** per controller | own `core/post/grbl.py` — GRBL dialect only |
| Dialect | whatever the VBS emits | G0/G1/G2/G3, G20/21, G90, M3/M5, **no canned cycles** |
| Two-sided | layers "Face Avant/Arriere" + manual flip | two `.nc` files (back / front+profile) or single-file `M0` pause |
| Cutter comp | `CreateOffsetPolyline(±d/2)` in geometry | offset in geometry (pyclipper), **not** G41/42 (GRBL lacks it) |

**Validation against current `grbl.py`:** the existing post is correct in spirit
(absolute G90, G21, explicit safe-Z rapids, `M0` flip pause, two-file default).
Add, informed by OLGA:

1. **Per-contour Z ramping / lead-in.** OLGA prompts a Z per contour and ramps; our
   `emit_polyline` plunges straight down. Add a helical/ramp plunge option for the
   bevel and pocket entries (kinder to the 3 mm cutter in acetate).
2. **`G2/G3` arc output** is declared in the docstring but `feed()` only emits `G1`.
   Either keep everything as fine polylines (OLGA's `Precision=500` approach — simple,
   GRBL-safe) **or** implement arc fitting. Recommendation: **stay polyline-only for
   v1** (matches OLGA, avoids arc-fitting bugs); revisit arcs as an optimization.
3. **Feeds/speeds for acetate & the 3 mm cutter** belong in `config/tools.yaml` /
   `materials.yaml`, not hard-coded. OLGA's default cutter is Ø3 mm.

---

## 6. DRM / phone-home — what we must NOT copy

Every OLGA plugin contains the same routine (fully decompiled in
`menuItem_Click`): run `cmd /C wmic csproduct get UUID` to read the motherboard
UUID, check connectivity via `Dns.GetHostEntry("www.google.com")`, then silently
drive a hidden `WebBrowser` to `http://lesopticiens.fr/olga/inscription.php` and
POST the UUID as both `username` and `password` ("utilisation du code CHANFREIN
<UUID>"). It is **usage telemetry / licensing**, over plain HTTP, with no response
check.

**GuildCAM stance:** none of this is reproduced. GuildCAM is fully offline, sends
no telemetry, requires no activation, and is GPLv3. This document studies OLGA's
*behaviour and domain*, not its source — keep that boundary clean.

---

## 7. Gap analysis vs current GuildCAM core

| Module | Current state | Action from this teardown |
|---|---|---|
| `io_import/dxf.py` | Solid (ezdxf, layer-keyed, arc/spline flattening at chord tol) | ✅ keep. Confirm layer names match what frame DXFs actually carry (OUTLINE/LENS/BRIDGE/HINGE/REF). |
| `relief/groove.py` | Single ring at `−depth` | ⬆ **Upgrade to ruled two-flank bevel** (§2.3); wire `vee`/`radius` profile; support draped Z (`button5` variant). |
| `relief/pocket.py` | exists | Reuse for hinge pockets. |
| `relief/hinge.py` | **missing** | ➕ **Add** with §3.1 vocabulary + `config/hinges/*.yaml` catalog. |
| `geometry/boxing.py` | exists | Implement true boxing system (A/B/DBL/ED), not OLGA's max−min. |
| `cam/profile.py`, `cam/tabs.py` | exist | Profile-with-tabs is the final cut; OLGA's temple tabs (§4) give real tab dimensions. |
| `cam/dropcutter.py` | drop-cutter via morphology | ✅ correct & strictly better than OLGA (which had no true 3D relief — it ruled between contours). |
| `post/grbl.py` | good | Add ramp/helical plunge; decide polyline-only vs arc (recommend polyline-only v1). |

---

## 8. Concrete next steps (slot into BUILDPLAN M0–M2)

1. **M0 spike:** implement `bevel_flank()` (§2.3) + the existing `grbl.py` to cut a
   single lens groove on scrap. Reuse OLGA defaults (Ø3 cutter, N=500, 3 mm flank,
   Z 6/4) as a known-good starting point, then dial in for your material.
2. **M1:** add `hinge.py` + hinge catalog YAML using §3.1 names; implement the
   boxing system properly in `boxing.py`.
3. **M2:** upgrade `groove.py` to the ruled two-flank form; add ramped plunge to the
   post; keep output polyline-only.
4. **Optional deep-dive:** the embedded **VBS post scripts** (`exportCharniereCB.vbs`,
   `exportCharniereBranches.vbs`, and OLGA V1's `GCODE` VBS) are string resources
   inside the DLLs and contain the *literal* CamBam cut recipe (op order, depths,
   feeds). Extract them if you want OLGA's exact hinge/temple machining sequence —
   say the word and they can be pulled from the `.resources` streams.

---

## Appendix A — French ↔ English glossary

| French | English |
|---|---|
| chanfrein | chamfer / bevel |
| charnière | hinge |
| branche | temple (arm) |
| polyligne | polyline |
| décalage | offset |
| calage | alignment / shimming |
| diamètre de la fraise | cutter (end-mill) diameter |
| précision | resolution (point count) |
| hauteur | height (Z) |
| face avant / arrière | front / back face |
| interne / externe | inner / outer |
| pente | slope / ramp |
| poche | pocket |
| encombrement | footprint / bulk envelope |
| profondeur | depth |
| inclinaison | inclination / tilt |
| rotation | rotation (yaw) |
| épaisseur labo (EpLabo) | lab (blank) thickness |

## Appendix B — Decompiled sources (local, for reference only — proprietary)

- `C:\Users\Chad\ClaudeProjects\decomp\olgaV5.decompiled.cs`
- `C:\Users\Chad\ClaudeProjects\decomp\siblings\{OLGA_V1,CHA,BR,courbes2,SVGStAlone,...}.cs`

Decompiled with ILSpy (`ilspycmd` 9.1) on the .NET 9 runtime. These are kept for
behavioural reference and are **not** to be incorporated into GuildCAM's GPLv3 source.
