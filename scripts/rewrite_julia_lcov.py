#!/usr/bin/env python3
"""Rewrite Coverage.jl LCOV SF: paths to absolute paths under the repo.

Coverage.jl emits package-relative paths (src/wrapper.jl). Codecov flag
paths are julia/ReadCon/src/**, so map SF records to absolute workspace paths.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="lcov.info from Coverage.jl")
    p.add_argument("output", help="rewritten LCOV path")
    p.add_argument(
        "--package-root",
        required=True,
        help="absolute path to julia/ReadCon (used for relative SF: joins)",
    )
    args = p.parse_args()
    prefix = os.path.abspath(args.package_root) + os.sep
    fixed: list[str] = []
    for line in open(args.input, encoding="utf-8", errors="replace"):
        if line.startswith("SF:"):
            path = line[3:].strip()
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(prefix, path))
            fixed.append(f"SF:{path}\n")
        else:
            fixed.append(line)
    text = "".join(fixed)
    if "SF:" not in text:
        print("ERROR: no SF: records in Julia LCOV", file=sys.stderr)
        return 1
    open(args.output, "w", encoding="utf-8").write(text)
    hits = tot = 0
    for line in fixed:
        if line.startswith("DA:"):
            h = int(line.split(":")[1].split(",")[1])
            tot += 1
            if h > 0:
                hits += 1
    pct = 100 * hits / tot if tot else 0.0
    print(f"julia lcov {pct:.1f}% {hits}/{tot} -> {args.output}")
    if tot == 0:
        print("ERROR: empty Julia LCOV (no DA records)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
