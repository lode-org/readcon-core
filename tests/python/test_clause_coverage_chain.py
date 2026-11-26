"""``check_manuscript.check_conformance`` follows the clause-coverage supersedes chain."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"


def _load(name: str, path: Path):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _fixture_tree(tmp_path: Path, *, macro_clauses: int, macro_covered: int):
    repo = tmp_path / "repo"
    cpc = repo / "paper" / "cpc"
    data = cpc / "data"
    spec_dir = data / "spec"
    src = cpc / "src"
    generated = src / "figures" / "generated"

    repo.mkdir(parents=True)
    generated.mkdir(parents=True)

    version = "0.99.0"
    (repo / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    spec_file = repo / "docs" / "orgmode" / "spec.org"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("- CON-test.1 :: MUST :: fixture clause.\n", encoding="utf-8")
    blob8 = subprocess.run(
        ["git", "-C", str(repo), "hash-object", str(spec_file)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()[:8]
    spec_sha = hashlib.sha256(spec_file.read_bytes()).hexdigest()

    base = spec_dir / f"clause_coverage-{version}.json"
    head = spec_dir / f"clause_coverage-{version}-{blob8}.json"
    middle = spec_dir / f"clause_coverage-{version}-{blob8}-zzzzzzzz.json"
    tail = spec_dir / f"clause_coverage-{version}-{blob8}-0000aaaa.json"

    _write_json(
        base,
        {
            "spec": {
                "path": "docs/orgmode/spec.org",
                "sha256": "0" * 64,
                "clauses": 99,
            },
            "totals": {"clauses": 99, "covered": 50},
        },
    )
    _write_json(
        head,
        {
            "supersedes": f"paper/cpc/data/spec/{base.name}",
            "spec": {
                "path": "docs/orgmode/spec.org",
                "sha256": spec_sha,
                "clauses": 100,
            },
            "totals": {"clauses": 100, "covered": 80},
        },
    )
    _write_json(
        middle,
        {
            "supersedes": f"paper/cpc/data/spec/{head.name}",
            "spec": {
                "path": "docs/orgmode/spec.org",
                "sha256": spec_sha,
                "clauses": 100,
            },
            "totals": {"clauses": 100, "covered": 85},
        },
    )
    _write_json(
        tail,
        {
            "supersedes": f"paper/cpc/data/spec/{middle.name}",
            "spec": {
                "path": "docs/orgmode/spec.org",
                "sha256": spec_sha,
                "clauses": 128,
            },
            "totals": {"clauses": 128, "covered": 105},
        },
    )

    _write_json(
        data / "referee" / "r1t" / "corpus31-results.json",
        {
            "summary": {
                "files": 10,
                "match": 10,
                "disagreements": [],
                "manifest_not_followed": [],
                "threads_disagree": [],
            }
        },
    )
    _write_json(
        data / "corpus_paths.json",
        {
            "results": {
                "totals": {
                    "files": 10,
                    "reads": 20,
                    "match": 20,
                    "differ": 0,
                    "files_differ": [],
                }
            }
        },
    )
    _write_json(data / "every_path.json", {"results": {"totals": {"inputs": 5}}})
    _write_json(
        data / "referee" / "r1t" / "mutant_differential.json",
        {"totals": {"cases": 12, "same": 12, "unexplained": 0}},
    )
    _write_json(
        data / "referee" / "r1h" / "corpus_crosscheck.json",
        {
            "groups": {
                "all": {
                    "files": 4,
                    "accepted_by_both": 1,
                    "field_identical": 1,
                    "readers": {
                        "readcon": {
                            "matches": 2,
                            "disagreements": 1,
                            "not_followed": 1,
                            "crashes": 0,
                        },
                        "readcon_iter": {
                            "matches": 2,
                            "disagreements": 1,
                            "not_followed": 1,
                            "crashes": 0,
                        },
                        "indep": {
                            "matches": 4,
                            "disagreements": 0,
                            "not_followed": 0,
                            "crashes": 0,
                        },
                    },
                }
            }
        },
    )
    _write_json(
        data / "referee_probes.json", {"summary": {"probes": 3, "failed_probes": []}}
    )

    (src / "commit.tex").write_text("", encoding="utf-8")
    (src / "release.tex").write_text("", encoding="utf-8")
    (generated / "velocity_case.tex").write_text("", encoding="utf-8")
    (generated / "clauses_macros.tex").write_text(
        "\n".join(
            [
                r"\newcommand{\cthreeoneFiles}{10}",
                r"\newcommand{\cthreeoneMatch}{10}",
                r"\newcommand{\cpathsFiles}{10}",
                r"\newcommand{\cpathsReads}{20}",
                r"\newcommand{\cpathsMatch}{20}",
                r"\newcommand{\everyPathInputs}{5}",
                rf"\newcommand{{\clauseTotal}}{{{macro_clauses}}}",
                rf"\newcommand{{\clauseCovered}}{{{macro_covered}}}",
                r"\newcommand{\mutantCases}{12}",
                r"\newcommand{\mutantSame}{12}",
                r"\newcommand{\corpusFiles}{4}",
                r"\newcommand{\corpusReadconAgree}{2}",
                r"\newcommand{\corpusReadconDisagree}{1}",
                r"\newcommand{\corpusReadconNotFollowed}{1}",
                r"\newcommand{\corpusIterAgree}{2}",
                r"\newcommand{\corpusIterDisagree}{1}",
                r"\newcommand{\corpusIterNotFollowed}{1}",
                r"\newcommand{\corpusIndepAgree}{4}",
                r"\newcommand{\corpusBoth}{1}",
                r"\newcommand{\corpusFieldIdentical}{1}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo, cpc, src, generated, head, tail


def test_check_conformance_reads_terminal_supersedes_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript = _load(
        "check_manuscript_under_test", SCRIPTS / "check_manuscript.py"
    )
    repo, cpc, src, generated, _, _ = _fixture_tree(
        tmp_path, macro_clauses=128, macro_covered=105
    )
    monkeypatch.setattr(check_manuscript, "ROOT", cpc)
    monkeypatch.setattr(check_manuscript, "REPO", repo)
    monkeypatch.setattr(check_manuscript, "SRC", src)
    monkeypatch.setattr(check_manuscript, "GENERATED", generated)
    monkeypatch.setattr(check_manuscript, "script_check", lambda script, what: "ok")

    summary = check_manuscript.check_conformance()
    assert "105 of 128 clauses" in summary


def test_check_conformance_rejects_macros_matching_non_terminal_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_manuscript = _load(
        "check_manuscript_under_test", SCRIPTS / "check_manuscript.py"
    )
    repo, cpc, src, generated, _, tail = _fixture_tree(
        tmp_path, macro_clauses=100, macro_covered=80
    )
    monkeypatch.setattr(check_manuscript, "ROOT", cpc)
    monkeypatch.setattr(check_manuscript, "REPO", repo)
    monkeypatch.setattr(check_manuscript, "SRC", src)
    monkeypatch.setattr(check_manuscript, "GENERATED", generated)
    monkeypatch.setattr(check_manuscript, "script_check", lambda script, what: "ok")

    with pytest.raises(check_manuscript.Failed) as excinfo:
        check_manuscript.check_conformance()
    message = str(excinfo.value)
    assert tail.name in message
    assert r"\clauseTotal is 100" in message
    assert r"\clauseCovered is 80" in message


def test_default_paths_rejects_fork_and_orphan(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    repo, cpc, _, _, head, tail = _fixture_tree(
        tmp_path, macro_clauses=128, macro_covered=105
    )
    orphan = head.with_name(head.stem + "-orphan.json")
    _write_json(orphan, {"supersedes": "paper/cpc/data/spec/nonexistent.json"})
    with pytest.raises(SystemExit, match="0 records of data/spec supersede"):
        clause_coverage.default_paths(root=cpc, repo=repo)

    orphan.unlink()
    fork = head.with_name(head.stem + "-fork.json")
    _write_json(fork, {"supersedes": f"paper/cpc/data/spec/{head.name}"})
    with pytest.raises(SystemExit, match="2 records of data/spec supersede"):
        clause_coverage.default_paths(root=cpc, repo=repo)
    assert tail.is_file()


def test_repo_clause_coverage_resolves_to_terminal_record() -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    spec_dir = ROOT / "paper" / "cpc" / "data" / "spec"
    # The chain named by git blob a8f263a2 forks at its r6 record, which
    # stored records keep. The live spec.org resolves through the final
    # spec-major chain.
    previous, newest = clause_coverage.default_paths()
    assert newest.name not in _children(spec_dir)
    assert newest == clause_coverage.FINAL_RECORD
    assert newest == clause_coverage.record_for_sources()[0]
    chain = [newest]
    cur = newest
    while True:
        prior_rel = json.loads(cur.read_text(encoding="utf-8")).get("supersedes")
        if not prior_rel:
            break
        cur = ROOT / prior_rel
        chain.append(cur)
    names = [p.name for p in chain]
    finals = clause_coverage.final_chain()
    assert finals
    assert clause_coverage.FINAL_RECORD == finals[-1]
    assert clause_coverage.default_paths() == (
        finals[-2] if len(finals) > 1 else spec_dir / f"clause_coverage-{version}.json",
        finals[-1],
    )
    assert newest == finals[-1]
    assert names[: len(finals)] == [p.name for p in reversed(finals)]
    assert f"clause_coverage-{version}-spec-major.json" in names
    assert f"clause_coverage-{version}.json" in names
    assert previous == chain[1]


def _walk_back(path: Path) -> list[Path]:
    chain = [path]
    while prior := json.loads(chain[-1].read_text(encoding="utf-8")).get("supersedes"):
        chain.append(ROOT / prior)
    return chain


def _children(spec_dir: Path) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for path in sorted(spec_dir.glob("clause_coverage*.json")):
        prior = json.loads(path.read_text(encoding="utf-8")).get("supersedes")
        if prior:
            children.setdefault(Path(prior).name, []).append(path.name)
    return children


def test_repo_a8f263a2_chain_forks_outside_the_active_chain(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    spec_dir = ROOT / "paper" / "cpc" / "data" / "spec"
    # The live spec.org is a later blob. The committed chain is the one
    # named by git blob a8f263a2. Its r6 record has two stored children,
    # a8f263a2-r7 and a8f263a2-cxx-wrap-pin, and stored records are never
    # rewritten, so default_paths still refuses that spec.
    spec = tmp_path / "spec.org"
    spec.write_bytes(
        subprocess.check_output(
            ["git", "-C", str(ROOT), "cat-file", "blob", "a8f263a2"]
        )
    )
    r6 = f"clause_coverage-{version}-a8f263a2-r6.json"
    with pytest.raises(SystemExit, match=f"2 records of data/spec supersede {r6}"):
        clause_coverage.default_paths(spec=spec)
    leaves = sorted(_children(spec_dir)[r6])
    assert leaves == [
        f"clause_coverage-{version}-a8f263a2-cxx-wrap-pin.json",
        f"clause_coverage-{version}-a8f263a2-r7.json",
    ]
    active = {p.name for p in _walk_back(clause_coverage.FINAL_RECORD)}
    for leaf in leaves:
        names = [p.name for p in _walk_back(spec_dir / leaf)]
        assert r6 in names
        assert f"clause_coverage-{version}-a8f263a2-5369dc50.json" in names
        assert f"clause_coverage-{version}-a8f263a2.json" in names
        assert not set(names[: names.index(f"clause_coverage-{version}.json")]) & active


def test_repo_final_clause_coverage_chain_is_linear() -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    spec_dir = ROOT / "paper" / "cpc" / "data" / "spec"
    finals = clause_coverage.final_chain()
    assert finals
    tip = finals[-1]
    assert clause_coverage.FINAL_RECORD == tip
    names = [p.name for p in finals]
    assert all(clause_coverage.record_series(p) for p in finals)
    assert names.count(tip.name) == 1
    assert f"clause_coverage-{version}-spec-major-10.json" in names
    assert f"clause_coverage-{version}-capi-r1.json" in names
    assert names.index(f"clause_coverage-{version}-capi-r1.json") == (
        names.index(f"clause_coverage-{version}-spec-major-10.json") + 1
    )
    assert names.index(f"clause_coverage-{version}-capi-r2.json") == (
        names.index(f"clause_coverage-{version}-capi-r1.json") + 1
    )
    assert names.index(f"clause_coverage-{version}-capi-r3.json") == (
        names.index(f"clause_coverage-{version}-capi-r2.json") + 1
    )
    assert names.index(f"clause_coverage-{version}-capi-r4.json") == (
        names.index(f"clause_coverage-{version}-capi-r3.json") + 1
    )
    assert names.index(f"clause_coverage-{version}-referee-r1.json") == (
        names.index(f"clause_coverage-{version}-capi-r4.json") + 1
    )
    assert names.index(f"clause_coverage-{version}-spec-major-11.json") == (
        names.index(f"clause_coverage-{version}-referee-r1.json") + 1
    )
    assert names[-1] == f"clause_coverage-{version}-spec-major-11.json"
    # The older -r2 recount supersedes the legacy record beside spec-major and
    # has no series name, so it is a side record and never final.
    assert (spec_dir / f"clause_coverage-{version}-r2.json").is_file()
    assert f"clause_coverage-{version}-r2.json" not in names
    assert clause_coverage.default_paths() == (
        finals[-2] if len(finals) > 1 else spec_dir / f"clause_coverage-{version}.json",
        tip,
    )
    walked = [p.name for p in _walk_back(tip)]
    assert walked == [
        *(p.name for p in reversed(finals)),
        f"clause_coverage-{version}.json",
        "clause_coverage.json",
    ]
    children = _children(spec_dir)
    assert tip.name not in children
    for parent, child in zip(walked[1 : len(finals)], walked[: len(finals) - 1]):
        assert children[parent] == [child], parent


def test_final_chain_rejects_a_second_child_of_a_final_record(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    legacy = f"clause_coverage-{version}.json"
    first = f"clause_coverage-{version}-spec-major.json"
    second = f"clause_coverage-{version}-spec-major-2.json"
    _write_json(spec_dir / legacy, {})
    _write_json(spec_dir / first, {"supersedes": f"paper/cpc/data/spec/{legacy}"})
    _write_json(spec_dir / second, {"supersedes": f"paper/cpc/data/spec/{first}"})
    assert [p.name for p in clause_coverage.final_chain(spec_dir, version)] == [
        first,
        second,
    ]

    fork = spec_dir / f"clause_coverage-{version}-a0b1c2d3-r2.json"
    _write_json(fork, {"supersedes": f"paper/cpc/data/spec/{first}"})
    with pytest.raises(SystemExit, match=f"2 records of data/spec supersede {first}"):
        clause_coverage.final_chain(spec_dir, version)

    fork.unlink()
    after_tip = spec_dir / f"clause_coverage-{version}-after-tip.json"
    _write_json(after_tip, {"supersedes": f"paper/cpc/data/spec/{second}"})
    with pytest.raises(SystemExit, match=f"1 records of data/spec supersede {second}"):
        clause_coverage.final_chain(spec_dir, version)


def test_final_chain_continues_through_capi_recounts(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    legacy = f"clause_coverage-{version}.json"
    first = f"clause_coverage-{version}-spec-major.json"
    second = f"clause_coverage-{version}-spec-major-2.json"
    capi1 = f"clause_coverage-{version}-capi-r1.json"
    capi2 = f"clause_coverage-{version}-capi-r2.json"
    _write_json(spec_dir / legacy, {})
    _write_json(spec_dir / first, {"supersedes": f"paper/cpc/data/spec/{legacy}"})
    _write_json(spec_dir / second, {"supersedes": f"paper/cpc/data/spec/{first}"})
    _write_json(spec_dir / capi1, {"supersedes": f"paper/cpc/data/spec/{second}"})
    _write_json(spec_dir / capi2, {"supersedes": f"paper/cpc/data/spec/{capi1}"})
    assert [p.name for p in clause_coverage.final_chain(spec_dir, version)] == [
        first,
        second,
        capi1,
        capi2,
    ]

    fork = spec_dir / f"clause_coverage-{version}-spec-major-fork.json"
    _write_json(fork, {"supersedes": f"paper/cpc/data/spec/{second}"})
    with pytest.raises(SystemExit, match=f"2 records of data/spec supersede {second}"):
        clause_coverage.final_chain(spec_dir, version)

    fork.unlink()
    after_tip = spec_dir / f"clause_coverage-{version}-after-tip.json"
    _write_json(after_tip, {"supersedes": f"paper/cpc/data/spec/{capi2}"})
    with pytest.raises(SystemExit, match=f"1 records of data/spec supersede {capi2}"):
        clause_coverage.final_chain(spec_dir, version)
