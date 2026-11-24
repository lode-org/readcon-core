"""Structural cxx wrap pin errors are never stale-pin warnings."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "packaging" / "wrapdb" / "readcon-core.sha256"
WRAP = ROOT / "packaging" / "wrapdb" / "readcon-core.wrap"
CHECK = ROOT / "scripts" / "check_cxx_wrap_pin.sh"


def run_check(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK), mode],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("mode", ["--pull-request", "--strict"])
def test_malformed_pin_fails_before_packaging(mode: str):
    original = PIN.read_text(encoding="utf-8")
    PIN.write_text(original.rstrip() + "0\n", encoding="utf-8")
    try:
        result = run_check(mode)
    finally:
        PIN.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "not a 64-character sha256" in result.stderr
    assert "Packaging readcon-core" not in result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["--pull-request", "--strict"])
def test_wrap_sidecar_mismatch_fails_before_packaging(mode: str):
    original = WRAP.read_text(encoding="utf-8")
    changed, count = re.subn(
        r"(?m)^(source_hash\s*=\s*)(?:sha256:)?[0-9a-f]{64}$",
        rf"\g<1>{'0' * 64}",
        original,
    )
    assert count == 1
    WRAP.write_text(changed, encoding="utf-8")
    try:
        result = run_check(mode)
    finally:
        WRAP.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "wrap hash" in result.stderr
    assert "sidecar" in result.stderr
    assert "Packaging readcon-core" not in result.stdout + result.stderr


def recorder_functions() -> str:
    workflow = (ROOT / ".github" / "workflows" / "record_cxx_wrap_pin.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.index("      - name: Record and push the pin")
    start = workflow.index("          pin_paths=(", step)
    end = workflow.index("\n          set +e\n          record_and_commit", start)
    return textwrap.dedent(workflow[start:end])


@pytest.mark.parametrize(
    ("record_body", "current_status", "changed", "expected", "error"),
    [
        (
            "exit 0\n",
            1,
            "docs/orgmode/bindings.org\nunexpected.txt\n",
            1,
            "Unexpected recorder change: unexpected.txt",
        ),
        (
            'printf "partial\\n" > partial-pin\nexit 7\n',
            1,
            "docs/orgmode/bindings.org\n",
            1,
            "",
        ),
        ("exit 0\n", 0, "", 0, ""),
    ],
)
def test_recorder_failures_never_create_a_commit(
    tmp_path: Path,
    record_body: str,
    current_status: int,
    changed: str,
    expected: int,
    error: str,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "record-cxx-wrap.sh").write_text(record_body, encoding="utf-8")
    (scripts / "cxx-wrap-pin-current.sh").write_text(
        f"exit {current_status}\n", encoding="utf-8"
    )

    marker = tmp_path / "commit-called"
    harness = tmp_path / "run-recorder.sh"
    harness.write_text(
        "set -euo pipefail\n"
        + recorder_functions()
        + textwrap.dedent(
            """

            git() {
              if [[ "$1" == "diff" && "$2" == "--name-only" ]]; then
                printf '%s' "${GIT_DIFF_OUTPUT:-}"
                return 0
              fi
              return 1
            }

            create_commit() {
              printf 'called\\n' > "$COMMIT_MARKER"
              return 0
            }

            set +e
            record_and_commit
            rc=$?
            set -e
            case "$rc" in
              0) exit 0 ;;
              2) exit 0 ;;
              *) exit 1 ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "COMMIT_MARKER": str(marker),
        "GIT_DIFF_OUTPUT": changed,
    }
    result = subprocess.run(
        ["bash", str(harness)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected
    assert not marker.exists()
    if error:
        assert error in result.stderr
