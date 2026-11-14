#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Write million_hold.json and peers_n1e6.json from one cross-format log.

The log is the raw record of the run (one summary line, then one
``sample`` line per timed call). Nothing is read from
``results/r0174/million``. A row whose IQR is larger than its median is
left out of the published files and named in ``unpublished.txt``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from million_paths import HOLD, PEERS

ATOMS = {"1k": 1_000, "100k": 100_000, "1M": 1_000_000}
READ = re.compile(
    r"^read (?P<cache>\S+) (?P<structure>\S+) (?P<arm>\S+) "
    r"(?P<median>\S+) (?P<iqr>\S+) rss (?P<rss>\d+) bytes (?P<nbytes>\d+) "
    r"loses (?P<loses>.*)$"
)
WRITE = re.compile(
    r"^write (?P<structure>\S+) (?P<arm>\S+) (?P<median>\S+) (?P<iqr>\S+) "
    r"rss (?P<rss>\d+) bytes (?P<nbytes>\d+) loses (?P<loses>.*)$"
)
SAMPLE = re.compile(r"^sample (?P<seconds>\S+)$")
FRAMES = re.compile(
    r"^frames (?P<structure>\S+) n_frames (?P<n_frames>\d+) unique (?P<unique>\d+)$"
)
COMMIT = re.compile(r"^commit (?P<sha>[0-9a-f]{40})$")


def _type7(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        raise ValueError("empty")
    if count == 1:
        return float(ordered[0])
    rank = (count - 1) * quantile
    low = int(rank)
    high = min(low + 1, count - 1)
    frac = rank - low
    return float(ordered[low] * (1.0 - frac) + ordered[high] * frac)


def parse_log(text: str) -> tuple[str, dict[str, dict[str, int]], list[dict]]:
    """Return the commit, frame counts, and timed rows. Samples stay in order."""
    commit = ""
    frames: dict[str, dict[str, int]] = {}
    rows: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("note "):
            current = None
            continue
        found = COMMIT.match(line)
        if found:
            commit = found.group("sha")
            current = None
            continue
        found = FRAMES.match(line)
        if found:
            frames[found.group("structure")] = {
                "n_frames": int(found.group("n_frames")),
                "n_unique_frames": int(found.group("unique")),
            }
            current = None
            continue
        found = SAMPLE.match(line)
        if found and current is not None:
            current["samples_s"].append(float(found.group("seconds")))
            continue
        found = READ.match(line)
        if found:
            current = _row("read", found.group("cache"), found)
            rows.append(current)
            continue
        found = WRITE.match(line)
        if found and found.group("median") != "no":
            current = _row("write", "create", found)
            rows.append(current)
            continue
        current = None
    if not commit:
        raise SystemExit("the log has no commit line")
    return commit, frames, rows


def _row(op: str, cache: str, found: re.Match[str]) -> dict:
    return {
        "op": op,
        "cache": cache,
        "structure": found.group("structure"),
        "arm": found.group("arm"),
        "median_s": float(found.group("median")),
        "iqr_s": float(found.group("iqr")),
        "rss_bytes": int(found.group("rss")),
        "file_bytes": int(found.group("nbytes")),
        "loses": found.group("loses"),
        "samples_s": [],
    }


def _publish(row: dict, frames: dict[str, dict[str, int]]) -> tuple[dict | None, str]:
    """One published record, or a reason to leave the row out."""
    samples = row["samples_s"]
    if len(samples) < 12:
        return None, f"{row['arm']} {row['op']} has {len(samples)} samples"
    info = frames.get(row["structure"])
    if info is None:
        return None, f"{row['structure']} has no frames line"
    median = _type7(samples, 0.5)
    iqr = _type7(samples, 0.75) - _type7(samples, 0.25)
    if median <= 0 or iqr > median:
        return None, (
            f"{row['arm']} {row['op']} {row['cache']} median {median:.4g}s "
            f"IQR {iqr:.4g}s is wider than the median"
        )
    atoms = ATOMS.get(row["structure"])
    if atoms is None:
        return None, f"unknown structure {row['structure']}"
    n_frames = info["n_frames"]
    if info["n_unique_frames"] != n_frames:
        return None, f"{row['structure']} frames are not all distinct"
    return {
        "arm": row["arm"],
        "op": row["op"],
        "cache": row["cache"],
        "threads": 1,
        "frames": n_frames,
        "atoms_per_frame": atoms,
        "atoms": atoms * n_frames,
        "n": len(samples),
        "samples_s": samples,
        "median_s": median,
        "iqr_s": iqr,
        "bytes": row["file_bytes"],
        "rss_bytes": row["rss_bytes"],
        "loses": row["loses"],
    }, ""


def write_release(
    log_path: Path, hold_path: Path = HOLD, peers_path: Path = PEERS
) -> dict:
    """Write the two JSON files. Returns the unpublished reasons."""
    if "r0174" in Path(log_path).parts:
        raise SystemExit("refusing to read the superseded r0174 tree")
    commit, frames, rows = parse_log(log_path.read_text(encoding="utf-8"))
    hold = []
    peers = []
    unpublished = []
    for row in rows:
        if row["op"] == "read" and row["cache"] != "warm":
            continue
        published, reason = _publish(row, frames)
        if published is None:
            unpublished.append(reason)
            continue
        published["commit"] = commit
        if row["arm"].startswith("readcon-"):
            hold.append(published)
        else:
            peers.append(published)
    if not hold or not peers:
        raise SystemExit("the log did not yield both a readcon row and a peer row")
    for path, payload in ((hold_path, hold), (peers_path, peers)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    note = hold_path.parent / "unpublished.txt"
    note.write_text(
        ("\n".join(unpublished) + "\n") if unpublished else "",
        encoding="utf-8",
    )
    return {
        "commit": commit,
        "hold": len(hold),
        "peers": len(peers),
        "unpublished": unpublished,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--hold", type=Path, default=HOLD)
    parser.add_argument("--peers", type=Path, default=PEERS)
    args = parser.parse_args()
    found = write_release(args.log, args.hold, args.peers)
    print(
        f"commit {found['commit']} hold {found['hold']} peers {found['peers']} "
        f"unpublished {len(found['unpublished'])}"
    )


if __name__ == "__main__":
    main()
