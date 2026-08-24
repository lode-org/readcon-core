#!/usr/bin/env bash
# Prepare a release commit per docs/orgmode/contributing.org.
# Usage: scripts/release-prep.sh X.Y.Z
# Requires: cog, prek, pixi (docs env), lychee. cargo test unless
# READCON_RELEASE_PREP_SKIP_TESTS=1 (run tests on the remote builder).
# Then open a PR (cargo-dist Release workflow runs plan on PRs), merge,
# and: git tag -s vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VER="${1:?usage: $0 X.Y.Z}"

if ! [[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].*)?$ ]]; then
  echo "version must look like X.Y.Z" >&2
  exit 1
fi

for cmd in cog prek pixi lychee; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd required on PATH" >&2
    exit 1
  fi
done

if [[ "${READCON_RELEASE_PREP_SKIP_TESTS:-}" == 1 ]]; then
  echo "==> tests skipped (READCON_RELEASE_PREP_SKIP_TESTS=1)"
else
  echo "==> tests (default features)"
  cargo test --locked
fi

echo "==> version bump -> $VER"
# Cargo.toml package version (first occurrence)
sed -i "0,/^version = /{s/^version = \".*\"/version = \"${VER}\"/}" Cargo.toml
sed -i "s/^    version: '.*'/    version: '${VER}'/" meson.build
sed -i "0,/^version = /{s/^version = \".*\"/version = \"${VER}\"/}" pyproject.toml
sed -i "0,/^version = /{s/^version = \".*\"/version = \"${VER}\"/}" pyproject.chemfiles.toml
# Keep optional extra pin in lockstep with the chemfiles distribution.
sed -i "s/readcon-chemfiles==[0-9.][0-9.]*/readcon-chemfiles==${VER}/" pyproject.toml
sed -i "0,/^version = /{s/^version = \".*\"/version = \"${VER}\"/}" pixi.toml
sed -i "s/^release = \".*\"/release = \"${VER}\"/" docs/source/conf.py
# lib.rs version assertion
sed -i "s/assert_eq!(VERSION, \"[^\"]*\")/assert_eq!(VERSION, \"${VER}\")/" src/lib.rs
sed -i "s/^version = \".*\"/version = \"${VER}\"/" fortran/ReadCon/fpm.toml
sed -i "s/^version = \".*\"/version = \"${VER}\"/" julia/ReadCon/Project.toml
sed -i "s/^version: .*/version: ${VER}/" CITATION.cff
# First JSON "version" key in each metadata file.
sed -i "0,/\"version\": /{s/\"version\": \"[^\"]*\"/\"version\": \"${VER}\"/}" codemeta.json
sed -i "0,/\"version\": /{s/\"version\": \"[^\"]*\"/\"version\": \"${VER}\"/}" .zenodo.json

echo "==> Cargo.lock refresh"
if [[ "${READCON_RELEASE_PREP_SKIP_TESTS:-}" == 1 ]]; then
  echo "skipping cargo test --locked; refresh Cargo.lock on the builder"
else
  cargo test --locked -q
fi

echo "==> CHANGELOG via cog"
# Full-history `cog changelog` fails on pre-v0.14 commits whose types
# are not conventional (`docs+bench:`, untyped merges). Generate the
# new section from the previous tag and keep existing ## v* sections.
# cog titles an untagged range "## Unreleased (...)"; retitle to
# ## vX.Y.Z so a shipped tag never dumps Unreleased at the tip.
prev="$(git describe --tags --abbrev=0)"
{
  sed -n '1,3p' CHANGELOG.md
  cog changelog "${prev}.." \
    | sed "s/^## Unreleased.*/## v${VER} - $(date +%F)/"
  echo
  awk '/^## v/{found=1} found' CHANGELOG.md
} > /tmp/CHANGELOG.md
mv /tmp/CHANGELOG.md CHANGELOG.md
if grep -q '^## Unreleased' CHANGELOG.md; then
  echo "CHANGELOG.md still has Unreleased; shipped tags must not dump it" >&2
  exit 1
fi

echo "==> prek"
prek run -a

echo "==> docs (orgbld + sphinx) and lychee"
pixi r -e docs docbld
pixi r -e docs linkcheck

echo "==> C/C++ distribution gate (no cbindgen required)"
scripts/check-cxx-dist.sh

echo "==> cbindgen header check (maintainer tool; optional)"
if command -v cbindgen >/dev/null 2>&1; then
  scripts/regen-capi-headers.sh
else
  echo "cbindgen not on PATH; leaving shipped include/readcon-core.h unchanged"
fi

echo "==> stage release files"
git add Cargo.toml Cargo.lock meson.build pyproject.toml pyproject.chemfiles.toml \
  pixi.toml docs/source/conf.py src/lib.rs CHANGELOG.md \
  include/readcon-core.h cmake/ fortran/ReadCon/fpm.toml \
  julia/ReadCon/Project.toml CITATION.cff codemeta.json .zenodo.json \
  2>/dev/null || true

echo "Ready. Review, then:"
echo "  git commit -m \"maint: bump to v${VER}\""
echo "  # open PR so .github/workflows/release.yml runs dist plan"
echo "  # after merge:"
echo "  git tag -s v${VER} -m \"v${VER}\""
echo "  git push origin v${VER}"
echo "  # crates_publish.yml + python_wheels.yml + cargo-dist Release + cxx_tarball.yml"
echo "  # + c_lib_tarball.yml (or dispatch later with tag=v${VER})"
echo "  # After the tag: scripts/package-cxx.sh dist/ --vendor"
echo "  # Attach readcon-core-cxx-${VER}.tar.gz to the GitHub Release (cxx_tarball.yml)"
echo "  # Attach readcon-core-clib-${VER}-\$target.tar.gz (c_lib_tarball.yml;"
echo "  #   Actions → C ABI library tarball → tag=v${VER} on a branch that has the workflow)"
