"""`.gcam` project container round-trip + hand-off (BUILDPLAN M5.1).

A .gcam holds everything to reopen a project with no external files, plus the
documented gSender-fork subset. These tests cover the full round-trip, staged
saves (project-only vs with-program), checksum verification, and hand-off
extraction.
"""
import json
import zipfile
from pathlib import Path

import pytest

from guildcam.core.project.schema import (
    ProjectSchema, MachineProfile, CastleCamParams,
)
from guildcam.core.project.gcam import (
    GcamError, save_gcam, load_gcam, extract_handoff, HANDOFF_FILES,
)


def _project() -> ProjectSchema:
    p = ProjectSchema(job_name="Demo Frame", source_file="frame.dxf")
    p.cam_params = CastleCamParams(machine_name="carbide_nomad3", relief_stepover_mm=1.1)
    p.castle.zones.endpiece_mm = 5.7
    return p


def test_full_round_trip(tmp_path):
    proj = _project()
    machine = MachineProfile(name="carbide_nomad3", display_name="Carbide 3D Nomad 3",
                             max_feed_mmpm=3000, supports_arcs=True)
    programs = {"posterior_cut.nc": "G21\nG0 Z5\nG1 X1 Y1 F750\nM30\n"}
    setup = {"tool": "flat_3175", "ops": [{"name": "Perimeter", "cut_mm": 1500}],
             "est_minutes": 9.6}
    report = {"status": "ok", "uncut_fraction": 0.0005}

    path = tmp_path / "job.gcam"
    save_gcam(path, project=proj, dxf_bytes=b"DXF-BYTES\x00\x01",
              programs=programs, machine=machine, setup=setup, report=report,
              stl_bytes=b"solid x\n", run_mode="single_m0")

    b = load_gcam(path)
    assert b.project.job_name == "Demo Frame"
    assert b.project.cam_params.machine_name == "carbide_nomad3"
    assert b.project.cam_params.relief_stepover_mm == 1.1
    assert b.project.castle.zones.endpiece_mm == 5.7
    assert b.dxf_bytes == b"DXF-BYTES\x00\x01"
    assert b.programs == programs
    assert b.machine["display_name"] == "Carbide 3D Nomad 3"
    assert b.setup["est_minutes"] == 9.6
    assert b.report["status"] == "ok"
    assert b.stl_bytes == b"solid x\n"
    assert b.run_mode == "single_m0"
    assert b.has_program()


def test_manifest_inventory_and_checksums(tmp_path):
    path = tmp_path / "job.gcam"
    save_gcam(path, project=_project(), dxf_bytes=b"abc",
              programs={"posterior_cut.nc": "G21\n"})
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
    assert manifest["format"] == "gcam" and manifest["format_version"] == 1
    assert "project.json" in manifest["contents"]
    assert "program/posterior_cut.nc" in manifest["contents"]
    # manifest is not listed in its own inventory; every listed file is present
    assert "manifest.json" not in manifest["contents"]
    assert set(manifest["contents"]) <= names


def test_project_only_save_is_reopenable(tmp_path):
    """A .gcam saved right after import (no program yet) still reopens."""
    path = tmp_path / "job.gcam"
    save_gcam(path, project=_project(), dxf_bytes=b"dxf")
    b = load_gcam(path)
    assert not b.has_program()
    assert b.machine is None and b.setup is None
    assert b.dxf_bytes == b"dxf"


def test_checksum_mismatch_raises(tmp_path):
    path = tmp_path / "job.gcam"
    save_gcam(path, project=_project(), dxf_bytes=b"abc")
    # tamper: rewrite source.dxf with different bytes, keep the old manifest
    import io
    with zipfile.ZipFile(path) as zf:
        items = {n: zf.read(n) for n in zf.namelist()}
    items["source.dxf"] = b"TAMPERED"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, d in items.items():
            zf.writestr(n, d)
    path.write_bytes(buf.getvalue())
    with pytest.raises(GcamError):
        load_gcam(path)
    # but verify=False still loads it
    assert load_gcam(path, verify=False).dxf_bytes == b"TAMPERED"


def test_not_a_gcam_raises(tmp_path):
    bad = tmp_path / "bad.gcam"
    bad.write_bytes(b"not a zip file")
    with pytest.raises(GcamError):
        load_gcam(bad)


def test_extract_handoff_subset(tmp_path):
    path = tmp_path / "job.gcam"
    save_gcam(path, project=_project(), dxf_bytes=b"dxf-should-not-be-handed-off",
              programs={"posterior_cut.nc": "G21\nM30\n"},
              machine=MachineProfile(), setup={"tool": "flat_3175"},
              report={"status": "ok"})
    dest = tmp_path / "out"
    written = extract_handoff(path, dest)
    rel = {p.relative_to(dest).as_posix() for p in written}
    assert "program/posterior_cut.nc" in rel
    assert set(HANDOFF_FILES) <= rel
    # the source DXF and the cut report are not part of the machine hand-off
    assert "source.dxf" not in rel and "cut_report.json" not in rel
    assert (dest / "program" / "posterior_cut.nc").read_text() == "G21\nM30\n"
