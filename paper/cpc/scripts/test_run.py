#!/usr/bin/env python3
"""The test run of the paper: the example program of the release reads Listing 1.

Writes

* ``data/test_run.json``, the commands, the toolchain and the printed output;
* ``src/figures/generated/test_run.tex``, the listing of those commands and that output;
* ``src/figures/generated/test_run_macros.tex``, the line the release names when it rejects a cell.

The same program then reads Listing 1 with line 4 replaced by the flat and by the impossible angles
of ``data/worked_example.json``, once as written and once with ``"validate": true`` on line 2.
The record keeps what it printed for each of the four files.

The checkout is a clone of the release commit of ``src/commit.tex`` with this ``paper/cpc`` directory
in it, the layout of the supplementary material.  The run stops unless the checkout is at that commit
and its ``Cargo.toml`` carries the version of ``src/release.tex``.  ``--tables`` writes the listing
from the committed record, after it checks that the record names the commit and the frame of the paper.

    python3 paper/cpc/scripts/test_run.py --checkout DIR --toolchain 1.88.0
    python3 paper/cpc/scripts/test_run.py --tables
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "src" / "figures" / "generated"
FRAME = GENERATED / "survey_frame.con"
COMMIT = ROOT / "src" / "commit.tex"
RELEASE = ROOT / "src" / "release.tex"
WORKED = ROOT / "data" / "worked_example.json"
RECORD = ROOT / "data" / "test_run.json"
OUT = GENERATED / "test_run.tex"
MACROS = GENERATED / "test_run_macros.tex"
INPUT = "paper/cpc/src/figures/generated/survey_frame.con"
CELL_DIR = "target/paper-test-run"
EXAMPLE = "rust_usage"
SHORT = 8
ANGLE_LINE = 4
JSON_LINE = 2
FAILED = re.compile(r"Failed to parse frame: (.*)")
AT_LINE = re.compile(r"AtLine \{ line: (\d+),")


def commit() -> str:
    return re.search(r"\\newcommand\{\\readconcommit\}\{([0-9a-f]{40})\}", COMMIT.read_text()).group(1)


def version() -> str:
    return re.search(r"\\newcommand\{\\readconversion\}\{([0-9.]+)\}", RELEASE.read_text()).group(1)


def frame_sha() -> str:
    return hashlib.sha256(FRAME.read_bytes()).hexdigest()


def commands(sha: str) -> list[str]:
    return [
        "git clone readcon-core.bundle readcon-core",
        "cd readcon-core",
        f"git checkout {sha[:SHORT]}",
        "tar -xzf ../paper-cpc.tar.gz",
        f"cargo run --release --locked --example {EXAMPLE} -- {INPUT}",
    ]


def cell_text(angles: list[float], validate: bool) -> str:
    lines = FRAME.read_text().split("\n")
    lines[ANGLE_LINE - 1] = " ".join(f"{a:g}" for a in angles)
    if validate:
        meta = json.loads(lines[JSON_LINE - 1])
        meta["validate"] = True
        lines[JSON_LINE - 1] = json.dumps(meta, separators=(",", ":"))
    return "\n".join(lines)


def cell_runs(checkout: Path, example: list[str]) -> dict:
    worked = json.loads(WORKED.read_text())
    (checkout / CELL_DIR).mkdir(parents=True, exist_ok=True)
    runs = {}
    for name in ("flat", "none"):
        for validate in (False, True):
            rel = f"{CELL_DIR}/{name}{'_validate' if validate else ''}.con"
            (checkout / rel).write_text(cell_text(worked[name]["angles"], validate))
            done = subprocess.run([*example, rel], cwd=checkout, capture_output=True, text=True)
            failed = FAILED.search(done.stderr)
            at = AT_LINE.search(failed.group(1)) if failed else None
            runs[f"{name}{'_validate' if validate else ''}"] = {
                "angles": worked[name]["angles"],
                "validate": validate,
                "input": rel,
                "exit": done.returncode,
                "stdout": done.stdout,
                "error": failed.group(1) if failed else None,
                "line": int(at.group(1)) if at else None,
            }
    return runs


def run(checkout: Path, toolchain: str) -> dict:
    sha = commit()
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != sha:
        raise SystemExit(f"checkout is at {head}, not at the commit of src/commit.tex")
    cargo_version = re.search(r'^version = "([^"]+)"', (checkout / "Cargo.toml").read_text(), re.M).group(1)
    if cargo_version != version():
        raise SystemExit(f"Cargo.toml says {cargo_version}, src/release.tex says {version()}")
    if (checkout / INPUT).read_bytes() != FRAME.read_bytes():
        raise SystemExit(f"{INPUT} in the checkout is not the frame of this paper")
    plus = [f"+{toolchain}"] if toolchain else []
    tool = lambda *args: subprocess.run(list(args), cwd=checkout, capture_output=True, text=True,
                                        check=True).stdout.strip()
    example = ["cargo", *plus, "run", "--release", "--locked", "--example", EXAMPLE, "--"]
    done = subprocess.run([*example, INPUT], cwd=checkout, capture_output=True, text=True, check=True)
    return {
        "tree_commit": sha,
        "readcon_version": cargo_version,
        "rustc": tool("rustc", *plus, "--version"),
        "cargo": tool("cargo", *plus, "--version"),
        "commands": commands(sha),
        "input": INPUT,
        "input_sha256": frame_sha(),
        "stdout": done.stdout,
        "cells": cell_runs(checkout, example),
    }


def listing(record: dict) -> str:
    body = ["$ " + line for line in record["commands"]] + record["stdout"].rstrip("\n").split("\n")
    caption = (f"Test run. The example program of readcon-core {record['readcon_version']}, built with "
               f"{record['rustc'].split(' (')[0]}, reads Listing~\\ref{{lst:frame}} and prints its cell, "
               "its counts and its first five atoms with their fixed flags, identifiers and velocities.")
    return ("% Written by paper/cpc/scripts/test_run.py from data/test_run.json.\n"
            "\\begin{lstlisting}[caption={" + caption + "},label={lst:testrun}]\n"
            + "\n".join(body) + "\n\\end{lstlisting}\n")


def macros(record: dict) -> str:
    cells = record["cells"]
    worked = json.loads(WORKED.read_text())
    for name in ("flat", "none"):
        for key in (name, f"{name}_validate"):
            if cells[key]["angles"] != worked[name]["angles"]:
                raise SystemExit(f"data/test_run.json reads other {name} angles than data/worked_example.json")
            if (cells[key]["exit"] == 0) != worked[name]["accepted"]:
                raise SystemExit(f"the release and data/worked_example.json disagree on the {name} cell")
    lines = {cells[key]["line"] for key in ("none", "none_validate")}
    if len(lines) != 1 or None in lines:
        raise SystemExit("the impossible cell is not rejected at one line in both modes")
    return ("% Written by paper/cpc/scripts/test_run.py from data/test_run.json.\n"
            f"\\newcommand{{\\trCellLine}}{{{lines.pop()}}}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkout", type=Path, help="clone of the release commit with this paper/cpc in it")
    ap.add_argument("--toolchain", default="", help="rustup toolchain, for example 1.88.0")
    ap.add_argument("--tables", action="store_true", help="write the listing from the committed record")
    args = ap.parse_args()
    if args.tables:
        record = json.loads(RECORD.read_text())
        if record["tree_commit"] != commit() or record["input_sha256"] != frame_sha():
            raise SystemExit("data/test_run.json names another commit or another frame")
    else:
        if args.checkout is None:
            raise SystemExit("--checkout is required to run the example")
        record = run(args.checkout.resolve(), args.toolchain)
        RECORD.write_text(json.dumps(record, indent=1) + "\n")
    OUT.write_text(listing(record))
    MACROS.write_text(macros(record))
    print(f"wrote {OUT.name} and {MACROS.name}")


if __name__ == "__main__":
    main()
