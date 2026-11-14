"""Release and wheel builds remap the cargo home and the source tree."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_rustflags_remap_cargo_home_and_the_source_tree() -> None:
    env = os.environ.copy()
    for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_HOME", "RUNNER_OS"):
        env.pop(key, None)
    env["CARGO_HOME"] = "/opt/cargo-home"
    env["ROOT_DIR"] = "/work/readcon-core"
    script = f"""
set -euo pipefail
source "{ROOT / "scripts" / "release-rustflags.sh"}"
release_rustflags "$ROOT_DIR"
printf '%s\\n' "${{RUSTFLAGS}}"
"""
    done = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    flags = done.stdout.strip()
    assert "--remap-path-prefix=/opt/cargo-home/=/cargo-home/" in flags
    assert "--remap-path-prefix=/work/readcon-core/=/src/" in flags
    assert "--remap-path-prefix=/root/.cargo/=/cargo-home/" in flags
    cargo_at = flags.index("--remap-path-prefix=/opt/cargo-home/=/cargo-home/")
    root_at = flags.index("--remap-path-prefix=/work/readcon-core/=/src/")
    assert cargo_at != root_at
