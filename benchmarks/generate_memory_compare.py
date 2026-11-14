#!/usr/bin/env python3
"""Write the memory comparison table with commit SHAs as column labels.

asv compare --format=latex decorates each column with the branch name it
saw at run time. This script keeps the table and labels each side by the
commit SHA passed on the command line.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _rewrite(table: str, before: str, after: str) -> str:
    """Replace asv's short-hash-plus-branch headers with the full SHAs."""

    def label(sha: str) -> str:
        # re.sub treats backslashes in the replacement as escapes.
        return r"\\texttt{" + sha + "}"

    rewritten = table
    for sha in (before, after):
        short = sha[:8]
        rewritten = re.sub(
            r"\\texttt\{" + re.escape(short) + r"\}",
            label(sha),
            rewritten,
        )
    # Drop the branch decoration asv appends after the hash.
    rewritten = re.sub(r"\s*\\texttt\{<[^>]*>\}", "", rewritten)
    return rewritten


def _stage(directory: Path, machine: str, before: Path, after: Path, benchmarks: Path, machine_file: Path) -> None:
    """Lay the committed results out the way asv compare reads them."""
    bench_dir = directory / machine
    bench_dir.mkdir(parents=True)
    shutil.copy(benchmarks, directory / "benchmarks.json")
    shutil.copy(machine_file, bench_dir / "machine.json")
    for path in (before, after):
        data = json.loads(path.read_text(encoding="utf-8"))
        env = data["env_name"]
        sha = data["commit_hash"]
        target = bench_dir / f"{sha[:8]}-{env}.json"
        shutil.copy(path, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="base commit SHA")
    parser.add_argument("after", help="head commit SHA")
    parser.add_argument("--before-json", type=Path, required=True)
    parser.add_argument("--after-json", type=Path, required=True)
    parser.add_argument("--benchmarks", type=Path, required=True)
    parser.add_argument("--machine-json", type=Path, required=True)
    parser.add_argument("--config", default="asv.mem.conf.json")
    parser.add_argument("--machine", default="pr-bench")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/records/memory-compare.tex"),
    )
    parser.add_argument("--asv", default=shutil.which("asv") or "asv")
    args = parser.parse_args(argv)
    stage_root = Path("build") / "bench"
    stage_root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="mem-compare-", dir=stage_root))
    try:
        _stage(staged, args.machine, args.before_json, args.after_json, args.benchmarks, args.machine_json)
        conf = json.loads(Path(args.config).read_text(encoding="utf-8"))
        conf["results_dir"] = str(staged)
        conf["repo"] = str(Path(args.config).resolve().parent)
        conf_path = staged / "asv.conf.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        proc = subprocess.run(
            [
                args.asv,
                "compare",
                args.before,
                args.after,
                "--format=latex",
                "--machine",
                args.machine,
                "--config",
                str(conf_path),
                "--split",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    if proc.returncode not in (0, 1) or r"\begin{tabular}" not in proc.stdout:
        sys.stderr.write(proc.stderr)
        sys.stderr.write(proc.stdout)
        raise SystemExit(proc.returncode or 1)
    table = _rewrite(proc.stdout, args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
