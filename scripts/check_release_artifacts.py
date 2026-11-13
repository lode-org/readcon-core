#!/usr/bin/env python3
"""Refuse a tag publish whose tree, manifest, or filenames disagree.

The v0.18.0 GitHub Release received 38 wheels named 0.17.3. Those names
came from Python wheels built while the tag pointed at a tree whose
package version was still 0.17.3. cargo-dist archives do not put the
version in the filename; their version is `announcement_tag` and
`app_version` in dist-manifest.json. This check requires VERSION, the
git tag, those manifest fields, and every versioned filename to be one
version. An unversioned dist archive is accepted only when the manifest
lists it and that version matches. Per-target and global
``*-dist-manifest.json`` files are the copies build jobs hand to the
host job. Their JSON version has to match, and the host job deletes
them before it uploads the release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
# A version prefix is not enough. A wrap whose name contains the version is
# still a build product, not a release asset.
RELEASE_ENDINGS = (".tar.gz.sha256", ".tar.gz", ".whl")
ARTIFACTS_NAME = re.compile(r"^Artifacts-([A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)+)\.toml$")
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
        if nxt not in {"-", "."}:
            return None
        if not name.endswith(RELEASE_ENDINGS):
            return None
        return match.group(0)
    return None


def is_scratch_manifest(name: str) -> bool:
    """True for ``global-`` and ``<triple>-dist-manifest.json``.

    ``plan-dist-manifest.json`` matches too. ``dist-manifest.json`` does
    not, and stays in ``UNVERSIONED``.
    """
    return name.endswith("-dist-manifest.json")


def is_unversioned_dist(name: str) -> bool:
    return (
        name in UNVERSIONED
        or is_scratch_manifest(name)
        or DIST_BINARY.match(name) is not None
    )


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


def check_julia_artifact(path: Path, want: str, files: list[Path]) -> None:
    """The clib job uploads one Artifacts-<target>.toml per built archive.

    The file is the Julia binding for that archive: its download URL has to
    name this tag, this target, and the clib tarball, and its sha256 has to
    be the bytes of that tarball. Any other toml stays unrecognized.
    """
    match = ARTIFACTS_NAME.fullmatch(path.name)
    if match is None:
        raise SystemExit(f"unrecognized release artifact name {path.name}")
    target = match.group(1)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"{path.name} is not a Julia artifact manifest") from exc
    block = data.get("readcon_core")
    downloads = block.get("download") if isinstance(block, dict) else None
    if (
        not isinstance(downloads, list)
        or len(downloads) != 1
        or not isinstance(downloads[0], dict)
    ):
        raise SystemExit(f"{path.name} needs one readcon_core download")
    download = downloads[0]
    archive = f"readcon-core-clib-{want}-{target}.tar.gz"
    url = (
        f"https://github.com/lode-org/readcon-core/releases/download/v{want}/{archive}"
    )
    if download.get("url") != url:
        raise SystemExit(
            f"{path.name} url is {download.get('url')!r}, tag asks for {url}"
        )
    sha = download.get("sha256")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        raise SystemExit(f"{path.name} sha256 is not 64 hex characters")
    tree = block.get("git-tree-sha1")
    if not isinstance(tree, str) or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise SystemExit(f"{path.name} git-tree-sha1 is not 40 hex characters")
    by_name = {item.name: item for item in files}
    archive_path = by_name.get(archive)
    sidecar = by_name.get(f"{archive}.sha256")
    if archive_path is None or sidecar is None:
        raise SystemExit(f"{path.name} does not sit next to {archive}")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    sidecar_hash = sidecar.read_text(encoding="utf-8").split()[0]
    if sha != digest or sidecar_hash != digest:
        raise SystemExit(f"{path.name} sha256 does not match {archive}")


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
            if (
                path.name not in listed
                and path.name not in UNVERSIONED
                and not is_scratch_manifest(path.name)
            ):
                raise SystemExit(f"{path.name} is not listed in the dist manifest")
            print(f"OK {path.name} via dist manifest v{want}")
            continue
        if ARTIFACTS_NAME.fullmatch(path.name):
            check_julia_artifact(path, want, files)
            print(f"OK {path.name}")
            continue
        raise SystemExit(f"unrecognized release artifact name {path.name}")
    print(f"OK VERSION {got} tag v{want} files {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
