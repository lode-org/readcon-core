#!/usr/bin/env bash
# Write one release version into every file that records it. cog.toml runs
# this as a pre-bump hook, so the tag and the published packages agree.
set -euo pipefail
v=${1:?usage: set-version.sh VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
# The outgoing version, read before Cargo.toml changes; install pins in the
# docs match on it so unrelated version numbers stay as they are.
old=$(sed -n -E 's/^version = "([^"]*)"$/\1/p' Cargo.toml | head -n 1)
o=${old//./\\.}
# First version key only: the package's own, not a dependency's.
sed -i -E "0,/^version = \"[^\"]*\"/s//version = \"$v\"/" Cargo.toml pyproject.toml \
    pyproject.chemfiles.toml pixi.toml julia/ReadCon/Project.toml fortran/ReadCon/fpm.toml
sed -i -E "s/readcon-chemfiles==$o\"/readcon-chemfiles==$v\"/" pyproject.toml
sed -i -E "s/assert_eq!\(VERSION, \"$o\"\)/assert_eq!(VERSION, \"$v\")/" src/lib.rs
sed -i -E "s/^release = \"[^\"]*\"/release = \"$v\"/" docs/source/conf.py
sed -i -E "s/^VER=.*/VER=$v/" julia/ReadCon/README.md fortran/README.md
# Install pins and version statements in the docs. The cxx tarball URL and
# its SHA256 name the published archive and move after the release does.
# Grid-table rows keep their column borders: a longer version takes its
# extra characters out of the padding before the next cell border.
python3 - "$old" "$v" docs/source/*.rst docs/orgmode/*.org <<'PY'
import re
import sys

old, new, *paths = sys.argv[1:]
o = re.escape(old)
patterns = [
    rf"(readcon(?:-chemfiles)?)=={o}\b",
    rf"readcon-core@{o}\b",
    rf"this tree \((``|=){o}(``|=)\)",
    rf"Fortran package are {o}\.",
]
pattern = re.compile("|".join(f"(?:{p})" for p in patterns))
delta = len(new) - len(old)


def rewrite(line):
    out, pos = [], 0
    for m in pattern.finditer(line):
        out.append(line[pos:m.start()])
        out.append(m.group(0).replace(old, new))
        pos = m.end()
    out.append(line[pos:])
    text = "".join(out)
    grid = re.match(r"\s*\|.*\|\s*$", line)
    if grid and delta and text != line:
        cells = text.split("|")
        for i, cell in enumerate(cells[1:-1], start=1):
            if old in line.split("|")[i] and new in cell:
                pad = len(cell) - len(cell.rstrip(" "))
                if delta > 0 and pad > delta:
                    cells[i] = cell[: len(cell) - delta]
                elif delta < 0:
                    cells[i] = cell + " " * -delta
        text = "|".join(cells)
    return text


for path in paths:
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rewrite(line) for line in lines))
PY
# The lock entry of the crate itself sits on the line after its name.
sed -i -E "/^name = \"readcon-core\"$/{n;s/^version = \"[^\"]*\"/version = \"$v\"/}" Cargo.lock
sed -i -E "0,/^    version: '[^']*',/s//    version: '$v',/" meson.build
sed -i -E "s/^version: .*/version: $v/" CITATION.cff
sed -i -E "0,/\"version\": \"[^\"]*\"/s//\"version\": \"$v\"/" codemeta.json .zenodo.json
sed -i -E "s|readcon-core/tree/v[0-9][0-9.]*|readcon-core/tree/v$v|; s/Deposit the v[0-9][0-9.]* software tag/Deposit the v$v software tag/" .zenodo.json
