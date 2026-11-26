"""The cross-format campaign is an untagged commit, not release v0.23.3."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "paper" / "cpc" / "data" / "h2h" / "format_h2h_record.json"
COMMIT = "e17abe9d065ddd74be71618014f048ac29ece534"


def _patch_id(commit: str) -> str:
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", commit],
        check=True,
        capture_output=True,
    )
    identified = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=shown.stdout,
        check=True,
        capture_output=True,
    )
    return identified.stdout.decode().split()[0]


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
    sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))
    import provenance

    # The digest is the measured tree, not the library at the replay commit.
    digest = provenance.library_digest_at(record["cross_format_tree"])
    assert digest == record["library_digest"]
    assert record["conbin_api"] == "readcon.read_conbin_columns()"
    source = (ROOT / "paper" / "cpc" / "scripts" / "format_h2h_tables.py").read_text()
    assert f'CONBIN_API = "{record["conbin_api"]}"' in source
    measured = record.get("measured_patch_id")
    if measured:
        assert _patch_id(record["cross_format_commit"]) == measured
    else:
        reached = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "merge-base",
                "--is-ancestor",
                record["cross_format_commit"],
                "HEAD",
            ],
            check=False,
        )
        assert reached.returncode == 0
