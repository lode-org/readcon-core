#!/usr/bin/env python3
"""Host files for one million-atom session.

The notes name this machine and this commit. They do not scale another
CPU's table onto these seconds. Release ratios come from the interleaved
A/B in ``ab.json`` (v0.23.0, v0.23.2, and this tree, same file, n=12).
``bench/h2h/scaling/h2h9`` is only read, and only so a caller can still
ask the old peer-factor helpers. Those helpers are not written into the
notes.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
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


def library_commit(root: Path = ROOT) -> str:
    """The newest commit of this checkout that changed the library sources.

    Bench-only commits are not that commit. The campaign records it beside
    the HEAD it was run from.
    """
    found = subprocess.check_output(
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "HEAD",
            "--",
            "src",
            "Cargo.toml",
            "packaging",
        ],
        cwd=root,
        text=True,
    ).strip()
    if len(found) != 40:
        raise SystemExit(f"library commit is not a sha: {found!r}")
    return found


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
        median = row.get("median_s")
        if not isinstance(median, (int, float)):
            continue
        cache = row.get("cache")
        if cache not in ("warm", "create"):
            continue
        key = (row["structure"], row["arm"], row["op"], cache)
        found[key] = row
    return found


def machine_factor(old: dict, new: dict, op: str) -> tuple[float, int]:
    """Peer slowdown between two saved tables. Not used in the notes."""
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


def _ab_index(ab: dict) -> dict[tuple[str, str, str], dict]:
    found = {}
    for row in ab.get("rows", []):
        median = row.get("median_s")
        if not isinstance(median, (int, float)):
            continue
        found[(row["build"], row["format"], row["op"])] = row
    return found


def release_ratios(ab: dict) -> list[str]:
    """head/release for each format and op. Same file, same host."""
    indexed = _ab_index(ab)
    lines = []
    for fmt in ("con", "con.gz"):
        for op in ("read", "write"):
            head = indexed.get(("head", fmt, op))
            if head is None:
                continue
            parts = [
                f"{fmt} {op} head {_fmt(head['median_s'])} iqr {_fmt(head['iqr_s'])}"
            ]
            for release in ("v0.23.0", "v0.23.2"):
                other = indexed.get((release, fmt, op))
                if other is None or not other["median_s"]:
                    continue
                ratio = float(head["median_s"]) / float(other["median_s"])
                parts.append(f"{release} {_fmt(other['median_s'])} ratio {ratio:.3f}")
            lines.append(" ".join(parts))
    return lines


def release_flags(ab: dict) -> list[str]:
    """A head row that is slower than a release by more than its own IQR."""
    indexed = _ab_index(ab)
    flags = []
    for fmt in ("con", "con.gz"):
        for op in ("read", "write"):
            head = indexed.get(("head", fmt, op))
            if head is None:
                continue
            for release in ("v0.23.0", "v0.23.2"):
                other = indexed.get((release, fmt, op))
                if other is None:
                    continue
                gap = float(head["median_s"]) - float(other["median_s"])
                if gap > float(head.get("iqr_s") or 0.0):
                    flags.append(
                        f"{fmt} {op} {head['median_s']:.4g}s vs {release} "
                        f"{other['median_s']:.4g}s ({gap:.4g}s above, "
                        f"IQR {float(head.get('iqr_s') or 0.0):.4g}s)"
                    )
    return flags


def render_notes(doc: dict, flags: list[str], ab: dict | None = None) -> str:
    host = doc["host"]
    ops = []
    for row in doc["rows"]:
        if row.get("op") in ("read", "write") and row["op"] not in ops:
            if isinstance(row.get("median_s"), (int, float)):
                ops.append(row["op"])
    lines = [
        "Million-atom "
        + " and ".join(f"{op}s" for op in ops)
        + ", one machine, one commit.",
        f"commit {doc['commit']}",
        "measured readcon " + str(doc.get("versions", {}).get("readcon", "")),
        f"protocol warmup {doc['warmup']} samples {doc['repeats']} "
        f"{doc['percentile']} serial fresh-process rotate {doc['affinity']}",
        f"versions {json.dumps(doc['versions'], sort_keys=True)}",
        f"cpu_mhz {host.get('cpu_mhz')} loadavg {host.get('loadavg')}",
        "Seconds are this host only. bench/h2h/scaling/h2h9 was not modified and "
        "is not used to scale these rows.",
        "",
        "This table times read_con(n_threads=1) plus NumPy copies of positions, "
        "the cell, and masses, on the alloy file that stores velocities and "
        "constraints. camp18 times read_positions on "
        "bench/h2h/work/inputs/con-1000000x1.con, the column slab. Those are "
        "different operations and different files.",
        "",
        "Same-host release comparison. v0.23.0, v0.23.2 at 8c2d9984, and this "
        "tree alternate on one file, n=12, one warmup. The timed read is the "
        "same read_con plus NumPy copies. Ratios are head/release.",
    ]
    if ab is None:
        lines.append("No ab.json was recorded for this directory.")
    else:
        lines.extend(release_ratios(ab))
    lines.extend(
        [
            "",
            "readcon rows. median and IQR are seconds. RSS and file size are bytes. "
            "loses is what that arm's round trip did not keep.",
            "arm op cache median iqr rss file loses",
        ]
    )
    for row in doc["rows"]:
        if row.get("tool") != "readcon" or row.get("structure") != STRUCTURE:
            continue
        if row.get("cache") not in ("warm", "create", "cold"):
            continue
        lines.append(
            " ".join(
                [
                    str(row.get("arm")),
                    str(row.get("op")),
                    str(row.get("cache")),
                    _fmt(row.get("median_s")),
                    _fmt(row.get("iqr_s")),
                    _fmt(row.get("rss_bytes")),
                    _fmt(row.get("file_bytes")),
                    str(row.get("loses")),
                ]
            )
        )
    lines.append("")
    if flags:
        lines.append("Same-host rows slower than a release by more than the head IQR:")
        lines.extend(flags)
    elif ab is None:
        lines.append("Release ratios were not recorded in this directory.")
    else:
        lines.append(
            "No same-host readcon row is slower than v0.23.0 or v0.23.2 by more "
            "than its own IQR."
        )
    lines.append("")
    lines.append(
        "CON plain, gzip, and zstd keep masses, velocities, constraints, and "
        "the text precision. Extended XYZ is the other text format in this "
        "table that keeps those fields. The loses column is the audit for "
        "that arm, including CON-bin. A faster row whose loses list is not "
        "none dropped mass, velocity, constraints, the cell, or precision, "
        "and it is not the same file."
    )
    lines.append("")
    lines.append(
        "gzip_into inflates a member straight into the caller's slice. "
        "The other gzip change is decode_thread_budget: a budget of 1 skips "
        "the indexed path and uses MultiGzDecoder on the calling thread. "
        "This harness calls read_con with n_threads=1 and does not pass "
        "decode_threads, so the indexed path still calls gzip_into. The two "
        "meet only when a caller sets the decode budget to 1."
    )
    lines.append("")
    return "\n".join(lines)


def cpu_model_name(lscpu: str) -> str:
    for line in lscpu.splitlines():
        if line.startswith("Model name:"):
            return line.split(":", 1)[1].strip()
    return ""


def disk_filesystem(root: Path) -> str:
    """`stat -f -c %T` of the directory the disk rows actually use."""
    found = subprocess.run(
        ["stat", "-f", "-c", "%T", str(root)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not found:
        raise SystemExit(f"no filesystem type for {root}")
    return found


def tree_hash(root: Path = ROOT) -> str:
    found = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        text=True,
    ).strip()
    if len(found) != 40:
        raise SystemExit(f"tree is not a sha: {found!r}")
    return found


def write_record(out: Path, doc: dict, notes: str, library: str | None = None) -> None:
    fresh_output(out)
    host = dict(doc["host"])
    disk = BENCH / "work" / "cross-format"
    disk.mkdir(parents=True, exist_ok=True)
    host["tree"] = tree_hash()
    host["cpu_model"] = cpu_model_name(host.get("lscpu") or "")
    host["disk"] = str(disk)
    host["disk_filesystem"] = disk_filesystem(disk)
    payload = {
        "commit": doc["commit"],
        "tree": host["tree"],
        "library_commit": library,
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
    notes = (
        notes.rstrip()
        + "\n\n"
        + f"disk {disk} filesystem {host['disk_filesystem']} (stat -f -c %T). "
        + f"cpu_model {host['cpu_model']}. tree {host['tree']}.\n"
    )
    (out / "NOTES.txt").write_text(notes, encoding="utf-8")
    if library:
        (out / "library-commit.txt").write_text(library + "\n", encoding="utf-8")


def build_notes(doc: dict, ab: dict | None = None) -> tuple[str, list[str]]:
    new = index_rows(doc)
    if not new:
        raise SystemExit("the campaign has no timed rows")
    flags = release_flags(ab) if ab else []
    return render_notes(doc, flags, ab), flags


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    fresh_output(args.out, args.baseline)
    doc = json.loads((args.out / "cross-format.json").read_text(encoding="utf-8"))
    if doc.get("repeats") != 12 or doc.get("warmup") != 1:
        raise SystemExit(
            f"campaign protocol is not warmup 1 n=12: {doc.get('repeats')}"
        )
    ab_path = args.out / "ab.json"
    ab = json.loads(ab_path.read_text(encoding="utf-8")) if ab_path.is_file() else None
    notes, flags = build_notes(doc, ab)
    library = library_commit(ROOT)
    notes = f"library_commit {library}\n" + notes
    write_record(args.out, doc, notes, library)
    print(notes, end="")
    if flags:
        print(f"regressions {len(flags)}", file=sys.stderr)


if __name__ == "__main__":
    main()
