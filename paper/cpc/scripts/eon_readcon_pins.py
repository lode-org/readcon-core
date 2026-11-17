#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Write the readcon-core pins of eOn, release v3.6.0 and development commit bf5d328, as a record.

eOn builds readcon-core from the Meson wrap ``subprojects/readcon-core.wrap``,
whose ``revision`` names a readcon-core tag.  This script fetches that wrap at
the eOn release tag and at the development commit the manuscript cites, the
commit the tag points to, and whether the development commit is in the tag,
and writes them to ``data/eon/readcon_pins.json``.  It needs the network.
``--check`` needs none: it fails unless each pinned readcon-core tag is a tag
of this repository and the development commit's benchmark notes name the
commit of that tag.

    python3 paper/cpc/scripts/eon_readcon_pins.py
    python3 paper/cpc/scripts/eon_readcon_pins.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "eon" / "readcon_pins.json"
EON = "TheochemUI/eOn"
TAG = "v3.6.0"
DEV = "bf5d328359457c4f8e724c2f411e340b802466e3"
WRAP = "subprojects/readcon-core.wrap"
NOTES = "bench/readcon-v020/after/meta.txt"


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode()


def raw(ref: str, path: str) -> str:
    return fetch(f"https://raw.githubusercontent.com/{EON}/{ref}/{path}")


def api(path: str) -> dict:
    return json.loads(fetch(f"https://api.github.com/repos/{EON}/{path}"))


def revision(wrap: str) -> str:
    found = re.search(r"^revision = (\S+)$", wrap, re.M)
    if not found:
        raise SystemExit(f"{WRAP}: no revision line")
    return found.group(1)


def build() -> dict:
    ref = api(f"git/ref/tags/{TAG}")["object"]
    commit = api(f"git/tags/{ref['sha']}")["object"]["sha"] if ref["type"] == "tag" else ref["sha"]
    compare = api(f"compare/{TAG}...{DEV}")
    tag_wrap, dev_wrap = raw(TAG, WRAP), raw(DEV, WRAP)
    return {
        "repository": f"https://github.com/{EON}",
        "release": {"tag": TAG, "commit": commit, "wrap": tag_wrap, "readcon_revision": revision(tag_wrap)},
        "development": {
            "commit": DEV,
            "in_release": compare["status"] in ("behind", "identical"),
            "ahead_of_release_by": compare["ahead_by"],
            "wrap": dev_wrap,
            "readcon_revision": revision(dev_wrap),
            "notes": {"path": NOTES, "text": raw(DEV, NOTES)},
        },
    }


def tag_commit(tag: str) -> str:
    found = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", f"{tag}^{{commit}}"], capture_output=True, text=True
    )
    if found.returncode != 0:
        raise SystemExit(f"readcon-core has no tag {tag}")
    return found.stdout.strip()


def check(record: dict) -> list[str]:
    bad = []
    for part in ("release", "development"):
        pinned = record[part]["readcon_revision"]
        if revision(record[part]["wrap"]) != pinned:
            bad.append(f"{part}: readcon_revision is not the revision of its wrap")
        tag_commit(pinned)
    dev = record["development"]
    notes = dict(line.split(" ", 1) for line in dev["notes"]["text"].splitlines() if " " in line)
    if notes.get("readcon_pin") != dev["readcon_revision"]:
        bad.append(f"{NOTES}: readcon_pin is not the wrap revision {dev['readcon_revision']}")
    if notes.get("readcon_commit") != tag_commit(dev["readcon_revision"]):
        bad.append(f"{NOTES}: readcon_commit is not the commit of readcon-core {dev['readcon_revision']}")
    if dev["in_release"]:
        bad.append(f"the development commit is in eOn {record['release']['tag']}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check the stored record offline")
    args = parser.parse_args()
    if args.check:
        bad = check(json.loads(OUT.read_text()))
        for line in bad:
            print(line, file=sys.stderr)
        if not bad:
            print(f"{OUT.relative_to(ROOT)} pins readcon-core tags of this repository")
        return 1 if bad else 0
    record = build()
    bad = check(record)
    if bad:
        raise SystemExit("; ".join(bad))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=2) + "\n")
    print(f"wrote paper/cpc/{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
