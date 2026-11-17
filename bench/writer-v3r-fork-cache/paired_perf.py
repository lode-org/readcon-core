#!/usr/bin/env python3
"""Run the pinned writer-v3 harness for the fork-safe cache rebase."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    harness = (
        Path(__file__).resolve().parents[1]
        / "writer-v3-atomic-cache"
        / "paired_perf.py"
    )
    runpy.run_path(harness, run_name="__main__")
