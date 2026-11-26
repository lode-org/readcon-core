"""Every tag and commit the paper names is an object in this repository.

A shallow checkout has no tags. The assertions that call git skip then.
A job that fetches the full history and the tags runs them.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc" / "src"
CURRENT_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
HEX = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
TAG = re.compile(r"\bv(\d+\.\d+\.\d+)\b")
COMMAND = re.compile(r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]+)\}")
COMMIT_NAMES = (
    "readconcommit",
    "readconcommitshort",
    "readconpublishedcommit",
    "readconpbccommit",
    "readconrcidxcommit",
    "readconbase",
    "rcLatestTagCommit",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _macros() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in CPC.rglob("*.tex"):
        for name, value in COMMAND.findall(path.read_text(encoding="utf-8")):
            found[name] = value
    return found


def _tags() -> list[str]:
    listed = _git("tag", "-l", "v[0-9]*")
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def _has_measurement_record(version: str) -> bool:
    """Return whether a benchmark record directory names this version."""
    h2h = ROOT / "bench" / "h2h"
    return any(
        path.is_dir() and path.name == f"v{version}" for path in h2h.glob("*/v*")
    )


def test_measurement_exemption_requires_a_record_directory() -> None:
    assert _has_measurement_record("0.23.3")
    assert not _has_measurement_record("9.9.9")


def test_named_commits_and_tags_exist() -> None:
    macros = _macros()
    assert macros["readconversion"] == "0.17.3"
    assert macros["readconcommitrole"] == "measured commit"
    assert macros["readconversion"] == macros["rcMeasuredVersion"]
    assert "v0.17.4" not in (CPC / "release.tex").read_text(encoding="utf-8")
    if not _tags():
        pytest.skip("this clone has no release tags")
    missing: list[str] = []
    for name in COMMIT_NAMES:
        value = macros[name]
        if _git("rev-parse", "--verify", f"{value}^{{commit}}").returncode != 0:
            missing.append(f"{name} {value}")
    full = HEX.findall((CPC / "rg_main.tex").read_text(encoding="utf-8"))
    full += HEX.findall((CPC / "commit.tex").read_text(encoding="utf-8"))
    for value in full:
        if len(value) < 40:
            continue
        if _git("cat-file", "-e", f"{value}^{{commit}}").returncode != 0:
            missing.append(value)
    tag = macros["rcLatestTag"]
    if _git("rev-parse", "--verify", f"refs/tags/v{tag}^{{}}").returncode != 0:
        missing.append(f"v{tag}")
    for text in (
        (CPC / "release.tex").read_text(encoding="utf-8"),
        (CPC / "rg_main.tex").read_text(encoding="utf-8"),
    ):
        for match in TAG.finditer(text):
            version = match.group(1)
            if _has_measurement_record(version):
                continue
            if (
                _git("rev-parse", "--verify", f"refs/tags/v{version}^{{}}").returncode
                != 0
            ):
                missing.append(f"v{version}")
    assert not missing, missing


def _external_pin(lines: list[str], digest: str) -> bool:
    """A 40-digit pin of another project, not a commit of this repository."""
    markers = (
        "gitlab.com",
        "github.com",
        "githubusercontent.com",
        "huggingface.co",
        "lode-org/readcon-db",
        "EON_COMMIT",
        "READCON_DB_REV",
        "eon_commit",
        "readcon_db_rev",
    )
    for index, line in enumerate(lines):
        if digest not in line:
            continue
        window = "\n".join(lines[max(0, index - 2) : index + 3])
        if any(marker in window for marker in markers):
            return True
    return False


def _is_commit_or_tree(value: str) -> bool:
    kind = _git("cat-file", "-t", value)
    return kind.returncode == 0 and kind.stdout.strip() in {"commit", "tree"}


def _is_named_spec_blob(lines: list[str], value: str) -> bool:
    if not any('"spec_blob"' in line and value in line for line in lines):
        return False
    kind = _git("cat-file", "-t", value)
    return kind.returncode == 0 and kind.stdout.strip() == "blob"


# These records name the build that was measured, not this release.
# cpp_coords.json, cpp_vel.json and cachegrind_results.json name that
# build's commit, ae4131ff. The others name readcon 0.17.4. settle.json
# and timings.json also name its commit, b65aa63d. versions.json records
# the specification's tags. The two eOn restart records also name eOn 3.6.0.
# cloud-runs-2/05/host.json names the commits of that measurement's build.
MEASUREMENT_RECORDS = frozenset(
    {
        "paper/cpc/bench/results/hcn_loss.json",
        "paper/cpc/bench/results/r0174/cachegrind/cachegrind_results.json",
        "paper/cpc/bench/results/r0174/h2h/cpp_coords.json",
        "paper/cpc/bench/results/r0174/h2h/cpp_vel.json",
        "paper/cpc/bench/results/r0174/binary_formats/build.json",
        "paper/cpc/bench/results/r0174/binary_formats/checks.json",
        "paper/cpc/bench/results/r0174/binary_formats/payloads.json",
        "paper/cpc/bench/results/r0174/binary_formats/settle.json",
        "paper/cpc/bench/results/r0174/binary_formats/timings.json",
        "paper/cpc/bench/results/r0174/h2h/payloads.json",
        "paper/cpc/bench/results/r0174/h2h/python_coords.json",
        "paper/cpc/bench/results/r0174/h2h/python_vel.json",
        "paper/cpc/bench/results/r0174/memray.json",
        "paper/cpc/bench/results/r0174/payloads.json",
        "paper/cpc/bench/results/r0174/provenance.json",
        "paper/cpc/bench/results/r0174/reads.json",
        "paper/cpc/bench/results/velocity_case.json",
        "paper/cpc/data/cloud-runs-2/05/host.json",
        "paper/cpc/data/corpus31-results.json",
        "paper/cpc/data/corpus_crosscheck.json",
        "paper/cpc/data/referee/r1h/corpus_crosscheck.json",
        "paper/cpc/data/referee/r1j/drift/drift_con.json",
        "paper/cpc/data/referee/r1j/drift/drift_extxyz.json",
        "paper/cpc/data/referee/r1t/mutant_differential.json",
        "paper/cpc/data/h2h/format_h2h_record.json",
        "paper/cpc/data/corpus_paths.json",
        "paper/cpc/data/every_path.json",
        "paper/cpc/data/failure/con_openers.json",
        "paper/cpc/data/failure/drift_con.json",
        "paper/cpc/data/failure/drift_extxyz.json",
        "paper/cpc/data/failure/matrix.json",
        "paper/cpc/data/failure/restart_bands.json",
        "paper/cpc/data/failure/restart_formats.json",
        "paper/cpc/data/failure/restart_kernels/cooperlake.json",
        "paper/cpc/data/failure/restart_kernels/haswell.json",
        "paper/cpc/data/failure/restart_kernels/nehalem.json",
        "paper/cpc/data/failure/restart_kernels/skylakex.json",
        "paper/cpc/data/failure/version_safety.json",
        "paper/cpc/data/referee_probes.json",
        "paper/cpc/data/sizes.json",
        "paper/cpc/data/restart_walls/restart_walls.json",
        "paper/cpc/data/spec/corpus_recount.json",
        # The model release is PET-MAD-S 1.1.0. The record keeps the
        # upstream file token, which is not a tag of this repository.
        "paper/cpc/data/claisen/results.json",
        *(
            p.relative_to(ROOT).as_posix()
            for p in sorted(
                (ROOT / "paper" / "cpc" / "data" / "spec").glob("clause_coverage*.json")
            )
        ),
        "paper/cpc/data/spec/mutant_differential.json",
        *(
            p.relative_to(ROOT).as_posix()
            for p in sorted(
                (ROOT / "paper" / "cpc" / "data" / "spec").glob(
                    "spec-measurement-*.json"
                )
            )
        ),
        "paper/cpc/data/spec/versions.json",
        "paper/cpc/data/survey_frame.json",
        "paper/cpc/data/worked_example.json",
        "paper/cpc/evidence/results/e1_restart.json",
        "paper/cpc/evidence/results/e1_restart_lbfgs_control.json",
        "paper/cpc/evidence/results/e5_prefactor.json",
        # Names the library that wrote each row, including the measured 0.17.4 builds.
        "paper/cpc/src/figures/generated/version_map.tex",
        # Names the readcon-core version of the library digest most of those records name.
        "paper/cpc/src/figures/generated/library_macros.tex",
        # The like-for-like harness names the revisions it measured.
        # Origin does not have those commits, so this clone cannot resolve them.
        "paper/cpc/bench-like-for-like/README.md",
        "paper/cpc/bench-like-for-like/pins.json",
        # The readcon-db db31 campaign records, copied verbatim from
        # lode-org/readcon-db ff1210e3. Each names the measured readcon-db
        # commit a584a288 and the commits it was compared against, not a tag
        # or a commit of this repository.
        "paper/cpc/data/db31/ase/ase_db_bench.json",
        "paper/cpc/data/db31/ase/host.json",
        "paper/cpc/data/db31/ase/RESULTS.md",
        "paper/cpc/data/db31/bisect/ab.json",
        "paper/cpc/data/db31/bisect/host.json",
        "paper/cpc/data/db31/bisect/RESULTS.md",
        "paper/cpc/data/db31/bisect/samples.json",
        "paper/cpc/data/db31/corpus-ops/readcon_db_bench.json",
        "paper/cpc/data/db31/db24/ab.json",
        "paper/cpc/data/db31/db24/campaign.log",
        "paper/cpc/data/db31/db24/levers.json",
        "paper/cpc/data/db31/db24/RESULTS.md",
        "paper/cpc/data/db31/db24/tables.json",
        "paper/cpc/data/db31/db25/ab.json",
        "paper/cpc/data/db31/db25/campaign.log",
        "paper/cpc/data/db31/db25/RESULTS.md",
        "paper/cpc/data/db31/db25/tables.json",
        "paper/cpc/data/db31/db26/ab.json",
        "paper/cpc/data/db31/db26/campaign.log",
        "paper/cpc/data/db31/db26/high_byte.json",
        "paper/cpc/data/db31/db26/RESULTS.md",
        "paper/cpc/data/db31/db26/tables.json",
        "paper/cpc/data/db31/db28/ab.json",
        "paper/cpc/data/db31/db28/campaign.log",
        "paper/cpc/data/db31/db28/host.json",
        "paper/cpc/data/db31/db28/RESULTS.md",
        "paper/cpc/data/db31/db29/ab.json",
        "paper/cpc/data/db31/db29/campaign.log",
        "paper/cpc/data/db31/db29/host.json",
        "paper/cpc/data/db31/db29/RESULTS.md",
        "paper/cpc/data/db31/fair-db31/campaign.json",
        "paper/cpc/data/db31/fair-db31/campaign.log",
        "paper/cpc/data/db31/fair-db31/noise.json",
        "paper/cpc/data/db31/fair-db31/RESULTS.md",
        "paper/cpc/data/db31/fair-db31/tables.json",
        # The readcon-db db30 campaign records that hold the one-million-atom
        # warm-read medians the paper reports as a range, copied verbatim from
        # lode-org/readcon-db ff1210e3. Each names the measured readcon-db
        # commit, not a tag or a commit of this repository.
        "paper/cpc/data/db30/db8/campaign.json",
        "paper/cpc/data/db30/fair-db30/campaign.json",
        # The readcon-db fair-db32 campaign store, the fair-ladder rerun that
        # moves the paper's fair-store numbers off fair-db31, copied verbatim
        # from lode-org/readcon-db 227e45cf. It names the measured readcon-db
        # commit d8bf1cb5, not a tag or a commit of this repository.
        "paper/cpc/data/db32/fair-db32/campaign.json",
        # The two-store fidelity field table, copied verbatim from
        # lode-org/readcon-db 0afbaa0b. rg_main.org cites that readcon-db
        # commit; the table itself names no tag or commit of this repository.
        "paper/cpc/data/db32/fair-fidelity/FIELDS.md",
    }
)


def _paper_sources() -> list[tuple[Path, str]]:
    root = ROOT / "paper" / "cpc"
    listings = root / "evidence" / "listings"
    suffixes = {".md", ".py", ".tex", ".json", ".log", ".org", ".bib", ".toml"}
    found: list[tuple[Path, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # paper/cpc/.pixi is the gitignored pixi environment. Generated
        # figures are gitignored too; regen writes them.
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if _git("check-ignore", "-q", "--", rel).returncode == 0:
            continue
        if rel in MEASUREMENT_RECORDS:
            continue
        # A TeX log is a build product. Package versions in it are not tags.
        if path.suffix == ".log" and path.parent == root / "src":
            continue
        if path.suffix in suffixes or listings in path.parents:
            found.append((path, path.read_text(encoding="utf-8", errors="replace")))
    return found


def _sha_context(line: str, digest: str) -> bool:
    """A short hash named as a commit, not a library digest."""
    if digest not in line:
        return False
    low = line.lower()
    if "digest" in low or "sha256" in low or "sha-256" in low:
        return False
    if "eon commit" in low or "eon commit" in line:
        return False
    if digest.isdigit() and "doi.org" in low:
        return False
    return "commit" in low or "revision" in low or f"`{digest}`" in line


def test_unpublished_identity_is_absent() -> None:
    for path, text in _paper_sources():
        assert "0.17.4" not in text, path
        assert "b65aa63d" not in text, path


def test_paper_sources_name_real_tags_and_commits() -> None:
    if not _tags():
        pytest.skip("this clone has no release tags")
    missing: list[str] = []
    full = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{40}(?![0-9A-Za-z])")
    for path, text in _paper_sources():
        rel = path.relative_to(ROOT)
        tag_text = text
        if path.suffix == ".bib":
            tag_text = "\n".join(
                line for line in text.splitlines() if "readcon" in line.lower()
            )
        for match in TAG.finditer(tag_text):
            version = match.group(1)
            # A directory name such as results/v0.23.3 is not a cited tag.
            if match.start() > 0 and tag_text[match.start() - 1] == "/":
                continue
            line_start = tag_text.rfind("\n", 0, match.start()) + 1
            line_end = tag_text.find("\n", match.end())
            line = tag_text[line_start : line_end if line_end >= 0 else None]
            # readcon-db's revision, not a tag of this repository.
            if "READCON_DB_REV" in line:
                continue
            # The results directory is named for this release. It is not a tag.
            if line.strip().startswith("VERSION ="):
                continue
            if _has_measurement_record(version):
                continue
            if (
                _git("rev-parse", "--verify", f"refs/tags/v{version}^{{}}").returncode
                != 0
            ):
                missing.append(f"{rel}: v{version}")
        lines = text.splitlines()
        short = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,39}(?![0-9A-Za-z])")
        seen: set[str] = set(full.findall(text))
        for value in short.findall(text):
            if any(_sha_context(line, value) for line in lines):
                seen.add(value)
        for value in seen:
            if _is_commit_or_tree(value):
                continue
            if _is_named_spec_blob(lines, value):
                continue
            if _external_pin(lines, value):
                continue
            missing.append(f"{rel}: {value}")
    assert not missing, missing


def test_shipped_spec_blob_is_the_measured_commit() -> None:
    supp = (CPC / "rg_supp.tex").read_text(encoding="utf-8")
    assert r"\rcMeasuredSpecBlob" in supp
    release = (CPC / "release.tex").read_text(encoding="utf-8")
    assert r"\rcMeasuredSpecBlob" in release
    assert "rcReleaseSpecBlob" not in release

    scripts_dir = ROOT / "paper" / "cpc" / "scripts"
    import sys

    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "gen_spec_supp", scripts_dir / "gen_spec_supp.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        org = (ROOT / "docs" / "orgmode" / "spec.org").read_text(encoding="utf-8")
        rows = module.history_rows(org)
        versions = [row["version"] for row in rows]
        assert "4.0.0" in versions and "4.0.4" in versions, versions
        macros = module.spec_macros(org)
        assert r"\newcommand{\specTextRelease}" in macros
        assert module.release_rows(org)
    finally:
        sys.path.remove(str(scripts_dir))


def test_measured_commit_matches_its_cargo_and_spec() -> None:
    macros = _macros()
    commit = macros["readconcommit"]
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        pytest.skip("the named commit is not in this clone")
    show = _git("show", f"{commit}:Cargo.toml")
    found = re.search(r'^version = "([^"]+)"', show.stdout, re.M)
    assert found is not None
    assert found.group(1) == macros["rcMeasuredVersion"]
    spec = _git("rev-parse", f"{commit}:docs/orgmode/spec.org")
    assert spec.returncode == 0
    assert spec.stdout.strip().startswith(macros["rcMeasuredSpecBlob"])
    assert macros["rcMeasuredVersion"] == macros["readconversion"]
    assert macros["readconcommitrole"] == "measured commit"


def test_recorded_tags_match_git() -> None:
    if not _tags():
        pytest.skip("this clone has no release tags")
    spec = importlib.util.spec_from_file_location(
        "measured_versions",
        ROOT / "paper" / "cpc" / "scripts" / "measured_versions.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    version, commit = module.latest_tag()
    newest = ""
    listed = _git("tag", "-l", "v[0-9]*", "--sort=-v:refname")
    for line in listed.stdout.splitlines():
        if re.fullmatch(r"v\d+\.\d+\.\d+", line.strip()):
            newest = line.strip()
            break
    assert newest == f"v{version}"
    peeled = _git("rev-parse", f"refs/tags/v{version}^{{}}")
    assert peeled.returncode == 0
    assert peeled.stdout.strip() == commit
    release = module.release_version()
    tagged = _git("rev-parse", f"refs/tags/v{release}^{{}}")
    assert tagged.returncode == 0
    log = (ROOT / "paper" / "cpc" / "logs" / "reader-exchange.log").read_text(
        encoding="utf-8"
    )
    named = next(
        line.split()[1]
        for line in log.splitlines()
        if line.startswith("release_commit ")
    )
    assert tagged.stdout.strip() == named


def test_provenance_uses_the_latest_library_source_commit() -> None:
    path = ROOT / "paper" / "cpc" / "scripts" / "provenance.py"
    spec = importlib.util.spec_from_file_location("paper_provenance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = _git(
        "log", "-1", "--format=%H", "HEAD", "--", *module.LIBRARY_PATHS
    ).stdout.strip()
    identity = module.source_identity()
    assert identity["source_commit"] == expected
    assert module.library_digest_at(expected) == identity["library_digest"]
