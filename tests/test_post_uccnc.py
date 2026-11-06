"""The UCCNC post (2.3.1): STEPCRAFT machines with the tool changer.

Modeled on Autodesk's certified "STEPCRAFT UCCNC" post with its tool changer
on, which the makers who run these machines post from today. The motion is
the GRBL post's word for word; these tests hold the words around it — the
comments, the top-of-travel retracts, ``T M6`` then ``G43 H``, the dwell in
milliseconds, arcs of at most 90 degrees — and that the readers of a posted
program (the simulations, the Z profile, the lint) read a UCCNC one.
"""
import math
import re
from pathlib import Path

import pytest

from guildmodel.core.cam.castle_ops import CamOp, build_tool_settings, write_castle_program
from guildmodel.core.cam.zprofile import annotate
from guildmodel.core.post import GRBLPost, make_post
from guildmodel.core.post.grbl import ToolSetting
from guildmodel.core.post.machine import (
    available_machines, lint_program, load_machine_profile,
)
from guildmodel.core.post.uccnc import UCCNCPost, comment_lines, program_label
from guildmodel.core.stock import parse_program

CONFIG = Path(__file__).parents[1] / "src" / "guildmodel" / "config"
STEPCRAFT = load_machine_profile("stepcraft_uccnc", CONFIG)


def _circle(cx, cy, r, z, n=60):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n), z)
            for k in range(n + 1)]


def _ops(tools=None):
    tools = tools or {"flat_2mm": {"name": "flat_2mm"}, "flat_3175": {"name": "flat_3175"}}
    return [CamOp("Frame Front · Component Pockets", tool=tools["flat_2mm"],
                  paths=[[(0.0, 0.0, -0.5), (5.0, 0.0, -0.5), (5.0, 5.0, -0.5)]]),
            CamOp("Frame Front · Eyewires", tool=tools["flat_3175"],
                  paths=[_circle(10.0, 10.0, 5.0, -1.0)])]


def _settings(**numbered):
    return {"flat_2mm": ToolSetting(3, "flat_2mm", 2.0, 500, 200, 15000,
                                    numbered=numbered.get("flat_2mm", True)),
            "flat_3175": ToolSetting(1, "flat_3175", 3.175, 700, 250, 12000,
                                     numbered=numbered.get("flat_3175", True))}


def _post(machine=STEPCRAFT, **kw):
    kw = {"job_name": "demo", "material": "acetate", "tool_diameter_mm": 2.0,
          "spindle_rpm": 15000, "feed_rate_mmpm": 500.0, "plunge_rate_mmpm": 200.0,
          "safe_z_mm": 5.0, "feed_plane_mm": 1.0, "work_offset": (85.0, 35.0, 0.0),
          "spindle_spinup_s": machine.spindle_spinup_s, **kw}
    return make_post(machine, **kw)


def _program(post, *, arc_tol=0.01, mode="m6", settings=None):
    write_castle_program(_ops(), post, tool_settings=settings or _settings(),
                         tool_change_mode=mode, contour_op_names={"Frame Front · Eyewires"},
                         arc_tol_mm=arc_tol)
    return post.to_string()


# ------------------------------------------------------------------ the profile

def test_the_stepcraft_profile_ships_and_picks_the_uccnc_post():
    assert ("stepcraft_uccnc", "STEPCRAFT (UCCNC, tool changer)") in available_machines(CONFIG)
    assert STEPCRAFT.controller == "uccnc" and STEPCRAFT.tool_change_mode == "m6"
    assert isinstance(_post(), UCCNCPost)
    grbl = load_machine_profile("guild_cnc", CONFIG)
    post = _post(grbl)
    assert type(post) is GRBLPost and not post.names_every_tool


# ------------------------------------------------------------------ the words

def test_a_tool_changer_program_reads_as_the_certified_post_writes_it():
    text = _program(_post())
    lines = text.splitlines()
    assert ";" not in text
    text.encode("ascii")
    assert all(l.startswith("(") and l.endswith(")") for l in lines[:8])
    # modal, then the top of travel before the first tool
    assert lines[lines.index("G90"):lines.index("G90") + 6] == [
        "G90", "G21", "G17", "G64", "G54", "G90 G53 G0 Z0"]
    # each tool: the top of travel, T M6, its length offset, the modal block,
    # the spindle and its dwell in milliseconds
    for n, rpm in ((3, 15000), (1, 12000)):
        i = lines.index(f"T{n} M6")
        before = [l for l in lines[:i] if not l.startswith("(")]
        assert before[-1] == "G90 G53 G0 Z0"
        assert lines[i + 1:i + 7] == [f"G43 H{n}", "G90", "G64", "G54", f"S{rpm} M3", "G4 P3000"]
    assert lines.index("T3 M6") < lines.index("T1 M6")
    assert [l for l in lines[:lines.index("T1 M6")] if not l.startswith("(")][-2] == "M5"
    assert lines[-3:] == ["M5", "G90 G53 G0 Z0", "M30"]


def test_the_motion_is_the_grbl_posts():
    """The cuts and the moves between them are the GRBL post's, line for line;
    only the words around them change."""
    def moves(text):
        return [l for l in text.splitlines() if l.startswith(("G1 ", "G0 X"))]
    grbl = GRBLPost(job_name="demo", material="acetate", tool_diameter_mm=2.0,
                    spindle_rpm=15000, feed_rate_mmpm=500.0, plunge_rate_mmpm=200.0,
                    safe_z_mm=5.0, feed_plane_mm=1.0, work_offset=(85.0, 35.0, 0.0))
    assert moves(_program(_post(), arc_tol=0.0)) == moves(_program(grbl, arc_tol=0.0))


def test_arcs_sweep_at_most_ninety_degrees_and_close_on_the_circle():
    text = _program(_post())
    x = y = None
    arcs = 0
    for line in text.splitlines():
        w = dict((k, float(v)) for k, v in re.findall(r"([XYIJ])(-?\d+\.?\d*)", line))
        if line.startswith(("G2 ", "G3 ")):
            arcs += 1
            cx, cy = x + w["I"], y + w["J"]
            a0 = math.atan2(y - cy, x - cx)
            a1 = math.atan2(w["Y"] - cy, w["X"] - cx)
            sweep = math.degrees((a1 - a0) % (2 * math.pi) if line.startswith("G3")
                                 else (a0 - a1) % (2 * math.pi))
            assert sweep <= 90.0 + 0.01, line          # the endpoints' rounding
        x, y = w.get("X", x), w.get("Y", y)
    assert arcs >= 4                                   # the eyewire's lap, split
    assert not any("arc" in w for w in lint_program(text, STEPCRAFT))


def test_a_tool_without_its_own_number_is_refused():
    """The changer fetches the pocket the number names: a number made up by
    machining order ("0 = auto"), or one two tools share, would fetch the
    wrong tool and apply the wrong length. Every such tool is named at once,
    before a word is written."""
    with pytest.raises(ValueError, match=r"^on a tool changer .* flat_2mm has none"):
        _program(_post(), settings=_settings(flat_2mm=False))
    with pytest.raises(ValueError, match="flat_2mm and flat_3175 have none of their own"):
        _program(_post(), settings=_settings(flat_2mm=False, flat_3175=False))
    # two tools on one pocket: the second is made up, and refused
    tools = {"flat_2mm": {"name": "flat_2mm", "diameter_mm": 2.0, "number": 4},
             "flat_3175": {"name": "flat_3175", "diameter_mm": 3.175, "number": 4}}
    settings, _ = build_tool_settings(_ops(tools), tools, default_feed=500,
                                      default_plunge=200, default_spindle=12000)
    assert settings["flat_2mm"].numbered and not settings["flat_3175"].numbered
    post = _post()
    with pytest.raises(ValueError, match="flat_3175 has none"):
        _program(post, settings=settings)
    assert post.to_string() == "\n"                # refused before a word was written
    # a tool whose op cuts nothing is not asked for
    settings["flat_9"] = ToolSetting(9, "flat_9", 9.0, 1, 1, 1)
    with pytest.raises(ValueError) as e:
        _program(_post(), settings=settings)
    assert "flat_9" not in str(e.value)


def test_a_manual_change_pauses_and_names_no_pocket():
    text = _program(_post(), mode="m0")
    assert "M6" not in text and "G43" not in text
    i = text.splitlines().index("M0")
    assert text.splitlines()[i - 1].startswith("(Load tool T1: flat_3175")


def test_a_shared_callers_semicolon_note_becomes_a_comment_line():
    post = _post(preamble=["; Re-zero Z: touch off on the blank's back and set it as Z6.000",
                           "G10 L20 P1 Z0 ; a code line with its note"])
    text = _program(post)
    assert ";" not in text
    assert "(Re-zero Z: touch off on the blank's back and set it as Z6.000)" in text
    lines = text.splitlines()
    assert lines[lines.index("G10 L20 P1 Z0") - 1] == "(a code line with its note)"
    with pytest.raises(ValueError, match="re-probe"):
        post.probe_z_block(6.0)


def test_comments_carry_ascii_and_wrap():
    assert program_label("Frame Front · Rough Relief") == "Frame Front - Rough Relief"
    assert program_label("Tool (2.00 mm); 30°") == "Tool [2.00 mm], 30 deg"
    long = comment_lines("word " * 40)
    assert len(long) > 1 and all(len(l) <= 78 and l[0] == "(" and l[-1] == ")" for l in long)


# ------------------------------------------------------------------ its readers

def test_the_simulation_reads_the_tools_and_ops_back():
    runs = parse_program(_program(_post()), work_offset=(85.0, 35.0, 0.0))
    cuts = [r for r in runs if r.is_cut]
    assert {r.tool for r in cuts} == {"flat_2mm", "flat_3175"}
    assert {r.label for r in cuts} == {program_label("Frame Front · Component Pockets"),
                                       program_label("Frame Front · Eyewires")}
    # the top-of-travel retract is machine coordinates, not a move to program Z0
    assert all(p[2] > 0 for r in runs if not r.is_cut for p in r.points[1:2])


def test_the_z_profile_annotates_in_the_programs_own_comments():
    text = annotate(_program(_post()))
    assert ";" not in text
    assert "(Z profile" in text
    head = text.splitlines()
    first_code = next(i for i, l in enumerate(head) if l and not l.startswith("("))
    assert any(l.startswith("(Z profile") for l in head[:first_code])


def test_the_lint_reads_the_top_of_travel_as_machine_coordinates():
    text = _program(_post())
    zs = [float(z) for z in re.findall(r"^G[01] .*Z(-?\d+\.\d+)", text, re.M)]
    assert min(zs) < 0 and "G53 G0 Z0" in text
    assert lint_program(text, STEPCRAFT) == []


def test_the_cut_time_reads_uccncs_dwell_in_milliseconds():
    """G4 P3000 is three seconds on UCCNC: read as GRBL's seconds, every
    spindle start added 50 minutes to the estimate."""
    from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program
    report = estimate_program(_program(_post()), MachineDynamics.from_profile(STEPCRAFT))
    assert report.dwell_seconds == pytest.approx(6.0)          # two starts, 3 s each
    grbl = load_machine_profile("guild_cnc", CONFIG)
    assert MachineDynamics.from_profile(grbl).dwell_p_seconds == 1.0


def test_a_section_marker_stays_on_one_line_however_long():
    """The readers take the op and the tool off the marker's one line."""
    label = "Frame Front · " + "a very long part label " * 4 + "· Rough Relief"
    (line,) = comment_lines(f"--- {label} ---")
    runs = parse_program(f"{line}\nG0 X0 Y0 Z5\nG1 Z-1 F100\nG1 X5 F100\n")
    assert runs[-1].label == program_label(label)


def test_a_refusal_is_a_post_error():
    """The window says a `PostError` to the maker and keeps every other error
    for the log, so the refusals are their own class (still a ValueError)."""
    from guildmodel.core.post.grbl import PostError
    with pytest.raises(PostError):
        _program(_post(), settings=_settings(flat_2mm=False))
    with pytest.raises(PostError):
        _post().probe_z_block(6.0)
    assert issubclass(PostError, ValueError)
