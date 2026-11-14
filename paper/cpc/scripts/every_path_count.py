#!/usr/bin/env python3
"""Count the inputs that the library's tests read on every reader path.

Each test file of the library that declares ``mod every_path;`` reads its
inputs through tests/every_path/mod.rs: the string and byte iterators, the
stream reader over bytes at a read of 1 byte, at the least integer above 1
that is coprime to the input length, and at 1 MiB, and over each file, the
frame lists from a string and from bytes, plain, gzip and zstd files, the
column readers including the streamed one, the frame count and the frame
index behind ConTrajectory, at 1, 2 and 8 threads and the default. Each input
is read as given and behind enough legal frames to reach the mapping
threshold (MMAP_THRESHOLD of src/compression.rs).

This script runs each of those test files with the zstd and parallel features
and EVERY_PATH_LOG set, so every input that passed every path logs one line
as given and one padded, with its size, its thread settings and its files.
The tests of a file run on one test thread, so the two lines of an input are
adjacent in the log.  It fails unless every test passes and every input was
read at four thread settings from three files.

    python paper/cpc/scripts/every_path_count.py            # writes data/every_path.json
    python paper/cpc/scripts/every_path_count.py --check    # compares a rerun with that file
    python paper/cpc/scripts/every_path_count.py --tables   # rewrites the TeX from that file only

The tests build in target/every_path, so the libraries other scripts load stay
as they are.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import provenance


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


ROOT = Path(__file__).resolve().parents[1]
REPO = provenance.REPO
OUT = ROOT / "data" / "every_path.json"
MACROS = ROOT / "src" / "figures" / "generated" / "every_path_macros.tex"
TARGET = REPO / "target" / "every_path"
FEATURES = ("zstd", "parallel")


THREAD_SETTINGS = 4
FILES = 3
RESULT = re.compile(
    r"^test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored", re.M
)


def test_files() -> list[str]:
    return sorted(
        path.stem
        for path in (REPO / "tests").glob("*.rs")
        if re.search(r"^mod every_path;", path.read_text(), re.M)
    )


def command(name: str) -> list[str]:
    return [
        "cargo",
        "test",
        "--release",
        "--features",
        ",".join(FEATURES),
        "--test",
        name,
        "--",
        "--test-threads=1",
    ]


def run(name: str, log: Path) -> dict:
    env = {**os.environ, "CARGO_TARGET_DIR": str(TARGET), "EVERY_PATH_LOG": str(log)}
    proc = subprocess.run(
        command(name), cwd=REPO, env=env, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-20:])
        raise SystemExit(
            f"{' '.join(command(name))} ended with exit status {proc.returncode}:\n{tail}"
        )
    results = RESULT.findall(proc.stdout)
    if not results or any(
        status != "ok" or int(failed) for status, _, failed, _ in results
    ):
        raise SystemExit(f"tests/{name}.rs: no passing test result in the cargo output")
    reads = (
        [
            tuple(int(field) for field in line.split())
            for line in log.read_text().splitlines()
        ]
        if log.is_file()
        else []
    )
    if not reads:
        raise SystemExit(
            f"tests/{name}.rs logged no input; does tests/every_path/mod.rs read EVERY_PATH_LOG?"
        )
    if len(reads) % 2:
        raise SystemExit(
            f"tests/{name}.rs logged {len(reads)} reads; each input logs two"
        )
    odd = [read for read in reads if read[1:] != (THREAD_SETTINGS, FILES)]
    if odd:
        raise SystemExit(
            f"tests/{name}.rs read {len(odd)} inputs at other thread settings or files: {odd[:3]}"
        )
    inputs = len(reads) // 2
    pairs = list(zip(reads[0::2], reads[1::2]))
    padded = sum(pad[0] >= given[0] for given, pad in pairs)
    if padded < inputs:
        raise SystemExit(
            f"tests/{name}.rs logged {padded} padded reads at least as long as the given read, for {inputs} inputs"
        )
    return {
        "tests": sum(int(passed) for _, passed, _, _ in results),
        "ignored": sum(int(ignored) for _, _, _, ignored in results),
        "inputs": inputs,
        "reads": len(reads),
        "reads_from_64k": padded,
        "given_from_64k": padded - inputs,
    }


def toolchain() -> dict:
    def version(tool: str) -> str | None:
        try:
            out = subprocess.run(
                [tool, "--version"], capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
        return out.removeprefix(f"{tool} ")

    return {"cargo": version("cargo"), "rustc": version("rustc")}


def measure() -> dict:
    names = test_files()
    if not names:
        raise SystemExit("no test file declares mod every_path")
    with bench_scratch("scratch") as tmp:
        per_file = {
            f"tests/{name}.rs": run(name, Path(tmp) / f"{name}.log") for name in names
        }
    totals = {
        key: sum(row[key] for row in per_file.values())
        for key in (
            "tests",
            "ignored",
            "inputs",
            "reads",
            "reads_from_64k",
            "given_from_64k",
        )
    }
    totals["test_files"] = len(per_file)
    return {
        "command": " ".join(command("<file>")),
        "features": list(FEATURES),
        "map_bytes": None,
        "thread_settings": ["1", "2", "8", "default"],
        "files": ["plain", "gzip", "zstd"],
        "results": {"totals": totals, "test_files": per_file},
        "provenance": {
            "build": {
                "readcon_version": provenance.library_version(),
                **toolchain(),
                **provenance.source_identity(),
            },
            "host": provenance.host(),
        },
    }


def macros(results: dict) -> str:
    t = results["totals"]
    values = {
        "everyPathInputs": f"{t['inputs']:,}",
        "everyPathTestFiles": t["test_files"],
        "everyPathTests": t["tests"],
        "everyPathReads": f"{t['reads']:,}",
    }
    return (
        "% Written by paper/cpc/scripts/every_path_count.py from data/every_path.json.\n"
        + "".join(
            f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=OUT, help="record (default: %(default)s)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare a rerun with --out instead of writing it",
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="rewrite the TeX from --out only; run nothing",
    )
    args = parser.parse_args()
    if args.tables:
        MACROS.write_text(macros(json.loads(args.out.read_text())["results"]))
        print(f"wrote {MACROS} from {args.out}")
        return 0
    record = measure()
    t = record["results"]["totals"]
    print(
        f"every path: {t['inputs']} inputs from {t['test_files']} test files ({t['tests']} tests), "
        f"each read as given and padded to the mapping threshold at {THREAD_SETTINGS} thread settings from {FILES} files"
    )
    if args.check:
        stored = json.loads(args.out.read_text())
        same = (
            stored["results"] == record["results"]
            and stored["provenance"]["build"]["library_digest"]
            == record["provenance"]["build"]["library_digest"]
        )
        if not same:
            print(f"{args.out} differs from this run", file=sys.stderr)
            return 1
        if not MACROS.is_file() or MACROS.read_text() != macros(stored["results"]):
            print(f"{MACROS} differs from {args.out}", file=sys.stderr)
            return 1
        print(f"{args.out} and {MACROS.name} match this run")
        return 0
    args.out.write_text(json.dumps(record, indent=1) + "\n")
    MACROS.write_text(macros(record["results"]))
    print(f"wrote {args.out} and {MACROS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
