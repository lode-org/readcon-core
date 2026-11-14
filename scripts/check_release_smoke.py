#!/usr/bin/env python3
"""Download one release's published assets and reject a C ABI tarball that
omits ``include/readcon-core-version.h``.

``v0.23.1`` shipped ``readcon-core.h`` (which includes that header) without
the header itself, so ``gcc`` against the published prefix failed. The
self-test builds that broken layout and requires the checker to fail.

A version that is not on GitHub yet exits 0 unless ``--require-published``
(tag pushes and workflow_dispatch). A release that exists must carry the
crate, both wheels, the cxx tarball, every clib tarball, and the cargo-dist
archives.

The wrap pin and ``VERSION`` are read with ``git show <tag>:path``. The
checked-out branch head is a later tree and its wrap describes the next
unreleased archive, not the tarball attached to the tag.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from work_dir import work_dir
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "lode-org/readcon-core"
USER_AGENT = "readcon-release-smoke"
CLIB_HEADERS = (
    "include/readcon-core.h",
    "include/readcon-core-version.h",
)
DIST_TARGETS = (
    "aarch64-apple-darwin",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
)

C_PROGRAM = r"""
#include "readcon-core.h"
#include <stdio.h>
int main(void) {
    const char *version = rkr_library_version();
    if (version == NULL || version[0] == '\0') return 1;
    printf("%s\n", version);
    return 0;
}
"""

CPP_PROGRAM = r"""
#include "readcon-core.hpp"
#include <iostream>
int main() {
    const char *version = readcon::rkr_library_version();
    if (version == NULL || version[0] == '\0') return 1;
    std::cout << version << "\n";
    return 0;
}
"""


class SmokeError(Exception):
    """A published asset is missing or does not build."""


def git_show(root: Path, tag: str, path: str) -> str:
    """File contents at ``tag``, not the checked-out worktree."""
    ran = subprocess.run(
        ["git", "-C", str(root), "show", f"{tag}:{path}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if ran.returncode != 0:
        detail = ran.stderr.strip() or f"git show {tag}:{path} failed"
        raise SmokeError(detail)
    return ran.stdout


def tag_version(tag: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SmokeError(f"tag {tag} is not vX.Y.Z")
    return tag[1:]


def wrap_pin(text: str) -> tuple[str, str]:
    """Return ``(version, source_hash)`` from a wrap file body."""
    fields = {}
    for line in text.splitlines():
        if "=" not in line or line.strip().startswith("["):
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    versions = set()
    for key in ("directory", "source_filename", "source_url"):
        found = re.findall(r"\d+\.\d+\.\d+", fields.get(key, ""))
        if not found:
            raise SmokeError(f"wrap {key} has no X.Y.Z version")
        versions.update(found)
    if len(versions) != 1:
        raise SmokeError("wrap version fields disagree: " + ", ".join(sorted(versions)))
    source_hash = fields.get("source_hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise SmokeError(f"wrap source_hash is not 64 hex digits: {source_hash!r}")
    return versions.pop(), source_hash


def pin_at_tag(root: Path, tag: str) -> tuple[str, str]:
    """Version and cxx hash recorded on ``tag``.

    The tag name, ``VERSION``, the wrap filename, and the sha256 sidecar
    must all name that same release. A branch head's wrap is not consulted.
    """
    version = tag_version(tag)
    tagged = git_show(root, tag, "VERSION").strip()
    if tagged != version:
        raise SmokeError(f"tag {tag} and VERSION {tagged} at that tag disagree")
    wrap_version, source_hash = wrap_pin(
        git_show(root, tag, "packaging/wrapdb/readcon-core.wrap")
    )
    if wrap_version != version:
        raise SmokeError(f"tag {tag} and wrap version {wrap_version} disagree")
    sidecar = git_show(root, tag, "packaging/wrapdb/readcon-core.sha256").strip()
    if sidecar != source_hash:
        raise SmokeError(
            f"tag {tag} wrap source_hash {source_hash} and sha256 sidecar {sidecar} disagree"
        )
    print(f"tag {tag} wrap {source_hash}")
    return version, source_hash


def member_names(blob: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
        return archive.getnames()


def missing_clib_headers(names: list[str]) -> list[str]:
    missing = []
    for header in CLIB_HEADERS:
        if not any(name.endswith(header) for name in names):
            missing.append(header)
    return missing


def require_clib_headers(blob: bytes, label: str) -> None:
    missing = missing_clib_headers(member_names(blob))
    if missing:
        raise SmokeError(f"{label} is missing {', '.join(missing)}")


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def fetch(url: str) -> tuple[int, bytes]:
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def github_release(version: str) -> dict | None:
    status, body = fetch(
        f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"
    )
    if status == 404:
        return None
    if status != 200:
        raise SmokeError(f"GitHub release v{version} returned HTTP {status}")
    return json.loads(body)


def asset_named(release: dict, name: str) -> dict:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    raise SmokeError(f"release v{release.get('tag_name')} has no {name}")


def download_asset(asset: dict) -> bytes:
    status, body = fetch(asset["browser_download_url"])
    if status != 200:
        raise SmokeError(f"{asset['name']} download returned HTTP {status}")
    return body


def pypi_wheel(project: str, version: str) -> bytes:
    status, body = fetch(f"https://pypi.org/pypi/{project}/{version}/json")
    if status == 404:
        raise SmokeError(f"PyPI has no {project}=={version}")
    if status != 200:
        raise SmokeError(f"PyPI {project}=={version} returned HTTP {status}")
    urls = json.loads(body)["urls"]
    wheels = [
        item
        for item in urls
        if item["packagetype"] == "bdist_wheel"
        and "manylinux" in item["filename"]
        and "x86_64" in item["filename"]
    ]
    if not wheels:
        wheels = [item for item in urls if item["packagetype"] == "bdist_wheel"]
    if not wheels:
        raise SmokeError(f"PyPI {project}=={version} has no wheel")
    status, blob = fetch(wheels[0]["url"])
    if status != 200:
        raise SmokeError(f"{wheels[0]['filename']} download returned HTTP {status}")
    print(f"wheel {wheels[0]['filename']} {sha256(blob)}")
    return blob


def crate_tarball(version: str) -> bytes:
    status, blob = fetch(
        f"https://crates.io/api/v1/crates/readcon-core/{version}/download"
    )
    if status == 404:
        raise SmokeError(f"crates.io has no readcon-core {version}")
    if status != 200:
        raise SmokeError(f"crates.io readcon-core {version} returned HTTP {status}")
    print(f"crate readcon-core-{version}.crate {sha256(blob)}")
    return blob


def dist_name(version: str, target: str) -> str:
    if target.endswith("windows-msvc"):
        return f"readcon-core-{target}.zip"
    return f"readcon-core-{target}.tar.xz"


def compile_against(prefix: Path) -> None:
    include = prefix / "include"
    lib = prefix / "lib"
    if not (include / "readcon-core-version.h").is_file():
        raise SmokeError(f"{prefix} has no include/readcon-core-version.h")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(lib)
    link = [
        "-I",
        str(include),
        "-L",
        str(lib),
        "-lreadcon_core",
        "-ldl",
        "-lpthread",
        "-lm",
    ]
    with work_dir("smoke") as work:
        (work / "smoke.c").write_text(C_PROGRAM, encoding="utf-8")
        (work / "smoke.cpp").write_text(CPP_PROGRAM, encoding="utf-8")
        c_bin = work / "smoke-c"
        cpp_bin = work / "smoke-cpp"
        subprocess.run(
            ["gcc", "-std=c99", str(work / "smoke.c"), "-o", str(c_bin), *link],
            check=True,
            env=env,
        )
        subprocess.run(
            ["g++", "-std=c++17", str(work / "smoke.cpp"), "-o", str(cpp_bin), *link],
            check=True,
            env=env,
        )
        for binary in (c_bin, cpp_bin):
            ran = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True, env=env
            )
            print(f"{binary.name} {ran.stdout.strip()}")


def unpack_clib(blob: bytes, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        extract = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        archive.extractall(dest, **extract)
    include = next(dest.rglob("include"), None)
    if include is None:
        raise SmokeError("clib tarball has no include directory")
    return include.parent


def check_published(version: str, pinned: str, tag: str) -> None:
    release = github_release(version)
    if release is None:
        raise SmokeError(f"GitHub release v{version} does not exist")
    crate_tarball(version)
    pypi_wheel("readcon", version)
    pypi_wheel("readcon-chemfiles", version)
    cxx_name = f"readcon-core-cxx-{version}.tar.gz"
    cxx = download_asset(asset_named(release, cxx_name))
    digest = sha256(cxx)
    if digest != pinned:
        raise SmokeError(f"{cxx_name} sha256 {digest} != wrap {pinned} at {tag}")
    print(f"cxx {cxx_name} matches wrap {digest} at {tag}")
    clib_names = [
        asset["name"]
        for asset in release.get("assets", [])
        if asset["name"].startswith(f"readcon-core-clib-{version}-")
        and asset["name"].endswith(".tar.gz")
    ]
    if not clib_names:
        raise SmokeError(f"release v{version} has no clib tarballs")
    linux = None
    for name in sorted(clib_names):
        blob = download_asset(asset_named(release, name))
        require_clib_headers(blob, name)
        print(f"clib {name} has both headers")
        if "x86_64-unknown-linux-gnu" in name:
            linux = blob
    if linux is None:
        raise SmokeError("release has no Linux clib tarball to compile against")
    for target in DIST_TARGETS:
        name = dist_name(version, target)
        blob = download_asset(asset_named(release, name))
        print(f"dist {name} {len(blob)} bytes")
    with work_dir("clib") as tmp:
        prefix = unpack_clib(linux, tmp)
        compile_against(prefix)


def fixture_tarball(include_version_header: bool) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        payload = b'#include "readcon-core-version.h"\n'
        info = tarfile.TarInfo("include/readcon-core.h")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        if include_version_header:
            version = b'#define READCON_VERSION "fixture"\n'
            info = tarfile.TarInfo("include/readcon-core-version.h")
            info.size = len(version)
            archive.addfile(info, io.BytesIO(version))
    return buf.getvalue()


def self_test() -> None:
    broken = fixture_tarball(False)
    try:
        require_clib_headers(broken, "v0.23.1-fixture")
    except SmokeError as exc:
        if "readcon-core-version.h" not in str(exc):
            raise
        print(f"self-test caught missing header: {exc}")
    else:
        raise SmokeError("a clib tarball without the version header was accepted")
    require_clib_headers(fixture_tarball(True), "complete-fixture")
    print("self-test accepted a clib tarball that has both headers")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--tag",
        help="vX.Y.Z tag whose VERSION and wrap pin are authoritative",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="only prove a missing version header is rejected",
    )
    parser.add_argument(
        "--require-published",
        action="store_true",
        help="fail when this tag has no GitHub release yet",
    )
    args = parser.parse_args(argv)
    self_test()
    if args.self_test:
        return 0
    if not args.tag:
        raise SmokeError(
            "pass --tag vX.Y.Z; the wrap is read from that tag, not the worktree"
        )
    version, pinned = pin_at_tag(args.root, args.tag)
    release = github_release(version)
    if release is None:
        message = f"v{version} is not published yet"
        if args.require_published:
            raise SmokeError(message)
        print(message)
        return 0
    check_published(version, pinned, args.tag)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeError, subprocess.CalledProcessError) as exc:
        print(f"release smoke: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
