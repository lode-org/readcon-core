#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Write the paired protocol of the db26 one-thread raw comparison as a record beside the saved db26 records.

The saved ``ab.json`` of db26 holds the paired median and interval but not the
fields ``ci_method`` and ``order`` that the db28 record carries.  The saved
``RESULTS.md`` of the same campaign states both, and ``campaign.log`` lists
every timed read in the order it ran.  This script reads the method from
``RESULTS.md``, reads the arm order from the log, and writes them under the
db28 field names to ``paired_protocol.json``.  It fails, and writes nothing,
unless the logged times are the samples of ``ab.json`` and the stated method
reproduces the saved interval.  The saved records are not changed.

    python3 paper/cpc/scripts/db26_protocol.py
    python3 paper/cpc/scripts/db26_protocol.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIR = "data/db31/db26"
AB = f"{DIR}/ab.json"
RESULTS = f"{DIR}/RESULTS.md"
LOG = f"{DIR}/campaign.log"
OUT = f"{DIR}/paired_protocol.json"
ARMS = ("tip", "aedcbda4")
COMPARISON = "raw_tip_vs_aedcbda4_rayon_1"
OP = "full_read:warm"
LOGGED = "raw-1 warm full_read"
METHOD = re.compile(
    r"The paired CI is a (\d+)-draw percentile bootstrap of the ratio at the same sample index "
    r"\(numpy Generator seed (\d+)\)\."
)
QUANTILE = re.compile(r"The median is type-(\d+)\.")
ORDER = re.compile(r"Arm order is tip, aedcbda4, reversed on odd indexes\.")


def method(text: str) -> tuple[int, int, int]:
    found, quantile = METHOD.search(text), QUANTILE.search(text)
    if not found or not quantile:
        raise SystemExit(f"{RESULTS}: no paired-interval method")
    return int(found.group(1)), int(found.group(2)), int(quantile.group(1))


def logged_order(text: str, n: int) -> tuple[list[tuple[str, ...]], dict[int, list[tuple[str, float]]]]:
    rows = [line.split() for line in text.splitlines() if line.startswith(LOGGED + " ")]
    pairs: dict[int, list[tuple[str, float]]] = {}
    for row in rows:
        pairs.setdefault(int(row[3]), []).append((row[4], float(row[5])))
    if sorted(pairs) != list(range(n)) or any(len(p) != 2 for p in pairs.values()):
        raise SystemExit(f"{LOG}: {LOGGED} is not {n} pairs")
    return [tuple(arm for arm, _ in pairs[i]) for i in range(n)], pairs


def build() -> dict:
    ab = json.loads((ROOT / AB).read_text())
    entry = ab[COMPARISON][OP]
    paired = entry["paired"]
    n = paired["n"]
    draws, seed, quantile = method((ROOT / RESULTS).read_text())
    if not ORDER.search((ROOT / RESULTS).read_text()):
        raise SystemExit(f"{RESULTS}: no arm order for the raw comparison")
    order, pairs = logged_order((ROOT / LOG).read_text(), n)
    expected = [ARMS if i % 2 == 0 else ARMS[::-1] for i in range(n)]
    if order != expected:
        raise SystemExit(f"{LOG}: the arm order is not tip first on even indexes and aedcbda4 first on odd ones")
    for i in range(n):
        for arm, seconds in pairs[i]:
            saved = entry[arm]["samples_s"][i]
            if abs(seconds - saved) > 5e-7 * saved:
                raise SystemExit(f"{LOG}: pair {i} {arm} {seconds} is not the saved sample {saved}")
    if quantile != 7:
        raise SystemExit(f"{RESULTS}: the median is type-{quantile}, not the linear type-7 numpy computes")
    ratios = np.asarray(paired["ratios"], dtype=float)
    rng = np.random.default_rng(seed)
    medians = np.median(ratios[rng.integers(0, n, size=(draws, n))], axis=1)
    ci = [float(x) for x in np.percentile(medians, [2.5, 97.5], method="linear")]
    if ci != paired["ci95"]:
        raise SystemExit(f"{RESULTS}: the stated method gives {ci}, not the saved interval {paired['ci95']}")
    return {
        "record": AB,
        "from": [RESULTS, LOG],
        "commit": ab["commit"],
        "tree": ab["tree"],
        "host": ab["host"],
        COMPARISON: {
            OP: {
                "paired": {
                    "n": n,
                    "ci95": paired["ci95"],
                    "ci_method": f"{draws}-draw percentile bootstrap, type-{quantile} median, numpy Generator seed {seed}",
                    "order": "the measured code first on even sample indexes and the earlier commit first on odd ones",
                }
            }
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail unless the record is what a run writes")
    args = parser.parse_args()
    text = json.dumps(build(), indent=2) + "\n"
    out = ROOT / OUT
    if args.check:
        if not out.is_file() or out.read_text() != text:
            print(f"{OUT} differs from what db26_protocol.py writes", file=sys.stderr)
            return 1
        print(f"{OUT} matches the saved db26 records")
        return 0
    out.write_text(text)
    print(f"wrote paper/cpc/{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
