#!/usr/bin/env python3
"""Measure the appendix database records and write them from the raw log.

Five kinds of row come from one log: ingest, query, file size, correctness
and deduplication. The published tables used five repeats. This run uses at
least twelve, interleaved, with one thread. The corpus is generated here.
It is not a copy of an older record.
"""

from __future__ import annotations

import csv
import ctypes
import gzip
import json
import os
import sys
import time
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
sys.path.insert(0, str(REPO / "bench" / "h2h"))

from bench_disk import bench_dir, release  # noqa: E402

DEFAULT_OUT = CPC / "campaign" / "3d2118af" / "data" / "db"
READCON_DB_REV = "v0.2.1"
N_ATOMS = 9
CHUNK = 64
SIZES = (1000, 10000)
DEDUP_FRAMES = 24000
DEDUP_UNIQUE = 7

for _key, _value in (
    ("OMP_NUM_THREADS", "1"),
    ("OPENBLAS_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
    ("NUMEXPR_NUM_THREADS", "1"),
    ("RAYON_NUM_THREADS", "1"),
    ("VECLIB_MAXIMUM_THREADS", "1"),
):
    os.environ.setdefault(_key, _value)


def repeats() -> int:
    return max(12, int(os.environ.get("READCON_DB_REPEATS", "12")))


def _frame(index: int, *, energy: float, force: float, pbc: list[bool] | None) -> str:
    meta: dict = {
        "con_spec_version": 3,
        "con_spec_minor": 1,
        "units": {"length": "angstrom", "energy": "eV"},
        "sections": ["forces"],
        "energy": energy,
    }
    if pbc is not None:
        meta["pbc"] = pbc
    lines = [
        "cpc-eval",
        json.dumps(meta, separators=(",", ":")),
        "12.0 12.0 12.0",
        "90.0 90.0 90.0",
        "",
        "",
        "1",
        str(N_ATOMS),
        "63.546",
        "Cu",
        "Coordinates of Component 1",
    ]
    for atom in range(N_ATOMS):
        x = 0.4 * atom + 1.0e-4 * index
        lines.append(f"{x:.8f} 0.20000000 0.30000000 0 {atom}")
    lines.extend(["", "Cu", "Forces of Component 1"])
    for atom in range(N_ATOMS):
        lines.append(f"{force:.8f} 0.00000000 0.00000000 0 {atom}")
    return "\n".join(lines) + "\n"


def write_corpus(path: Path, n_frames: int) -> dict:
    """Distinct coordinates, an energy ladder and two force magnitudes."""
    parts = []
    energy_hits = 0
    fmax_hits = 0
    for index in range(n_frames):
        energy = 0.01 * index
        force = 0.05 if index % 5 == 0 else 0.01
        if 2.0 <= energy < 3.0:
            energy_hits += 1
        if force >= 0.04:
            fmax_hits += 1
        parts.append(_frame(index, energy=energy, force=force, pbc=[True, True, True]))
    path.write_text("".join(parts))
    return {
        "n_frames": n_frames,
        "composition_hits": n_frames,
        "composition_index_sum": n_frames * (n_frames - 1) // 2,
        "energy_hits": energy_hits,
        "energy_lo": 2.0,
        "energy_hi": 3.0,
        "fmax_hits": fmax_hits,
        "fmax_lo": 0.04,
        "raw_bytes": path.stat().st_size,
    }


def _stat_tree(path: Path) -> tuple[int, int]:
    if path.is_file():
        stat = path.stat()
        return stat.st_size, stat.st_blocks * 512
    apparent = allocated = 0
    for child in path.rglob("*"):
        if child.is_file():
            stat = child.stat()
            apparent += stat.st_size
            allocated += stat.st_blocks * 512
    return apparent, allocated


def _dontneed(path: Path) -> None:
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                _dontneed(child)
        return
    if not path.is_file():
        return
    libc = ctypes.CDLL(None, use_errno=True)
    fd = os.open(path, os.O_RDONLY)
    try:
        libc.posix_fadvise(ctypes.c_int(fd), ctypes.c_int64(0), ctypes.c_int64(0), 4)
    finally:
        os.close(fd)


def _select(db, **overrides):
    args = {
        "traj_id": None,
        "symbol": None,
        "natoms_min": 0,
        "natoms_max": 10**9,
        "exact_hash": None,
        "energy_min": None,
        "energy_max": None,
        "fmax_min": None,
        "fmax_max": None,
        "mass_min": None,
        "mass_max": None,
        "volume_min": None,
        "volume_max": None,
        "frame_index_min": None,
        "frame_index_max": None,
        "charge_min": None,
        "charge_max": None,
        "element_exact": None,
        "element_min": None,
        "formula": None,
        "require_forces": False,
        "require_velocities": False,
        "require_energy": False,
        "limit": None,
    }
    args.update(overrides)
    return db.select(**args)


def _atoms(path: Path):
    import numpy as np
    import readcon
    from ase.calculators.singlepoint import SinglePointCalculator

    atoms = []
    for index, frame in enumerate(readcon.read_con(str(path))):
        item = frame.to_ase()
        forces = np.asarray(frame.forces_array(), dtype=float)
        item.calc = SinglePointCalculator(
            item, energy=float(frame.energy), forces=forces
        )
        item.info["frame_index"] = index
        atoms.append(item)
    return atoms


def _check_composition_readcon(db, oracle: dict) -> tuple[int, int]:
    keys = _select(db, formula="Cu:9")
    return len(keys), sum(index for _, index in keys)


def worker_ingest(src: Path, dest: Path, kind: str, oracle: dict) -> dict:
    import shutil

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if kind == "readcon-db":
        from readcon_db import ConCorpus

        text = src.read_text()
        t0 = time.perf_counter()
        db = ConCorpus(str(dest / "corpus.lmdb"))
        stored = db.append_trajectory_str(1, text, source="traj.con")
        hits, index_sum = _check_composition_readcon(db, oracle)
        seconds = time.perf_counter() - t0
        store = dest / "corpus.lmdb"
    elif kind == "ase.db":
        from ase.db import connect

        prepared = _atoms(src)
        t0 = time.perf_counter()
        db = connect(dest / "atoms.db")
        for item in prepared:
            db.write(item)
        stored = len(prepared)
        hits = db.count(formula="Cu9")
        seconds = time.perf_counter() - t0
        index_sum = hits
        store = dest / "atoms.db"
    elif kind == "ase.db-txn":
        from ase.db import connect

        prepared = _atoms(src)
        t0 = time.perf_counter()
        db = connect(dest / "atoms.db")
        with db:
            for item in prepared:
                db.write(item)
        stored = len(prepared)
        hits = db.count(formula="Cu9")
        seconds = time.perf_counter() - t0
        index_sum = hits
        store = dest / "atoms.db"
    else:
        raise SystemExit(kind)
    apparent, allocated = _stat_tree(store)
    return {
        "event": "ingest",
        "system": kind if kind != "ase.db-txn" else "ase.db-txn",
        "seconds": seconds,
        "frames": int(stored),
        "hits": int(hits),
        "index_sum": int(index_sum),
        "check": int(hits) == oracle["composition_hits"]
        and int(stored) == oracle["n_frames"],
        "apparent_bytes": apparent,
        "allocated_bytes": allocated,
        "raw_bytes": oracle["raw_bytes"],
    }


def _query_readcon(store: Path, kind: str, oracle: dict) -> tuple[int, int]:
    from readcon_db import ConCorpus

    db = ConCorpus(str(store), readonly=True)
    if kind == "composition":
        keys = _select(db, formula="Cu:9")
    elif kind == "energy":
        keys = _select(
            db, energy_min=oracle["energy_lo"], energy_max=oracle["energy_hi"]
        )
    elif kind == "fmax":
        keys = _select(db, fmax_min=oracle["fmax_lo"], fmax_max=oracle["fmax_hi"])
    else:
        raise SystemExit(kind)
    return len(keys), sum(index for _, index in keys)


def _query_ase(store: Path, kind: str, oracle: dict) -> tuple[int, int]:
    from ase.db import connect

    db = connect(store)
    if kind == "composition":
        rows = list(db.select(formula="Cu9"))
    elif kind == "energy":
        rows = list(
            db.select(f"energy>={oracle['energy_lo']},energy<{oracle['energy_hi']}")
        )
    elif kind == "fmax":
        rows = list(db.select(f"fmax>={oracle['fmax_lo']},fmax<{oracle['fmax_hi']}"))
    else:
        raise SystemExit(kind)
    indexes = []
    for row in rows:
        indexes.append(int(getattr(row, "frame_index", row.id - 1)))
    return len(rows), sum(indexes)


def _query_directory(chunks: Path, kind: str, oracle: dict) -> tuple[int, int]:
    import readcon

    hits = []
    index = 0
    for path in sorted(chunks.glob("chunk-*.con")):
        for frame in readcon.read_con(str(path)):
            force = float(frame.fmax)
            if (
                (kind == "composition" and str(frame.composition_formula) == "Cu:9")
                or (
                    kind == "energy"
                    and oracle["energy_lo"] <= float(frame.energy) < oracle["energy_hi"]
                )
                or (kind == "fmax" and oracle["fmax_lo"] <= force < oracle["fmax_hi"])
            ):
                hits.append(index)
            index += 1
    return len(hits), sum(hits)


def _fresh_query(store: Path, system: str, kind: str, oracle: dict) -> dict:
    """A new interpreter, so the cold sample does not reuse this process."""
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "query",
            "--store",
            str(store),
            "--system",
            system,
            "--kind",
            kind,
            "--oracle",
            json.dumps(oracle),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    line = ""
    for item in reversed(proc.stdout.splitlines()):
        if item.startswith("{"):
            line = item
            break
    if proc.returncode != 0 or not line:
        raise SystemExit(
            f"query worker {system} {kind} exited {proc.returncode}: "
            f"{proc.stderr[-400:]}"
        )
    return json.loads(line)


def worker_query(store: Path, system: str, kind: str, oracle: dict) -> dict:
    expect = {
        "composition": oracle["composition_hits"],
        "energy": oracle["energy_hits"],
        "fmax": oracle["fmax_hits"],
    }[kind]
    _dontneed(store)

    def once():
        if system == "readcon-db":
            return _query_readcon(store, kind, oracle)
        if system == "ase.db":
            return _query_ase(store, kind, oracle)
        if system == "con-directory":
            return _query_directory(store, kind, oracle)
        raise SystemExit(system)

    t0 = time.perf_counter()
    hits, index_sum = once()
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    hits_warm, index_warm = once()
    warm = time.perf_counter() - t0
    return {
        "event": "query",
        "system": system,
        "query": kind,
        "cold_s": cold,
        "warm_s": warm,
        "hits": hits,
        "index_sum": index_sum,
        "check": hits == expect and hits_warm == expect and index_sum == index_warm,
    }


def _chunks(src: Path, dest: Path) -> None:
    import readcon

    frames = readcon.read_con(str(src))
    dest.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(frames), CHUNK):
        group = frames[start : start + CHUNK]
        readcon.write_con(str(dest / f"chunk-{start:06d}.con"), group)


def correctness(log) -> None:
    import readcon
    from readcon_db import ConCorpus

    work = bench_dir("db-correctness")
    try:
        frames = []
        for index, pbc in enumerate(
            ([True, True, False], [True, True, True], [False, False, False], None)
        ):
            frames.append(_frame(index, energy=1.0 + index, force=0.02, pbc=pbc))
        text = "".join(frames[:3])
        path = work / "spans.con"
        path.write_text(text)
        parsed = readcon.read_con(str(path))
        db = ConCorpus(str(work / "corpus.lmdb"))
        db.append_trajectory_str(1, text, source="spans.con")
        same = True
        for index in range(3):
            stored = db.get_frame_text(1, index)
            again = (
                readcon.read_con_string(stored)
                if hasattr(readcon, "read_con_string")
                else None
            )
            positions = db.get_positions(1, index)
            original = parsed[index].coords_array()
            if list(map(tuple, positions)) != [tuple(row) for row in original]:
                same = False
            if again is not None and len(again) != 1:
                same = False
        _emit(
            log,
            {
                "event": "correctness",
                "name": "round_trip",
                "pass": same,
                "detail": "stored positions match the readcon spans",
            },
        )
        dup = frames[0]
        db.append_trajectory_str(2, dup, source="dup-a.con")
        db.append_trajectory_str(3, dup, source="dup-b.con")
        hash_a = bytes(db.frame_hash(2, 0))
        hash_b = bytes(db.frame_hash(3, 0))
        text_a = db.get_frame_text(2, 0)
        text_b = db.get_frame_text(3, 0)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "dedup_identical_bytes",
                "pass": hash_a == hash_b and text_a == text_b and len(text_a) > 0,
                "detail": "two copies share a digest and each keeps its text",
            },
        )
        changed = dup.replace("0.00000000 0.20000000", "0.00000001 0.20000000", 1)
        db.append_trajectory_str(4, changed, source="one.con")
        hash_c = bytes(db.frame_hash(4, 0))
        found_old = db.find_by_hash(hash_a)
        found_new = db.find_by_hash(hash_c)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "one_byte_change",
                "pass": hash_c != hash_a
                and found_old is not None
                and found_new is not None,
                "detail": f"find_by_hash old={found_old} new={found_new}",
            },
        )
        bare = (
            _frame(0, energy=1.0, force=0.0, pbc=[True, True, True]).split(
                "\n\nCu\nForces of Component 1", 1
            )[0]
            + "\n"
        )
        bare = bare.replace(',"sections":["forces"]', "")
        no_energy = bare.replace(',"energy":1.0', "")
        db.append_trajectory_str(5, no_energy, source="bare.con")
        with_forces = set(_select(db, require_forces=True))
        with_velocity = set(_select(db, require_velocities=True))
        with_energy = set(_select(db, require_energy=True))
        bare_key = (5, 0)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "missing_forces_or_velocities",
                "pass": bare_key not in with_forces
                and bare_key not in with_velocity
                and bare_key not in with_energy,
                "detail": "a frame without forces, velocities or energy misses those indexes",
            },
        )
        pbc_keys = {}
        for traj, label in ((1, "stored"),):
            text_back = db.get_frame_text(traj, 0)
            pbc_keys[label] = "pbc" in text_back
        no_key = _frame(9, energy=1.0, force=0.02, pbc=None)
        db.append_trajectory_str(6, no_key, source="nopbc.con")
        stored_no = db.get_frame_text(6, 0)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "periodicity_not_inferred",
                "pass": "pbc" not in stored_no
                and '"pbc":[true,true,false]' in db.get_frame_text(1, 0),
                "detail": "a box without metadata pbc is stored without a pbc key",
            },
        )
        before = [db.get_frame_text(1, index) for index in range(3)]
        answers = _select(db, formula="Cu:9")
        rebuilt = db.reindex()
        after = [db.get_frame_text(1, index) for index in range(3)]
        _emit(
            log,
            {
                "event": "correctness",
                "name": "rebuild_from_text",
                "pass": before == after
                and _select(db, formula="Cu:9") == answers
                and rebuilt > 0,
                "detail": f"reindex rebuilt {rebuilt} frames",
            },
        )
        second = db.reindex()
        _emit(
            log,
            {
                "event": "correctness",
                "name": "reindex_twice",
                "pass": [db.get_frame_text(1, index) for index in range(3)] == before
                and second == rebuilt,
                "detail": "a second reindex left the stored text unchanged",
            },
        )
        digest = bytes(db.frame_hash(1, 0))
        cooked = db.cook_frame(1, 0)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "numeric_cache_ignored",
                "pass": cooked > 0
                and bytes(db.frame_hash(1, 0)) == digest
                and db.get_frame_text(1, 0) == before[0],
                "detail": f"cooked {cooked} bytes; hash and CON text stayed put",
            },
        )
        rewritten = db.set_units(2, {"length": "nanometer", "energy": "eV"})
        moved = db.find_by_hash(hash_a)
        _emit(
            log,
            {
                "event": "correctness",
                "name": "hash_index_survives_rewrite_of_duplicate",
                "pass": rewritten > 0
                and moved is not None
                and moved[0] != 2
                and bytes(db.frame_hash(moved[0], moved[1])) == hash_a,
                "detail": (
                    "set_units rewrote trajectory 2; "
                    f"find_by_hash of the old digest returns {moved}"
                ),
            },
        )
    finally:
        release(work)


def dedup(log, src_unique: Path) -> None:
    from readcon_db import ConCorpus

    work = bench_dir("db-dedup")
    try:
        text = src_unique.read_text()
        db = ConCorpus(str(work / "corpus.lmdb"))
        stored = db.append_trajectory_str(1, text, source=src_unique.name)
        hashes = []
        blob = 0
        for index in range(int(stored)):
            digest = bytes(db.frame_hash(1, index))
            hashes.append(digest)
            blob += len(db.get_frame_text(1, index).encode())
        distinct = set(hashes)
        seen = []
        unique_parts = []
        for index, digest in enumerate(hashes):
            if digest in seen:
                continue
            seen.append(digest)
            unique_parts.append(db.get_frame_text(1, index))
        unique_text = "".join(unique_parts)
        unique_path = work / "unique.con"
        unique_path.write_text(unique_text)
        db_unique = ConCorpus(str(work / "unique.lmdb"))
        db_unique.append_trajectory_str(1, unique_text, source="unique.con")
        corpus_apparent, corpus_allocated = _stat_tree(work / "corpus.lmdb")
        unique_apparent, unique_allocated = _stat_tree(work / "unique.lmdb")
        unique_blob = sum(
            len(db_unique.get_frame_text(1, index).encode())
            for index in range(len(seen))
        )
        _emit(
            log,
            {
                "event": "dedup",
                "n_frames": int(stored),
                "n_keys": int(stored),
                "n_unique_hashes": len(distinct),
                "n_unique_index": len(distinct),
                "raw_bytes": src_unique.stat().st_size,
                "stored_blob_bytes": blob,
                "unique_blob_bytes": unique_blob,
                "corpus_apparent_bytes": corpus_apparent,
                "corpus_allocated_bytes": corpus_allocated,
                "unique_corpus_apparent_bytes": unique_apparent,
                "unique_corpus_allocated_bytes": unique_allocated,
                "unique_reingest_frames": len(seen),
                "ok": len(distinct) == len(seen) and int(stored) == DEDUP_FRAMES,
            },
        )
    finally:
        release(work)


def file_sizes(log, src: Path, n_frames: int) -> None:
    import zstandard

    work = bench_dir("db-sizes")
    try:
        raw_a, raw_b = _stat_tree(src)
        gz_path = work / "corpus.con.gz"
        with gzip.open(gz_path, "wb", compresslevel=6) as handle:
            handle.write(src.read_bytes())
        gz_a, gz_b = _stat_tree(gz_path)
        zs_path = work / "corpus.con.zst"
        zs_path.write_bytes(
            zstandard.ZstdCompressor(level=3).compress(src.read_bytes())
        )
        zs_a, zs_b = _stat_tree(zs_path)
        chunks = work / "chunks"
        _chunks(src, chunks)
        ch_a, ch_b = _stat_tree(chunks)
        for store, apparent, allocated, note in (
            ("raw_con", raw_a, raw_b, "multi-frame CON"),
            ("gzip", gz_a, gz_b, "gzip level 6"),
            ("zstd", zs_a, zs_b, "zstd level 3"),
            ("con_directory", ch_a, ch_b, "chunk files"),
        ):
            _emit(
                log,
                {
                    "event": "size",
                    "n_frames": n_frames,
                    "store": store,
                    "apparent_bytes": apparent,
                    "allocated_bytes": allocated,
                    "note": note,
                },
            )
    finally:
        release(work)


def _emit(log, payload: dict) -> None:
    log.write(json.dumps(payload) + "\n")
    log.flush()


def _median(values: list[float]) -> tuple[float, float, float]:
    ordered = sorted(values)
    return ordered[len(ordered) // 2], ordered[0], ordered[-1]


def _hardware() -> dict:
    from importlib.metadata import version

    import readcon

    mem_gb = None
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal"):
            mem_gb = round(int(line.split()[1]) / 1024 / 1024, 2)
    cpu = "unknown"
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = " ".join(line.split(":", 1)[1].replace("(R)", "").split())
            break
    rustc = os.popen("rustc --version").read().strip()
    return {
        "cpu_model": cpu,
        "ncpu": os.cpu_count(),
        "mem_gb": mem_gb,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "rustc": rustc,
        "readcon_db": version("readcon-db"),
        "readcon_db_pin": READCON_DB_REV,
        "readcon_core": readcon.__version__,
        "readcon_commit": getattr(readcon, "__commit__", None),
        "ase": version("ase"),
        "numpy": version("numpy"),
        "matplotlib": version("matplotlib"),
        "zstandard": version("zstandard"),
        "threads": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "RAYON_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "page_cache_drop": False,
        "repeats": repeats(),
        "summary": "median, minimum, and maximum of the paired interleaved repeats",
        "megabyte": "1e6 bytes",
        "repeats_are_paired_and_interleaved": True,
    }


def reduce_log(path: Path, out: Path) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    summary = []
    by_ingest: dict[tuple, list] = {}
    for row in rows:
        if row["event"] == "ingest" and row["check"]:
            by_ingest.setdefault((row["n_frames"], row["system"]), []).append(row)
    for (n_frames, system), samples in sorted(by_ingest.items()):
        seconds = [row["seconds"] for row in samples]
        med, lo, hi = _median(seconds)
        raw = samples[0]["raw_bytes"]
        summary.append(("ingest_s", n_frames, system, "", "", med, lo, hi))
        rates = [n_frames / row["seconds"] for row in samples]
        summary.append(("frames_per_s", n_frames, system, "", "", *_median(rates)))
        bandwidth = [raw / row["seconds"] / 1e6 for row in samples]
        summary.append(("mb_per_s", n_frames, system, "", "", *_median(bandwidth)))
        if system == "readcon-db":
            for other in ("ase.db", "ase.db-txn"):
                paired = by_ingest.get((n_frames, other))
                if not paired:
                    continue
                ratios = [
                    left["seconds"] / right["seconds"]
                    for left, right in zip(samples, paired)
                ]
                summary.append(
                    (
                        "paired_time_ratio",
                        n_frames,
                        f"readcon-db/{other}",
                        "",
                        "",
                        *_median(ratios),
                    )
                )
    by_query: dict[tuple, list] = {}
    for row in rows:
        if row["event"] == "query" and row["check"]:
            by_query.setdefault(
                (row["n_frames"], row["system"], row["query"]), []
            ).append(row)
    for key, samples in sorted(by_query.items()):
        n_frames, system, query = key
        for cache, field in (("cold", "cold_s"), ("warm", "warm_s")):
            summary.append(
                (
                    "query_s",
                    n_frames,
                    system,
                    query,
                    cache,
                    *_median([row[field] for row in samples]),
                )
            )
        if system == "readcon-db":
            for other in ("ase.db", "con-directory"):
                paired = by_query.get((n_frames, other, query))
                if not paired:
                    continue
                for cache, field in (("cold", "cold_s"), ("warm", "warm_s")):
                    ratios = [
                        left[field] / right[field]
                        for left, right in zip(samples, paired)
                    ]
                    summary.append(
                        (
                            "paired_time_ratio",
                            n_frames,
                            f"readcon-db/{other}",
                            query,
                            cache,
                            *_median(ratios),
                        )
                    )
    out.mkdir(parents=True, exist_ok=True)
    with (out / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "kind",
                "n_frames",
                "system",
                "query",
                "cache",
                "n",
                "median",
                "minimum",
                "maximum",
            ]
        )
        for kind, n_frames, system, query, cache, med, lo, hi in summary:
            writer.writerow(
                [
                    kind,
                    n_frames,
                    system,
                    query,
                    cache,
                    repeats(),
                    f"{med:.8g}",
                    f"{lo:.8g}",
                    f"{hi:.8g}",
                ]
            )
    size_rows = []
    grouped: dict[tuple, list] = {}
    for row in rows:
        if row["event"] == "size":
            size_rows.append(row)
        if row["event"] == "ingest" and row["check"]:
            grouped.setdefault((row["n_frames"], row["system"]), []).append(row)
    with (out / "sizes.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "n_frames",
                "store",
                "apparent_bytes",
                "allocated_bytes",
                "allocated_minimum",
                "allocated_maximum",
                "note",
            ]
        )
        for row in size_rows:
            writer.writerow(
                [
                    row["n_frames"],
                    row["store"],
                    row["apparent_bytes"],
                    row["allocated_bytes"],
                    row["allocated_bytes"],
                    row["allocated_bytes"],
                    row["note"],
                ]
            )
        for (n_frames, system), samples in sorted(grouped.items()):
            allocated = sorted(row["allocated_bytes"] for row in samples)
            apparent = sorted(row["apparent_bytes"] for row in samples)
            writer.writerow(
                [
                    n_frames,
                    system,
                    apparent[len(apparent) // 2],
                    allocated[len(allocated) // 2],
                    allocated[0],
                    allocated[-1],
                    "median file size over ingests",
                ]
            )
    checks = [row for row in rows if row["event"] == "correctness"]
    (out / "correctness.json").write_text(
        json.dumps(
            {
                "checks": [
                    {"name": row["name"], "pass": row["pass"], "detail": row["detail"]}
                    for row in checks
                ],
                "n_checks": len(checks),
                "n_pass": sum(row["pass"] for row in checks),
                "n_fail": sum(not row["pass"] for row in checks),
            },
            indent=2,
        )
        + "\n"
    )
    dedup_rows = [row for row in rows if row["event"] == "dedup"]
    if dedup_rows:
        payload = dict(dedup_rows[-1])
        payload.pop("event")
        payload["logical_unique_over_stored"] = (
            payload["n_unique_hashes"] / payload["n_frames"]
        )
        (out / "dedup.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out / "hardware.json").write_text(json.dumps(_hardware(), indent=2) + "\n")


def measure(out: Path) -> None:
    try:
        import readcon_db  # noqa: F401
    except ModuleNotFoundError as exc:
        pin = (
            "readcon-db @ git+https://github.com/lode-org/readcon-db.git"
            f"@{READCON_DB_REV}#subdirectory=python"
        )
        raise SystemExit(
            f"readcon_db is not installed ({exc}). pip install '{pin}'"
        ) from exc
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "raw.log"
    work = bench_dir("db-campaign")
    try:
        with log_path.open("w") as log:
            _emit(
                log,
                {
                    "event": "header",
                    "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "repeats": repeats(),
                    "command": "python paper/cpc/scripts/measure_db.py",
                    "readcon_db_pin": READCON_DB_REV,
                },
            )
            stores = {}
            oracles = {}
            import make_db_traces

            manifest = make_db_traces.build(work / "traces")
            _emit(log, {"event": "traces", **manifest["summary"]})
            for n_frames in SIZES:
                src = Path(manifest["scale"][str(n_frames)]["path"])
                oracle = manifest["scale"][str(n_frames)]["oracle"]
                oracles[n_frames] = oracle
                file_sizes(log, src, n_frames)
                chunks = work / f"chunks-{n_frames}"
                _chunks(src, chunks)
                made = {}
                order = ["readcon-db", "ase.db", "ase.db-txn"]
                for repeat in range(repeats()):
                    rotated = (
                        order[repeat % len(order) :] + order[: repeat % len(order)]
                    )
                    for kind in rotated:
                        dest = work / f"ingest-{n_frames}-{kind}-{repeat}"
                        row = worker_ingest(src, dest, kind, oracle)
                        row["n_frames"] = n_frames
                        row["repeat"] = repeat
                        _emit(log, row)
                        if repeat == 0:
                            made[kind] = dest
                        else:
                            release(dest)
                stores[n_frames] = {
                    "readcon-db": made["readcon-db"] / "corpus.lmdb",
                    "ase.db": made["ase.db"] / "atoms.db",
                    "con-directory": chunks,
                }
                queries = ("composition", "energy", "fmax")
                systems = ("readcon-db", "ase.db", "con-directory")
                for repeat in range(repeats()):
                    rotated = (
                        systems[repeat % len(systems) :]
                        + systems[: repeat % len(systems)]
                    )
                    for system in rotated:
                        for kind in queries:
                            row = _fresh_query(
                                stores[n_frames][system], system, kind, oracle
                            )
                            row["n_frames"] = n_frames
                            row["repeat"] = repeat
                            _emit(log, row)
            correctness(log)
            dedup(log, Path(manifest["akmc"]["path"]))
    finally:
        release(work)
    reduce_log(log_path, out)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--reduce", type=Path, help="write the tables from this raw log"
    )
    parser.add_argument("--worker", choices=("query",))
    parser.add_argument("--store", type=Path)
    parser.add_argument("--system")
    parser.add_argument("--kind")
    parser.add_argument("--oracle")
    args = parser.parse_args()
    if args.worker == "query":
        row = worker_query(args.store, args.system, args.kind, json.loads(args.oracle))
        print(json.dumps(row))
        return
    if args.reduce:
        reduce_log(args.reduce, args.out)
        return
    measure(args.out)


if __name__ == "__main__":
    main()
