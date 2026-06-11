# GuildCAM Integration Notes
# For companion DXF-drawing application — planning reference

Answers derived from GuildCAM source as of Session 5 (2026-06-04).

---

## 1. DXF intake — SPLINE support

GuildCAM accepts **any DXF version R12–R2018** via ezdxf. SPLINE entities are handled
natively: they are tessellated to polylines at 0.01 mm chord tolerance on import.
R12 polyline flattening is not the default — SPLINE is the preferred path.

**Output recommendation:** R2000+ with SPLINE entities. Do not pre-flatten to polylines
unless you have a specific reason to target R12.

---

## 2. Units

All GuildCAM internal coordinates are **millimeters**. The DXF importer reads raw numeric
coordinates and assumes they are already in mm — it does not read or enforce `$INSUNITS`.

**Output requirement:** Author all geometry in mm at 1:1 scale. Set `$INSUNITS = 4`
(millimeters) in the DXF header as a convention signal.

---

## 3. Closed contours

GuildCAM converts every imported curve to a Shapely `Polygon`. It auto-closes contours
whose start and end points are within **0.1 mm** of each other.

**Output requirement:** One **single closed entity** per outline (LWPOLYLINE or SPLINE,
start == end or within 0.1 mm gap). Do not split a lens or frame outline across multiple
open subpaths.

**Layer expectations (validator is strict):**

| Layer     | Expected count | Notes                                    |
|-----------|----------------|------------------------------------------|
| `OUTLINE` | 1              | Full frame front profile                 |
| `LENS`    | 2              | One per lens opening (OD + OS)           |
| `BRIDGE`  | optional       | Bridge/keel shape                        |
| `HINGE`   | optional       | Hinge pocket position markers            |
| `REF`     | optional       | Reference geometry (not machined)        |

Any layer name not in this set is logged as a warning and ignored.

---

## 4. Guild presets — bridge angle and apical radius

These are **forming (heat-bending) parameters, not machined in v1**. They are stored as
metadata in the project file (`FormingMetadata`) but have no effect on G-code output.

Current defaults for bridge geometry (the only machined bridge values):

| Parameter      | Default | Description                    |
|----------------|---------|--------------------------------|
| `bridge_depth` | 4.0 mm  | Keel depth                     |
| `bridge_width` | 5.0 mm  | Bridge width at narrowest      |

Bridge angle and apical radius presets do not exist in the current codebase.
Defer to v2 / M5 scope.

---

## 5. Calibration

**No calibration module exists in GuildCAM.** There is no PD entry, ruler placement,
or scale-factor mechanism. Scale is entirely implicit — DXF coordinates are used as-is
in mm.

**Output requirement:** Export coordinates in real-world mm at 1:1 scale. Do not build
a calibration step expecting GuildCAM to compensate for a scale factor.

---

## 6. Mirror semantics

Mirror is **effectively live**, not a one-shot operation.

- `BoxingParams.symmetric = True` (default) — every geometry rebuild re-derives the OS
  side by mirroring OD about the frame's vertical centre-line.
- `symmetric = False` — OD and OS are edited independently.
- The user edits one side only; the mirror is always current after any rebuild.

**Plan for live reflection as the default workflow.** A one-shot "mirror then unlock"
mode is not the current design.
