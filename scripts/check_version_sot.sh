#!/usr/bin/env bash
# Fail when a package-version string disagrees with VERSION.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ver="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import read_version; print(read_version(), end="")')"
fail=0
die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

for f in CMakeLists.txt meson.build docs/source/conf.py build.rs; do
  if grep -q -F "$ver" "$f"; then
    die "$f embeds ${ver}; it must read VERSION"
  else
    ok "$f has no literal package version"
  fi
done
if ! grep -q 'CMAKE_CONFIGURE_DEPENDS' CMakeLists.txt || ! grep -q 'file(READ' CMakeLists.txt; then
  die "CMakeLists.txt must read VERSION and set CMAKE_CONFIGURE_DEPENDS"
else
  ok "CMakeLists.txt rereads VERSION on configure"
fi
if ! grep -q "files('VERSION')" meson.build; then
  die "meson.build must pass files('VERSION') to project()"
else
  ok "meson.build uses files('VERSION')"
fi
if ! grep -q 'VERSION' docs/source/conf.py || ! grep -q 'VERSION' build.rs; then
  die "conf.py or build.rs does not reference VERSION"
else
  ok "conf.py and build.rs reference VERSION"
fi

if grep -q -F "$ver" src/lib.rs src/python.rs; then
  die "Rust sources embed ${ver}"
else
  ok "Rust sources take the version from the package at compile time"
fi

org_pins=(
  docs/orgmode/index.org
  docs/orgmode/migrate.org
  docs/orgmode/getting-started.org
  docs/orgmode/bindings.org
  docs/orgmode/chemfiles-howto.org
  docs/orgmode/architecture.org
)
for f in "${org_pins[@]}"; do
  if grep -q -F "$ver" "$f"; then
    die "$f still embeds ${ver}; use @READCON_VERSION@"
  fi
  if ! grep -q '@READCON_VERSION@' "$f"; then
    die "$f is missing @READCON_VERSION@"
  fi
  rst="docs/source/$(basename "$f" .org).rst"
  org_count="$( { grep -o '@READCON_VERSION@' "$f" || true; } | wc -l | tr -d ' ')"
  rst_count="$( { grep -o -F "$ver" "$rst" || true; } | wc -l | tr -d ' ')"
  if [[ "$org_count" != "$rst_count" ]]; then
    die "$f has ${org_count} placeholders but $rst has ${rst_count} copies"
  else
    ok "$rst matches $f (${org_count})"
  fi
done

tutorial_org="$(grep -o -F "$ver" docs/orgmode/chemfiles-tutorial.org | wc -l | tr -d ' ')"
tutorial_rst="$(grep -o -F "$ver" docs/source/chemfiles-tutorial.rst | wc -l | tr -d ' ')"
if [[ "$tutorial_org" != "$tutorial_rst" || "$tutorial_org" == 0 ]]; then
  die "chemfiles-tutorial pin count org=${tutorial_org} rst=${tutorial_rst}"
else
  ok "chemfiles-tutorial pin count ${tutorial_org}"
fi
if ! grep -q "^VER=${ver}$" fortran/README.md; then
  die "fortran/README.md VER= line does not match VERSION"
else
  ok "fortran/README.md VER= line"
fi

python3 - "$ver" <<'PY'
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, "scripts")
from version_sot import changelog_headings

version = sys.argv[1]
root = pathlib.Path(".")
fail = 0


def die(msg: str) -> None:
    global fail
    print(f"ERROR: {msg}", file=sys.stderr)
    fail = 1


zen_path = root / ".zenodo.json"
zen = json.loads(zen_path.read_text(encoding="utf-8"))
creators = zen.get("creators") or []
if len(creators) != 1:
    die(".zenodo.json must list one creator")
elif creators[0].get("affiliation") != "TurtleTech ehf":
    die('.zenodo.json affiliation must be "TurtleTech ehf"')
elif creators[0].get("orcid") != "0000-0002-2393-8056":
    die(".zenodo.json ORCID must be 0000-0002-2393-8056")
else:
    print("OK: .zenodo.json affiliation and ORCID")

cite = (root / "CITATION.cff").read_text(encoding="utf-8")
if 'affiliation: "TurtleTech ehf"' not in cite:
    die('CITATION.cff must list affiliation "TurtleTech ehf"')
elif "0000-0002-2393-8056" not in cite:
    die("CITATION.cff is missing ORCID 0000-0002-2393-8056")
else:
    print("OK: CITATION.cff affiliation and ORCID")
code = json.loads((root / "codemeta.json").read_text(encoding="utf-8"))
authors = code.get("author") or []
aff = authors[0].get("affiliation") if authors else None
aff_name = aff.get("name") if isinstance(aff, dict) else aff
if aff_name != "TurtleTech ehf":
    die("codemeta.json affiliation must be TurtleTech ehf")
else:
    print("OK: codemeta.json affiliation")

lock = (root / "Cargo.lock").read_text(encoding="utf-8")
if not re.search(
    rf'name = "readcon-core"\nversion = "{re.escape(version)}"',
    lock,
):
    die("Cargo.lock readcon-core version does not match VERSION")
else:
    print("OK: Cargo.lock readcon-core entry")

changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
headings = changelog_headings(changelog)
if not headings or headings[0] != f"v{version}":
    die(f"CHANGELOG.md first heading is {headings[:1]}, expected v{version}")
else:
    print(f"OK: CHANGELOG.md first heading is v{version}")
if f"[v{version}]:" not in changelog:
    die("CHANGELOG.md is missing the compare link for the current version")
else:
    print("OK: CHANGELOG.md compare link")
if "<!-- towncrier release notes start -->" not in changelog:
    die("CHANGELOG.md is missing the towncrier start marker")
else:
    print("OK: towncrier start marker")

import importlib.util

meta = root / "readcon_meta.py"
text = meta.read_text(encoding="utf-8")
if version in text:
    die("readcon_meta.py embeds the version; it must read VERSION")
else:
    print("OK: readcon_meta.py reads VERSION")
spec = importlib.util.spec_from_file_location("readcon_meta", meta)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
if module.__version__ != version:
    die(f"readcon_meta.__version__ is {module.__version__!r}")
else:
    print("OK: readcon_meta.__version__")

town = (root / "towncrier.toml").read_text(encoding="utf-8")
if version in town:
    die("towncrier.toml embeds the version; it must import readcon_meta")
elif 'package = "readcon_meta"' not in town:
    die("towncrier.toml must import readcon_meta")
else:
    print("OK: towncrier.toml points at readcon_meta")

allow_exact = {
    "VERSION",
    "CHANGELOG.md",
    "Cargo.lock",
    "fuzz/Cargo.lock",
    "Cargo.toml",
    "pyproject.toml",
    "pyproject.chemfiles.toml",
    "pixi.toml",
    "julia/ReadCon/Project.toml",
    "julia/ReadCon/README.md",
    "fortran/ReadCon/fpm.toml",
    "fortran/ReadCon/src/readcon.f90",
    "fortran/README.md",
    "docs/orgmode/chemfiles-tutorial.org",
    "CITATION.cff",
    ".zenodo.json",
    "codemeta.json",
    "include/readcon-core-version.h",
    "packaging/wrapdb/readcon-core.wrap",
    "README.md",
    # Cargo writes the path dependency's version into these lockfiles.
    # A lockfile that omits it is not a lockfile cargo will keep.
    "paper/cpc/bench/mpi_cost/Cargo.lock",
    "paper/cpc/bench/dlpack_cost/Cargo.lock",
    "paper/cpc/bench/readcon-bench/Cargo.lock",
    "tests/minimage-link/Cargo.lock",
    # The release-guard fixtures name the current package version on purpose.
    "tests/python/test_check_release_artifacts.py",
    # The one macro the paper reads. scripts/cargo_version_tex.py writes
    # it from Cargo.toml, and the Snakemake rule cargo_version runs that.
    "paper/cpc/src/cargo_version.tex",
}
# gen_spec_supp.py records a measured release-preparation tree in a
# version-named file. An unmeasured release is pending, not a reason to
# manufacture a placeholder record.
spec_measurement = f"paper/cpc/data/spec/spec-measurement-{version}.json"
if (root / spec_measurement).is_file():
    allow_exact.add(spec_measurement)
else:
    print(f"PENDING: {spec_measurement} has not been measured")
# The measured file is the rerun of gen_spec_supp.py --measure. It names
# the stored record in supersedes. The stored file stays byte-identical.
spec_measured = f"paper/cpc/data/spec/spec-measurement-{version}-measured.json"
if (root / spec_measured).is_file():
    allow_exact.add(spec_measured)
else:
    print(f"PENDING: {spec_measured} has not been measured")
# A later rerun writes -measured-<n>.json and supersedes the newest file.
for later in sorted((root / "paper/cpc/data/spec").glob(f"spec-measurement-{version}-measured-*.json")):
    allow_exact.add(later.relative_to(root).as_posix())
for extra in sorted(
    (root / "paper/cpc/data/spec").glob(f"spec-measurement-{version}-*.json")
):
    allow_exact.add(extra.relative_to(root).as_posix())
clause_coverage = f"paper/cpc/data/spec/clause_coverage-{version}.json"
if (root / clause_coverage).is_file():
    allow_exact.add(clause_coverage)
else:
    print(f"PENDING: {clause_coverage} has not been measured")
clause_recount = f"paper/cpc/data/spec/clause_coverage-{version}-recount.json"
if (root / clause_recount).is_file():
    allow_exact.add(clause_recount)
else:
    print(f"PENDING: {clause_recount} has not been measured")
# The sources file is the count clause_coverage.py writes. The recount stays
# byte-identical because it embeds the hand-entered REASONS text.
clause_sources = f"paper/cpc/data/spec/clause_coverage-{version}-sources.json"
if (root / clause_sources).is_file():
    allow_exact.add(clause_sources)
else:
    print(f"PENDING: {clause_sources} has not been measured")
for later in sorted((root / "paper/cpc/data/spec").glob(f"clause_coverage-{version}-sources-*.json")):
    allow_exact.add(later.relative_to(root).as_posix())
for extra in sorted(
    (root / "paper/cpc/data/spec").glob(f"clause_coverage-{version}-*.json")
):
    allow_exact.add(extra.relative_to(root).as_posix())
# The like-for-like rows, samples and summary name the build they measured.
# A later release must not rewrite those fields.
allow_exact.update({
    "paper/cpc/bench-like-for-like/results/rows.csv",
    "paper/cpc/bench-like-for-like/results/samples.csv",
    "paper/cpc/bench-like-for-like/results/summary.csv",
})
# Measured campaigns keep the package version they were timed with.
# A later release must not rewrite that field to VERSION.
recorded_results = {
    "bench/fidelity/results/fidelity.json",
    "bench/fidelity/results/timing.json",
    "bench/h2h/versions.json",
    "paper/cpc/data/claisen/readcon-build.json",
    "paper/cpc/data/spec/version_drift.json",
    "paper/cpc/data/spec/corpus_recount.json",
    "paper/cpc/data/spec/corpus_recount-2.json",
    *(
        later.relative_to(root).as_posix()
        for later in sorted((root / "paper/cpc/data/spec").glob("corpus_recount-*.json"))
    ),
}
skip_dirs = {
    ".git",
    "target",
    ".pixi",
    "bbdir",
    "builddir",
    "docs/build",
    "docs/doctrees",
    ".venv",
    "work",
}
# The bench/ tree is campaign harness, fixtures, and recorded rows. Its
# paths and payloads name the release they were measured with, so they
# are data, not package metadata. The library build and the cxx wrap
# both drop this tree wholesale (Cargo.toml ``exclude = ["bench/**"]``
# and scripts/package-cxx.sh), and the lockstep scan excludes it the
# same way. Any recorded-result file under bench/ is still version
# checked by the recorded_results walk below. bench/h2h/work is
# generated, gitignored output; the gate lists tracked files, so it is
# only reached by a stray walk, and this prefix drops it too.
skip_prefixes = (
    "bench/",
    "paper/cpc/bench/results/r0174/million/SUPERSEDED.md",
    # version_map.tex names the library that wrote it. That is a measurement.
    "paper/cpc/src/figures/generated/version_map.tex",
)
# The Claisen campaign records this package's version beside the Baker
# geometry source_commit. That commit is not a readcon-core commit, so
# the campaign file cannot itself satisfy the recorded-result walk. The
# append-only build record names the commit that stored the campaign,
# and the walk below requires the campaign's readcon version to be the
# VERSION of that commit. Exempting the campaign without that check
# would let the embedded version drift.
measured_campaigns = set()
for rel in sorted(recorded_results):
    build_path = root / rel
    if not build_path.is_file():
        continue
    named = json.loads(build_path.read_text(encoding="utf-8")).get("record")
    if isinstance(named, str):
        measured_campaigns.add(named)
bad = []
listed = subprocess.check_output(["git", "ls-files", "-z"])
for raw in listed.split(b"\0"):
    if not raw:
        continue
    rel = raw.decode()
    path = root / rel
    if not path.is_file():
        continue
    parts = set(pathlib.PurePosixPath(rel).parts)
    if rel.startswith(skip_prefixes) or parts & skip_dirs or any(part in skip_dirs for part in parts):
        continue
    if (
        rel in allow_exact
        or rel in recorded_results
        or rel in measured_campaigns
        or rel.startswith("docs/source/") and rel.endswith(".rst")
    ):
        continue
    try:
        data = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    # A comparison pin such as ``trio>=0.22.0`` is not this package.
    # A conda build string such as ``libpsl-0.23.1-hd9e3e90_1`` is not either.
    # A conda upper bound can contain these digits followed by a letter.
    # Require a version token boundary so that pin is not this package.
    if re.search(
        rf"(?<![0-9A-Za-z.>=<~^-]){re.escape(version)}(?![0-9A-Za-z.-])",
        data,
    ):
        bad.append(rel)
if bad:
    die("package version embedded outside the allowlist: " + ", ".join(bad))
else:
    print("OK: no stray package-version strings")

required = sorted(allow_exact - {"VERSION", "CHANGELOG.md", "Cargo.lock"})
measured = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?$")
for rel in sorted(recorded_results):
    payload = json.loads((root / rel).read_text(encoding="utf-8"))
    found = []
    source_commits = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("readcon", "readcon_version"):
                value = node.get(key)
                if isinstance(value, str) and measured.fullmatch(value):
                    found.append(value)
            source_commit = node.get("source_commit")
            if isinstance(source_commit, str):
                source_commits.append(source_commit)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    versions = sorted(set(found))
    if len(versions) != 1:
        die(f"{rel} must record one measured readcon version, found {versions}")
        continue
    recorded = versions[0]
    commits = sorted(set(source_commits))
    commits_ok = True
    if not commits:
        tagged = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/tags/v{recorded}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if tagged.returncode != 0:
            die(f"{rel} records readcon {recorded} but has no source_commit or v{recorded} tag")
            commits_ok = False
            continue
        commits = [tagged.stdout.strip()]
    for commit in commits:
        shown = subprocess.run(
            ["git", "show", f"{commit}:VERSION"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        source_version = shown.stdout.strip()
        if shown.returncode != 0:
            die(f"{rel} source_commit {commit} has no readable VERSION")
            commits_ok = False
        elif source_version != recorded:
            die(
                f"{rel} records readcon {recorded}, but source_commit {commit} "
                f"records VERSION {source_version!r}"
            )
            commits_ok = False
        else:
            print(f"OK: {rel} records measured readcon {recorded} from {commit}")
    named = payload.get("record")
    if commits_ok and isinstance(named, str):
        named_path = root / named
        if not named_path.is_file():
            die(f"{rel} names {named}, which is absent")
        else:
            if len(source_commits) != 1 or not re.fullmatch(
                r"[0-9a-f]{40}", source_commits[0]
            ):
                die(
                    f"{rel} names {named} and must record one 40-char source_commit, "
                    f"found {source_commits}"
                )
            else:
                record_commit = source_commits[0]
                touched = subprocess.run(
                    [
                        "git",
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        "--root",
                        record_commit,
                        "--",
                        named,
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                if touched.returncode != 0 or named not in touched.stdout.splitlines():
                    die(f"{rel} source_commit {record_commit} did not store {named}")
                stored = subprocess.run(
                    ["git", "cat-file", "blob", f"{record_commit}:{named}"],
                    cwd=root,
                    capture_output=True,
                )
                if stored.returncode != 0 or stored.stdout != named_path.read_bytes():
                    die(f"{named} does not match {record_commit}:{named}")

            named_versions = []

            def collect(node, into=named_versions):
                if isinstance(node, dict):
                    for key in ("readcon", "readcon_version"):
                        value = node.get(key)
                        if isinstance(value, str) and measured.fullmatch(value):
                            into.append(value)
                    for child in node.values():
                        collect(child)
                elif isinstance(node, list):
                    for child in node:
                        collect(child)

            collect(json.loads(named_path.read_text(encoding="utf-8")))
            named_found = sorted(set(named_versions))
            if named_found != [recorded]:
                die(f"{named} must record readcon {recorded}, found {named_found}")
            else:
                print(f"OK: {named} records measured readcon {recorded} via {rel}")
for rel in required:
    data = (root / rel).read_text(encoding="utf-8")
    if version not in data:
        die(f"{rel} does not contain {version}")
    else:
        print(f"OK: {rel} contains {version}")

if fail:
    sys.exit(1)
PY

if [[ "$fail" -ne 0 ]]; then
  echo "check_version_sot: FAILED" >&2
  exit 1
fi
echo "check_version_sot: all checks passed"
