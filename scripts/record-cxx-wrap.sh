#!/usr/bin/env bash
# Pin the Meson wrap to one slim cxx archive.
#
# The digest, the wrap file, and the FetchContent snippets are written
# from this build. The vendor tarball is a different archive and must
# not supply the pin. packaging/wrapdb is omitted from the archive, so
# committing the pin does not change the digest.
#
# The epoch is the v$VERSION tag's committer date when that tag exists,
# otherwise HEAD. It is saved next to the digest. Later package-cxx.sh
# runs read that pin, including a shallow CI checkout of the tagged commit.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

epoch="$(bash "$ROOT/scripts/source-date-epoch.sh" --fresh "$ROOT")"
printf '%s\n' "$epoch" > "$ROOT/packaging/wrapdb/source-date-epoch"
export SOURCE_DATE_EPOCH="$epoch"

out="$(scratch_dir)"
trap 'rm -rf "$out"' EXIT
bash "$ROOT/scripts/package-cxx.sh" "$out"

ver="$(tr -d '[:space:]' < "$ROOT/VERSION")"
archive="readcon-core-cxx-${ver}.tar.gz"
sha="$(tr -d '[:space:]' < "$out/${archive}.sha256")"
if [[ ! "$sha" =~ ^[0-9a-f]{64}$ ]]; then
    echo "record-cxx-wrap: slim archive has no sha256" >&2
    exit 1
fi

printf '%s\n' "$sha" > "$ROOT/packaging/wrapdb/readcon-core.sha256"
python3 - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from version_sot import render_wrap

Path("packaging/wrapdb/readcon-core.wrap").write_text(
    render_wrap(), encoding="utf-8"
)
PY

python3 - "$sha" <<'PY'
import re
import sys
from pathlib import Path

sha = sys.argv[1]
files = (
    "docs/source/getting-started.rst",
    "docs/source/bindings.rst",
    "docs/orgmode/getting-started.org",
    "docs/orgmode/bindings.org",
)
pattern = re.compile(r"SHA256=[0-9a-f]{64}")
for rel in files:
    path = Path(rel)
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(f"SHA256={sha}", text)
    if count < 1:
        raise SystemExit(f"{rel} has no SHA256= pin")
    path.write_text(updated, encoding="utf-8")
PY

echo "record-cxx-wrap: ${archive} sha256:${sha}"
echo "SOURCE_DATE_EPOCH=${epoch}"
echo "Commit this pin with the cxx tarball job. It refuses an upload whose digest differs."
