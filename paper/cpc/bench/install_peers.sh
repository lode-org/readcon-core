#!/usr/bin/env bash
# Build the comparison peers from their public source trees.
# Logs stay under paper/cpc/bench/results/v2 and use repo-relative paths.
set -u
cd "$(git rev-parse --show-toplevel)"
OUT=paper/cpc/bench/results/v2
WORK=paper/cpc/bench/work/peers
mkdir -p "$OUT" "$WORK"
LOG=$OUT/install.log
{
  echo "date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "uname_m=$(uname -m)"
  echo "nproc=$(nproc)"
  echo "cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
  echo "head=$(git rev-parse HEAD)"
  echo "pwd=."
} > "$LOG"

clone_one() {
  local name="$1" url="$2" dest="$3"
  if [ -d "$dest/.git" ]; then
    echo "have $name" >> "$LOG"
    return 0
  fi
  git clone --depth 1 "$url" "$dest" >> "$LOG" 2>&1
  echo "clone_$name=$?" >> "$LOG"
}

pip_one() {
  local name="$1" dest="$2"
  python3 -m pip install --user "$dest" >> "$LOG" 2>&1
  echo "pip_$name=$?" >> "$LOG"
}

echo "step readcon" >> "$LOG"
python3 -m pip install --user maturin >> "$LOG" 2>&1
python3 -m pip install --user . >> "$LOG" 2>&1
echo "pip_readcon=$?" >> "$LOG"

clone_one ase https://github.com/ase/ase.git "$WORK/ase"
pip_one ase "$WORK/ase"

clone_one mdanalysis https://github.com/MDAnalysis/mdanalysis.git "$WORK/mdanalysis"
pip_one mdanalysis "$WORK/mdanalysis/package"

clone_one pymatgen https://github.com/materialsproject/pymatgen.git "$WORK/pymatgen"
pip_one pymatgen "$WORK/pymatgen"

clone_one chemfiles https://github.com/chemfiles/chemfiles.git "$WORK/chemfiles"
pip_one chemfiles "$WORK/chemfiles/python"

clone_one numpy https://github.com/numpy/numpy.git "$WORK/numpy"
pip_one numpy "$WORK/numpy"

clone_one readcon-db https://github.com/lode-org/readcon-db.git "$WORK/readcon-db"
pip_one readcon-db "$WORK/readcon-db"

clone_one eon https://github.com/TheochemUI/eOn.git "$WORK/eon"
echo "eon_tree=$?" >> "$LOG"

python3 - << 'PY' >> "$LOG" 2>&1
mods = ["readcon", "ase", "numpy", "MDAnalysis", "pymatgen", "chemfiles", "h5py"]
for name in mods:
    try:
        mod = __import__(name)
        print(f"import {name} {getattr(mod, '__version__', '?')}")
    except Exception as exc:
        print(f"import {name} FAIL {type(exc).__name__}: {exc}")
PY
echo "install_done" >> "$LOG"
