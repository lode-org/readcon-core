"""Dry-run and refusal-guard tests for the ``rerun_release`` Snakemake target."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_RULES = (
    "final_bindings",
    "final_ceilings",
    "final_strong_threads",
    "final_strong_mpi",
    "final_weak",
    "sink_ceiling",
    "weak_write",
    "final_langs",
    "final_compressed",
    "final_table2",
    "cross_format",
    "compressed_h2h",
    "final_con_h2h",
    "final_db",
    "final_fidelity",
    "compressed_write_memory",
    "plugin_rss",
    "mw_persistence",
    "hop_barrier",
    "eon_loadcons",
    "reader_exchange",
    "roofline",
    "final_check",
    "million_measure",
    "million_asv",
    "million_record",
    "rerun_million_summary",
    "rerun_cross_1k",
    "rerun_cross_100k",
    "rerun_cross_1m",
    "rerun_cross_1m_mmcif",
    "rerun_cross_traj",
    "rerun_cross_extra",
    "rerun_cross_asv",
    "rerun_cross_lscpu",
    "rerun_mpi_cost",
    "rerun_mpi_fallback",
    "rerun_reader_exchange_cpc",
    "rerun_dlpack_cost",
    "rerun_db_appendix",
    "rerun_novel_fidelity",
    "rerun_camp24_extras",
    "rerun_gil_threadfix",
    "rerun_parse_limiter",
    "rerun_supersede",
    "rerun_paper",
    "rerun_release",
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Rohit Goswami",
    "GIT_AUTHOR_EMAIL": "rgoswami@ieee.org",
    "GIT_COMMITTER_NAME": "Rohit Goswami",
    "GIT_COMMITTER_EMAIL": "rgoswami@ieee.org",
}


def _snakemake_exe() -> str:
    found = shutil.which("snakemake")
    if found is not None:
        return found
    sibling = Path(sys.executable).with_name("snakemake")
    assert sibling.is_file(), f"snakemake not found beside {sys.executable}"
    return str(sibling)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _sync_uncommitted(src: Path, dst: Path) -> None:
    status = _git(src, "status", "--porcelain")
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        rel = line[3:].split(" -> ")[-1]
        target = dst / rel
        if "D" in code:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)


def _isolated_clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    done = subprocess.run(
        ["git", "clone", "--shared", "--quiet", str(ROOT), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    _sync_uncommitted(ROOT, repo)
    if _git(repo, "status", "--porcelain").stdout.strip():
        add = _git(repo, "add", "-A")
        assert add.returncode == 0, add.stderr
        commit = _git(
            repo,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "test: stage candidate changes",
        )
        assert commit.returncode == 0, commit.stderr
    # Simulate HEAD existing on origin for the clean pushed dry-run case.
    upd = _git(repo, "update-ref", "refs/remotes/origin/release-test", "HEAD")
    assert upd.returncode == 0, upd.stderr
    return repo


def _run_snakemake_dry(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _snakemake_exe(),
            "-n",
            "-s",
            "bench/h2h/Snakefile",
            "--cores",
            "1",
            "rerun_release",
            *extra,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_rerun_release_dry_run_resolves_all_campaigns_and_refuses_unpushed(
    tmp_path: Path,
) -> None:
    """``snakemake -n rerun_release`` resolves every campaign when clean+remote and refuses unpushed/dirty/saved."""
    repo = _isolated_clean_repo(tmp_path)

    # 1. Clean + contained on remote branch -> dry-run resolves every campaign rule
    # and targets only new versioned directories (never saved records).
    ok = _run_snakemake_dry(repo)
    output = ok.stdout + ok.stderr
    assert ok.returncode == 0, output
    missing = [rule for rule in EXPECTED_RULES if rule not in output]
    assert not missing, f"missing rules in dry-run plan: {missing}\n{output}"
    for saved in (
        "bench/h2h/scaling/rel1/",
        "bench/h2h/formats/v0.23.3/",
        "bench/h2h/million/v0.23.3/",
        "paper/cpc/bench/results/v0.23.3/",
        "paper/cpc/logs/",
        "paper/cpc/data/db/",
        "paper/cpc/data/novel/",
    ):
        assert saved not in output, f"dry-run plan touched saved dir {saved}:\n{output}"

    # 2. Saved directory override or < 6 repeats is refused.
    bad_repeats = _run_snakemake_dry(repo, "--config", "repeats=5")
    assert bad_repeats.returncode != 0
    assert "repeats" in (bad_repeats.stdout + bad_repeats.stderr)

    bad_out = _run_snakemake_dry(repo, "--config", "out=bench/h2h/scaling/rel1")
    assert bad_out.returncode != 0
    assert "saved record" in (bad_out.stdout + bad_out.stderr)

    bad_fmt = _run_snakemake_dry(
        repo, "--config", "formats_out=bench/h2h/formats/v0.23.3"
    )
    assert bad_fmt.returncode != 0
    assert "saved record" in (bad_fmt.stdout + bad_fmt.stderr)

    # 3. Dirty working tree is refused even when HEAD is on a remote branch.
    readme = repo / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    dirty = _run_snakemake_dry(repo)
    assert dirty.returncode != 0
    assert "dirty tree" in (dirty.stdout + dirty.stderr)
    _git(repo, "checkout", "--", "README.md")

    # 4. Unpushed commit (not contained on any remote branch) is refused.
    unpushed_commit = _git(
        repo,
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-m",
        "test: unpushed commit",
    )
    assert unpushed_commit.returncode == 0, unpushed_commit.stderr
    unpushed = _run_snakemake_dry(repo)
    assert unpushed.returncode != 0
    assert "not on any remote branch" in (unpushed.stdout + unpushed.stderr)


def test_rerun_release_refuses_an_untracked_file(tmp_path: Path) -> None:
    """An untracked campaign file is a dirty tree, not an invisible one."""
    repo = _isolated_clean_repo(tmp_path)
    (repo / "campaign-untracked.txt").write_text("not a record\n", encoding="utf-8")
    refused = _run_snakemake_dry(repo)
    output = refused.stdout + refused.stderr
    assert refused.returncode != 0, output
    assert "dirty tree" in output
    assert "campaign-untracked.txt" in output


def test_rerun_drivers_enforce_minimum_repeats_and_perf(tmp_path: Path) -> None:
    """New campaign drivers enforce repeats >= 6 and refuse missing perf."""
    gil = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "h2h" / "gil_threadfix_bench.py"),
            "--out",
            str(tmp_path / "gil"),
            "--repeats",
            "5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gil.returncode != 0
    assert "at least 6" in (gil.stdout + gil.stderr)

    lim = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "h2h" / "parse_limiter.py"),
            "--out",
            str(tmp_path / "lim"),
            "--repeats",
            "5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert lim.returncode != 0
    assert "at least 6" in (lim.stdout + lim.stderr)
