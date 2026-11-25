"""spec_corpus_recount.py appends a superseding recount and never rewrites a stored one."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "spec_corpus_recount", SCRIPTS / "spec_corpus_recount.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_result(n_valid: int = 80) -> dict:
    return {
        "provenance": {
            "build": {
                "readcon_version": "0.1.0",
                "library_digest": "a" * 64,
                "source_commit": "b" * 40,
            }
        },
        "readcon_version": "0.1.0",
        "tree_commit": "b" * 40,
        "manifest": "resources/conformance/manifest.toml",
        "n_total": n_valid + 53,
        "n_valid": n_valid,
        "n_invalid": 53,
        "n_accepted": n_valid,
        "n_rejected": 53,
        "n_disagreements": 0,
        "rejected_by_class": {
            "truncated file": 10,
            "missing or non-integer atom count": 8,
            "header count mismatch": 11,
            "malformed numeric token": 12,
            "non-finite value": 7,
            "constraint violation": 5,
        },
        "records": [],
    }


def test_corpus_recount_appends_superseding_files_and_reads_newest_in_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    repo = tmp_path / "repo"
    out = repo / "paper" / "cpc" / "data" / "spec"
    tex = repo / "paper" / "cpc" / "src" / "figures" / "generated"
    out.mkdir(parents=True, exist_ok=True)
    tex.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "REPO", repo)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "TEX", tex)

    counts = [80]
    monkeypatch.setattr(module, "run", lambda _tree: _sample_result(counts[0]))

    monkeypatch.setattr("sys.argv", ["spec_corpus_recount.py"])
    assert module.main() == 0
    first = out / "corpus_recount.json"
    assert first.is_file()
    first_bytes = first.read_bytes()
    assert "supersedes" not in json.loads(first.read_text(encoding="utf-8"))

    counts[0] = 81
    assert module.main() == 0
    second = out / "corpus_recount-2.json"
    assert second.is_file()
    assert first.read_bytes() == first_bytes
    second_bytes = second.read_bytes()
    assert json.loads(second.read_text(encoding="utf-8"))["supersedes"] == (
        "paper/cpc/data/spec/corpus_recount.json"
    )

    counts[0] = 82
    assert module.main() == 0
    third = out / "corpus_recount-3.json"
    assert third.is_file()
    assert first.read_bytes() == first_bytes
    assert second.read_bytes() == second_bytes
    assert json.loads(third.read_text(encoding="utf-8"))["supersedes"] == (
        "paper/cpc/data/spec/corpus_recount-2.json"
    )

    # --tables reads the newest superseding record in the chain.
    (tex / "corpus_recount_macros.tex").unlink()
    monkeypatch.setattr("sys.argv", ["spec_corpus_recount.py", "--tables"])
    assert module.main() == 0
    assert "\\newcommand{\\corpusConfValid}{82}" in (
        tex / "corpus_recount_macros.tex"
    ).read_text(encoding="utf-8")


def test_stale_terminal_corpus_recount_still_fails_release_guard() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_manuscript

    stale = _sample_result(80)
    stale["provenance"]["build"]["library_digest"] = "0" * 64
    bad, _, _ = check_manuscript.record_builds(
        [("data/spec/corpus_recount-3.json", stale)],
        "0.1.0",
        "f" * 64,
    )
    assert len(bad) == 1
    assert bad[0].startswith(
        "data/spec/corpus_recount-3.json (provenance.build): library 000000000000, this tree ffffffffffff"
    )


REL = "data/spec/corpus_recount-5.json"


def _stored_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library_when_stored: str
):
    """A repository whose first commit stores the record, and the module under test.

    ``library_at`` names the digest the library has at each commit: the one the
    record was stored under, then a newer one.
    """
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import check_manuscript

    repo = tmp_path / "repo"
    path = repo / "paper" / "cpc" / REL
    path.parent.mkdir(parents=True)

    def git(*args: str) -> str:
        done = subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@test.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q")
    record = _sample_result(80)
    record["provenance"]["build"]["library_digest"] = library_when_stored
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "store the record")
    stored = git("rev-parse", "HEAD")
    (repo / "lib.txt").write_text("a newer library\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "change the library")
    newer = git("rev-parse", "HEAD")
    digests = {stored: "1" * 64, newer: "2" * 64}
    monkeypatch.setattr(check_manuscript, "REPO", repo)
    monkeypatch.setattr(check_manuscript, "ROOT", repo / "paper" / "cpc")
    monkeypatch.setattr(check_manuscript, "library_at", digests.get)
    return check_manuscript, record, path, git, digests


def test_record_keeps_the_library_of_the_commit_that_stored_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript, record, *_ = _stored_record(tmp_path, monkeypatch, "1" * 64)
    bad, _, checked = check_manuscript.record_builds([(REL, record)], "0.1.0", "2" * 64)
    assert bad == []
    assert checked == 1


def test_record_stored_under_another_library_than_it_names_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript, record, *_ = _stored_record(tmp_path, monkeypatch, "3" * 64)
    bad, _, _ = check_manuscript.record_builds([(REL, record)], "0.1.0", "2" * 64)
    assert len(bad) == 1
    assert bad[0].startswith(f"{REL} (provenance.build): library 333333333333")


def test_record_edited_after_it_was_stored_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript, record, path, *_ = _stored_record(tmp_path, monkeypatch, "1" * 64)
    record["n_total"] += 1
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    bad, _, _ = check_manuscript.record_builds([(REL, record)], "0.1.0", "2" * 64)
    assert len(bad) == 1


def test_record_never_committed_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript, record, path, git, digests = _stored_record(
        tmp_path, monkeypatch, "1" * 64
    )
    other = path.with_name("corpus_recount-6.json")
    other.write_bytes(path.read_bytes())
    bad, _, _ = check_manuscript.record_builds(
        [("data/spec/corpus_recount-6.json", record)], "0.1.0", "2" * 64
    )
    assert len(bad) == 1


def test_new_record_cannot_claim_an_older_commit_for_its_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript, record, path, git, digests = _stored_record(
        tmp_path, monkeypatch, "1" * 64
    )
    stored = git("rev-list", "--max-parents=0", "HEAD")
    new = path.with_name("corpus_recount-6.json")
    claim = json.loads(json.dumps(record))
    claim["provenance"]["build"]["source_commit"] = stored
    new.write_text(json.dumps(claim, indent=1) + "\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "store a record measured on the older library")
    digests[git("rev-parse", "HEAD")] = "2" * 64
    bad, _, _ = check_manuscript.record_builds(
        [("data/spec/corpus_recount-6.json", claim)], "0.1.0", "2" * 64
    )
    assert len(bad) == 1
    assert bad[0].startswith(
        "data/spec/corpus_recount-6.json (provenance.build): library 111111111111"
    )
