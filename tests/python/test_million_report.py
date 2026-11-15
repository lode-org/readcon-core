"""The million-atom comparison reads the 0.23.0 record and does not rewrite it."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import million_report as report


def _row(arm, tool, op, median, iqr=0.01, cache=None):
    return {
        "structure": "1M",
        "arm": arm,
        "tool": tool,
        "op": op,
        "cache": cache or ("warm" if op == "read" else "create"),
        "median_s": median,
        "iqr_s": iqr,
        "rss_bytes": 10,
        "file_bytes": 20,
        "loses": "none",
    }


def _pair(old_rc, new_rc, old_peer, new_peer):
    old = {
        ("1M", "readcon-con", "read", "warm"): _row(
            "readcon-con", "readcon", "read", old_rc
        ),
        ("1M", "ase-extxyz", "read", "warm"): _row(
            "ase-extxyz", "ase", "read", old_peer
        ),
    }
    new = {
        ("1M", "readcon-con", "read", "warm"): _row(
            "readcon-con", "readcon", "read", new_rc
        ),
        ("1M", "ase-extxyz", "read", "warm"): _row(
            "ase-extxyz", "ase", "read", new_peer
        ),
    }
    return old, new


def test_type7_median_matches_the_middle_of_an_odd_count():
    assert report.type7_median([1.0, 3.0, 2.0]) == 2.0


def test_uniform_slowdown_is_not_a_readcon_regression():
    old, new = _pair(0.10, 0.20, 2.0, 4.0)
    factor = {"read": report.machine_factor(old, new, "read")[0], "write": 1.0}
    assert factor["read"] == pytest.approx(2.0)
    assert report.self_regressions(old, new, factor) == []
    assert report.lost_leads(old, new) == []


def test_readcon_slower_than_the_peer_factor_is_a_regression():
    old, new = _pair(0.10, 0.40, 2.0, 2.0)
    factor = {"read": 1.0, "write": 1.0}
    found = report.self_regressions(old, new, factor)
    assert len(found) == 1
    assert "readcon-con" in found[0]


def test_lost_lead_needs_a_real_gap():
    old, new = _pair(0.50, 1.50, 1.0, 1.0)
    assert report.lost_leads(old, new)
    old_close, new_close = _pair(0.99, 1.01, 1.0, 1.0)
    assert report.lost_leads(old_close, new_close) == []


def _tip(root: Path) -> tuple[str, str]:
    full = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    short = subprocess.check_output(
        ["git", "rev-parse", "--short=12", "HEAD"], cwd=root, text=True
    ).strip()
    return full, short


_STUB = """\
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
out = None
ops = "read,write"
index = 0
while index < len(args):
    if args[index] == "--out":
        out = Path(args[index + 1])
        index += 2
    elif args[index] == "--ops":
        ops = args[index + 1]
        index += 2
    else:
        index += 1
if os.environ.get("READCON_STUB_FAIL") == "1":
    sys.exit(1)
if os.environ.get("READCON_STUB_EMPTY") == "1":
    sys.exit(0)
if out is None:
    sys.exit("missing --out")
out.mkdir(parents=True, exist_ok=True)
for name in ("cross-format.json", "cross-format.log", "cross-format.tsv"):
    (out / name).write_text("measured\\n", encoding="utf-8")
if "read" in ops.split(","):
    (out / "chemfiles-write-profile.txt").write_text("measured\\n", encoding="utf-8")
"""


_ASV_STUB = """\
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

out = Path(sys.argv[1])
if os.environ.get("READCON_STUB_ASV_FAIL") == "1":
    sys.exit(1)
(out / "asv.json").write_text("asv\\n", encoding="utf-8")
(out / "asv-machine.json").write_text("machine\\n", encoding="utf-8")
"""

_RECORD_STUB = """\
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

out = None
index = 0
while index < len(sys.argv):
    if sys.argv[index] == "--out":
        out = Path(sys.argv[index + 1])
        index += 2
    else:
        index += 1
if os.environ.get("READCON_STUB_RECORD_FAIL") == "1":
    sys.exit(1)
if out is None:
    sys.exit("missing --out")
for name in ("host.json", "lscpu.txt", "NOTES.txt", "library-commit.txt"):
    (out / name).write_text("record\\n", encoding="utf-8")
"""


def _worktree(tmp_path: Path, name: str) -> Path:
    source = Path(__file__).resolve().parents[2]
    tree = tmp_path / name
    subprocess.check_call(
        ["git", "worktree", "add", "--detach", str(tree), "HEAD"],
        cwd=source,
    )
    shutil.copy(source / "bench/h2h/Snakefile", tree / "bench/h2h/Snakefile")
    bench = tree / "bench" / "h2h"
    (bench / "cross_format.py").write_text(_STUB, encoding="utf-8")
    (bench / "million_asv.py").write_text(_ASV_STUB, encoding="utf-8")
    (bench / "million_report.py").write_text(_RECORD_STUB, encoding="utf-8")
    return tree


def _snakemake(
    tree: Path,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
):
    snakemake = shutil.which("snakemake")
    if snakemake is None:
        pytest.skip("snakemake is not installed")
    run_cwd = tree if cwd is None else cwd
    if cwd is None:
        snakefile = "bench/h2h/Snakefile"
    else:
        snakefile = os.path.relpath(tree / "bench" / "h2h" / "Snakefile", run_cwd)
    command = [snakemake, "-s", snakefile, "-c1", *args]
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        command,
        cwd=run_cwd,
        check=False,
        capture_output=True,
        text=True,
        env=merged,
    )


def _record_hashes(record: Path) -> dict[str, str]:
    found = {}
    for path in sorted(record.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        found[path.relative_to(record).as_posix()] = digest
    return found


def test_million_rule_targets_the_versioned_record(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    trees = []
    try:
        fresh_tree = _worktree(tmp_path, "fresh")
        trees.append(fresh_tree)
        tip, short = _tip(fresh_tree)
        fresh = f"bench/h2h/million/v{version}-{short}"
        saved = fresh_tree / "bench/h2h/million" / f"v{version}"
        before = (
            (saved / "cross-format.json").read_bytes(),
            (saved / "cross-format.log").read_bytes(),
        )
        accepted = _snakemake(fresh_tree, "million_measure")
        shown = accepted.stdout + accepted.stderr
        assert accepted.returncode == 0, shown
        for name in (
            "cross-format.json",
            "cross-format.log",
            "cross-format.tsv",
            "chemfiles-write-profile.txt",
        ):
            assert (fresh_tree / fresh / name).read_text(
                encoding="utf-8"
            ) == "measured\n"
        assert (saved / "cross-format.json").read_bytes() == before[0]
        assert (saved / "cross-format.log").read_bytes() == before[1]

        existing = _worktree(tmp_path, "existing")
        trees.append(existing)
        _, existing_short = _tip(existing)
        existing_fresh = existing / "bench/h2h/million" / f"v{version}-{existing_short}"
        existing_fresh.mkdir(parents=True)
        (existing_fresh / "cross-format.json").write_text("kept\n", encoding="utf-8")
        (existing_fresh / "cross-format.log").write_text("kept\n", encoding="utf-8")
        saved_existing = existing / "bench/h2h/million" / f"v{version}"
        existing_before = (
            (saved_existing / "cross-format.json").read_bytes(),
            (saved_existing / "cross-format.log").read_bytes(),
        )
        refused = _snakemake(existing, "million_measure")
        refused_text = refused.stdout + refused.stderr
        assert refused.returncode != 0, refused_text
        assert "refusing to write a saved record" in refused_text
        assert (existing_fresh / "cross-format.json").read_text(
            encoding="utf-8"
        ) == "kept\n"
        assert (existing_fresh / "cross-format.log").read_text(
            encoding="utf-8"
        ) == "kept\n"
        assert (saved_existing / "cross-format.json").read_bytes() == existing_before[0]
        assert (saved_existing / "cross-format.log").read_bytes() == existing_before[1]
        other = _snakemake(existing, "-n", "publication")
        assert other.returncode == 0, other.stdout + other.stderr

        scaling = _worktree(tmp_path, "scaling")
        trees.append(scaling)
        denied = _snakemake(
            scaling,
            "million_measure",
            "--config",
            "million_out=bench/h2h/scaling/new",
        )
        denied_text = denied.stdout + denied.stderr
        assert denied.returncode != 0, denied_text
        assert "refusing to write a saved record" in denied_text
        assert not (scaling / "bench/h2h/scaling/new").exists()
        assert tip
    finally:
        for tree in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=root,
                check=False,
            )


def test_superseded_note_follows_a_complete_measurement(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    trees = []
    try:
        done = _worktree(tmp_path, "done")
        trees.append(done)
        tip, short = _tip(done)
        fresh = f"bench/h2h/million/v{version}-{short}"
        saved = done / "bench/h2h/million" / f"v{version}"
        before = (
            (saved / "cross-format.json").read_bytes(),
            (saved / "cross-format.log").read_bytes(),
        )
        accepted = _snakemake(done, "million_measure")
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        note = (saved / "SUPERSEDED.md").read_text(encoding="utf-8")
        assert fresh in note
        assert tip in note
        assert (done / fresh / "cross-format.json").is_file()
        assert (saved / "cross-format.json").read_bytes() == before[0]
        assert (saved / "cross-format.log").read_bytes() == before[1]

        failed = _worktree(tmp_path, "failed")
        trees.append(failed)
        failed_saved = failed / "bench/h2h/million" / f"v{version}"
        failed_run = _snakemake(
            failed, "million_measure", env={"READCON_STUB_FAIL": "1"}
        )
        assert failed_run.returncode != 0
        assert not (failed_saved / "SUPERSEDED.md").exists()
        assert (failed_saved / "cross-format.json").read_bytes() == before[0]
        assert (failed_saved / "cross-format.log").read_bytes() == before[1]

        empty = _worktree(tmp_path, "empty")
        trees.append(empty)
        empty_saved = empty / "bench/h2h/million" / f"v{version}"
        empty_run = _snakemake(
            empty, "million_measure", env={"READCON_STUB_EMPTY": "1"}
        )
        assert empty_run.returncode != 0
        assert not (empty_saved / "SUPERSEDED.md").exists()
        assert (empty_saved / "cross-format.json").read_bytes() == before[0]
    finally:
        for tree in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=root,
                check=False,
            )


def test_a_finished_measure_can_resume(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    trees = []
    try:
        resume = _worktree(tmp_path, "resume")
        trees.append(resume)
        _, short = _tip(resume)
        fresh = resume / "bench/h2h/million" / f"v{version}-{short}"
        measured = _snakemake(resume, "million_measure")
        assert measured.returncode == 0, measured.stdout + measured.stderr
        measured_bytes = (fresh / "cross-format.json").read_bytes()
        planned = _snakemake(resume, "-n", "million")
        planned_text = planned.stdout + planned.stderr
        assert planned.returncode == 0, planned_text
        assert "refusing to write a saved record" not in planned_text
        assert "rule million_measure:" not in planned_text
        assert "rule million_asv:" in planned_text
        assert (fresh / "cross-format.json").read_bytes() == measured_bytes

        asv_fail = _worktree(tmp_path, "asv-fail")
        trees.append(asv_fail)
        _, asv_short = _tip(asv_fail)
        asv_fresh = asv_fail / "bench/h2h/million" / f"v{version}-{asv_short}"
        first_asv = _snakemake(asv_fail, "million", env={"READCON_STUB_ASV_FAIL": "1"})
        assert first_asv.returncode != 0
        asv_bytes = (asv_fresh / "cross-format.json").read_bytes()
        continued = _snakemake(asv_fail, "million")
        assert continued.returncode == 0, continued.stdout + continued.stderr
        assert (asv_fresh / "cross-format.json").read_bytes() == asv_bytes
        assert (asv_fresh / "asv.json").read_text(encoding="utf-8") == "asv\n"
        assert (asv_fresh / "host.json").read_text(encoding="utf-8") == "record\n"

        record_fail = _worktree(tmp_path, "record-fail")
        trees.append(record_fail)
        _, record_short = _tip(record_fail)
        record_fresh = record_fail / "bench/h2h/million" / f"v{version}-{record_short}"
        first_record = _snakemake(
            record_fail, "million", env={"READCON_STUB_RECORD_FAIL": "1"}
        )
        assert first_record.returncode != 0
        record_bytes = (record_fresh / "cross-format.json").read_bytes()
        assert (record_fresh / "asv.json").is_file()
        assert not (record_fresh / "host.json").exists()
        finished = _snakemake(record_fail, "million")
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert (record_fresh / "cross-format.json").read_bytes() == record_bytes
        assert (record_fresh / "host.json").read_text(encoding="utf-8") == "record\n"

        blocked = _worktree(tmp_path, "blocked")
        trees.append(blocked)
        _, blocked_short = _tip(blocked)
        blocked_fresh = blocked / "bench/h2h/million" / f"v{version}-{blocked_short}"
        blocked_fresh.mkdir(parents=True)
        (blocked_fresh / "sentinel").write_text("kept\n", encoding="utf-8")
        refused = _snakemake(blocked, "million")
        refused_text = refused.stdout + refused.stderr
        assert refused.returncode != 0, refused_text
        assert "refusing to write a saved record" in refused_text
        assert (blocked_fresh / "sentinel").read_text(encoding="utf-8") == "kept\n"
        assert not (blocked_fresh / "cross-format.json").exists()
    finally:
        for tree in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=root,
                check=False,
            )


def test_a_protected_measure_is_not_rewritten(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    trees = []
    try:
        forced = _worktree(tmp_path, "forced")
        trees.append(forced)
        _, short = _tip(forced)
        fresh = forced / "bench/h2h/million" / f"v{version}-{short}"
        measured = _snakemake(forced, "million_measure")
        assert measured.returncode == 0, measured.stdout + measured.stderr
        measured_bytes = (fresh / "cross-format.json").read_bytes()
        forced_run = _snakemake(forced, "-F", "million")
        forced_text = forced_run.stdout + forced_run.stderr
        assert forced_run.returncode != 0, forced_text
        assert "ProtectedOutputException" in forced_text
        assert (fresh / "cross-format.json").read_bytes() == measured_bytes

        edited = _worktree(tmp_path, "edited")
        trees.append(edited)
        _, edited_short = _tip(edited)
        edited_fresh = edited / "bench/h2h/million" / f"v{version}-{edited_short}"
        edited_measure = _snakemake(edited, "million_measure")
        assert edited_measure.returncode == 0, (
            edited_measure.stdout + edited_measure.stderr
        )
        edited_bytes = (edited_fresh / "cross-format.json").read_bytes()
        snakefile = edited / "bench/h2h/Snakefile"
        original = snakefile.read_text(encoding="utf-8")
        needle = (
            'python3 bench/h2h/cross_format.py --out "{params.out}" '
            '--repeats 12 --ops "{params.ops}"\n'
        )
        assert needle in original
        snakefile.write_text(
            original.replace(needle, needle + "        : record stays\n", 1),
            encoding="utf-8",
        )
        changed = _snakemake(edited, "million")
        changed_text = changed.stdout + changed.stderr
        assert changed.returncode != 0, changed_text
        assert "ProtectedOutputException" in changed_text
        assert (edited_fresh / "cross-format.json").read_bytes() == edited_bytes

        moved = _worktree(tmp_path, "moved")
        trees.append(moved)
        _, moved_short = _tip(moved)
        moved_rel = f"bench/h2h/million/v{version}-{moved_short}"
        moved_fresh = moved / moved_rel
        moved_measure = _snakemake(moved, "million_measure")
        assert moved_measure.returncode == 0, (
            moved_measure.stdout + moved_measure.stderr
        )
        moved_bytes = (moved_fresh / "cross-format.json").read_bytes()
        subprocess.check_call(
            ["git", "commit", "--allow-empty", "-m", "note a later tip"],
            cwd=moved,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Rohit Goswami",
                "GIT_AUTHOR_EMAIL": "rgoswami@ieee.org",
                "GIT_COMMITTER_NAME": "Rohit Goswami",
                "GIT_COMMITTER_EMAIL": "rgoswami@ieee.org",
            },
        )
        retargeted = _snakemake(
            moved,
            "million",
            "--config",
            f"million_out={moved_rel}",
        )
        retargeted_text = retargeted.stdout + retargeted.stderr
        assert retargeted.returncode != 0, retargeted_text
        assert "ProtectedOutputException" in retargeted_text
        assert (moved_fresh / "cross-format.json").read_bytes() == moved_bytes
    finally:
        for tree in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=root,
                check=False,
            )


def _committed_attack(
    tree: Path, record: str, kind: str
) -> tuple[str, Path | None, bool]:
    record_path = tree / record
    if kind == "plain":
        return record, None, False
    if kind == "leading-dot":
        return f"./{record}", None, False
    if kind == "embedded-dot":
        return "bench/h2h/million/./v0.23.3", None, False
    if kind == "parent-foo":
        return "bench/h2h/foo/../million/v0.23.3", None, False
    if kind == "parent-million":
        return "bench/h2h/million/../million/v0.23.3", None, False
    if kind == "absolute":
        return str(record_path.resolve()), None, False
    if kind == "symlink-dir":
        link = tree / "bench" / "h2h" / "record-link"
        link.symlink_to(Path("million") / "v0.23.3", target_is_directory=True)
        return "bench/h2h/record-link", None, False
    if kind == "symlink-parent":
        link = tree / "bench" / "h2h" / "parent-link"
        link.symlink_to("million", target_is_directory=True)
        return "bench/h2h/parent-link/v0.23.3", None, False
    if kind == "removed-leading-dot":
        return f"./{record}", None, True
    if kind == "nested-cwd":
        return "v0.23.3", tree / "bench" / "h2h" / "million", False
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "plain",
        "leading-dot",
        "embedded-dot",
        "parent-foo",
        "parent-million",
        "absolute",
        "symlink-dir",
        "symlink-parent",
        "removed-leading-dot",
        "nested-cwd",
    ],
)
def test_a_committed_record_is_refused(tmp_path: Path, kind: str):
    root = Path(__file__).resolve().parents[2]
    record = "bench/h2h/million/v0.23.3"
    trees = []
    try:
        tree = _worktree(tmp_path, "committed")
        trees.append(tree)
        before = _record_hashes(tree / record)
        million_out, cwd, remove = _committed_attack(tree, record, kind)
        if remove:
            shutil.rmtree(tree / record)
        targets = ["million", "million_asv", "million_record"]
        for target in targets:
            refused = _snakemake(
                tree,
                target,
                "--config",
                f"million_out={million_out}",
                cwd=cwd,
            )
            refused_text = refused.stdout + refused.stderr
            assert refused.returncode != 0, refused_text
            assert "refusing to write a saved record" in refused_text
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--", record],
            cwd=tree,
            text=True,
        )
        if remove:
            assert not (tree / record).exists()
            assert status != ""
            for line in status.splitlines():
                assert line.startswith(" D"), line
        else:
            assert _record_hashes(tree / record) == before
            assert status == ""
            assert not (tree / record / "NOTES.txt").exists()
            assert not (tree / record / "asv.json").exists()
            assert not (tree / record / "asv-machine.json").exists()
            assert not (tree / record / "library-commit.txt").exists()
            assert not (tree / record / "lscpu.txt").exists()
    finally:
        for path in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=root,
                check=False,
            )


def test_a_fresh_directory_still_measures_and_resumes(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    trees = []
    try:
        tree = _worktree(tmp_path, "fresh-resume")
        trees.append(tree)
        _, short = _tip(tree)
        fresh = tree / "bench/h2h/million" / f"v{version}-{short}"
        measured = _snakemake(tree, "million_measure")
        assert measured.returncode == 0, measured.stdout + measured.stderr
        measured_bytes = (fresh / "cross-format.json").read_bytes()
        resumed = _snakemake(tree, "million")
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert (fresh / "cross-format.json").read_bytes() == measured_bytes
        assert (fresh / "asv.json").read_text(encoding="utf-8") == "asv\n"
        assert (fresh / "host.json").read_text(encoding="utf-8") == "record\n"
    finally:
        for path in trees:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=root,
                check=False,
            )


def test_a_per_size_repeat_map_is_the_campaign_protocol():
    assert report.protocol_error({"warmup": 1, "repeats": 12}) is None
    assert (
        report.protocol_error(
            {"warmup": 1, "repeats": {"1k": 12, "100k": 12, "1M": 6, "traj": 12}}
        )
        is None
    )
    assert report.protocol_error({"warmup": 1, "repeats": {"1M": 0}}) is not None


def test_report_refuses_to_write_the_baseline_directory():
    with pytest.raises(SystemExit, match="existing records"):
        report.fresh_output(report.BASELINE.parent)


def test_notes_name_the_fields_con_keeps(tmp_path: Path):
    doc = {
        "commit": "abc",
        "warmup": 1,
        "repeats": 12,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "affinity": "taskset -c 0",
        "versions": {"readcon": "0.23.2"},
        "host": {"cpu_mhz": 2400.0, "loadavg": "0.1", "lscpu": "Model name: test\n"},
        "rows": [
            _row("readcon-con", "readcon", "read", 0.20),
            _row("ase-extxyz", "ase", "read", 4.0),
            _row("readcon-con", "readcon", "write", 0.30),
            _row("ase-extxyz", "ase", "write", 8.0),
        ],
    }
    (tmp_path / "cross-format.json").write_text(json.dumps(doc))
    notes, flags = report.build_notes(doc)
    assert flags == []
    assert "measured readcon 0.23.2" in notes
    assert "masses, velocities, constraints" in notes
    assert "adjusted" not in notes
    assert "Peer reads" not in notes and "Peer writes" not in notes
    assert "one file" in notes
    report.write_record(tmp_path, doc, notes)
    saved = json.loads((tmp_path / "host.json").read_text())
    assert len(saved["tree"]) == 40
    assert saved["host"]["cpu_model"] == "test"
    assert saved["host"]["disk_filesystem"]
    assert (tmp_path / "lscpu.txt").read_text().startswith("Model name")


def test_session_record_keeps_the_version_and_the_rows() -> None:
    import importlib

    driver = importlib.import_module("million_ab")
    rows = [
        {
            "build": "head",
            "format": "con",
            "op": "read",
            "median_s": 0.2,
            "iqr_s": 0.01,
            "n": 12,
            "samples_s": [0.2] * 12,
            "checks": [1.0] * 12,
        },
        {
            "build": "v0.23.2",
            "format": "con",
            "op": "read",
            "median_s": 0.1,
            "iqr_s": 0.01,
            "n": 12,
            "samples_s": [0.1] * 12,
            "checks": [1.0] * 12,
            "head_over_this": 2.0,
        },
    ]
    doc = driver.session_record(
        "8c2d9984c40aedfb2e0084fedefaa02e930957f2",
        "0.23.2",
        {"cpu_mhz": 2400.0},
        rows,
        ["host_mhz 2400.0"],
    )
    assert doc["readcon_version"] == "0.23.2"
    assert doc["head"] == "8c2d9984c40aedfb2e0084fedefaa02e930957f2"
    assert doc["rows"][0]["samples_s"] == [0.2] * 12
    assert doc["rows"][1]["head_over_this"] == 2.0
    assert doc["lines"] == ["host_mhz 2400.0"]


def test_library_commit_matches_the_sources_at_head():
    import subprocess

    found = report.library_commit(report.ROOT)
    head_src = subprocess.check_output(
        ["git", "rev-parse", "HEAD:src"], cwd=report.ROOT, text=True
    )
    lib_src = subprocess.check_output(
        ["git", "rev-parse", f"{found}:src"], cwd=report.ROOT, text=True
    )
    assert head_src == lib_src
    assert len(found) == 40


def test_a_string_median_is_not_a_timed_row():
    doc = {"rows": [_row("chemfiles-con", "readcon", "write", "no writer")]}
    assert report.index_rows(doc) == {}


def test_same_host_gap_wider_than_the_iqr_is_a_regression():
    ab = {
        "rows": [
            {
                "build": "head",
                "format": "con.gz",
                "op": "read",
                "median_s": 0.120,
                "iqr_s": 0.005,
            },
            {
                "build": "v0.23.0",
                "format": "con.gz",
                "op": "read",
                "median_s": 0.096,
                "iqr_s": 0.004,
            },
        ]
    }
    flags = report.release_flags(ab)
    assert len(flags) == 1
    assert "con.gz read" in flags[0]
    close = {
        "rows": [
            {
                "build": "head",
                "format": "con",
                "op": "read",
                "median_s": 0.086,
                "iqr_s": 0.003,
            },
            {
                "build": "v0.23.0",
                "format": "con",
                "op": "read",
                "median_s": 0.085,
                "iqr_s": 0.002,
            },
        ]
    }
    assert report.release_flags(close) == []


def test_write_only_campaign_does_not_demand_read_rows():
    doc = {
        "commit": "abc",
        "warmup": 1,
        "repeats": 12,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "affinity": "taskset -c 0",
        "versions": {"readcon": "0.23.2"},
        "host": {"cpu_mhz": 2400.0, "loadavg": "0.1", "lscpu": "Model name: test\n"},
        "rows": [
            _row("readcon-con", "readcon", "write", 0.30),
            _row("ase-extxyz", "ase", "write", 8.0),
        ],
    }
    notes, flags = report.build_notes(doc)
    assert flags == []
    assert "readcon-con write" in notes
    assert "readcon-con read" not in notes
    assert "adjusted" not in notes
