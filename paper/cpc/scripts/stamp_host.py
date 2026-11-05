#!/usr/bin/env python3
"""Rewrite stored host names with provenance.host().

The kernel string is read once. Every cpu_model field and every copy of
that kernel string is replaced with the name the writers now record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from provenance import host, normalize_cpu

ROOT = Path(__file__).resolve().parents[1]
RAW = ""
try:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            RAW = line.split(":", 1)[1].strip()
            break
except OSError:
    RAW = ""
CANON = host()["cpu_model"]


def stamp_text(text: str) -> str:
    if RAW:
        text = text.replace(RAW, CANON)
    text = text.replace("Intel(R) Xeon(R) Processor", CANON)
    return text


def stamp_json(node):
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in {"cpu_model", "cpu"} and isinstance(value, str):
                node[key] = normalize_cpu(value)
            else:
                stamp_json(value)
    elif isinstance(node, list):
        for item in node:
            stamp_json(item)


def one(path: Path) -> None:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp_json(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return
    path.write_text(stamp_text(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")


def main() -> int:
    roots = [Path(arg) for arg in sys.argv[1:]] or [
        ROOT / "bench" / "results",
        ROOT / "evidence" / "results",
        ROOT.parents[1] / "benches" / "results",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".csv", ".log", ".txt", ".tsv", ".tex"}:
                blob = path.read_bytes()
                if b"Intel(R)" in blob or (RAW and RAW.encode() in blob):
                    one(path)
                    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
