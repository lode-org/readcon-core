"""gen_spec_supp.py --measure adds a file and never rewrites a stored one."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "gen_spec_supp.py"
IDENTITY = (
    "-c",
    "user.name=spec test",
    "-c",
    "user.email=spec@test.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *IDENTITY, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _load(tmp: Path):
    spec = importlib.util.spec_from_file_location("gen_spec_supp", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp / "VERSION").write_text("9.9.9\n")
    module.ROOT = tmp
    module.VERSION = "9.9.9"
    module.SPEC_DATA = tmp / "paper" / "cpc" / "data" / "spec"
    module.SPEC_DATA.mkdir(parents=True)
    module._spec_blob = lambda: "c" * 40
    module.git = lambda *args, check=True: subprocess.CompletedProcess(
        args, 0, stdout="b" * 40 + "\n", stderr=""
    )
    module.versions_record = lambda: {
        "spec": "docs/orgmode/spec.org",
        "tags": [],
        "tree": {"release": "9.9.9", "tagged": False, "spec_blob": "c" * 40},
    }
    return module


def test_a_rerun_keeps_the_measured_file(tmp_path: Path) -> None:
    module = _load(tmp_path)
    data = module.SPEC_DATA
    stored = data / "spec-measurement-9.9.9.json"
    measured = data / "spec-measurement-9.9.9-measured.json"
    stored_text = json.dumps(
        {"spec": "docs/orgmode/spec.org", "tree": {"spec_blob": "c" * 40}}
    )
    stored.write_text(stored_text + "\n")
    measured_text = json.dumps(
        {
            "supersedes": "paper/cpc/data/spec/spec-measurement-9.9.9.json",
            "measured_at": {"commit": "a" * 40},
        }
    )
    measured.write_text(measured_text)
    module.measure()
    assert measured.read_text() == measured_text
    fresh = json.loads((data / "spec-measurement-9.9.9-measured-2.json").read_text())
    assert fresh["supersedes"] == (
        "paper/cpc/data/spec/spec-measurement-9.9.9-measured.json"
    )
    assert fresh["measured_at"] == {"commit": "b" * 40}


def test_the_first_rerun_supersedes_the_stored_file(tmp_path: Path) -> None:
    module = _load(tmp_path)
    stored = module.SPEC_DATA / "spec-measurement-9.9.9.json"
    stored_text = (
        json.dumps({"spec": "docs/orgmode/spec.org", "tree": {"spec_blob": "c" * 40}})
        + "\n"
    )
    stored.write_text(stored_text)
    module.measure()
    assert stored.read_text() == stored_text
    fresh = json.loads(
        (module.SPEC_DATA / "spec-measurement-9.9.9-measured.json").read_text()
    )
    assert fresh["supersedes"] == "paper/cpc/data/spec/spec-measurement-9.9.9.json"


def test_spec_edit_measure_writes_blob_record_that_reader_selects(
    tmp_path: Path,
) -> None:
    module = _load(tmp_path)
    stored = module.SPEC_DATA / "spec-measurement-9.9.9.json"
    stored_text = (
        json.dumps({"spec": "docs/orgmode/spec.org", "tree": {"spec_blob": "a" * 40}})
        + "\n"
    )
    stored.write_text(stored_text)
    module.measure()
    assert stored.read_text() == stored_text
    by_blob = module.SPEC_DATA / "spec-measurement-9.9.9-cccccccc.json"
    assert by_blob.is_file()
    assert module.active_versions_file() == by_blob


def test_spec_edit_measure_then_generate_in_temp_copy(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    _git(ROOT, "clone", "-q", "--local", str(ROOT), str(clone))
    _git(clone, "checkout", "-q", "--detach", _git(ROOT, "rev-parse", "HEAD").strip())
    changed = _git(
        ROOT, "ls-files", "-z", "--modified", "--others", "--exclude-standard"
    )
    for name in filter(None, changed.split("\0")):
        if (ROOT / name).is_file():
            (clone / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, clone / name)
    if _git(clone, "status", "--porcelain"):
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "working tree")

    spec_dir = clone / "paper" / "cpc" / "data" / "spec"
    before_records = {
        p.name: p.read_bytes() for p in sorted(spec_dir.glob("spec-measurement-*.json"))
    }

    spec_file = clone / "docs" / "orgmode" / "spec.org"
    spec_file.write_text(
        spec_file.read_text(encoding="utf-8")
        + "\n# Regression test comment for spec measurement selection.\n",
        encoding="utf-8",
    )
    _git(clone, "add", "docs/orgmode/spec.org")
    _git(clone, "commit", "-q", "-m", "edit spec.org in temp copy")
    new_blob = _git(clone, "hash-object", "docs/orgmode/spec.org").strip()
    version = (clone / "VERSION").read_text(encoding="utf-8").strip()

    env = dict(os.environ)
    pixi_bin = ROOT / "paper" / "cpc" / ".pixi" / "envs" / "default" / "bin"
    if (pixi_bin / "pandoc").is_file():
        env["PATH"] = f"{pixi_bin}{os.pathsep}{env.get('PATH', '')}"

    stale_gen = subprocess.run(
        [sys.executable, "paper/cpc/scripts/gen_spec_supp.py", "--as-is"],
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale_gen.returncode != 0
    assert new_blob[:8] in (stale_gen.stdout + stale_gen.stderr)

    measured = subprocess.run(
        [sys.executable, "paper/cpc/scripts/gen_spec_supp.py", "--measure"],
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert measured.returncode == 0, measured.stdout + measured.stderr

    expected_record = spec_dir / f"spec-measurement-{version}-{new_blob[:8]}.json"
    assert expected_record.is_file(), (
        f"expected {expected_record.name}, got {[p.name for p in spec_dir.glob('spec-measurement-*.json')]}"
    )
    for name, content in before_records.items():
        assert (spec_dir / name).read_bytes() == content

    generated = subprocess.run(
        [sys.executable, "paper/cpc/scripts/gen_spec_supp.py", "--as-is"],
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr

    checked = subprocess.run(
        [sys.executable, "paper/cpc/scripts/gen_spec_supp.py", "--check"],
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

