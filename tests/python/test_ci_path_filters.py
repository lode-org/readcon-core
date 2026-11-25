"""Workflow path filters include the files each job actually builds or reads."""

from __future__ import annotations

import subprocess
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


def test_cxx_wrap_pin_does_not_run_for_bench_only_changes():
    text = (ROOT / ".github/workflows/ci_cxx_wrap_pin.yml").read_text(encoding="utf-8")
    assert text.count("paths-ignore:") == 2
    assert text.count("- 'bench/**'") == 2
    assert "bash scripts/check_cxx_wrap_pin.sh" in text
    assert "--pull-request" in text
    assert "--strict" in text
    assert "- main" in text
    assert "- '**'" in text
    assert "permissions:\n  contents: read" in text


def test_cxx_wrap_pin_current_skips_only_an_unchanged_pin():
    script = ROOT / "scripts" / "cxx-wrap-pin-current.sh"
    pin = ROOT / "packaging" / "wrapdb" / "readcon-core.sha256"
    original = pin.read_text(encoding="utf-8")
    current = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert current.returncode == 0
    assert "current" in current.stdout

    pin.write_text(original.rstrip() + "0\n", encoding="utf-8")
    try:
        stale = subprocess.run(
            ["bash", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        pin.write_text(original, encoding="utf-8")
    assert stale.returncode == 1
    assert "needs recording" in stale.stdout


def test_develop_pin_recorder_has_guard_and_one_retry():
    workflow = (ROOT / ".github" / "workflows" / "record_cxx_wrap_pin.yml").read_text(
        encoding="utf-8"
    )
    assert "permissions:\n  contents: write" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "steps.loop-guard.outputs.skip != 'true'" in workflow
    assert workflow.count("git push origin HEAD:develop") == 2
    assert 'git add -- "${pin_paths[@]}"' in workflow
    assert "bash scripts/check_cxx_wrap_pin.sh --strict" in workflow
    assert "statuses: write" in workflow
    assert 'context="cxx wrap pin"' in workflow
    assert "state=success" in workflow
    assert "state=failure" in workflow
    assert "gh api --method POST" in workflow
    assert "git rebase" not in workflow
    assert "commit --amend" not in workflow
    assert "if ! record_pin" not in workflow
    assert "bash scripts/record-cxx-wrap.sh || return 1" in workflow
    assert "validate_changes || return 1" in workflow
    assert "2) return 2" in workflow

    retry = workflow.split(
        'echo "develop moved; resetting and retrying once."',
        maxsplit=1,
    )[1]
    commands = (
        "git fetch origin develop",
        "git reset --hard origin/develop",
        "set +e",
        "record_and_commit",
        "rc=$?",
        "set -e",
        'case "$rc"',
        "git push origin HEAD:develop",
    )
    positions = [retry.index(command) for command in commands]
    assert positions == sorted(positions)


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
