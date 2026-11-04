#!/usr/bin/env python3
"""Write paper-cpc.tar.gz, the directory paper/cpc that the supplementary material holds.

The members are every file of paper/cpc that git does not ignore, except the
two PDFs that build_tex.sh writes into src/, and the records that the ignore
rules would drop: the log and the raw output of the Cachegrind run
(bench/results/r0174/cachegrind) and the eOn runs under evidence/work/e1,
which Figure fig:restart plots and the version map names.  bench/work (the
timed files, which bench/make_payloads.py and bench/h2h.py write), .pixi, the
target directories of Cargo and the TeX build products stay out.  Members are
named paper/cpc/..., sorted, owned by uid 0 and dated SOURCE_DATE_EPOCH of
regen_paper.py, and gzip carries no name or time, so two runs on one tree give
the same bytes.

    python paper/cpc/scripts/pack_paper.py OUT.tar.gz
"""

from __future__ import annotations

import argparse
import gzip
import io
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regen_paper  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "paper/cpc"
BUILT = {"src/rg_main.pdf", "src/rg_supp.pdf"}
IGNORED_RECORDS = ("bench/results/r0174/cachegrind", "evidence/work/e1")


def kept() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                            check=True, capture_output=True).stdout.decode().split("\0")
    return [name for name in listed if name and (ROOT / name).is_file()]


def records() -> list[str]:
    out = []
    for name in IGNORED_RECORDS:
        path = ROOT / name
        if not path.exists():
            raise SystemExit(f"{name} is missing")
        out += [p.relative_to(ROOT).as_posix() for p in ([path] if path.is_file() else sorted(path.rglob("*")))
                if p.is_file()]
    return out


def members() -> list[str]:
    names = sorted(set(kept()) - BUILT | set(records()))
    stray = [n for n in names if {"__pycache__", "target"} & set(n.split("/")[:-1]) or n.endswith(".pyc")
             or n.startswith("bench/work/")]
    if stray:
        raise SystemExit(f"{len(stray)} build products would ship, among them {stray[0]}")
    return names


def pack(out: Path) -> int:
    mtime = int(regen_paper.SOURCE_DATE_EPOCH)
    names = members()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in names:
            path = ROOT / name
            info = tarfile.TarInfo(f"{PREFIX}/{name}")
            info.size = path.stat().st_size
            info.mtime = mtime
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    with out.open("wb") as handle, gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as gz:
        gz.write(raw.getvalue())
    return len(names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="the tarball to write")
    args = parser.parse_args()
    n = pack(args.out)
    print(f"wrote {args.out}: {n} files under {PREFIX}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
