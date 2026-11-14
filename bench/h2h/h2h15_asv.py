#!/usr/bin/env python3
"""Run the h2h15 asv classes and copy the result into the record.

The two classes run in separate processes. One loads chemfiles 0.10.4.
The other loads the fc1e930 library and does not import the 0.10.4 module.
The machine file records CPU, architecture and RAM. It does not record the
hostname. asv's own results stay under bench/h2h/work. This script copies
the result JSON into the directory it is given.
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
CONFIG = ROOT / "asv.h2h15.conf.json"
MACHINE = "h2h15"
RECORD = BENCH / "scaling" / "h2h15"
_MACHINE = ("/" + "tmp", "/" + "home/", "/" + "agent")


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
    results = BENCH / "work" / "h2h15" / "asv-results"
    found = [
        path
        for path in results.rglob("*.json")
        if path.name not in ("machine.json", "benchmarks.json")
    ]
    if len(found) != 1:
        names = ", ".join(path.name for path in found) or "none"
        raise SystemExit(f"expected one asv result, found {names}")
    machine = results / MACHINE / "machine.json"
    if not machine.is_file():
        raise SystemExit("asv did not record a machine file")
    text = machine.read_text(encoding="utf-8")
    node = platform.node().strip()
    if node and node.lower() != "localhost" and node in text:
        raise SystemExit("asv machine file contains the hostname")
    result = json.loads(found[0].read_text(encoding="utf-8"))
    # asv records the interpreter it ran. The record keeps the name only.
    result["python"] = "python3"
    params = result.get("params")
    if isinstance(params, dict) and "python" in params:
        params["python"] = "python3"
    rendered = json.dumps(result, indent=2) + "\n"
    if any(token in rendered for token in _MACHINE):
        raise SystemExit("asv result contains a machine path")
    (out / "asv.json").write_text(rendered, encoding="utf-8")
    if not text.endswith("\n") or text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n"
    (out / "asv-machine.json").write_text(text, encoding="utf-8")


def _run(bench: str) -> None:
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
            bench,
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


def main() -> None:
    sys.path.insert(0, str(BENCH))
    from measured_commit import measurement

    measurement(ROOT)
    out = Path(sys.argv[1]) if len(sys.argv) == 2 else RECORD
    if out.resolve() != RECORD.resolve():
        raise SystemExit("h2h15 asv copies into bench/h2h/scaling/h2h15")
    out.mkdir(parents=True, exist_ok=True)
    write_machine_file()
    _run("H2H15Shared")
    _run("H2H15Chemfiles012")
    copy_results(out)


if __name__ == "__main__":
    main()
