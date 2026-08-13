# GuildCAM Icon Style Guide — design brief for Claude Design

**Deliverable:** 11 monochrome SVG line icons for the GuildCAM toolbar and
viewport strip (M4.6, BUILDPLAN § M4.6 Part C). Two further icons are
**reused verbatim from GuildDraw** and must NOT be redrawn (§ 5).

GuildDraw's icon set (`GuildDraw/framedraft/resources/icons/*.svg`, 31
icons) is the established visual language. GuildCAM is its companion app;
a maker switching between the two should feel one product. Match the
language exactly — when in doubt, open the GuildDraw set and compare at
20 px.

---

## 1. Technical format (hard requirements)

Every icon is a standalone SVG exactly in this frame:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none"
     stroke="currentColor" stroke-width="1.6"
     stroke-linecap="round" stroke-linejoin="round">
  <!-- geometry -->
</svg>
```

- **viewBox `0 0 20 20`**, no width/height attributes.
- **`stroke="currentColor"` on the root** — the application recolors icons
  at runtime by string-replacing `currentColor` (light `#1f1f1f`, dark
  `#d4cfc0`, checked-state inversions). Never hardcode a color; never use
  more than one color.
- **`stroke-width="1.6"`**, round caps, round joins. Don't vary the weight
  within an icon.
- **`fill="none"`** on the root. A *small solid accent* (an endpoint dot,
  a filled node) may use `fill="currentColor" stroke="none"` on that
  element only — GuildDraw's `tool-spline.svg` does this for the on-curve
  node (`<circle fill="currentColor" stroke="none" r="1.25"/>`). Use
  sparingly: one accent per icon at most.
- **Safe area:** keep geometry inside `2.8 … 17.2` (≈ 1.5 px breathing room
  at render size); corner brackets may reach `3.2`. Optical centering beats
  mathematical centering.
- No transforms, groups with styles, masks, gradients, text elements, or
  embedded raster. Plain `<path>`, `<line>`, `<rect>`, `<circle>`,
  `<polyline>` only. Rounded rects use `rx≈0.6–1.6`.
- Rendered size is **20 × 20 px** (QToolBar). Check legibility at 100 % —
  if a detail disappears at 20 px, delete the detail.

States and themes are handled by the runtime (`gui/icons.py` renders
normal/checked variants per theme). **Draw one neutral drawing per icon;
do not produce state or dark variants.**

## 2. Drawing language

- Line icons, geometric, slightly rounded — drafting-instrument feel, not
  cartoon. GuildDraw references: `tool-select.svg` (arrow), `op-fit.svg`
  (corner brackets + rect), `view-sidebar.svg` (panel + chevron).
- One idea per icon. Silhouettes must be distinguishable from their toolbar
  neighbors at a glance (the list in § 4 is the final neighbor order).
- Frame-making motifs are encouraged where they help: the spectacles front
  (two rounded rects + bridge), the castle tower (the teaching metaphor for
  the posterior build — see BUILDPLAN § 2). Do not letterform (no "G",
  "3D", "STL" as text).
- Perspective: flat/orthographic by default; the 3D-flavored icons
  (`view-3d`, `view-iso`…) use a simple isometric cube vocabulary —
  hexagon outline + three inner edges meeting at the center.

## 3. Naming & delivery

- Files: `GuildCAM/src/guildcam/gui/resources/icons/<name>.svg`.
- Prefixes follow GuildDraw: `op-` one-shot actions, `view-` view/camera
  controls, `toggle-` checkable states. Names below are final — the code
  references them literally.

## 4. The icons (11 drawings)

Toolbar, in order:

| # | File | Action | Drawing brief |
|---|------|--------|---------------|
| 1 | `op-open-dxf.svg` | Open DXF… | Open-folder outline; a simple spectacles front (two small rounded rects joined by a bridge stroke) rising from / overlapping the folder mouth. Folder dominant, spectacles ≈ 40 %. |
| 2 | `op-build-3d.svg` | Build 3D Model | **The castle.** A single crenellated tower (rect with 2–3 merlons) on a wider base course. This is the brand motif for "build the posterior"; keep it sturdy and centered. |
| 3 | `op-gcode.svg` | Generate G-code | A boustrophedon toolpath: 3 horizontal raster strokes connected by short turns (an S-snake), with a small filled dot at the start point (the one allowed accent). Reads as "machine path", no letters. |
| 4 | `op-export-stl.svg` | Export STL… | A wireframe triangle-mesh patch (two adjacent triangles sharing an edge) with an arrow leaving the frame to the upper right. Arrow stroke same weight. |
| 5 | `view-2d.svg` | 2D Outline view (checkable) | Flat spectacles front, face-on: two rounded eyewire rects + bridge stroke. The companion of #6 — same spectacles, different projection. |
| 6 | `view-3d.svg` | 3D Preview view (checkable) | Isometric cube (hexagon + three inner edges). Optionally a hint of the part: skip the part, keep the cube clean — pairs with #5 by contrast. |
| 7 | `view-iso.svg` | Camera: isometric | The same isometric cube as #6 but with the top-front-right corner accented by a small filled dot — "you are looking from here". |
| 8 | `view-top.svg` | Camera: top | Cube with the **top face** drawn (others implied): a flat diamond/parallelogram with a short downward arrow above it, or top face double-stroked. Must contrast with #9 at 20 px. |
| 9 | `view-front.svg` | Camera: front | Square (the front face, face-on) with the two receding top edges hinted behind it. |
| 10 | `view-reset.svg` | Camera: reset | Circular arrow (¾ circle, arrowhead) around a small center dot. Classic reset, drawn in this set's weight. |
| 11 | `toggle-log.svg` | Show/hide log dock (checkable) | Companion of GuildDraw's `view-sidebar.svg` but horizontal: rounded rect with a line dividing off the **bottom** strip, chevron pointing down inside the strip. Match `view-sidebar.svg`'s rect (rx 1.6) so they read as siblings. |

Stage-stepper buttons (Towers / +Walls / +Footing / Full) stay **text** —
they are teaching labels (castle vocabulary, BUILDPLAN § 2). Do not draw
icons for them.

## 5. Reused from GuildDraw — do not redraw

Copy these files byte-for-byte from
`GuildDraw/framedraft/resources/icons/`; identical drawings build cross-app
muscle memory:

- `op-fit.svg` — Fit view (corner brackets + centered rect)
- `view-sidebar.svg` — show/hide the right params dock

## 6. Acceptance checklist (per icon)

- [ ] Root attrs exactly as § 1 (viewBox 20, currentColor, 1.6, round/round)
- [ ] Legible and unambiguous at 20 px on `#ffd580` (light) and `#1a1a1a`
      (dark) — test both by recoloring `currentColor` to `#1f1f1f` /
      `#d4cfc0`
- [ ] Silhouette distinct from its toolbar neighbors (§ 4 order)
- [ ] ≤ 1 filled accent; no hardcoded colors; no text; geometry inside the
      safe area
- [ ] Visually consistent next to `tool-select.svg` / `op-fit.svg` from
      GuildDraw at the same size
