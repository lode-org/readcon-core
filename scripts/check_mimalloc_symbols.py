#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Require every named timed artifact to contain a defined mimalloc symbol."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def defined_mimalloc(path: Path) -> list[str]:
    done = subprocess.run(
        ["nm", "--defined-only", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise SystemExit(f"nm failed for {path}:\n{done.stderr}")
    return [
        line
        for line in done.stdout.splitlines()
        if line.split() and line.split()[-1].startswith("mi_")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.artifacts:
        if not path.is_file():
            raise SystemExit(f"timed artifact is missing: {path}")
        symbols = defined_mimalloc(path)
        if not symbols:
            raise SystemExit(
                f"{path} has no defined mi_ symbol; rebuild it with --features benchmark"
            )
        name = symbols[0].split()[-1]
        print(f"mimalloc-ok {path}: {name}")


if __name__ == "__main__":
    main()
