#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Build the timed Rust artifacts and require mimalloc in every executable and cdylib."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_mimalloc_symbols import defined_mimalloc


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target" / "timed-allocator-gate"
EXAMPLES = ("cachegrind_harness", "wall_scale_harness", "weak_scale_threads")
BENCHES = ("iterator_bench", "speed_checks", "traj10k", "wide_write")


def cargo(*args: str) -> list[dict]:
    command = [
        "cargo",
        *args,
        "--message-format=json-render-diagnostics",
        "--target-dir",
        str(TARGET),
    ]
    done = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CXX": os.environ.get("CXX", "g++")},
    )
    if done.returncode:
        sys.stderr.write(done.stderr)
        raise SystemExit(f"{' '.join(command)} exited {done.returncode}")
    artifacts = []
    for line in done.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("reason") == "compiler-artifact":
            artifacts.append(message)
    return artifacts


def executable(artifacts: list[dict], name: str) -> Path:
    matches = [
        Path(item["executable"])
        for item in artifacts
        if item["target"]["name"] == name and item.get("executable")
    ]
    if len(matches) != 1:
        raise SystemExit(f"expected one executable for {name}, found {matches}")
    return matches[0]


def require(path: Path) -> None:
    symbols = defined_mimalloc(path)
    if not symbols:
        raise SystemExit(f"{path} has no defined mi_ symbol")
    print(f"mimalloc-ok {path}: {symbols[0].split()[-1]}")


def main() -> None:
    example_args = [
        "build",
        "--locked",
        "--release",
        "--features",
        "parallel,benchmark",
    ]
    for name in EXAMPLES:
        example_args.extend(["--example", name])
    examples = cargo(*example_args)
    paths = [executable(examples, name) for name in EXAMPLES]

    if shutil.which("mpicc"):
        mpi = cargo(
            "build",
            "--locked",
            "--release",
            "--features",
            "mpi,benchmark",
            "--example",
            "weak_scale_mpi",
        )
        paths.append(executable(mpi, "weak_scale_mpi"))
    else:
        print("skip weak_scale_mpi: mpicc is unavailable")

    benches = cargo(
        "bench",
        "--locked",
        "--no-run",
        "--features",
        "parallel,benchmark",
    )
    paths.extend(executable(benches, name) for name in BENCHES)

    library = cargo(
        "build",
        "--locked",
        "--release",
        "--lib",
        "--features",
        "benchmark",
    )
    shared = {
        Path(filename)
        for item in library
        if item["target"]["name"] == "readcon_core"
        for filename in item.get("filenames", [])
        if filename.endswith((".so", ".dylib", ".dll"))
    }
    if len(shared) != 1:
        raise SystemExit(f"expected one readcon shared library, found {sorted(shared)}")
    paths.extend(shared)

    for path in paths:
        require(path)


if __name__ == "__main__":
    main()
