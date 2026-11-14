#!/usr/bin/env python3
"""Write the memory comparison table with commit SHAs as column labels.

asv compare --format=latex decorates each column with the branch name it
saw at run time. This script keeps the table and labels each side by the
commit SHA passed on the command line.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="base commit SHA")
    parser.add_argument("after", help="head commit SHA")
    parser.add_argument("--config", default="asv.mem.conf.json")
    parser.add_argument("--machine", default="pr-bench")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/records/memory-compare.tex"),
    )
    parser.add_argument("--asv", default=shutil.which("asv") or "asv")
    args = parser.parse_args(argv)
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
            args.config,
            "--split",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode or 1)
    table = _rewrite(proc.stdout, args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
