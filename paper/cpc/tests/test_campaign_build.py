"""A campaign keeps the library of the commit that stored it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
RECORD = "data/claisen/readcon-build.json"
# No build has this digest, so neither case passes by naming this tree.
OTHER_TREE = "0" * 64


def _checker():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_manuscript

    return check_manuscript


def _record() -> dict:
    return json.loads((ROOT / "paper" / "cpc" / RECORD).read_text(encoding="utf-8"))


def test_the_claisen_build_record_keeps_the_library_that_stored_it() -> None:
    cm = _checker()
    data = _record()
    commit = data["source_commit"]
    assert cm.campaign_commit(data) == commit
    assert cm.library_at(commit) is not None
    bad, _, checked = cm.record_builds(
        [(RECORD, data)], data["readcon_version"], OTHER_TREE
    )
    assert bad == []
    assert checked == 1


def test_a_commit_that_did_not_store_the_campaign_is_this_tree() -> None:
    cm = _checker()
    data = _record()
    unrelated = subprocess.check_output(
        ["git", "rev-parse", "af7f800603ac"], cwd=ROOT, text=True
    ).strip()
    tampered = dict(data, source_commit=unrelated)
    assert cm.campaign_commit(tampered) is None
    bad, _, _ = cm.record_builds(
        [(RECORD, tampered)], data["readcon_version"], OTHER_TREE
    )
    assert len(bad) == 1
    assert bad[0].startswith(f"{RECORD}: library ")
