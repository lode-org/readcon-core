#!/usr/bin/env bash
# Release version bump.
# 1. Write VERSION.
# 2. The release heading comes from towncrier when changelog.d has fragments.
#    Otherwise the written ## Unreleased section is retitled. Towncrier
#    would insert "No significant changes" and leave those notes unreleased.
# 3. python -m cogapp stamps copies, including compare links, which need that heading.
# https://towncrier.readthedocs.io/en/stable/
# https://cog.readthedocs.io/en/latest/
# Usage: scripts/bump-version.sh X.Y.Z
# cog.toml pre_bump_hooks runs this. cocogitto does not write a second heading.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VER="${1:?usage: bump-version.sh X.Y.Z}"

python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import accept_version; accept_version(sys.argv[1])' "$VER"
OLD="$(python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import read_version; print(read_version(), end="")')"

printf '%s\n' "$VER" > VERSION
python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import refresh_rendered_pins; refresh_rendered_pins(sys.argv[1], sys.argv[2])' "$OLD" "$VER"
fragments=()
if [[ -d changelog.d ]]; then
    while IFS= read -r -d '' fragment; do
        fragments+=("$fragment")
    done < <(find changelog.d -type f \( -name '*.rst' -o -name '*.md' \) ! -name 'README*' -print0)
fi
if [[ ${#fragments[@]} -gt 0 ]]; then
    if grep -q '^## Unreleased$' CHANGELOG.md; then
        echo "bump-version: changelog.d fragments and a written ## Unreleased section would both become the release" >&2
        exit 1
    fi
    python3 -m towncrier build --yes --version "$VER"
else
    python3 - "$VER" <<'PY'
import datetime
import pathlib
import sys

version = sys.argv[1]
path = pathlib.Path("CHANGELOG.md")
text = path.read_text(encoding="utf-8")
heading = "## Unreleased\n"
if heading not in text:
    raise SystemExit(
        "CHANGELOG.md has no ## Unreleased section and changelog.d has no fragments"
    )
replacement = f"## v{version} - {datetime.date.today().isoformat()}\n"
path.write_text(text.replace(heading, replacement, 1), encoding="utf-8")
PY
fi
# stamp-version does not retarget packaging/wrapdb/readcon-core.wrap.
# That URL stays on the previous archive until record-cxx-wrap.sh has a digest.
bash "$ROOT/scripts/stamp-version.sh"

python3 - "$VER" <<'PY'
import re
import sys
from pathlib import Path

version = sys.argv[1]
for path in (Path("Cargo.lock"), Path("fuzz/Cargo.lock")):
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(name = "readcon-core"\nversion = ")[^"]+(")',
        rf"\g<1>{version}\2",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"{path} is missing the readcon-core package entry")
    path.write_text(updated, encoding="utf-8")
PY

echo "bump-version: VERSION is ${VER}"
