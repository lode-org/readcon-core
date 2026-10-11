#!/usr/bin/env python3
"""Paired parse-throughput ratio of this tree against a base checkout.

Repeats are interleaved base, branch, base, branch. Rows that fail are
kept in the CSV and omitted from the ratio interval.
"""

import csv
import math
import platform
import random
import statistics
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benches" / "results" / "v31_parse_ratio.csv"
REPEATS = 30
SEED = 20261011


def norm_ppf(p: float) -> float:
    if p <= 0.0 or p >= 1.0:
        raise ValueError(p)
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bca_median(samples, alpha=0.05, nboot=4000):
    n = len(samples)
    theta = statistics.median(samples)
    rng = random.Random(SEED)
    boots = []
    for _ in range(nboot):
        draw = [samples[rng.randrange(n)] for _ in range(n)]
        boots.append(statistics.median(draw))
    boots.sort()
    prop = sum(1 for value in boots if value < theta) / nboot
    prop = min(max(prop, 1.0 / nboot), 1.0 - 1.0 / nboot)
    z0 = norm_ppf(prop)
    jack = []
    for i in range(n):
        left = samples[:i] + samples[i + 1 :]
        jack.append(statistics.median(left))
    jack_mean = sum(jack) / n
    num = sum((jack_mean - value) ** 3 for value in jack)
    den = sum((jack_mean - value) ** 2 for value in jack) ** 1.5
    acc = num / (6.0 * den) if den else 0.0

    def adjust(z):
        return norm_cdf(z0 + (z0 + z) / (1.0 - acc * (z0 + z)))

    lo_p = adjust(norm_ppf(alpha / 2))
    hi_p = adjust(norm_ppf(1 - alpha / 2))
    lo = boots[min(nboot - 1, max(0, math.floor(lo_p * nboot)))]
    hi = boots[min(nboot - 1, max(0, math.floor(hi_p * nboot)))]
    return theta, lo, hi


def cpu_model():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def main():
    if len(sys.argv) != 3:
        print("usage: bench_v31_ratio.py BASE_BIN BRANCH_BIN", file=sys.stderr)
        return 2
    base_bin, branch_bin = sys.argv[1:]
    data = Path("/tmp/v31-bench")
    data.mkdir(exist_ok=True)
    cuh2 = (ROOT / "resources" / "test" / "cuh2.con").read_text()
    (data / "cuh2x100.con").write_text(cuh2 * 100)
    lines = [
        "bench",
        '{"con_spec_version":2}',
        "100.0 100.0 100.0",
        "90.0 90.0 90.0",
        "A",
        "B",
        "1",
        "10000",
        "12.011",
        "C",
        "Coordinates of Component 1",
    ]
    for i in range(10000):
        lines.append(f"{i * 0.001:.8f} 0.0 0.0 0 {i}")
    (data / "atoms10000.con").write_text("\n".join(lines) + "\n")

    host = platform.node()
    cpu = cpu_model()
    day = date.today().isoformat()
    rustc = subprocess.check_output(["rustc", "--version"], text=True).strip()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    rows = []
    workloads = ["cuh2x100", "atoms10000"]
    for name in workloads:
        path = data / f"{name}.con"
        for repeat in range(1, REPEATS + 1):
            for side, binary in (("base", base_bin), ("branch", branch_bin)):
                proc = subprocess.run(
                    [binary, str(path), "1"],
                    text=True,
                    capture_output=True,
                )
                status = "ok" if proc.returncode == 0 else "fail"
                seconds = ""
                nbytes = path.stat().st_size
                frames = ""
                if status == "ok":
                    ns, nbytes_s, frames = proc.stdout.split()
                    seconds = int(ns) / 1e9
                    nbytes = int(nbytes_s)
                rows.append(
                    {
                        "repeat": repeat,
                        "workload": name,
                        "side": side,
                        "seconds": seconds,
                        "bytes": nbytes,
                        "frames": frames,
                        "status": status,
                        "stderr": proc.stderr.strip().replace("\n", " ")[:200],
                        "host": host,
                        "cpu": cpu,
                        "commit": commit,
                        "base_commit": "f09b1afaf29bb9ab184d508553730b8dd8fe3f73",
                        "rustc": rustc,
                        "date": day,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT}")
    for name in workloads:
        pairs = []
        censored = 0
        for repeat in range(1, REPEATS + 1):
            got = {
                row["side"]: row
                for row in rows
                if row["workload"] == name and row["repeat"] == repeat
            }
            if got["base"]["status"] != "ok" or got["branch"]["status"] != "ok":
                censored += 1
                continue
            base_t = got["base"]["seconds"]
            branch_t = got["branch"]["seconds"]
            pairs.append(
                (got["base"]["bytes"] / branch_t) / (got["base"]["bytes"] / base_t)
            )
        median, lo, hi = bca_median(pairs)
        print(
            f"{name}: n={len(pairs)} censored={censored} "
            f"median={median:.4f} bca95=[{lo:.4f}, {hi:.4f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
