"""Camp records cite a commit that exists on the published branch."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "bench" / "h2h" / "measured_commit.py"


def _load():
    spec = importlib.util.spec_from_file_location("measured_commit", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_a_tracked_edit_is_refused() -> None:
    module = _load()
    with pytest.raises(SystemExit, match="dirty tree"):
        module.require_clean(" M src/writer.rs\n")


def test_untracked_files_are_not_a_dirty_tree() -> None:
    module = _load()
    module.require_clean("?? bench/h2h/camp16_run.py\n")


def test_an_unpublished_head_cites_the_origin_ancestor_and_the_diff() -> None:
    module = _load()
    diff = b"diff --git a/src/writer.rs b/src/writer.rs\n"
    info = module.cite_from(
        "local-head",
        "d305d3d498fab2a515d270c68635ecffc5aa209a",
        lambda rev: rev.startswith("d305d3d4"),
        diff,
    )
    assert info["commit"] == "d305d3d498fab2a515d270c68635ecffc5aa209a"
    assert info["diff_sha256"] == hashlib.sha256(diff).hexdigest()


def test_a_published_head_records_an_empty_diff() -> None:
    module = _load()
    info = module.cite_from("d305d3d4", "d305d3d4", lambda _rev: True, b"ignored")
    assert info["commit"] == "d305d3d4"
    assert info["diff_sha256"] == hashlib.sha256(b"").hexdigest()


def test_a_base_that_origin_lacks_is_refused() -> None:
    module = _load()
    with pytest.raises(SystemExit, match="not on"):
        module.cite_from("local", "deadbeef", lambda _rev: False, b"")


def _needles() -> tuple[str, ...]:
    return (
        "/" + "agent",
        "/" + "tmp",
        "/" + "var/" + "tmp",
        "/" + "home/",
    )


def offending(text: str) -> list[str]:
    return [needle for needle in _needles() if needle in text]


def test_a_planted_agent_path_is_rejected() -> None:
    planted = '{"disk": "' + _needles()[0] + '/repos/readcon"}\n'
    assert offending(planted)


def test_a_repo_relative_path_is_kept() -> None:
    assert offending('{"disk": "build/bench", "dest": "shm/camp24/out.con"}\n') == []


def test_camp24_records_have_no_machine_paths() -> None:
    folder = ROOT / "bench" / "h2h" / "scaling" / "camp24"
    if not folder.is_dir():
        return
    found = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".json", ".log"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = offending(text)
        if hits:
            found.append(f"{path.relative_to(ROOT)}: {hits[0]}")
    assert not found, found


def test_library_publish_is_one_rename_and_ordered_receives() -> None:
    writer = (ROOT / "src" / "writer.rs").read_text(encoding="utf-8")
    ranked = (ROOT / "src" / "distrib_write.rs").read_text(encoding="utf-8")
    assert "READCON_DEFER_UNLINK" not in writer
    assert "READCON_RANKED_READY" not in ranked
    assert "any_process()" not in ranked
