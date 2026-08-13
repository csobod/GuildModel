"""M8 — arc endpoints must satisfy Carbide Motion's strict arc check.

Carbide Motion rejects an arc whose start radius (|I,J|) and end radius differ by
more than a tiny tolerance. The Kasa best-fit center is not equidistant from the two
endpoints, so the emitted I/J mismatched by ~0.01 mm on the long eyewire / perimeter
arcs. The fix snaps the center onto the chord's perpendicular bisector.
"""
import math

import numpy as np

from guildmodel.core.post.arcfit import _equidistant_center, _fit_circle, fit_arcs
from guildmodel.core.post.machine import lint_program, load_machine_profile


def test_equidistant_center_makes_radii_equal():
    start, end = (0.0, 0.0), (10.0, 0.0)
    # a deliberately off-center fit (equidistant would sit on x = 5)
    cx, cy, R = 5.3, 8.0, 9.5
    cx2, cy2 = _equidistant_center(start, end, cx, cy, R)
    sr = math.hypot(cx2 - start[0], cy2 - start[1])
    er = math.hypot(cx2 - end[0], cy2 - end[1])
    assert abs(sr - er) < 1e-9                 # exactly equidistant
    assert cy2 > 0                             # stayed on the fitted side


def test_equidistant_center_coincident_endpoints_is_safe():
    # a closed loop (start == end) is left to the fitted center, no crash
    assert _equidistant_center((1.0, 2.0), (1.0, 2.0), 3.0, 4.0, 5.0) == (3.0, 4.0)


def _noisy_arc():
    # a ~48 mm arc like the failing eyewire pass, with a few microns of radial noise
    # so the best-fit center is genuinely not equidistant from the endpoints
    rng = np.random.default_rng(7)
    R0, cx0, cy0 = 48.0, -28.9, -27.9
    out = []
    for t in np.linspace(0.30, 0.90, 60):
        r = R0 + rng.normal(0.0, 0.004)
        out.append((cx0 + r * math.cos(t), cy0 + r * math.sin(t), 6.8))
    return out


def test_unsnapped_kasa_center_is_not_equidistant():
    """Proves the test input is non-trivial — the raw fit is what broke Carbide."""
    P = np.asarray(_noisy_arc())
    cx, cy, R, _dev = _fit_circle(P[:, :2])
    s, e = P[0, :2], P[-1, :2]
    sr = math.hypot(cx - s[0], cy - s[1])
    er = math.hypot(cx - e[0], cy - e[1])
    assert abs(sr - er) > 2e-3                 # > Carbide's tolerance


def test_emitted_arcs_pass_carbide_endpoint_check():
    pts = _noisy_arc()
    moves = fit_arcs(pts, tol_mm=0.02)
    assert any(m[0] == "arc" for m in moves), "expected at least one fitted arc"
    cur = pts[0]
    worst = 0.0
    for m in moves:
        if m[0] == "arc":
            _, end, (cx, cy), _ccw = m
            # mimic the post: round start / end / I,J to 4 decimals
            i_off = round(cx - cur[0], 4)
            j_off = round(cy - cur[1], 4)
            crx = round(cur[0], 4) + i_off
            cry = round(cur[1], 4) + j_off
            start_r = math.hypot(i_off, j_off)
            end_r = math.hypot(round(end[0], 4) - crx, round(end[1], 4) - cry)
            worst = max(worst, abs(start_r - end_r))
            cur = end
        else:
            cur = m[1]
    # Carbide rejects > ~0.002 mm; the fix keeps it at 4-decimal rounding precision
    assert worst < 1e-3, f"endpoint radius mismatch {worst:.5f} mm too large"


def test_lint_flags_arc_endpoint_mismatch():
    """The inspector catches a bad arc before it reaches Carbide Motion."""
    prof = load_machine_profile("carbide_nomad3")
    bad = "G21\nG0 X0.0 Y0.0\nG2 X12.0 Y0.0 I5.0 J3.0 F500\n"   # ~1.78 mm mismatch
    warns = lint_program(bad, prof)
    assert any("endpoint" in w.lower() for w in warns)


def test_lint_passes_a_consistent_arc():
    prof = load_machine_profile("carbide_nomad3")
    good = "G21\nG0 X0.0 Y0.0\nG2 X10.0 Y0.0 I5.0 J3.0 F500\n"  # equidistant center
    warns = lint_program(good, prof)
    assert not any("endpoint" in w.lower() for w in warns)
