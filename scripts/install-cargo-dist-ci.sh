#!/usr/bin/env bash
# Install cargo-dist 0.28.0 from a sha256-pinned archive. Used by
# .github/workflows/release.yml on Linux, macOS, and Windows (bash).
set -euo pipefail
VER=0.28.0
BASE="https://github.com/axodotdev/cargo-dist/releases/download/v${VER}"

os="$(uname -s)"
arch="$(uname -m)"
asset=""
sha=""
if [[ "$os" == Linux && "$arch" == x86_64 ]]; then
  asset=cargo-dist-x86_64-unknown-linux-gnu.tar.xz
  sha=c5da0fc4e782315e860bf5d1fb5f9a35e0e78c2d61f27662dfb096cf43de12d8
elif [[ "$os" == Linux && "$arch" == aarch64 ]]; then
  asset=cargo-dist-aarch64-unknown-linux-gnu.tar.xz
  sha=96ac038f1c01a1d3aeed56668c6fb60f9303770d40b3cdfe1c1a5224a2823060
elif [[ "$os" == Darwin && "$arch" == x86_64 ]]; then
  asset=cargo-dist-x86_64-apple-darwin.tar.xz
  sha=de231817ab627c605f4e8aeca409db164b0b749f57b0df5e37a88ff805109698
elif [[ "$os" == Darwin && "$arch" == arm64 ]]; then
  asset=cargo-dist-aarch64-apple-darwin.tar.xz
  sha=436e9d1e503b106e938ac8e5e8218d5ad12b161430c8a1f874934271a1f869e9
elif [[ "$os" == MINGW* || "$os" == MSYS* || "$os" == CYGWIN* ]] && [[ "$arch" == x86_64 ]]; then
  asset=cargo-dist-x86_64-pc-windows-msvc.zip
  sha=8d92e7a9542692bbaae85bdb52eee6234627067eb0700841dcb36d89896fd9ca
else
  echo "unsupported platform ${os} ${arch} for checksummed cargo-dist" >&2
  exit 1
fi

curl --proto '=https' --tlsv1.2 -LsSf -o "${asset}" "${BASE}/${asset}"
python3 - "$asset" "$sha" <<'PY'
import hashlib, sys
path, expect = sys.argv[1], sys.argv[2]
h = hashlib.sha256()
with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
got = h.hexdigest()
if got != expect:
    raise SystemExit(f"sha256 mismatch for {path}: {got} != {expect}")
print(f"OK {path} {got}")
PY

mkdir -p "${HOME}/.cargo/bin"
if [[ "${asset}" == *.zip ]]; then
  python3 - "$asset" <<'PY'
import sys, zipfile
from pathlib import Path
zf = zipfile.ZipFile(sys.argv[1])
zf.extractall(".")
dest = Path.home() / ".cargo" / "bin"
dest.mkdir(parents=True, exist_ok=True)
copied = False
for name in zf.namelist():
    if name.endswith("dist.exe") or name.endswith("/dist") or name.endswith("dist"):
        src = Path(name)
        if src.is_file():
            target = dest / src.name
            target.write_bytes(src.read_bytes())
            target.chmod(0o755)
            copied = True
            break
if not copied:
    raise SystemExit("dist binary not found in zip")
PY
else
  tar -xf "${asset}"
  install -m 755 cargo-dist-*/dist "${HOME}/.cargo/bin/dist"
fi
echo "${HOME}/.cargo/bin" >> "${GITHUB_PATH:-/dev/null}"
export PATH="${HOME}/.cargo/bin:${PATH}"
command -v dist
