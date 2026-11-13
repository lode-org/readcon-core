#!/usr/bin/env python3
"""Shared protocol for the final paper-campaign rerun.

One warmup, then ``n`` serial samples. The median and IQR are type-7
(NumPy ``percentile`` method ``linear``). Writes unlink the destination
before each create. Every campaign file carries the git commit that
produced it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
BINARY_SUFFIXES = {".gz", ".zst", ".pdf", ".png", ".con", ".convel", ".bin"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def head_sha(root: Path | None = None) -> str:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root or repo_root(),
        text=True,
    ).strip()
    if not SHA.fullmatch(sha):
        raise SystemExit(f"HEAD is not a commit sha: {sha}")
    return sha


def protocol(repeats: int) -> dict:
    return {
        "warmup": 1,
        "samples": repeats,
        "percentile": "type7",
        "serial": True,
        "unlink_create": True,
    }


def strong_efficiency(serial_s: float, parallel_s: float, workers: int) -> float:
    """Strong-scaling efficiency, ``(t(1) / t(n)) / n``.

    One worker is 1. A value below 1 means the extra workers did not
    each carry a full share of the single-worker time.
    """
    if workers < 1 or parallel_s <= 0 or serial_s < 0:
        raise SystemExit("efficiency needs a positive parallel time")
    if workers == 1:
        return 1.0
    return (serial_s / parallel_s) / workers


def type7(values: list[float]) -> tuple[float, float]:
    import numpy as np

    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def stamp_text(text: str, sha: str) -> str:
    prefix = f"commit {sha}\n"
    if text.startswith(prefix):
        return text
    if text.startswith("commit ") and SHA.fullmatch(text.split()[1]):
        rest = text.split("\n", 1)[1] if "\n" in text else ""
        return prefix + rest
    return prefix + text


def stamp_file(
    path: Path,
    sha: str,
    repeats: int,
    ceilings: dict | None = None,
) -> None:
    """Record ``sha`` inside ``path``. Binary payloads get a sibling stamp."""
    if path.suffix in BINARY_SUFFIXES:
        path.with_name(path.name + ".commit").write_text(sha + "\n")
        return
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, list):
            data = {"rows": data}
        if not isinstance(data, dict):
            raise SystemExit(f"{path} is not a JSON object or array")
        data["commit"] = sha
        data["protocol"] = protocol(repeats)
        if ceilings is not None:
            data["ceilings"] = ceilings
        path.write_text(json.dumps(data, indent=2) + "\n")
        return
    path.write_text(stamp_text(path.read_text(), sha))


def file_commit(path: Path) -> str | None:
    if path.suffix == ".commit":
        token = path.read_text().strip()
        return token if SHA.fullmatch(token) else None
    if path.suffix in BINARY_SUFFIXES:
        side = path.with_name(path.name + ".commit")
        if not side.is_file():
            return None
        token = side.read_text().strip()
        return token if SHA.fullmatch(token) else None
    text = path.read_text(errors="replace")
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and SHA.fullmatch(str(data.get("commit", ""))):
            return str(data["commit"])
    for line in text.splitlines():
        if line.startswith("commit "):
            token = line.split()[1]
            if SHA.fullmatch(token):
                return token
        if line.startswith("rev_parse "):
            token = line.split()[1]
            if SHA.fullmatch(token):
                return token
    stripped = text.strip()
    if SHA.fullmatch(stripped):
        return stripped
    return None


def check_directory(directory: Path, head: str) -> None:
    """Fail when any file under ``directory`` was produced on another commit.

    The production directory is ``bench/h2h/scaling/rel1``. A smoke rerun
    points the same check at its own output directory.
    """
    if not SHA.fullmatch(head):
        raise SystemExit(f"HEAD is not a commit sha: {head}")
    if not directory.is_dir():
        raise SystemExit(f"missing campaign directory {directory}")
    mismatches: list[str] = []
    files = [path for path in directory.rglob("*") if path.is_file()]
    if not files:
        raise SystemExit(f"{directory} has no campaign outputs")
    for path in sorted(files):
        if path.name == "COMMIT_OK":
            continue
        found = file_commit(path)
        if found != head:
            mismatches.append(f"{path}: {found or 'missing'} != {head}")
    if mismatches:
        raise SystemExit("commit check failed\n" + "\n".join(mismatches))
