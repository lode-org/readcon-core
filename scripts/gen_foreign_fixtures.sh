#!/usr/bin/env bash
# Rebuild the eOn 3.6.0 and ASE 3.29 fixtures committed under
# resources/conformance/valid/. Requires micromamba on PATH.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${EON_PREFIX:-/tmp/eon-env}"
MM="${MICROMAMBA:-micromamba}"

if [[ ! -x "$PREFIX/bin/eonclient" ]]; then
  "$MM" create -y -p "$PREFIX" -c conda-forge "eon=3.6.0" "ase=3.29" eigen
fi

MAGIC="$ROOT/build/magic_enum"
if [[ ! -f "$MAGIC/magic_enum/magic_enum_all.hpp" ]]; then
  mkdir -p "$MAGIC/magic_enum"
  base="https://raw.githubusercontent.com/TheochemUI/eOn/v3.6.0/client/thirdparty/magic_enum"
  for f in magic_enum.hpp magic_enum_all.hpp magic_enum_containers.hpp magic_enum_flags.hpp \
           magic_enum_format.hpp magic_enum_fuse.hpp magic_enum_iostream.hpp \
           magic_enum_switch.hpp magic_enum_utility.hpp; do
    curl -fsSL "$base/$f" -o "$MAGIC/magic_enum/$f"
  done
fi

OUT="$ROOT/resources/conformance/valid"
export OUT
mkdir -p "$OUT" "$ROOT/resources/conformance/foreign"
g++ -std=c++20 -O2 \
  -I"$PREFIX/include" -I"$PREFIX/include/eigen3" -I"$MAGIC" \
  "$ROOT/scripts/eon_thermal_fixture.cpp" \
  -L"$PREFIX/lib" -leonclib -lemt -Wl,-rpath,"$PREFIX/lib" \
  -o "$ROOT/build/eon_thermal_fixture"
"$ROOT/build/eon_thermal_fixture" "$OUT"

"$MM" run -p "$PREFIX" python - <<'PY'
from ase import Atoms
from ase.io import write
from pathlib import Path
import os
out = Path(os.environ["OUT"])
a = Atoms("Cu", positions=[[0.0, 0.0, 0.0]], cell=[8.0, 8.0, 8.0], pbc=True)
b = a.copy()
b.positions += [0.2, 0.0, 0.0]
write(out / "ase_single.con", a, format="eon")
write(out / "ase_multi.con", [a, b], format="eon")
PY
echo "foreign fixtures written under $OUT"
