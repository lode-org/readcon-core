#!/usr/bin/env python3
"""Run one command and write a log with the revision, the tree and the exit code."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def redact(line: str) -> str:
    """Rewrite home and checkout paths so a log stays inside the tree."""
    home = Path.home()
    user = home.name
    repo = str(ROOT)
    line = line.replace(repo + "/", "")
    line = line.replace(repo, ".")
    line = line.replace(str(home) + "/", "")
    line = line.replace(str(home), ".")
    line = line.replace("~/.local", "")
    line = line.replace("~/", "")
    line = line.replace(f"_home_{user}_.local", "")
    line = line.replace(f"_home_{user}_", "")
    line = re.sub(
        r"\S*site-packages[/_.]nanobind[/_.]",
        "<site-packages>/nanobind/",
        line,
    )
    line = re.sub(r"\S*site-packages/", "<site-packages>/", line)
    line = re.sub(r"\S*site-packages_", "<site-packages>/", line)
    cargo = ROOT / "Cargo.toml"
    if cargo.is_file():
        for row in cargo.read_text(encoding="utf-8").splitlines():
            if row.startswith('version = "'):
                line = line.replace(row.split('"', 2)[1], "<package-version>")
                break
    return line


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: logged_cmd.py LOG command...", file=sys.stderr)
        return 2
    log_path = Path(sys.argv[1])
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    command = sys.argv[2:]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    shown = " ".join(command)
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    lines = [
        f"rev_parse {head}",
        f"tree {tree}",
        f"command {shown}",
    ]
    for stream in (proc.stdout, proc.stderr):
        for line in stream.splitlines():
            line = redact(line)
            if any(token in line for token in ("/agent", "/tmp", "/home", "/cursor", "~/", "_home_")):
                continue
            lines.append(line)
    lines.append(f"exit_code {proc.returncode}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
