"""The cross-format campaign is an untagged commit, not release v0.23.3."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "paper" / "cpc" / "data" / "h2h" / "format_h2h_record.json"
COMMIT = "e938ccf4fae892302ffe0b3a72a0361233b05970"


def test_the_measured_format_commit_is_not_release_v0_23_3() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["cross_format_commit"] == COMMIT
    assert record["readcon_version"] == "0.23.3"
    assert record["release_tag"] is None
    assert record["tagged"] is False
    version = subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{COMMIT}:VERSION"], text=True
    ).strip()
    assert version == "0.23.3"
    tagged = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "refs/tags/v0.23.3"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tagged.returncode != 0
    release = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "v0.23.2^{}"], text=True
    ).strip()
    assert release != COMMIT
