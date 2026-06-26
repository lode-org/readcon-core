#!/usr/bin/env python3
"""Render docs/source/_generated/cachegrind_results.rst from JSON (optional)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON = ROOT / "docs/source/_generated/cachegrind_results.json"
RST = ROOT / "docs/source/_generated/cachegrind_results.rst"

NOTES = {
    "parse_multi_2x4": "2-frame multi CON",
    "forward_multi_2x4": "forward() line skip",
    "convel_multi": "coords + velocities",
    "parse_100_frames": "synthetic 100× tiny_cuh2",
    "forward_100_frames": "skip mode",
    "parse_cuh2_218": "218-atom frame",
    "float_fast_float2": "5-column fast-float2",
    "float_std_parse": "5-column str::parse",
    "write_100_frames": "buffer writer",
}


def main() -> int:
    if not JSON.is_file():
        print(f"missing {JSON}", file=sys.stderr)
        return 1
    data = json.loads(JSON.read_text())
    scenarios = data.get("scenarios", {})
    lines = [
        ".. cachegrind-results — generated; do not edit by hand.",
        "",
        ".. list-table:: Cachegrind instruction counts (CI-refreshable)",
        "   :header-rows: 1",
        "   :widths: 40 25 35",
        "",
        "   * - Scenario",
        "     - I refs",
        "     - Notes",
    ]
    for name, irefs in scenarios.items():
        note = NOTES.get(name, "")
        lines.append(f"   * - ``{name}``")
        lines.append(f"     - {irefs}")
        lines.append(f"     - {note}")
    lines += [
        "",
        f"Generated **{data.get('generated_at', '?')}** from commit ``{data.get('git_sha', '?')}``.",
        "Metric: Valgrind Cachegrind **I refs** (instruction references).",
        "",
    ]
    RST.parent.mkdir(parents=True, exist_ok=True)
    RST.write_text("\n".join(lines) + "\n")
    print(f"wrote {RST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
