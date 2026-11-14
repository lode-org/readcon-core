#!/usr/bin/env python3
"""Compare each fresh-file store with the readcon write."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp10"


def pair(rows: list[dict], **match: object) -> tuple[dict, dict]:
    def pick(workers: int) -> dict:
        for row in rows:
            if row["workers"] == workers and all(
                row.get(key) == value for key, value in match.items()
            ):
                return row
        raise KeyError((match, workers))

    return pick(1), pick(8)


def main() -> None:
    parts = json.loads((OUT / "parts.json").read_text())
    ceiling = parts["ceiling"]
    readcon = parts["readcon"]
    print(
        f"{'fs':12} {'mode':7} {'store':16} {'t1':7} {'t8':7} {'t1/t8':7} {'vs mmap8':8}"
    )
    fastest: dict[tuple[str, str], tuple[str, float]] = {}
    for fs in ("tmpfs", "thp", "ext4", "ext4-fsync"):
        for mode in ("procs", "threads"):
            mmap1, mmap8 = pair(ceiling, filesystem=fs, mode=mode, store="mmap")
            for store in sorted({row["store"] for row in ceiling}):
                try:
                    one, eight = pair(ceiling, filesystem=fs, mode=mode, store=store)
                except KeyError:
                    continue
                eff = one["median_s"] / eight["median_s"] if eight["median_s"] else None
                delta = eight["median_s"] - mmap8["median_s"]
                print(
                    f"{fs:12} {mode:7} {store:16} {one['median_s']:7.4f} "
                    f"{eight['median_s']:7.4f} {eff:7.3f} {delta:8.4f}"
                )
                key = (fs, mode)
                best = fastest.get(key)
                if best is None or eight["median_s"] < best[1]:
                    fastest[key] = (store, eight["median_s"])
    print("fastest at 8 workers:")
    for key, (store, seconds) in fastest.items():
        print(f"  {key[0]} {key[1]} {store} {seconds:.4f}")
    print("readcon weak write efficiency on tmpfs:")
    for kind in ("threads", "ranks"):
        for fmt in ("con", "convel"):
            one, eight = pair(
                readcon, filesystem="tmpfs", kind=kind, op="write", format=fmt
            )
            eff = one["median_s"] / eight["median_s"]
            print(
                f"  {kind} {fmt} t1={one['median_s']:.4f} t8={eight['median_s']:.4f} eff={eff:.3f}"
            )
    finding = (
        "On default tmpfs the fastest 8-worker copy is a plain per-worker mmap. "
        "MADV_HUGEPAGE lands inside that interquartile range. MAP_POPULATE, "
        "MADV_POPULATE_WRITE, fallocate, 1 MiB pwrites, one shared mapping, and a "
        "per-page touch are slower at 8 workers. The copy's weak efficiency is "
        "0.39 for 16 MiB processes and 0.32 for 64 MiB threads, and the readcon "
        "write grows with that copy. fallocate before pwrite is a faster pure "
        "ext4 copy and a slower tmpfs copy; putting it in the writer did not "
        "lower ext4 end-to-end time, so the writer keeps the existing store."
    )
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "finding": finding,
                "fastest_at_8": [
                    {
                        "filesystem": fs,
                        "mode": mode,
                        "store": store,
                        "median_s": seconds,
                    }
                    for (fs, mode), (store, seconds) in fastest.items()
                ],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
