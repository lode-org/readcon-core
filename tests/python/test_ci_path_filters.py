"""Workflow path filters include the files each job actually builds or reads."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Inputs tests/python import or read, plus the extension build.
PYTHON_INPUTS = (
    "bench/h2h/**",
    "bench/fidelity/**",
    "benches/**",
    "examples/**",
    "ase-readcon/**",
    "docs/source/**",
    "scripts/**",
    "packaging/wrapdb/**",
    "include/**",
    "cmake/**",
    "CMakeLists.txt",
    "meson.build",
    "meson_options.txt",
    "LICENSE",
    "build.rs",
    ".cargo/config.toml",
    "VERSION",
    "resources/examples/**",
    "dist-workspace.toml",
    ".github/workflows/release.yml",
    ".github/workflows/dist_backfill.yml",
    ".github/workflows/cxx_tarball.yml",
    ".github/workflows/c_lib_tarball.yml",
    ".github/workflows/ci_julia.yml",
    ".github/workflows/python_wheels.yml",
)

# The Julia job links libreadcon_core and reads these trees.
JULIA_INPUTS = (
    "src/**",
    "build.rs",
    ".cargo/config.toml",
    "Cargo.lock",
    "VERSION",
    "resources/test/**",
)

# Wheel builds run build.rs, which reads VERSION, under cargo's env config.
WHEEL_INPUTS = (
    "build.rs",
    ".cargo/config.toml",
    "VERSION",
)


def _path_lists(text: str) -> list[list[str]]:
    lists: list[list[str]] = []
    pending: list[str] | None = None
    for line in text.splitlines():
        if line.strip() == "paths:":
            pending = []
            lists.append(pending)
            continue
        if pending is None:
            continue
        if line.startswith("      - "):
            pending.append(line.split("- ", 1)[1].strip().strip("'\""))
            continue
        if line.strip() == "":
            continue
        pending = None
    return lists


def _require(lists: list[list[str]], required: tuple[str, ...], workflow: str) -> None:
    assert lists, workflow
    for paths in lists:
        missing = [item for item in required if item not in paths]
        assert not missing, f"{workflow} missing {missing}"


def test_python_push_and_pull_request_see_the_same_inputs():
    text = (ROOT / ".github/workflows/ci_python.yml").read_text(encoding="utf-8")
    lists = _path_lists(text)
    assert len(lists) == 2
    assert lists[0] == lists[1]
    _require(lists, PYTHON_INPUTS, "ci_python.yml")


def test_julia_push_and_pull_request_see_the_library_inputs():
    text = (ROOT / ".github/workflows/ci_julia.yml").read_text(encoding="utf-8")
    lists = _path_lists(text)
    assert len(lists) == 2
    assert lists[0] == lists[1]
    _require(lists, JULIA_INPUTS, "ci_julia.yml")


def test_wheel_pull_requests_rebuild_when_the_build_script_changes():
    text = (ROOT / ".github/workflows/python_wheels.yml").read_text(encoding="utf-8")
    lists = _path_lists(text)
    assert len(lists) == 1
    _require(lists, WHEEL_INPUTS, "python_wheels.yml")


def test_release_branch_pushes_build_wheels_before_the_tag():
    text = (ROOT / ".github/workflows/python_wheels.yml").read_text(encoding="utf-8")
    push, _, rest = text.partition("\n  pull_request:")
    assert "workflow_dispatch:" in rest
    assert "- 'v*'" in push
    assert "- 'feat/release-*'" in push
    assert "tags:" in push
    assert "branches:" in push
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert (
        "cancel-in-progress: ${{ !startsWith(github.ref, 'refs/tags/') }}" not in text
    )
