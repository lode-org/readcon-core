"""The Claisen reproduction stops when the model or any output digest differs."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
SCRIPT = SCRIPTS / "run_claisen_order.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_claisen_order", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_checker():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_manuscript

    return check_manuscript


def _copy_claisen(tmp_path: Path, source: Path) -> Path:
    dest = tmp_path / "claisen"
    shutil.copytree(source, dest)
    return dest


def _bump_first_con_coordinate(path: Path, delta: float = 0.3) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index in range(9, len(lines)):
        parts = lines[index].split()
        if len(parts) >= 3:
            try:
                x = float(parts[0])
            except ValueError:
                continue
            lines[index] = lines[index].replace(parts[0], f"{x + delta:.6f}", 1)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise AssertionError(f"no coordinate line found in {path}")


def test_a_model_or_export_digest_mismatch_stops(tmp_path, monkeypatch) -> None:
    module = _load()
    record = json.loads((module.DATA / "results.json").read_text(encoding="utf-8"))
    assert module.CKPT_SHA256 == record["potential"]["checkpoint_sha256"]
    assert module.PT_SHA256 == record["potential"]["torchscript_sha256"]

    bad_export = tmp_path / "pet.pt"
    bad_export.write_bytes(b"not-the-recorded-export")
    monkeypatch.setenv("CLAISEN_PT", str(bad_export))
    with pytest.raises(SystemExit, match="torchscript sha256"):
        module.ensure_model()

    monkeypatch.delenv("CLAISEN_PT")
    monkeypatch.setenv("CLAISEN_CKPT", str(tmp_path / "checkpoint.ckpt"))
    monkeypatch.setattr(module, "CACHE", tmp_path)
    (tmp_path / "checkpoint.ckpt").write_bytes(b"not-the-recorded-checkpoint")
    with pytest.raises(SystemExit, match="checkpoint sha256"):
        module.ensure_model()


def test_committed_claisen_outputs_match_manifest() -> None:
    module = _load()
    summary = module.check_outputs(module.DATA)
    assert "outputs match outputs.sha256" in summary
    recorded = module.parse_outputs_manifest(module.DATA / module.OUTPUTS_MANIFEST)
    for rel in (
        "results.json",
        "identity/band.con",
        "identity/ts.con",
        "identity/neb.dat",
        "ira/band.con",
        "ira/ts.con",
        "ira/neb.dat",
    ):
        assert rel in recorded

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_tampered_con_coordinate_fails_output_check(tmp_path, monkeypatch) -> None:
    module = _load()
    checker = _load_checker()
    copy = _copy_claisen(tmp_path, module.DATA)
    monkeypatch.setenv("CLAISEN_DATA", str(copy))
    assert "outputs match" in checker.script_check("run_claisen_order.py", "Claisen")

    for rel in ("identity/ts.con", "identity/band.con"):
        target = copy / rel
        original = target.read_bytes()
        _bump_first_con_coordinate(target, delta=0.3)
        with pytest.raises(SystemExit, match=rel):
            module.check_outputs(copy)
        with pytest.raises(checker.Failed, match=rel):
            checker.script_check("run_claisen_order.py", "Claisen outputs")
        target.write_bytes(original)


def test_tampered_band_energy_in_results_json_fails_output_check(
    tmp_path, monkeypatch
) -> None:
    module = _load()
    checker = _load_checker()
    copy = _copy_claisen(tmp_path, module.DATA)
    monkeypatch.setenv("CLAISEN_DATA", str(copy))
    assert "outputs match" in checker.script_check("run_claisen_order.py", "Claisen")

    results = copy / "results.json"
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["identity"]["band"][3]["energy_eV"] += 0.5
    results.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="results.json"):
        module.check_outputs(copy)
    with pytest.raises(checker.Failed, match="results.json"):
        checker.script_check("run_claisen_order.py", "Claisen outputs")


def test_tampered_neb_dat_and_truncated_manifest_fail(tmp_path) -> None:
    module = _load()
    copy = _copy_claisen(tmp_path, module.DATA)

    neb = copy / "identity" / "neb.dat"
    original_neb = neb.read_bytes()
    neb.write_text(
        neb.read_text(encoding="utf-8") + "99 0.0 0.0 0.0\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="identity/neb.dat"):
        module.check_outputs(copy)
    neb.write_bytes(original_neb)

    manifest = copy / module.OUTPUTS_MANIFEST
    kept = [
        line
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if not line.endswith("  ira/ts.con")
    ]
    manifest.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="ira/ts.con"):
        module.check_outputs(copy)


def test_stage_refuses_to_overwrite_divergent_outputs(tmp_path) -> None:
    module = _load()
    copy = _copy_claisen(tmp_path / "committed", module.DATA)
    staged = _copy_claisen(tmp_path / "staged", module.DATA)
    (staged / "identity" / "ts.con").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="--overwrite"):
        module.stage_or_verify(staged, copy, overwrite=False)
    assert (copy / "identity" / "ts.con").read_bytes() == (
        module.DATA / "identity" / "ts.con"
    ).read_bytes()

    module.stage_or_verify(staged, copy, overwrite=True)
    assert (copy / "identity" / "ts.con").read_text(encoding="utf-8") == "tampered\n"
    module.check_outputs(copy)
