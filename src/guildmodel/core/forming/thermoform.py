"""The frame front after forming, as one smooth map (BUILDPLAN M18).

A front is cut flat and then formed: the **base curve** is moulded into each
rim on the press, the **face form** is the angle between the two eyewire
planes at the bridge centre line, and the **bridge** is projected at the
bench — a convex die pressed against the posterior while a V-shaped plate
braces the anterior, which leaves the classic crease along the plate's two
edges and the bulbous bump between them. The app models, previews and exports
the flat part because the flat part is what the machine cuts; this module is
what the part looks like afterwards, so a prototype can be printed and put on
a face. It never touches the CAM — see `test_forming_m18`, which pins that
`core.cam` cannot import it.

Lifted from `scripts/spike_thermoform.py` and then corrected twice; the
vocabulary is the maker's press (the SBT base-curve press drawing), the
top-down comparison sheet, and the bridge-forming sketch of 2026-09-25:

* **Base curve** is the lens base curve in diopters, in the quarter steps a
  frame is ordered in (0 to 16). The rim it is moulded into is a spherical
  cap apexed at the lens centre, because the lens block sits in the eyewire
  on the press. On a press row the die's own radius is used — the SBT dies
  are R259 / R181 / R144 for base 2 / 3 / 4 with lens curve 4, which are not
  530 / D — and off a row the optical convention 530 / D is the only radius
  there is. One sphere apexed at the bridge is the special case ``apex_x =
  0`` and is kept as the exactness test.
* **Face form** is the included angle between the two eyewire planes, formed
  at the bridge centre line irrespective of the base curve: 180 is flat, the
  press forms 174.69 / 169.24 / 163.97 / 170.11. The material bends over the
  bridge zone's width, so the bend is spread across that band.
* **Bridge projection** is the forward set of the bridge, in millimetres,
  formed between two creases. Seen from the front the creases are the two
  edges of the V plate: they start at the bridge's upper corners, a set
  distance apart, and converge toward the nose at the V's angle. Between
  them the die's convex face leaves a bump that is tallest along the V's
  centre line, which can sit off the frame's axis for a bridge that is not
  drawn centred.

In the flat model's coordinates (anterior face at z = 0, the castle rising to
+z toward the face, x across the frame, y up) the base curve and the face form
are curvatures along x, integrated into the tangent angle theta(x) of the
horizontal line through the lens centres::

    theta(x) = (x - apex_x * s(x)) / R      rim curvature, apexed at +-apex_x
             + (wrap / 2) * s(x)            wrap = 180 - face form, over the band

``s(x)`` runs smoothly -1 -> +1 across the band. The midline is ``M(x) = (int
cos theta, y_c, int sin theta)``, anchored at the bridge. The vertical
direction is the rim curvature alone: a bend of radius R about the local
horizontal tangent through the lens-centre height. Thickness rides the local
normal, so the castle keeps its depth everywhere.

The bridge bump is applied *before* that, as a displacement along z in the
flat frame — forward is away from the face, so toward -z — and then rides the
curved surface as an offset along the local normal like the thickness does.
It is the die's own shape: a cylinder of one radius, pressed into the V until
its edges crease, so across the gap it is a parabola that is zero at each
crease with a kink (the crease) and ``p`` on the centre line at the bridge's
top edge (the bump), and along the V it shrinks with the square of the V's
width as the creases converge — the same cylinder over a narrower opening
sags less. Outside the V it is zero. A displacement in z cannot fold
anything, whatever the gap or the angle: ``z - d(x, y)`` is monotone in
``z``. That matters because the first
version of this map bent the projection as a smooth S in ``theta(x)`` over
the bridge zone's own half-width, whose tightest radius at 4 mm of set was
5 mm, and a 10 mm castle offset along the normal at a 5 mm radius folded
through itself — "Model verified" and 7 % heavier than the flat part,
because a fold is neither a gap nor a self-touching edge. The bend radius
that remains is the rim's (R >= 33 mm at 16 diopters) and the wrap's (23 mm
at 150 degrees over a 9 mm band), both well over any castle;
`min_bend_radius_mm` reports it so a test can hold the condition.

What the model assumes, so the maker can disagree with any of it: the press
is the authority on R where it has one; the wrap band is the bridge zone; the
creases start at the bridge's top edge and converge toward the nose;
thickness is preserved and volume is not (the posterior sits on the concave
side and is compressed a few percent, and for a preview and a printed
stand-in this is the right trade, stated so nobody measures a formed volume
and calls it a defect); pantoscopic tilt is the angle between front and
temples, not a deformation of the front, so it is not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "DEFAULT_BAND_HALF_MM",
    "DEFAULT_CREASE_ANGLE_DEG",
    "DEFAULT_CREASE_GAP_MM",
    "EXPORT_FINE_MM",
    "EXPORT_REFINE_MM",
    "PREVIEW_FINE_MM",
    "PREVIEW_REFINE_MM",
    "SIMPLIFY_TOL_MM",
    "BridgeGeometry",
    "ThermoformMap",
    "bridge_band",
    "bridge_geometry",
    "diopters",
    "form_trimesh",
    "formed_model",
    "manifold_from_trimesh",
    "radius_for",
    "refine",
    "rim_apex",
    "warp",
]

#: Refinement edge length for the formed **export** outside the bridge, mm.
#: Measured in BUILDPLAN §0.4: worst chord 0.004-0.008 mm outside the bends on
#: the three fixtures at the four press rows, for 52-70 thousand triangles and
#: a 2.6-3.5 MB STL.
EXPORT_REFINE_MM = 1.5

#: Edge length inside the bridge band for the export, mm. The die is a 2-10 mm
#: radius against the rim's 144, so the band is subdivided a further two to
#: three halvings (`core.forming.tessellate`): a facet on an 8 mm die turns
#: under 2 degrees at this length.
EXPORT_FINE_MM = 0.25

#: The tolerance the flat model is simplified to before it is refined, mm.
#: A castle straight from the booleans carries three vertices for every one
#: its shape needs, and the long slivers between them are what streaked the
#: formed preview: a triangle thinner than the chord sag of its own length
#: (0.008 mm at 3 mm on R144) comes out of the warp with a normal pointing
#: along the surface instead of out of it. Simplifying at a millionth of a
#: millimetre changes no dimension (the gabriel's volume agrees to 1e-3
#: mm^3) and removes 84 % of the pairs the warp had turned sharp.
SIMPLIFY_TOL_MM = 1e-6

#: Refinement edge length for the live **preview**, mm. Half the triangles of
#: the export setting; 0.029 mm chord at a deliberately harsh 88 mm radius,
#: which is invisible on screen. A 3 mm chord on a 144 mm radius turns 1.2
#: degrees, nowhere near the 20 degree crease threshold, so the edge detector
#: survives the warp unchanged and all four display modes work on the formed
#: front for free.
PREVIEW_REFINE_MM = 3.0

#: Edge length inside the bridge band for the preview, mm: 3.6 degrees per
#: facet on an 8 mm die, which smooth shading hides.
PREVIEW_FINE_MM = 0.5

#: Half-width of the wrap band when the drawing gives no bridge zone, mm. The
#: three fixtures' bridge zones are 11.2 / 12.5 / 9.2 mm half-wide; this is the
#: narrowest of them, so a frame that cannot say lands on a plausible bend.
DEFAULT_BAND_HALF_MM = 9.0

#: Distance between the two creases at the bridge's top edge when the drawing
#: gives none, mm. The fixtures' bridges are 20.3 / 19.5 / 13.1 mm wide there.
DEFAULT_CREASE_GAP_MM = 20.0

#: The V plate's included angle when none is given, degrees: how fast the two
#: creases converge toward the nose. 0 is parallel creases. Read off the
#: maker's sketch, whose two examples sit at about 42 and 56.
DEFAULT_CREASE_ANGLE_DEG = 45.0

#: The optical convention's constant: base curve in diopters is this over the
#: radius in millimetres (the 1.53 index tool-maker's sphere).
# The optical convention lives with the schema (`core.project.schema`), which
# the CAM imports: were it here, a schema method that needs it would have to
# import this package, and the CAM could reach the forming code through it.
from ..project.schema import DIOPTER_MM as _DIOPTER_MM, radius_for  # noqa: E402


def diopters(radius_mm: float) -> float:
    """The base-curve readout for a radius, 0 for flat."""
    return _DIOPTER_MM / radius_mm if radius_mm and radius_mm > 0 else 0.0


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ------------------------------------------------------------ from the drawing

@dataclass(frozen=True)
class BridgeGeometry:
    """Where the drawing puts the bends: what the map needs from a front.

    * ``apex_x`` / ``apex_y`` — where the rims are apexed: mean |x| and mean y
      of the two lens centroids.
    * ``band_half`` — half-width of the wrap band, the bridge zone's x extent.
    * ``top_y`` — the bridge's edge away from the nose, where the creases
      start; ``centre_y`` its centroid height, where the readout measures.
    * ``top_width`` — the bridge's width at that edge: the default gap.
    * ``nose_dir`` — +1 or -1: which way along y the nose lies, so the V
      converges toward it whichever way the intake oriented the frame.
    """
    apex_x: float = 30.0
    apex_y: float = 0.0
    band_half: float = DEFAULT_BAND_HALF_MM
    top_y: float = 12.0
    centre_y: float = 7.0
    top_width: float = DEFAULT_CREASE_GAP_MM
    nose_dir: float = -1.0


def rim_apex(lens_od, lens_os) -> tuple[float, float]:
    """Where the rims are apexed: mean |x| and mean y of the two lens centroids.

    Symmetric by construction — the map apexes at +-apex_x — so a slightly
    asymmetric drawing gets the mean rather than one eye's centre.
    """
    cs = [c.centroid for c in (lens_od, lens_os) if c is not None]
    if not cs:
        return 0.0, 0.0
    return (float(np.mean([abs(c.x) for c in cs])),
            float(np.mean([c.y for c in cs])))


def bridge_band(partition, lens_od=None, lens_os=None) -> float:
    """Half-width of the wrap band, mm: the bridge zone's x extent.

    The bridge zone is the material between the eyewires, and the posterior
    bridge relief is cut in the same band, which is not a coincidence. A
    drawing whose partition has no zone by that name (a non-standard layout)
    falls back to half the gap between the lens apertures, and a drawing that
    cannot say either gets `DEFAULT_BAND_HALF_MM`.
    """
    try:
        x0, _, x1, _ = partition.zone("bridge").polygon.bounds
        if x1 > x0:
            return 0.5 * float(x1 - x0)
    except (KeyError, AttributeError):
        pass
    if lens_od is not None and lens_os is not None:
        inner = sorted([lens_od.bounds[0], lens_od.bounds[2],
                        lens_os.bounds[0], lens_os.bounds[2]])[1:3]
        gap = float(inner[1] - inner[0])
        if gap > 0:
            return 0.5 * gap
    return DEFAULT_BAND_HALF_MM


def bridge_geometry(partition, lens_od=None, lens_os=None) -> BridgeGeometry:
    """Everything the map takes from a front, in one read of the partition.

    The nose is found from the nosepad zones' centroid against the bridge's:
    the intake mirrors a drawing into posterior coordinates, so "down" is
    not a fixed sign of y and is measured rather than assumed. Without a
    bridge zone the wrap band falls back as `bridge_band` does and the
    creases start a band's width above the lens centres.
    """
    from shapely.geometry import box

    apex_x, apex_y = rim_apex(lens_od, lens_os)
    band = bridge_band(partition, lens_od, lens_os)
    try:
        bridge = partition.zone("bridge").polygon
    except (KeyError, AttributeError):
        return BridgeGeometry(apex_x, apex_y, band, apex_y + band, apex_y,
                              2.0 * band, -1.0)
    x0, y0, x1, y1 = bridge.bounds
    centre_y = float(bridge.centroid.y)
    pads = [z.polygon.centroid.y for z in getattr(partition, "zones", [])
            if z.name.startswith("nosepad")]
    nose_dir = -1.0
    if pads and abs(float(np.mean(pads)) - centre_y) > 1e-6:
        nose_dir = 1.0 if float(np.mean(pads)) > centre_y else -1.0
    top_y = float(y0 if nose_dir > 0 else y1)
    strip = bridge.intersection(box(x0 - 1.0, top_y - 1.0, x1 + 1.0, top_y + 1.0))
    if strip.is_empty:
        top_width = float(x1 - x0)
    else:
        sx0, _, sx1, _ = strip.bounds
        top_width = float(sx1 - sx0)
    return BridgeGeometry(apex_x, apex_y, band, top_y, centre_y,
                          max(top_width, 1.0), nose_dir)


# ------------------------------------------------------------ the die's section

def _die_profile(u, h, R: float, p: float, blend: float = 0.0):
    """The bump's section across the gap, mm, for ``u >= 0`` off the centre
    line at a height where the crease is ``h`` from it; vectorised over both.

    The die is a cylinder of radius ``R`` pressed ``p`` into the sheet while
    the V plate holds the sheet flat outside ``+-h``. Between them the sheet
    is the die's arc where it touches the die, a straight flank tangent to
    the arc down to the crease where it does not, and flat outside. The apex
    at this height is the projection unless the die is wider than the gap
    here — then it rests on the plate's two edges and the arc passes through
    the creases — or the projection is deeper than the die's radius, which a
    height field cannot hold (the flanks would overhang), so it is capped.
    Both keep the profile continuous along the V, where ``h`` shrinks to
    zero and the bump with it.

    With a ``blend`` the fold at each crease is a concave fillet of that
    radius, tangent to the flat and to the flank (or, when it would eat the
    whole flank, to the arc), which spreads the bump a little past the
    crease and takes the kink out of it.
    """
    u = np.asarray(u, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    if R <= 0.0 or p <= 0.0:
        return np.zeros(np.broadcast(u, h).shape, dtype=np.float64)
    tiny = 1e-12
    p_eff = min(p, R)
    a = np.minimum(p_eff, R - np.sqrt(np.clip(R * R - h * h, 0.0, None)))
    c = a - R                                              # the die's centre height, <= 0
    D2 = h * h + c * c
    L = np.sqrt(np.clip(D2 - R * R, 0.0, None))            # crease -> tangent point
    Tu = R * (h * R + c * L) / np.maximum(D2, tiny)
    Td = c + R * (h * L - c * R) / np.maximum(D2, tiny)
    arc = c + np.sqrt(np.clip(R * R - u * u, 0.0, None))
    run = np.maximum(h - Tu, tiny)
    flank = Td * (h - u) / run
    if blend <= 0.0:
        d = np.where(u <= Tu, arc, np.where(u <= h, flank, 0.0))
        return np.where(h > 0.0, np.clip(d, 0.0, None), 0.0)

    rf = float(blend)
    # the slope just inside the crease: the flank's, or the arc's where the
    # flank has no length
    tan_phi = np.where(h - Tu > 1e-9, Td / run, h / np.maximum(-c, tiny))
    phi = np.arctan(tan_phi)
    s_len = rf * np.tan(0.5 * phi)                         # kink -> tangent point
    flank_len = np.sqrt((h - Tu) ** 2 + Td ** 2)
    on_flank = s_len <= flank_len
    # fillet against the flank: centre (h + s, rf); against the arc: the
    # circle of radius rf tangent to the flat and to the die's circle
    uc_flank = h + s_len
    uc_arc = np.sqrt(np.clip(a * (R + 2.0 * rf - c), 0.0, None))
    uc = np.where(on_flank, uc_flank, uc_arc)
    fillet = rf - np.sqrt(np.clip(rf * rf - (u - uc) ** 2, 0.0, None))
    # where the arc stops: at the flank's tangent point, or at the fillet's
    # own tangent point on the die when the fillet has eaten the flank
    arc_end = np.where(on_flank, Tu, R * uc / (R + rf))
    flank_end = uc - rf * np.sin(phi)                      # meaningful on a flank only
    d = np.where(u <= arc_end, arc,
                 np.where(on_flank & (u <= flank_end), flank,
                          np.where(u <= uc, fillet, 0.0)))
    return np.where(h > 0.0, np.clip(d, 0.0, None), 0.0)


# --------------------------------------------------------------------- the map

class ThermoformMap:
    """Flat posterior coordinates ``(N, 3)`` -> formed coordinates ``(N, 3)``.

    A pure function of its parameters; the tangent-angle integral is tabulated
    once on construction (0.05 mm over +-150 mm, which covers any front) and
    every call is three interpolations, a rotation and the bump.
    """

    def __init__(self, *, radius_mm: float = 0.0, face_form_deg: float = 180.0,
                 projection_mm: float = 0.0,
                 crease_gap_mm: float = DEFAULT_CREASE_GAP_MM,
                 crease_angle_deg: float = DEFAULT_CREASE_ANGLE_DEG,
                 bridge_offset_mm: float = 0.0,
                 die_radius_mm: float = 0.0,
                 crease_blend_mm: float = 0.0,
                 bridge: BridgeGeometry | None = None,
                 x_range=(-150.0, 150.0), grid_mm: float = 0.05) -> None:
        self.bridge = bridge if bridge is not None else BridgeGeometry()
        # 0 (or anything non-positive) means flat, which the arithmetic below
        # reads as an infinite radius.
        self.R = float(radius_mm) if radius_mm and radius_mm > 0 else float("inf")
        self.face_form_deg = float(face_form_deg)
        self.wrap = np.radians(180.0 - self.face_form_deg)
        # The die only presses forward: a negative projection is read as
        # none rather than as a bump the other way.
        self.p = max(float(projection_mm), 0.0)
        self.gap = max(float(crease_gap_mm), 1e-3)
        self.crease_angle_deg = float(crease_angle_deg)
        self._half_tan = float(np.tan(np.radians(0.5 * self.crease_angle_deg)))
        self.offset = float(bridge_offset_mm)
        # 0 is "auto": the largest die that still reaches the projection
        # through this gap, which is the arc through both creases.
        self.die = float(die_radius_mm) if die_radius_mm and die_radius_mm > 0 else 0.0
        self.blend = max(float(crease_blend_mm or 0.0), 0.0)
        self.apex_x, self.apex_y = float(self.bridge.apex_x), float(self.bridge.apex_y)
        self.b = max(float(self.bridge.band_half), 1e-3)
        self._grid = float(grid_mm)
        self._xs = np.arange(x_range[0], x_range[1] + grid_mm, grid_mm)
        self._tabulate()

    def _tabulate(self) -> None:
        xs, grid_mm = self._xs, self._grid
        s = 2.0 * _smoothstep((xs + self.b) / (2.0 * self.b)) - 1.0
        theta = np.zeros_like(xs)
        if np.isfinite(self.R):
            theta += (xs - self.apex_x * s) / self.R
        theta += 0.5 * self.wrap * s
        i0 = int(np.argmin(np.abs(xs)))
        cx, sx = np.cos(theta), np.sin(theta)
        X = np.concatenate(([0.0], np.cumsum(0.5 * (cx[1:] + cx[:-1]) * grid_mm)))
        Z = np.concatenate(([0.0], np.cumsum(0.5 * (sx[1:] + sx[:-1]) * grid_mm)))
        self._theta = theta
        self._X, self._Z = X - X[i0], Z - Z[i0]

    @property
    def is_flat(self) -> bool:
        """True when the map is the identity: no curve, no wrap, no projection."""
        return not np.isfinite(self.R) and self.wrap == 0.0 and self.p == 0.0

    def bend_radii_mm(self) -> tuple[float, float]:
        """The two radii that bound what the map can carry, ``(thickness,
        projection)``, by the sign of the midline's curvature.

        Where the midline turns the way the rims do (``theta' > 0``) the
        centre of curvature is behind the part; the castle's depth runs into
        it, and the map folds when the part is thicker than that radius (or
        than ``R``, the y direction's). Between two rims apexed at their own
        lens centres the midline turns the other way (``theta' < 0``): the
        centre is in front, thickness cannot fold there — but the bridge
        bump is an offset *toward* that centre, so a projection larger than
        that radius folds the bridge. The first version took |theta'| for
        both and read a safe 16 D aviator as folding while an 8 mm
        projection on the same frame folded 1,159 triangles unreported.
        """
        d = np.gradient(self._theta, self._grid)
        k_thick = float(max(d.max(), 0.0))
        k_proj = float(max((-d).max(), 0.0))
        along = 1.0 / k_thick if k_thick > 0 else float("inf")
        thickness = float(min(along, self.R))
        projection = 1.0 / k_proj if k_proj > 0 else float("inf")
        return thickness, projection

    def min_bend_radius_mm(self) -> float:
        """The radius the part's thickness has to stay under (see
        `bend_radii_mm`)."""
        return self.bend_radii_mm()[0]

    def fold_warning(self, thickness_mm: float) -> str | None:
        """Why this map folds a part this thick, or None when it does not."""
        thickness, projection = self.bend_radii_mm()
        if thickness_mm > thickness:
            return (f"bends tighter (R {thickness:.1f} mm) than the part is thick "
                    f"({thickness_mm:.1f} mm)")
        if self.p > 0.0 and abs(self.apex_mm()) > projection:
            return (f"the bridge set ({abs(self.apex_mm()):.1f} mm) is more than the "
                    f"reverse bend between the rims can carry (R {projection:.1f} mm)")
        return None

    def crease_half_width(self, y):
        """Half the distance between the creases at height ``y``: the gap's
        half at the bridge's top edge, narrowing toward the nose at the V's
        angle and zero past the V's apex. Above the top edge the creases run
        on parallel, so an aviator's brow bar or an eyewire's upper rim that
        sits over the bridge corners is carried forward with the bridge
        rather than stepped — the first version cut the bump off a
        millimetre above the edge, and on the aviator that step ran straight
        through the bar."""
        y = np.asarray(y, dtype=np.float64)
        t = (y - self.bridge.top_y) * self.bridge.nose_dir       # depth toward the nose
        h = 0.5 * self.gap - np.clip(t, 0.0, None) * self._half_tan
        return np.clip(h, 0.0, None)

    def bump(self, x, y):
        """Forward displacement of the bridge bump at ``(x, y)``, mm.

        Across the gap it is the die's own section: a circular arc of the
        die's radius on the centre line, a straight flank tangent to it
        running down to each crease where the die does not reach the plate,
        and a crease blend of ``crease_blend_mm`` where the maker asks for
        one. Along the V it is the same die at every height, resting on the
        plate's two edges wherever the gap is narrower than the die's
        footprint (`_die_profile`). Zero outside the creases (outside the
        blend, with one), and never negative: the die only presses forward.
        """
        x = np.asarray(x, dtype=np.float64)
        if self.p == 0.0:
            return np.zeros_like(x)
        h = self.crease_half_width(y)
        u = np.abs(x - self.offset)
        return _die_profile(u, h, self.die_radius_mm(), self.p, self.blend)

    @staticmethod
    def auto_die_radius(gap_mm: float, projection_mm: float) -> float:
        """The die a bump implies when none is named: the largest radius that
        still sets the bridge the full projection through the gap, which is
        the arc through both creases, ``(h^2 + p^2) / 2p``. Through a gap
        narrower than the projection no die reaches it (the flanks would
        overhang), and the die is the gap's half-width — it sets the bridge
        as far as that gap allows, with the flanks vertical at the crease.
        ``inf`` with no projection."""
        h, p = 0.5 * abs(float(gap_mm)), abs(float(projection_mm))
        if p == 0.0:
            return float("inf")
        return (h * h + p * p) / (2.0 * p) if h >= p else h

    def die_radius_mm(self) -> float:
        """The radius of the die's convex face in use: the named one, else
        `auto_die_radius` for this gap and projection."""
        if self.die > 0.0:
            return self.die
        return self.auto_die_radius(self.gap, self.p)

    def apex_mm(self) -> float:
        """How far the die actually sets the bridge on the centre line at the
        top edge, mm: the projection, unless the die is too wide for the gap
        (it rests on the plate's edges first) or the projection is deeper
        than the die's own radius (the sheet cannot wrap past its equator)."""
        if self.p == 0.0:
            return 0.0
        return float(_die_profile(
            np.zeros(1), np.full(1, 0.5 * self.gap), self.die_radius_mm(),
            self.p, self.blend)[0])

    @property
    def is_creased(self) -> bool:
        """True when the bump has a real fold at each crease: a projection
        and no blend. The tessellation cuts the flat mesh along the creases
        so the fold is a mesh edge, and splits the normals there."""
        return self.p != 0.0 and self.blend == 0.0

    def crease_planes(self):
        """The vertical planes the creases lie in, as ``(normal, offset,
        kind)`` with the plane ``{q : normal . q = offset}``: for each side
        the parallel run above the top edge, the converging run below it
        (omitted at a 0 degree V, where the two coincide), and the top edge
        itself, where the apex profile kinks from parallel to converging.
        Each plane runs on through the whole part, which is harmless: past
        the crease's own segment it lies where the bump is zero.
        """
        if self.p == 0.0:
            return []
        ht, k, nd, ty, ox = (0.5 * self.gap, self._half_tan, self.bridge.nose_dir,
                             float(self.bridge.top_y), self.offset)
        planes = []
        for side in (1.0, -1.0):
            planes.append((np.array([1.0, 0.0, 0.0]), ox + side * ht,
                           ("parallel", side)))
            if k > 0.0:
                n = np.array([side, nd * k, 0.0])
                norm = float(np.linalg.norm(n))
                planes.append((n / norm, (side * ox + ht + ty * nd * k) / norm,
                               ("converge", side)))
        planes.append((np.array([0.0, 1.0, 0.0]), ty, ("top", 0.0)))
        return planes

    def crease_is_live(self, xy, kind, eps: float = 1e-6):
        """For points ``xy`` on the plane of ``kind``: True where the crease
        actually runs — the parallel plane above the top edge (or at any
        height when the V is 0 degrees), the converging plane below it and
        before the V's apex. The top-edge plane is a kink in the apex, not
        a fold, so it is never live."""
        xy = np.asarray(xy, dtype=np.float64)
        y = xy[:, 1]
        h = self.crease_half_width(y)
        what, _ = kind
        if what == "parallel":
            return h >= 0.5 * self.gap - eps
        if what == "converge":
            t = (y - self.bridge.top_y) * self.bridge.nose_dir
            return (t >= -eps) & (h > eps)
        return np.zeros(len(xy), dtype=bool)

    def bump_margin_mm(self) -> float:
        """How far past the creases the bump can reach, mm, plus a millimetre:
        a blend spreads outward by up to its radius on a flank and, against
        the arc, by ``r p / h`` — under twice its radius wherever the gap is
        at least half the projection. A bound rather than the current value
        so a projection or die drag does not re-cut the mesh."""
        return 2.0 * self.blend + 1.0

    def in_band(self, x, y, margin_mm: float = 0.0):
        """True where the bump lives, widened by ``margin_mm`` each way and
        past the V's apex by the same, in flat coordinates: the region the
        tessellation refines finely."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if self.p == 0.0:
            return np.zeros(np.broadcast(x, y).shape, dtype=bool)
        t = (y - self.bridge.top_y) * self.bridge.nose_dir
        h = 0.5 * self.gap - np.clip(t, 0.0, None) * self._half_tan   # unclipped
        return (np.abs(x - self.offset) <= h + margin_mm) & (h + margin_mm > 0.0)

    def layout_key(self):
        """What the tessellation depends on: the crease layout, whether the
        creases are folds, and how far the bump can spread. The base curve,
        the face form, the projection and the die are *not* in it, so a
        drag of any of those reuses the prepared mesh."""
        return (round(self.gap, 6), round(self.crease_angle_deg, 6),
                round(self.offset, 6), round(float(self.bridge.top_y), 6),
                float(self.bridge.nose_dir), self.p != 0.0, self.is_creased,
                round(self.bump_margin_mm(), 3))

    def __call__(self, pts):
        pts = np.asarray(pts, dtype=np.float64)
        if self.is_flat:
            # Literally the flat part, not the flat part to 3e-11 mm: the
            # tabulated integral carries that much rounding at x = 0.
            return pts.copy()
        x, y = pts[:, 0], pts[:, 1] - self.apex_y
        # forward is away from the face, and the face is at +z
        z = pts[:, 2] - self.bump(pts[:, 0], pts[:, 1])
        th = np.interp(x, self._xs, self._theta)
        M = np.stack([np.interp(x, self._xs, self._X),
                      np.full_like(x, self.apex_y),
                      np.interp(x, self._xs, self._Z)], axis=1)
        n = np.stack([-np.sin(th), np.zeros_like(th), np.cos(th)], axis=1)
        yhat = np.array([0.0, 1.0, 0.0])
        if np.isfinite(self.R):
            phi = y / self.R
            arc = ((self.R * np.sin(phi))[:, None] * yhat
                   + (self.R * (1 - np.cos(phi)))[:, None] * n)
            n2 = np.cos(phi)[:, None] * n - np.sin(phi)[:, None] * yhat
        else:
            arc, n2 = y[:, None] * yhat, n
        return M + arc + z[:, None] * n2

    def bridge_set_mm(self) -> float:
        """z of the bridge's centre line relative to the rims at the same
        height; negative means the bridge sits forward of them (away from
        the face).

        Measured at the bridge's top edge, where the bump is its full height,
        against the rims at the same height so the rim's own sag in y
        cancels. With the rims apexed at the lens centres their sag puts the
        bridge *behind* the apexes and the face form pulls it forward again;
        at the press's pairings the two nearly cancel, which is what makes
        the front read as one continuous bow rather than a W. The bump then
        adds its set on top.
        """
        ty = float(self.bridge.top_y)
        apex = self(np.array([[self.apex_x, ty, 0.0]]))[0, 2]
        return float(self(np.array([[self.offset, ty, 0.0]]))[0, 2] - apex)

    @classmethod
    def from_metadata(cls, forming, *,
                      bridge: BridgeGeometry | None = None) -> "ThermoformMap":
        """The map a component's `FormingMetadata` describes.

        `base_radius_mm` is the radius in use — a press row's die or the
        optical convention's, as `FormingMetadata.with_base_curve` decided —
        and a gap of 0 means the drawing's own bridge width.
        """
        bridge = bridge if bridge is not None else BridgeGeometry()
        gap = float(forming.crease_gap_mm) or float(bridge.top_width)
        return cls(radius_mm=float(forming.base_radius_mm),
                   face_form_deg=180.0 - float(forming.face_form_wrap_deg),
                   projection_mm=float(forming.bridge_projection_mm),
                   crease_gap_mm=gap,
                   crease_angle_deg=float(forming.crease_angle_deg),
                   bridge_offset_mm=float(forming.bridge_offset_mm),
                   die_radius_mm=float(getattr(forming, "die_radius_mm", 0.0)),
                   crease_blend_mm=float(getattr(forming, "crease_blend_mm", 0.0)),
                   bridge=bridge)


# ---------------------------------------------------------------- the meshes

def refine(model, length_mm: float):
    """The flat model, simplified to `SIMPLIFY_TOL_MM` and then refined so no
    edge is longer than `length_mm`.

    The simplification is the cure for the streaks (see `tessellate`): the
    booleans leave slivers thinner than the chord sag of their own length,
    and a sliver like that comes out of the warp pointing along the surface.
    Cached by the caller for a live preview: it depends on the model and the
    length only.
    """
    return model.simplify(SIMPLIFY_TOL_MM).refine_to_length(float(length_mm))


def warp(model, fmap: ThermoformMap):
    """`model` through the map. Every vertex moves; nothing is rebuilt and
    nothing is re-booleaned, so a closed input stays closed."""
    from guildmodel.core.model.kernel import ManifoldError

    out = model.warp_batch(fmap)
    status = out.status()
    if getattr(status, "name", str(status)) not in ("NoError", "0"):
        raise ManifoldError(f"warp: {status}")
    return out


def formed_model(model, fmap: ThermoformMap, length_mm: float = EXPORT_REFINE_MM):
    """Refine, then warp: the formed part from the mesh kernel's own model."""
    return warp(refine(model, length_mm), fmap)


def manifold_from_trimesh(mesh):
    """A Manifold from a closed trimesh, at full precision.

    The app's caches hold the kernel's output as a `trimesh.Trimesh` (see
    `core.model.kernel.to_trimesh`); rebuilding the Manifold from that is
    ~10 ms on a frame front and volume-exact, so the live preview forms the
    cached mesh rather than keeping a second object alive per component.
    Raises `ManifoldError` when the input is not a closed manifold — a raster
    heightfield can be, a B-Rep tessellation usually is not.
    """
    import manifold3d

    from guildmodel.core.model.kernel import ManifoldError

    verts = np.array(mesh.vertices, dtype=np.float64, order="C")
    faces = np.array(mesh.faces, dtype=np.uint64, order="C")
    if len(faces) == 0:
        raise ManifoldError("cannot form an empty mesh")
    man = manifold3d.Manifold(
        manifold3d.Mesh64(vert_properties=verts, tri_verts=faces))
    status = man.status()
    if getattr(status, "name", str(status)) not in ("NoError", "0"):
        raise ManifoldError(f"not a closed manifold: {status}")
    return man


def form_trimesh(mesh, fmap: ThermoformMap, length_mm: float = PREVIEW_REFINE_MM,
                 fine_mm: float = PREVIEW_FINE_MM):
    """The formed part from any kernel's trimesh, in one call.

    `tessellate.FormingMesh` with nothing kept: the base goes through
    Manifold when the mesh is closed (simplified, coarsely refined), else it
    is subdivided in place — a mesh Manifold rejects, a B-Rep tessellation
    usually, stays positionally continuous but carries T-junctions and will
    not verify as watertight (11,094 such edges on the gabriel), which is a
    *preview*, not an export path. Then the creases are cut in, the band is
    refined to `fine_mm` and the part is warped. A window that forms the
    same flat part again and again keeps a `FormingMesh` instead.
    """
    from .tessellate import FormingMesh

    return FormingMesh(mesh, coarse_mm=length_mm, fine_mm=fine_mm).formed(fmap)
