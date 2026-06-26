#!/usr/bin/env bash
# Prepare a release commit per docs/orgmode/contributing.org (items 1–6).
# Usage: scripts/release-prep.sh X.Y.Z
# Then open a PR (cargo-dist Release workflow runs plan on PRs), merge,
# and: git tag -s vX.Y.Z -m "vX.Y.Z" && git push origin main --tags
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VER="${1:?usage: $0 X.Y.Z}"

if ! [[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].*)?$ ]]; then
  echo "version must look like X.Y.Z" >&2
  exit 1
fi

echo "==> tests (default features)"
cargo test --locked

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

echo "==> Cargo.lock refresh"
cargo test --locked -q

echo "==> CHANGELOG via cog"
if ! command -v cog >/dev/null 2>&1; then
  echo "cog (cocogitto) required on PATH" >&2
  exit 1
fi
{
  sed -n '1,3p' CHANGELOG.md
  cog changelog
} > /tmp/CHANGELOG.md
mv /tmp/CHANGELOG.md CHANGELOG.md

echo "==> cbindgen header check"
if command -v cbindgen >/dev/null 2>&1; then
  scripts/regen-capi-headers.sh
fi

echo "==> stage release files"
git add Cargo.toml Cargo.lock meson.build pyproject.toml pyproject.chemfiles.toml \
  pixi.toml docs/source/conf.py src/lib.rs CHANGELOG.md \
  include/readcon-core.h 2>/dev/null || true

echo "Ready. Review, then:"
echo "  git commit -m \"maint: bump to v${VER}\""
echo "  # open PR so .github/workflows/release.yml runs dist plan"
echo "  # after merge:"
echo "  git tag -s v${VER} -m \"v${VER}\""
echo "  git push origin main --tags"
echo "  # crates_publish.yml + python_wheels.yml + cargo-dist Release run on the tag"
