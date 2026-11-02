#!/usr/bin/env bash
# Restamp generated package-version copies from VERSION.
# cogapp: https://cog.readthedocs.io/en/latest/
# Run from anywhere; the script cds to the repository root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import read_version; read_version()'

mapfile -t files < <(python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import marker_files; print("\n".join(marker_files()))')
if [[ "${#files[@]}" -eq 0 ]]; then
  echo "stamp-version: no cogapp markers" >&2
  exit 1
fi
python3 -m cogapp -r "${files[@]}"
while IFS=$'\t' read -r out src; do
  python3 -m cogapp -d -o "$out" "$src"
done < <(python3 -c 'import sys; sys.path.insert(0, "scripts"); from version_sot import generated_targets; print("\n".join(f"{out}\t{src}" for out, src in generated_targets()))')

# Two prose pins stay literal. Neighboring lines make an in-file cog
# marker a poor fit; rewrite the pin from VERSION here.
python3 - <<'PY'
import re
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from version_sot import read_version

version = read_version()
readme = Path("fortran/README.md")
text = readme.read_text(encoding="utf-8")
updated, count = re.subn(r"^VER=.*$", f"VER={version}", text, count=1, flags=re.M)
if count != 1:
    raise SystemExit("fortran/README.md is missing VER=")
readme.write_text(updated, encoding="utf-8")

tutorial = Path("docs/orgmode/chemfiles-tutorial.org")
text = tutorial.read_text(encoding="utf-8")
updated, count = re.subn(
    r"readcon-chemfiles==[^'\"\s]+",
    f"readcon-chemfiles=={version}",
    text,
    count=1,
)
if count != 1:
    raise SystemExit("docs/orgmode/chemfiles-tutorial.org is missing the install pin")
tutorial.write_text(updated, encoding="utf-8")
PY
echo "stamp-version: cogapp output matches VERSION"
