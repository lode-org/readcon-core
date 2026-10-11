#!/usr/bin/env python3
"""Median ratios, BCa intervals, and Holm adjustment for the CPC bench."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.stats import norm

RESULTS = Path(__file__).resolve().parent / "results"
N_BOOT = 9999
SEED = 20261011
ALPHA = 0.05


def _rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def bca_median(samples: np.ndarray, alpha: float = ALPHA) -> tuple[float, float, float]:
    samples = np.asarray(samples, dtype=float)
    n = samples.size
    theta = float(np.median(samples))
    rng = np.random.default_rng(SEED)
    boots = np.empty(N_BOOT, dtype=float)
    for i in range(N_BOOT):
        boots[i] = np.median(rng.choice(samples, size=n, replace=True))
    # Probability of a bootstrap median strictly below the point estimate.
    prop = float(np.mean(boots < theta))
    prop = min(max(prop, 1.0 / (N_BOOT + 1)), 1.0 - 1.0 / (N_BOOT + 1))
    z0 = float(norm.ppf(prop))
    jack = np.array([np.median(np.delete(samples, i)) for i in range(n)])
    jack_mean = float(jack.mean())
    diff = jack_mean - jack
    denom = np.sum(diff**2) ** 1.5
    acc = float(np.sum(diff**3) / (6.0 * denom)) if denom else 0.0

    def level(prob: float) -> float:
        z = float(norm.ppf(prob))
        numer = z0 + z
        denom_z = 1.0 - acc * numer
        if denom_z == 0:
            return float(np.quantile(boots, prob))
        return float(np.quantile(boots, norm.cdf(z0 + numer / denom_z)))

    return theta, level(alpha / 2), level(1 - alpha / 2)


def bootstrap_p(samples: np.ndarray) -> float:
    """Two-sided bootstrap p for H0: median equals 1."""
    samples = np.asarray(samples, dtype=float)
    n = samples.size
    rng = np.random.default_rng(SEED)
    boots = np.empty(N_BOOT, dtype=float)
    for i in range(N_BOOT):
        boots[i] = np.median(rng.choice(samples, size=n, replace=True))
    # Shift samples so the observed median sits at 1, then see how often
    # the bootstrap median is at least as far from 1 as the observation.
    observed = float(np.median(samples))
    null = samples - observed + 1.0
    extreme = 0
    for _ in range(N_BOOT):
        med = float(np.median(rng.choice(null, size=n, replace=True)))
        if abs(med - 1.0) >= abs(observed - 1.0) - 1e-15:
            extreme += 1
    # Plus-one correction so a count of zero is not reported as p = 0.
    return (extreme + 1) / (N_BOOT + 1)


def holm(pvalues: list[float]) -> list[float]:
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[idx]))
        adjusted[idx] = running
    return adjusted


def analyze_ratios() -> None:
    rows = _rows("repeats.csv")
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["payload"], row["peer"]), []).append(row)
    pending = []
    for (payload, peer), group in sorted(groups.items()):
        base = {int(r["repeat"]): r for r in group if r["role"] == "baseline"}
        peer_rows = {int(r["repeat"]): r for r in group if r["role"] == "peer"}
        n_timeout = sum(1 for r in peer_rows.values() if r["status"] == "timeout")
        n_failure = sum(1 for r in peer_rows.values() if r["status"] == "failure")
        n_base_bad = sum(1 for r in base.values() if r["status"] != "ok")
        ratios = []
        peer_times = []
        base_times = []
        for repeat, prow in sorted(peer_rows.items()):
            brow = base.get(repeat)
            if brow is None or brow["status"] != "ok" or prow["status"] != "ok":
                continue
            bt = float(brow["seconds"])
            pt = float(prow["seconds"])
            if bt <= 0 or pt <= 0:
                continue
            base_times.append(bt)
            peer_times.append(pt)
            ratios.append(bt / pt)
        item = {
            "payload": payload,
            "peer": peer,
            "n_pair_ok": len(ratios),
            "n_timeout": n_timeout,
            "n_failure": n_failure,
            "n_baseline_not_ok": n_base_bad,
            "median_readcon_s": "",
            "median_peer_s": "",
            "median_ratio_readcon_over_peer": "",
            "bca_low": "",
            "bca_high": "",
            "p_raw": "",
            "holm_p": "",
            "readcon_faster": "0",
        }
        if len(ratios) >= 2:
            arr = np.array(ratios)
            theta, lo, hi = bca_median(arr)
            p_raw = bootstrap_p(arr)
            item.update(
                {
                    "median_readcon_s": f"{float(np.median(base_times)):.6g}",
                    "median_peer_s": f"{float(np.median(peer_times)):.6g}",
                    "median_ratio_readcon_over_peer": f"{theta:.6g}",
                    "bca_low": f"{lo:.6g}",
                    "bca_high": f"{hi:.6g}",
                    "p_raw": f"{p_raw:.6g}",
                    "_lo": lo,
                    "_hi": hi,
                }
            )
        pending.append(item)
    tested = [item for item in pending if item["p_raw"] != ""]
    adjusted = holm([float(item["p_raw"]) for item in tested]) if tested else []
    for item, adj in zip(tested, adjusted, strict=True):
        item["holm_p"] = f"{adj:.6g}"
        lo = item.pop("_lo")
        hi = item.pop("_hi")
        item.pop("_p", None)
        if adj < ALPHA and hi < 1.0:
            item["readcon_faster"] = "1"
    for item in pending:
        item.pop("_lo", None)
        item.pop("_hi", None)
        item.pop("_p", None)
    _write("ratios.csv", pending)


def analyze_threads() -> None:
    rows = [r for r in _rows("threads.csv") if r["payload"] == "frames-10000"]
    by_threads: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_threads.setdefault(int(row["threads"]), []).append(row)
    hash_rows = [r for r in _rows("threads.csv") if r["payload"] == "frames-10000-hash"]
    hash_set = {r["field_hash"] for r in hash_rows if r["status"] == "ok" and r["field_hash"]}
    identical = len(hash_set) == 1 and bool(hash_set)
    out = []
    # The one-worker point is the reference. Its speedup is 1 by construction.
    baselines = [
        float(r["seconds"])
        for r in rows
        if r.get("role") == "baseline" and r["status"] == "ok" and r["seconds"]
    ]
    t1 = float(np.median(baselines)) if baselines else float("nan")
    out.append(
        {
            "payload": "frames-10000",
            "threads": 1,
            "n_ok": len(baselines),
            "median_s": f"{t1:.6g}" if np.isfinite(t1) else "",
            "speedup": "1",
            "speedup_low": "1",
            "speedup_high": "1",
            "efficiency": "1",
            "hashes_identical_1_2_3_4_8": "yes" if identical else "no",
            "n_distinct_hashes": len(hash_set),
        }
    )
    for threads, group in sorted(by_threads.items()):
        base = {int(r["repeat"]): r for r in group if r.get("role") == "baseline"}
        scaled = {int(r["repeat"]): r for r in group if r.get("role") == "scaled"}
        ratios = []
        scaled_times = []
        for repeat, srow in sorted(scaled.items()):
            brow = base.get(repeat)
            if brow is None or brow["status"] != "ok" or srow["status"] != "ok":
                continue
            bt = float(brow["seconds"])
            st = float(srow["seconds"])
            if bt <= 0 or st <= 0:
                continue
            scaled_times.append(st)
            ratios.append(bt / st)
        if len(ratios) < 2:
            continue
        arr = np.array(ratios)
        theta, lo, hi = bca_median(arr)
        median_s = float(np.median(scaled_times))
        out.append(
            {
                "payload": "frames-10000",
                "threads": threads,
                "n_ok": len(ratios),
                "median_s": f"{median_s:.6g}",
                "speedup": f"{theta:.6g}",
                "speedup_low": f"{lo:.6g}",
                "speedup_high": f"{hi:.6g}",
                "efficiency": f"{theta / threads:.6g}",
                "hashes_identical_1_2_3_4_8": "yes" if identical else "no",
                "n_distinct_hashes": len(hash_set),
            }
        )
    _write("threads_summary.csv", out)


def _write(name: str, rows: list[dict]) -> None:
    if not rows:
        raise SystemExit(f"no rows for {name}")
    path = RESULTS / name
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path}")


def main() -> None:
    analyze_ratios()
    analyze_threads()


if __name__ == "__main__":
    main()
