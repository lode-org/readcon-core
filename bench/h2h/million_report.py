#!/usr/bin/env python3
"""Host files and the comparison with the 0.23.0 million-atom rows.

The baseline is ``bench/h2h/scaling/h2h9/cross-format.json`` (readcon
0.23.0). This script only reads that file. The two tables are different
CPUs, so a readcon row is not compared by its raw seconds. Peer rows on
this machine supply a factor for reads and a factor for writes. A readcon
row regresses when it is more than 25% slower than that factor and the
excess is larger than its IQR. It loses a lead when it was faster than a
peer in the baseline, is slower now, and that ratio moved by more than 25%
by more than both IQRs.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
BASELINE = BENCH / "scaling" / "h2h9" / "cross-format.json"
RELATIVE = 1.25
STRUCTURE = "1M"


def type7(values: list[float], quantile: float) -> float:
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


def type7_median(values: list[float]) -> float:
    return type7(values, 0.5)


def fresh_output(out: Path, baseline: Path = BASELINE) -> None:
    target = out.resolve()
    saved = baseline.resolve().parent
    if target == saved or saved in target.parents or "scaling" in target.parts:
        raise SystemExit(f"refusing to write into existing records: {target}")


def index_rows(doc: dict) -> dict[tuple, dict]:
    found = {}
    for row in doc["rows"]:
        if row.get("structure") != STRUCTURE:
            continue
        if row.get("median_s") is None:
            continue
        cache = row.get("cache")
        if cache not in ("warm", "create"):
            continue
        key = (row["structure"], row["arm"], row["op"], cache)
        found[key] = row
    return found


def machine_factor(old: dict, new: dict, op: str) -> tuple[float, int]:
    ratios = []
    for key, old_row in old.items():
        if key[2] != op or old_row.get("tool") == "readcon":
            continue
        new_row = new.get(key)
        if new_row is None:
            continue
        old_median = old_row["median_s"]
        new_median = new_row["median_s"]
        if old_median is None or new_median is None or old_median <= 0:
            continue
        ratios.append(float(new_median) / float(old_median))
    if not ratios:
        raise SystemExit(f"no peer {op} rows to scale the machine")
    return type7_median(ratios), len(ratios)


def self_regressions(old: dict, new: dict, factors: dict[str, float]) -> list[str]:
    messages = []
    for key, old_row in old.items():
        if old_row.get("tool") != "readcon":
            continue
        new_row = new.get(key)
        if new_row is None:
            messages.append(f"missing {key[1]} {key[2]}")
            continue
        factor = factors[key[2]]
        expected = float(old_row["median_s"]) * factor
        actual = float(new_row["median_s"])
        excess = actual - expected
        if actual > expected * RELATIVE and excess > float(new_row.get("iqr_s") or 0.0):
            messages.append(
                f"{key[1]} {key[2]} {actual:.4g}s vs {expected:.4g}s "
                f"expected ({actual / expected:.2f}x the machine factor)"
            )
    return messages


def lost_leads(old: dict, new: dict) -> list[str]:
    messages = []
    readcon_keys = [key for key, row in old.items() if row.get("tool") == "readcon"]
    peer_keys = [key for key, row in old.items() if row.get("tool") != "readcon"]
    for readcon_key in readcon_keys:
        old_readcon = old[readcon_key]
        new_readcon = new.get(readcon_key)
        if new_readcon is None:
            continue
        for peer_key in peer_keys:
            if peer_key[0] != readcon_key[0] or peer_key[2:] != readcon_key[2:]:
                continue
            old_peer = old[peer_key]
            new_peer = new.get(peer_key)
            if new_peer is None:
                continue
            old_ratio = float(old_readcon["median_s"]) / float(old_peer["median_s"])
            new_ratio = float(new_readcon["median_s"]) / float(new_peer["median_s"])
            if old_ratio >= 1.0 or new_ratio <= 1.0:
                continue
            if new_ratio / old_ratio <= RELATIVE:
                continue
            gap = float(new_readcon["median_s"]) - float(new_peer["median_s"])
            noise = float(new_readcon.get("iqr_s") or 0.0) + float(
                new_peer.get("iqr_s") or 0.0
            )
            if gap <= noise:
                continue
            messages.append(
                f"{readcon_key[1]} {readcon_key[2]} lost the lead to {peer_key[1]} "
                f"({old_ratio:.2f}x to {new_ratio:.2f}x)"
            )
    return messages


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def render_notes(
    doc: dict, old: dict, factors: dict, counts: dict, flags: list[str]
) -> str:
    host = doc["host"]
    lines = [
        "Million-atom read and write, one machine.",
        f"commit {doc['commit']}",
        f"protocol warmup {doc['warmup']} samples {doc['repeats']} "
        f"{doc['percentile']} serial fresh-process rotate {doc['affinity']}",
        f"versions {json.dumps(doc['versions'], sort_keys=True)}",
        f"cpu_mhz {host.get('cpu_mhz')} loadavg {host.get('loadavg')}",
        "Baseline is bench/h2h/scaling/h2h9 (readcon 0.23.0, Xeon model 173 at 2700 MHz). "
        "That file was not modified. Raw seconds are not compared across the two CPUs. "
        f"Peer reads on this machine are {factors['read']:.3f}x that record "
        f"({counts['read']} rows). Peer writes are {factors['write']:.3f}x "
        f"({counts['write']} rows).",
        "",
        "readcon rows. median and IQR are seconds. RSS and file size are bytes. "
        "loses is what the format did not round-trip.",
        "arm op median iqr rss file loses adjusted",
    ]
    new = index_rows(doc)
    for key in sorted(new):
        row = new[key]
        if row.get("tool") != "readcon":
            continue
        old_row = old.get(key)
        adjusted = ""
        if old_row is not None and old_row.get("median_s"):
            expected = float(old_row["median_s"]) * factors[key[2]]
            adjusted = f"{float(row['median_s']) / expected:.3f}"
        lines.append(
            " ".join(
                [
                    key[1],
                    key[2],
                    _fmt(row.get("median_s")),
                    _fmt(row.get("iqr_s")),
                    _fmt(row.get("rss_bytes")),
                    _fmt(row.get("file_bytes")),
                    str(row.get("loses")),
                    adjusted,
                ]
            )
        )
    lines.append("")
    if flags:
        lines.append("Regressions against the machine-adjusted 0.23.0 rows:")
        lines.extend(flags)
    else:
        lines.append(
            "No readcon row is more than 25% slower than the machine-adjusted "
            "0.23.0 record, and none lost a lead it held there."
        )
    lines.append("")
    lines.append(
        "CON plain, gzip, and zstd keep masses, velocities, constraints, and "
        "the text precision. Extended XYZ is the other format in this table "
        "that keeps those fields. CON-bin keeps positions and velocities at "
        "float64 and drops masses, constraints, and the cell. PDB, XYZ, DCD, "
        "XTC, NetCDF, TRR, and GRO each drop at least one of mass, velocity, "
        "constraints, the cell, or precision. A faster row that drops those "
        "fields is not the same file."
    )
    lines.append("")
    return "\n".join(lines)


def write_record(out: Path, doc: dict, notes: str) -> None:
    fresh_output(out)
    host = doc["host"]
    payload = {
        "commit": doc["commit"],
        "warmup": doc["warmup"],
        "repeats": doc["repeats"],
        "percentile": doc["percentile"],
        "serial": doc["serial"],
        "process": doc["process"],
        "affinity": doc["affinity"],
        "versions": doc["versions"],
        "host": host,
    }
    text = json.dumps(payload, indent=2) + "\n"
    node = platform.node().strip()
    if node and node.lower() != "localhost" and node in text:
        raise SystemExit("host record contains the hostname")
    (out / "host.json").write_text(text, encoding="utf-8")
    (out / "lscpu.txt").write_text(host.get("lscpu") or "", encoding="utf-8")
    (out / "NOTES.txt").write_text(notes, encoding="utf-8")


def build_notes(doc: dict, baseline_doc: dict) -> tuple[str, list[str]]:
    old = index_rows(baseline_doc)
    new = index_rows(doc)
    factors = {}
    counts = {}
    for op in ("read", "write"):
        factor, count = machine_factor(old, new, op)
        factors[op] = factor
        counts[op] = count
    flags = self_regressions(old, new, factors) + lost_leads(old, new)
    return render_notes(doc, old, factors, counts, flags), flags


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    fresh_output(args.out, args.baseline)
    doc = json.loads((args.out / "cross-format.json").read_text(encoding="utf-8"))
    baseline_doc = json.loads(args.baseline.read_text(encoding="utf-8"))
    if doc.get("repeats") != 12 or doc.get("warmup") != 1:
        raise SystemExit(
            f"campaign protocol is not warmup 1 n=12: {doc.get('repeats')}"
        )
    notes, flags = build_notes(doc, baseline_doc)
    write_record(args.out, doc, notes)
    print(notes, end="")
    if flags:
        print(f"regressions {len(flags)}", file=sys.stderr)


if __name__ == "__main__":
    main()
