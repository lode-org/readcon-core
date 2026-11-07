#!/usr/bin/env python3
"""Refuse a tag publish whose tree, manifest, or filenames disagree.

The v0.18.0 GitHub Release received 38 wheels named 0.17.3. Those names
came from Python wheels built while the tag pointed at a tree whose
package version was still 0.17.3. cargo-dist archives do not put the
version in the filename; their version is `announcement_tag` and
`app_version` in dist-manifest.json. This check requires VERSION, the
git tag, those manifest fields, and every versioned filename to be one
version. An unversioned dist archive is accepted only when the manifest
lists it and that version matches.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
PREFIXES = (
    "readcon-core-clib-",
    "readcon-core-cxx-",
    "readcon_chemfiles-",
    "readcon-",
)
DIST_BINARY = re.compile(
    r"^readcon-core-(?:aarch64|x86_64)-.+\.(?:tar\.xz|zip)(?:\.sha256)?$"
)
UNVERSIONED = {
    "source.tar.gz",
    "source.tar.gz.sha256",
    "sha256.sum",
    "dist-manifest.json",
    "plan-dist-manifest.json",
}


def tag_version(tag: str) -> str:
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/") :]
    if not tag.startswith("v") or VERSION_RE.fullmatch(tag[1:]) is None:
        raise SystemExit(f"tag {tag!r} is not vX.Y.Z")
    return tag[1:]


def versioned_name(name: str) -> str | None:
    for prefix in PREFIXES:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        match = VERSION_RE.match(rest)
        if match is None:
            return None
        nxt = rest[match.end() : match.end() + 1]
        if nxt in {"", "-", "."}:
            return match.group(0)
        return None
    return None


def is_unversioned_dist(name: str) -> bool:
    return name in UNVERSIONED or DIST_BINARY.match(name) is not None


def manifest_names(path: Path, want: str) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tag = data.get("announcement_tag")
    if tag != f"v{want}":
        raise SystemExit(f"{path.name} announcement_tag is {tag}, tag asks for v{want}")
    names: set[str] = set()
    for release in data.get("releases") or []:
        found = release.get("app_version")
        if found != want:
            raise SystemExit(f"{path.name} app_version is {found}, tag asks for {want}")
        names.update(release.get("artifacts") or [])
    names.update((data.get("artifacts") or {}).keys())
    return names


def iter_files(directories: list[str]) -> list[Path]:
    files: list[Path] = []
    for directory in directories:
        root = Path(directory)
        if not root.is_dir():
            raise SystemExit(f"missing artifact directory {directory}")
        files.extend(path for path in sorted(root.iterdir()) if path.is_file())
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version-file", default="VERSION")
    parser.add_argument("--dist", action="append", default=[])
    parser.add_argument("--manifest", action="append", default=[])
    args = parser.parse_args()
    want = tag_version(args.tag)
    got = Path(args.version_file).read_text(encoding="utf-8").strip()
    if got != want:
        raise SystemExit(f"VERSION is {got}, tag asks for {want}")
    files = iter_files(args.dist)
    manifests = [Path(item) for item in args.manifest]
    manifests.extend(path for path in files if path.name.endswith("dist-manifest.json"))
    listed: set[str] = set()
    for manifest in manifests:
        if not manifest.is_file():
            raise SystemExit(f"missing manifest {manifest}")
        listed.update(manifest_names(manifest, want))
    if args.dist and not files:
        raise SystemExit("no release artifacts found")
    for path in files:
        version = versioned_name(path.name)
        if version is not None:
            if version != want:
                raise SystemExit(
                    f"{path.name} is version {version}, tag asks for {want}"
                )
            print(f"OK {path.name}")
            continue
        if is_unversioned_dist(path.name):
            if not manifests:
                raise SystemExit(
                    f"{path.name} has no version in its name and no dist manifest"
                )
            if path.name not in listed and path.name not in UNVERSIONED:
                raise SystemExit(f"{path.name} is not listed in the dist manifest")
            print(f"OK {path.name} via dist manifest v{want}")
            continue
        raise SystemExit(f"unrecognized release artifact name {path.name}")
    print(f"OK VERSION {got} tag v{want} files {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
