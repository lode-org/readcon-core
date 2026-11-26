"""The cargo package is exactly the library and the cxx wrap surface that Cargo.toml includes.

scripts/package-cxx.sh builds the cxx wrap archive from this package, so a
file listed here is a file whose edit moves the archive digest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The include list of Cargo.toml, written out again so that a change to it is a change to this test too.
ALLOWLIST = (
    "/src/**",
    "/include/**",
    "/build.rs",
    "/Cargo.toml",
    "/Cargo.lock",
    "/LICENSE",
    "/README.md",
    "/VERSION",
    "/grammar/readcon.pest",
    "/support/metatensor_install.rs",
    "/support/python_link.rs",
    "/schema/ReadCon.capnp",
    "/CMakeLists.txt",
    "/cmake/**",
    "/meson.build",
    "/meson_options.txt",
    "/scripts/meson_cargo_build.py",
    "/examples/c_api_sample.c",
    "/examples/frame_builder_consume.c",
    "/examples/cpp_api_sample.cpp",
    "/examples/meson.build",
    "/examples/cpp_displacements_roundtrip.cpp",
    "/examples/cpp_spreads_roundtrip.cpp",
    "/examples/cpp_trajectory.cpp",
    "/examples/cpp_v31_units_roundtrip.cpp",
    "/examples/print_neb_band.cpp",
    "/resources/test/tiny_multi_cuh2.con",
    "/resources/examples/neb_band.con",
)
# Files cargo writes into every package.
GENERATED = {"Cargo.toml.orig", ".cargo_vcs_info.json"}


def allowed_by(pattern: str, path: str) -> bool:
    """Whether ``path``, relative to the package root, matches one anchored include pattern."""
    anchored = pattern.removeprefix("/")
    if anchored.endswith("/**"):
        return path.startswith(anchored.removesuffix("**"))
    return path == anchored


def allowed(path: str) -> bool:
    return any(allowed_by(pattern, path) for pattern in ALLOWLIST)


def _package_list() -> list[str]:
    if shutil.which("cargo") is None:
        pytest.fail("cargo is missing; the crate list needs it")
    env = {**os.environ, "RUSTUP_TOOLCHAIN": "1.88.0"}
    env.pop("CARGO_TARGET_DIR", None)
    done = subprocess.run(
        ["cargo", "package", "--list", "--allow-dirty", "--package", "readcon-core"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in out.split("\0") if path]


def test_cargo_toml_includes_exactly_the_allowlist() -> None:
    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    assert tuple(manifest["package"]["include"]) == ALLOWLIST
    assert "exclude" not in manifest["package"]


def test_the_package_lists_exactly_the_allowed_tracked_files() -> None:
    listed = set(_package_list())
    expected = {path for path in _tracked() if allowed(path)} | GENERATED
    assert sorted(listed - expected) == []
    assert sorted(expected - listed) == []
    assert not [
        path
        for path in listed
        if path.startswith(("paper/", "tests/", "docs/", "bench/"))
    ]


def test_every_allowlist_entry_names_a_tracked_file() -> None:
    tracked = _tracked()
    assert [
        pattern
        for pattern in ALLOWLIST
        if not any(allowed_by(pattern, path) for path in tracked)
    ] == []
