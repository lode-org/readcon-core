#!/usr/bin/env python3
"""Run the million-atom asv class and copy its result next to the table.

asv's existing-environment runner records the commit named by
``--set-commit-hash`` and does not check the tree out again. The machine
name is the campaign id. CPU, architecture, and RAM are recorded. The
hostname is not.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
CONFIG = ROOT / "asv.million.conf.json"
MACHINE = "million-v0232b"


def cpu_description() -> str:
    model_name = "unknown"
    model = "unknown"
    mhz = "unknown"
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            model_name = line.split(":", 1)[1].strip()
        elif line.lower().startswith("model\t") or line.lower().startswith("model "):
            model = line.split(":", 1)[1].strip()
        elif line.lower().startswith("cpu mhz"):
            mhz = line.split(":", 1)[1].strip()
    cores = os.cpu_count() or 1
    return f"{model_name} model {model} at {mhz} MHz ({cores} cores)"


def ram_label() -> str:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                return f"{kib / (1024 * 1024):.1f}GB"
    except (OSError, ValueError, IndexError):
        pass
    return "unspecified"


def write_machine_file() -> None:
    info = {
        "machine": MACHINE,
        "os": "Linux",
        "arch": platform.machine() or "x86_64",
        "cpu": cpu_description(),
        "num_cpu": str(os.cpu_count() or 1),
        "ram": ram_label(),
    }
    path = Path.home() / ".asv-machine.json"
    existing: dict = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    existing["version"] = 1
    existing[MACHINE] = info
    path.write_text(
        json.dumps(existing, indent=4, sort_keys=True) + "\n", encoding="utf-8"
    )


def copy_results(out: Path) -> None:
    results = out / "asv-results"
    found = [
        path
        for path in results.rglob("*.json")
        if path.name != "machine.json" and path.name != "benchmarks.json"
    ]
    if len(found) != 1:
        names = ", ".join(str(path) for path in found) or "none"
        raise SystemExit(f"expected one asv result, found {names}")
    machine = results / MACHINE / "machine.json"
    if not machine.is_file():
        raise SystemExit(f"asv did not record {machine}")
    text = machine.read_text(encoding="utf-8")
    node = platform.node().strip()
    if node and node.lower() != "localhost" and node in text:
        raise SystemExit("asv machine file contains the hostname")
    (out / "asv.json").write_text(
        found[0].read_text(encoding="utf-8"), encoding="utf-8"
    )
    (out / "asv-machine.json").write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: million_asv.py OUT")
    out = Path(sys.argv[1])
    if "scaling" in out.parts:
        raise SystemExit(f"refusing to write a saved record: {out}")
    out.mkdir(parents=True, exist_ok=True)
    write_machine_file()
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "asv",
            "run",
            "--config",
            os.fspath(CONFIG),
            "--machine",
            MACHINE,
            "--set-commit-hash",
            "HEAD",
            "--bench",
            "MillionCon",
            "--record-samples",
            "-a",
            "repeat=12",
            "-a",
            "rounds=1",
            "-a",
            "number=1",
            "-a",
            "warmup_time=0",
        ],
        cwd=ROOT,
    )
    copy_results(out)


if __name__ == "__main__":
    main()
