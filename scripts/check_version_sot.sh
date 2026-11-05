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
    # The one macro the paper reads. scripts/cargo_version_tex.py writes
    # it from Cargo.toml, and the Snakemake rule cargo_version runs that.
    "paper/cpc/src/cargo_version.tex",
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
# bench/h2h/work is generated campaign output. It is gitignored, and a
# full-tree walk would still open it. The gate lists tracked files and
# also skips this prefix.
skip_prefixes = ("bench/h2h/work/",)
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
    if rel in allow_exact or rel.startswith("docs/source/") and rel.endswith(".rst"):
        continue
    try:
        data = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    if version in data:
        bad.append(rel)
if bad:
    die("package version embedded outside the allowlist: " + ", ".join(bad))
else:
    print("OK: no stray package-version strings")

required = sorted(allow_exact - {"VERSION", "CHANGELOG.md", "Cargo.lock"})
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
