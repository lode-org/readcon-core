#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Write the upstream release records of the peer releases the manuscript names but did not run.

Each release is taken from the page its project publishes it on: the OVITO
release notes, the GitHub release of MDAnalysis and of ase-extxyz, and the
Python Package Index (PyPI) for extxyz-ng, which has no GitHub release.  The
script stores the version and the date each page gives, with the text it read
them from, in ``data/peers/releases.json``.  It needs the network.  ``--check``
needs none: it fails unless each stored version and date is the one its stored
text gives.

    python3 paper/cpc/scripts/peer_releases.py
    python3 paper/cpc/scripts/peer_releases.py --check
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "peers" / "releases.json"
OVITO = "https://www.ovito.org/docs/current/new_features.html"
OVITO_VERSIONS = ("3.17.0",)
# Each GitHub release tag is its prefix followed by the version.
GITHUB = {
    "MDAnalysis": ("MDAnalysis/mdanalysis", "package-", "2.11.0"),
    "ase-extxyz": ("libAtoms/extxyz", "ase-extxyz-v", "0.1.2"),
}
PYPI = {"extxyz-ng": "0.0.2"}
OVITO_HEADING = re.compile(r"Version (\d+\.\d+\.\d+) \((\d{2}-[A-Z][a-z]{2}-\d{4})\)")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "readcon-core paper records"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def ovito_release(heading: str) -> dict:
    version, day = OVITO_HEADING.fullmatch(heading).groups()
    return {"version": version, "date": datetime.datetime.strptime(day, "%d-%b-%Y").date().isoformat()}


def github_release(prefix: str, tag: str, published: str) -> dict:
    if not tag.startswith(prefix):
        raise SystemExit(f"GitHub release tag {tag} does not start with {prefix}")
    return {"version": tag.removeprefix(prefix), "date": published[:10]}


def build() -> dict:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fetch(OVITO)))
    headings = {v: d for v, d in OVITO_HEADING.findall(text) if v in OVITO_VERSIONS}
    if set(headings) != set(OVITO_VERSIONS):
        raise SystemExit(f"{OVITO}: no release heading for {sorted(set(OVITO_VERSIONS) - set(headings))}")
    releases = {
        "OVITO": [
            {"url": OVITO, "heading": f"Version {v} ({d})", **ovito_release(f"Version {v} ({d})")}
            for v, d in headings.items()
        ]
    }
    for name, (repo, prefix, version) in GITHUB.items():
        data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/tags/{prefix}{version}"))
        releases[name] = [
            {
                "url": data["url"],
                "tag_prefix": prefix,
                "tag_version": data["tag_name"].removeprefix(prefix),
                "published_at": data["published_at"],
                **github_release(prefix, data["tag_name"], data["published_at"]),
            }
        ]
    for name, version in PYPI.items():
        data = json.loads(fetch(f"https://pypi.org/pypi/{name}/{version}/json"))
        uploaded = min(u["upload_time_iso_8601"] for u in data["urls"])
        releases[name] = [
            {
                "url": f"https://pypi.org/project/{name}/{version}/",
                "pypi_version": data["info"]["version"],
                "first_upload": uploaded,
                "version": data["info"]["version"],
                "date": uploaded[:10],
            }
        ]
    return releases


def check(releases: dict) -> list[str]:
    bad = []
    for name, entries in releases.items():
        for entry in entries:
            if "heading" in entry:
                want = ovito_release(entry["heading"])
            elif "tag_prefix" in entry:
                want = github_release(
                    entry["tag_prefix"], entry["tag_prefix"] + entry["tag_version"], entry["published_at"]
                )
            else:
                want = {"version": entry["pypi_version"], "date": entry["first_upload"][:10]}
            got = {"version": entry["version"], "date": entry["date"]}
            if got != want:
                bad.append(f"{name}: stored {got} where its text gives {want}")
    return bad


def release(name: str, version: str) -> dict:
    """The stored release ``version`` of ``name``."""
    found = [e for e in json.loads(OUT.read_text())[name] if e["version"] == version]
    if len(found) != 1:
        raise SystemExit(f"{OUT.relative_to(ROOT)}: {name} {version} is not one release")
    return found[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check the stored record offline")
    args = parser.parse_args()
    releases = json.loads(OUT.read_text()) if args.check else build()
    bad = check(releases)
    for line in bad:
        print(line, file=sys.stderr)
    if bad:
        return 1
    if args.check:
        print(f"{OUT.relative_to(ROOT)}: every version and date is the one its text gives")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(releases, indent=2) + "\n")
    print(f"wrote paper/cpc/{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
