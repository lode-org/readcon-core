#!/usr/bin/env python3
"""Fail when a commit after BASE deletes a line of a stored record.

    python3 paper/cpc/scripts/record_history.py BASE

The directories are paper/cpc/data, paper/cpc/logs and paper/cpc/bench/results.
A later record supersedes an earlier one by adding a file. This script does
not rewrite a commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PREFIXES = (
    "paper/cpc/data/",
    "paper/cpc/logs/",
    "paper/cpc/bench/results/",
)
# The versioned coverage file is the recount of the sources. Replacing it records
# the current tests. The superseded clause_coverage.json stays byte-identical.
RECOUNT = "paper/cpc/data/spec/clause_coverage-"
# The figure-step open list. It is rewritten when the figures are regenerated.
FIGURE_READS = "paper/cpc/data/figure_reads.json"


def deleted_lines(text: str) -> list[str]:
    """Commits in a ``git log --numstat`` transcript that delete record lines."""
    bad = []
    commit = ""
    for line in text.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        removed, path = parts[1], parts[2]
        if not removed.isdigit() or int(removed) == 0:
            continue
        if path == FIGURE_READS or path.startswith(RECOUNT):
            continue
        if any(path.startswith(prefix) for prefix in PREFIXES):
            bad.append(f"{commit} deletes {removed} lines of {path}")
    return bad


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: record_history.py BASE", file=sys.stderr)
        return 2
    done = subprocess.run(
        [
            "git",
            "log",
            "--format=commit %H",
            "--numstat",
            f"{sys.argv[1]}..HEAD",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        print(done.stderr.strip(), file=sys.stderr)
        return done.returncode
    bad = deleted_lines(done.stdout)
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
