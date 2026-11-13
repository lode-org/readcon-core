#!/usr/bin/env python3
"""Compressed CON and extxyz head-to-head.

The same ``.con.gz``, ``.con.zst``, ``.extxyz.gz`` and ``.extxyz.zst``
files are read by readcon, by ASE, and by eOn's Python reader where it
handles CON. Writes time readcon's default and explicit thread counts
against ASE writing into a gzip or zstd stream at the same levels
(gzip 6, zstd 3). Sizes are the 1k, 100k and 1M single-frame grids from
the existing head-to-head generator.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"
EON_PIN = "579738a9387e8d0ea55496f45dd057812cfab892"
EON_SRC = WORK / "eon-src"
SIZES = (("1k", 1_000), ("100k", 100_000), ("1M", 1_000_000))
THREADS = (1, 2, 4, 8)
GZIP_LEVEL = 6
ZSTD_LEVEL = 3
ABS_TOL = 1e-6
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def serial_threads() -> None:
    for key in THREAD_ENV:
        os.environ[key] = "1"


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def time_call(fn, repeats: int) -> tuple[float, float, list[float]]:
    fn()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    median, iqr = type7(samples)
    return median, iqr, samples


def ensure_eon() -> None:
    needed = [
        EON_SRC / "eon" / "__init__.py",
        EON_SRC / "eon" / "fileio.py",
        EON_SRC / "eon" / "structure.py",
        EON_SRC / "eon" / "geometry" / "cell.py",
    ]
    base = f"https://raw.githubusercontent.com/TheochemUI/eOn/{EON_PIN}/"
    for rel in (
        "eon/__init__.py",
        "eon/fileio.py",
        "eon/structure.py",
        "eon/geometry/cell.py",
    ):
        dest = EON_SRC / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and dest.stat().st_size > 0:
            continue
        urllib.request.urlretrieve(base + rel, dest)
    if any(not path.is_file() for path in needed):
        raise SystemExit("eon python sources did not download")
    # The upstream package init pulls neighbor lists. loadcons only needs
    # the cell transform, which structure.py imports by module path.
    (EON_SRC / "eon" / "geometry" / "__init__.py").write_text("")


def write_grid(path: Path, n_atoms: int) -> None:
    sys.path.insert(0, str(BENCH))
    from run_h2h import write_grid as write_h2h_grid

    if path.is_file() and path.stat().st_size > 0:
        return
    write_h2h_grid(path, n_atoms, 1)


def symbols_of(species) -> list[str]:
    if species is None:
        return []
    row = species[0]
    if hasattr(row, "tolist"):
        row = row.tolist()
    return [str(item) for item in row]


def view_from_columns(cols: dict) -> dict:
    return {
        "positions": np.asarray(cols["positions"], dtype=np.float64),
        "masses": np.asarray(cols["masses"], dtype=np.float64),
        "cell": np.asarray(cols["cell"], dtype=np.float64),
        "symbols": symbols_of(cols.get("species")),
    }


def read_readcon_con(path: str) -> dict:
    import readcon

    frames = readcon.read_con(path)
    view = view_from_columns(frames.columns())
    # Checked before the clock. The timed read does not build this string.
    view["formula"] = str(frames[0].composition_formula)
    view["symbols"] = []
    return view


def touch_readcon_con(path: str) -> None:
    """Read and copy positions, masses, and cell. No formula."""
    import readcon

    cols = readcon.read_con(path).columns()
    np.asarray(cols["positions"])
    np.asarray(cols["masses"])
    np.asarray(cols["cell"])


def touch_readcon_extxyz(path: str) -> None:
    import readcon

    data = readcon.read_extxyz(path)
    np.asarray(data["positions"])
    np.asarray(data["masses"])
    np.asarray(data["cell"])


def read_readcon_extxyz(path: str) -> dict:
    import readcon

    data = readcon.read_extxyz(path)
    return view_from_columns(data)


def ase_images(path: str, kind: str):
    import gzip

    import zstandard
    from ase.io import read as ase_read

    fmt = "eon" if kind == "con" else "extxyz"
    try:
        images = ase_read(path, index=":", format=fmt)
    except Exception:
        if path.endswith(".gz"):
            with gzip.open(path, "rt") as handle:
                images = ase_read(handle, index=":", format=fmt)
        elif path.endswith(".zst"):
            dctx = zstandard.ZstdDecompressor()
            with open(path, "rb") as raw:
                text = dctx.stream_reader(raw).read().decode("utf-8")
            images = ase_read(io.StringIO(text), index=":", format=fmt)
        else:
            raise
    if not isinstance(images, list):
        return [images]
    return images


def touch_ase(path: str, kind: str) -> None:
    """Same geometry copy as readcon. No chemical formula."""
    for image in ase_images(path, kind):
        np.asarray(image.positions, dtype=np.float64)
        np.asarray(image.get_masses(), dtype=np.float64)
        np.asarray(image.cell.lengths(), dtype=np.float64)
        np.asarray(image.cell.angles(), dtype=np.float64)


def read_ase(path: str, kind: str) -> dict:
    images = ase_images(path, kind)
    positions, masses, cells, symbols = [], [], [], []
    for image in images:
        positions.append(np.array(image.positions, dtype=np.float64, copy=True))
        masses.append(np.array(image.get_masses(), dtype=np.float64, copy=True))
        cells.append(
            np.concatenate(
                [
                    np.asarray(image.cell.lengths(), dtype=np.float64),
                    np.asarray(image.cell.angles(), dtype=np.float64),
                ]
            )
        )
        symbols.append([str(symbol) for symbol in image.get_chemical_symbols()])
    return {
        "positions": np.stack(positions),
        "masses": np.stack(masses),
        "cell": np.stack(cells),
        "symbols": symbols[0],
        "images": images,
    }


def eon_frames(path: str):
    ensure_eon()
    sys.path.insert(0, str(EON_SRC))
    from eon.fileio import loadcons

    return loadcons(path)


def touch_eon(path: str) -> None:
    """Same geometry copy as readcon. No chemical formula."""
    for frame in eon_frames(path):
        np.asarray(frame.r, dtype=np.float64)
        np.asarray(frame.mass, dtype=np.float64)
        np.asarray(frame.box, dtype=np.float64)


def read_eon(path: str) -> dict:
    frames = eon_frames(path)
    positions, masses, cells, symbols = [], [], [], []
    for frame in frames:
        positions.append(np.array(frame.r, dtype=np.float64, copy=True))
        masses.append(np.array(frame.mass, dtype=np.float64, copy=True).reshape(-1))
        box = np.asarray(frame.box, dtype=np.float64).reshape(3, 3)
        lengths = np.sqrt(np.sum(box * box, axis=1))
        cells.append(np.concatenate([lengths, np.array([90.0, 90.0, 90.0])]))
        symbols.append([str(name) for name in frame.names])
    return {
        "positions": np.stack(positions),
        "masses": np.stack(masses),
        "cell": np.stack(cells),
        "symbols": symbols[0],
    }


def formula_of(view: dict) -> str:
    if view.get("formula"):
        return str(view["formula"])
    counts: dict[str, int] = {}
    for symbol in view["symbols"]:
        counts[symbol] = counts.get(symbol, 0) + 1
    return "|".join(f"{name}:{counts[name]}" for name in sorted(counts))


def same(left: dict, right: dict, label: str) -> None:
    if formula_of(left) != formula_of(right):
        raise SystemExit(f"{label} symbols {formula_of(left)} != {formula_of(right)}")
    for key in ("positions", "masses", "cell"):
        delta = float(np.max(np.abs(left[key] - right[key])))
        if delta > ABS_TOL:
            raise SystemExit(f"{label} {key} delta {delta}")


def write_readcon(
    path: Path, kind: str, payload, threads: int | None, codec: str
) -> None:
    import readcon

    path.unlink(missing_ok=True)
    kwargs = {}
    if threads is not None:
        kwargs["n_threads"] = threads
    if kind == "con":
        readcon.write_con(os.fspath(path), payload, compression=codec, **kwargs)
    else:
        readcon.write_extxyz(os.fspath(path), payload, **kwargs)


def write_ase(path: Path, kind: str, images) -> None:
    import zstandard
    from ase.io import write as ase_write

    fmt = "eon" if kind == "con" else "extxyz"
    path.unlink(missing_ok=True)
    if path.name.endswith(".gz"):
        with gzip.open(path, "wt", compresslevel=GZIP_LEVEL) as handle:
            ase_write(handle, images, format=fmt)
        return
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL)
    with path.open("wb") as raw:
        with compressor.stream_writer(raw) as stream:
            text = io.StringIO()
            ase_write(text, images, format=fmt)
            stream.write(text.getvalue().encode("utf-8"))


def prepare_inputs() -> dict[str, dict]:
    import readcon

    folder = WORK / "compressed-h2h"
    folder.mkdir(parents=True, exist_ok=True)
    cases = {}
    for label, n_atoms in SIZES:
        plain = folder / f"{label}.con"
        if label == "1M" and (WORK / "inputs" / "con-1000000x1.con").is_file():
            plain = WORK / "inputs" / "con-1000000x1.con"
        else:
            write_grid(plain, n_atoms)
        frames = readcon.read_con(os.fspath(plain), n_threads=1)
        ext_path = folder / f"{label}.extxyz"
        write_plain_extxyz(ext_path, frames)
        ext = readcon.read_extxyz(os.fspath(ext_path), n_threads=1)
        shared = {}
        for kind, suffix in (("con", ".con"), ("extxyz", ".extxyz")):
            for codec, extra in (("gzip", ".gz"), ("zstd", ".zst")):
                path = folder / f"{label}{suffix}{extra}"
                if not path.is_file() or path.stat().st_size == 0:
                    if kind == "con":
                        readcon.write_con(os.fspath(path), frames, compression=codec)
                    else:
                        readcon.write_extxyz(os.fspath(path), ext)
                shared[f"{kind}-{codec}"] = path
        cases[label] = {
            "atoms": n_atoms,
            "frames": frames,
            "extxyz": ext,
            "plain": plain,
            "files": shared,
        }
    return cases


def write_plain_extxyz(path: Path, frames) -> None:
    if path.is_file() and path.stat().st_size > 0:
        return
    cols = frames.columns()
    pos = np.asarray(cols["positions"], dtype=np.float64)[0]
    cell = np.asarray(cols["cell"], dtype=np.float64)[0]
    n_atoms = pos.shape[0]
    a, b, c = (float(cell[0]), float(cell[1]), float(cell[2]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{n_atoms}\n")
        handle.write(
            f'Lattice="{a} 0 0 0 {b} 0 0 0 {c}" '
            'Properties=species:S:1:pos:R:3 pbc="T T T"\n'
        )
        chunk: list[str] = []
        for index, (x, y, z) in enumerate(pos):
            chunk.append(f"Cu {x:.8f} {y:.8f} {z:.8f}\n")
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=BENCH / "scaling" / "rel1")
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    serial_threads()
    ensure_eon()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    lscpu = subprocess.check_output(["lscpu"], text=True)
    (out / "compressed-h2h-lscpu.txt").write_text(lscpu)
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    cases = prepare_inputs()
    rows: list[dict] = []
    lines = [
        f"commit {sha}",
        f"warmup 1 samples {args.repeats} percentile type7 serial 1",
        "levels gzip 6 zstd 3",
        "shared files are readcon's default compressed write",
        "timed read copies positions, masses, and cell; no reader builds a formula",
    ]

    def add(row: dict) -> None:
        rows.append(row)
        print(
            f"{row['op']} {row['file']} {row['tool']} "
            f"{row.get('threads')} med={row['median_s']:.6f}",
            flush=True,
        )

    for label, case in cases.items():
        reference = read_readcon_con(os.fspath(case["files"]["con-gzip"]))
        for kind in ("con", "extxyz"):
            for codec in ("gzip", "zstd"):
                path = case["files"][f"{kind}-{codec}"]
                file_id = f"{label}-{kind}-{codec}"
                checkers = {
                    "readcon": (
                        read_readcon_con if kind == "con" else read_readcon_extxyz
                    ),
                    "ase": lambda path, kind=kind: read_ase(path, kind),
                }
                timers = {
                    "readcon": (
                        touch_readcon_con if kind == "con" else touch_readcon_extxyz
                    ),
                    "ase": lambda path, kind=kind: touch_ase(path, kind),
                }
                if kind == "con":
                    checkers["eon"] = read_eon
                    timers["eon"] = touch_eon
                views = {}
                for name, fn in checkers.items():
                    views[name] = fn(os.fspath(path))
                    same(
                        reference if kind == "con" else views["readcon"],
                        views[name],
                        f"check {file_id} {name}",
                    )
                ext_ref = views["readcon"] if kind == "extxyz" else reference
                if kind == "extxyz":
                    same(ext_ref, views["ase"], f"check {file_id} ase")
                for name, fn in timers.items():

                    def once(fn=fn, path=path):
                        fn(os.fspath(path))

                    median, iqr, samples = time_call(once, args.repeats)
                    add(
                        {
                            "op": "read",
                            "file": file_id,
                            "tool": name,
                            "threads": None,
                            "atoms": case["atoms"],
                            "median_s": median,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    lines.append(
                        f"read {file_id} {name} {median:.6f} {iqr:.6f} "
                        + " ".join(f"{sample:.6f}" for sample in samples)
                    )

                images = None
                if kind == "con":
                    images = read_ase(os.fspath(path), "con")["images"]
                else:
                    images = read_ase(os.fspath(path), "extxyz")["images"]
                payload = case["frames"] if kind == "con" else case["extxyz"]
                suffix = ".gz" if codec == "gzip" else ".zst"
                for threads in (None, *THREADS):
                    dest = out / "compressed-h2h-tmp" / f"{file_id}-t{threads}{suffix}"
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    def once_write(
                        dest=dest,
                        threads=threads,
                        kind=kind,
                        payload=payload,
                        codec=codec,
                    ):
                        write_readcon(dest, kind, payload, threads, codec)

                    once_write()
                    check_reader = (
                        read_readcon_con if kind == "con" else read_readcon_extxyz
                    )
                    same(
                        ext_ref if kind == "extxyz" else reference,
                        check_reader(os.fspath(dest)),
                        f"rewrite {file_id} {threads}",
                    )
                    median, iqr, samples = time_call(once_write, args.repeats)
                    add(
                        {
                            "op": "write",
                            "file": file_id,
                            "tool": "readcon",
                            "threads": "default" if threads is None else threads,
                            "atoms": case["atoms"],
                            "median_s": median,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    lines.append(
                        f"write {file_id} readcon {threads} {median:.6f} {iqr:.6f} "
                        + " ".join(f"{sample:.6f}" for sample in samples)
                    )
                dest = out / "compressed-h2h-tmp" / f"{file_id}-ase{suffix}"

                def once_ase(dest=dest, kind=kind, images=images):
                    write_ase(dest, kind, images)

                once_ase()
                median, iqr, samples = time_call(once_ase, args.repeats)
                add(
                    {
                        "op": "write",
                        "file": file_id,
                        "tool": "ase",
                        "threads": None,
                        "atoms": case["atoms"],
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                    }
                )
                lines.append(
                    f"write {file_id} ase {median:.6f} {iqr:.6f} "
                    + " ".join(f"{sample:.6f}" for sample in samples)
                )

    payload = {
        "commit": sha,
        "lscpu": lscpu,
        "warmup": 1,
        "repeats": args.repeats,
        "percentile": "type7",
        "serial": True,
        "rows": rows,
    }
    (out / "compressed-h2h.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out / "compressed-h2h.log").write_text("\n".join(lines) + "\n")
    print("wrote", out / "compressed-h2h.json", flush=True)


if __name__ == "__main__":
    main()
