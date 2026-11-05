#!/usr/bin/env python3
"""Rebuild the eOn client and write a repo-relative build log."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logged_cmd import ROOT, redact

LOG = ROOT / "paper" / "cpc" / "logs" / "eon-build.log"
EON = ROOT / "paper" / "cpc" / "bench" / "work" / "peers" / "eon"
BUILD = EON / "build-h2h"


def git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def main() -> int:
    command = [
        "ninja",
        "-C",
        "paper/cpc/bench/work/peers/eon/build-h2h",
        "client/python/_core.abi3.so",
    ]
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    version = "3.6.0"
    project = EON / "pyproject.toml"
    if project.is_file():
        for line in project.read_text(encoding="utf-8").splitlines():
            if line.startswith("version ="):
                version = line.split("=", 1)[1].strip().strip("'\"")
                break
    lines = [
        f"rev_parse {git(['rev-parse', 'HEAD'], ROOT)}",
        f"tree {git(['rev-parse', 'HEAD^{tree}'], ROOT)}",
        "command ninja -C paper/cpc/bench/work/peers/eon/build-h2h client/python/_core.abi3.so",
        f"eon_commit {git(['rev-parse', 'HEAD'], EON)}",
        f"eon_version {version}",
    ]
    for stream in (proc.stdout, proc.stderr):
        for line in stream.splitlines():
            line = redact(line)
            if any(token in line for token in ("/agent", "/tmp", "/home", "/cursor", "~/", "_home_")):
                continue
            lines.append(line)
    lines.append(f"exit_code {proc.returncode}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proc.returncode


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
