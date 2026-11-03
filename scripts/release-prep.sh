#!/usr/bin/env bash
# Prepare a release commit per docs/orgmode/contributing.org.
# Usage: scripts/release-prep.sh X.Y.Z
# Requires: prek, pixi (docs env), lychee, and the pins in
# requirements-version.txt (cogapp and towncrier). cargo test unless
# READCON_RELEASE_PREP_SKIP_TESTS=1 (run tests on the remote builder).
# Then open a PR (cargo-dist Release workflow runs plan on PRs), merge,
# and: git tag -s vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VER="${1:?usage: $0 X.Y.Z}"

python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import accept_version; accept_version(sys.argv[1])' "$VER"

for cmd in prek pixi lychee; do
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
# Towncrier writes the heading, then cogapp stamps compare links.
# https://towncrier.readthedocs.io/en/stable/
# https://cog.readthedocs.io/en/latest/
bash scripts/bump-version.sh "$VER"
if ! grep -q '<!-- towncrier release notes start -->' CHANGELOG.md; then
  echo "CHANGELOG.md lost the towncrier marker" >&2
  exit 1
fi
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
git add VERSION Cargo.toml Cargo.lock fuzz/Cargo.lock meson.build pyproject.toml pyproject.chemfiles.toml \
  pixi.toml docs/source/conf.py src/lib.rs build.rs CHANGELOG.md changelog.d \
  include/readcon-core.h include/readcon-core-version.h include/readcon-core.hpp \
  cmake/ fortran/ReadCon/fpm.toml fortran/ReadCon/src/readcon.f90 fortran/README.md \
  julia/ReadCon/Project.toml julia/ReadCon/README.md CITATION.cff codemeta.json .zenodo.json \
  packaging/wrapdb/readcon-core.wrap towncrier.toml readcon_meta.py docs/source docs/orgmode \
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
