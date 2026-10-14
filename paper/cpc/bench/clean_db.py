"""readcon-db ingest on current main, including LMDB map growth.

The paired ingest follows the stored protocol: the clock starts before the
write and stops after a composition check. Threads are pinned to one.
ASE is the commit-per-write writer and the single-transaction writer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from clean_common import (
    MAPSIZE_BIN,
    REPEATS,
    RESULTS,
    ROOT,
    WORK,
    bca_median,
    bootstrap_p,
    environment_row,
    holm,
    write_csv,
)

os.environ["RAYON_NUM_THREADS"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "1")

import readcon
from ase.db import connect
from readcon_db import ConCorpus


def map_size(path: Path) -> int:
    proc = subprocess.run(
        [MAPSIZE_BIN, str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return int(proc.stdout.strip().splitlines()[-1])


def data_bytes(path: Path) -> int:
    file = path / "data.mdb"
    return file.stat().st_size if file.exists() else 0


def slice_con(src: Path, dest: Path, n_frames: int) -> None:
    """Keep the first n_frames. Each frame starts with the file's first line."""
    marker = src.read_text().splitlines()[0]
    kept: list[str] = []
    seen = 0
    buf: list[str] = []
    with src.open() as handle:
        for line in handle:
            if line.rstrip("\n") == marker and buf:
                if seen < n_frames:
                    kept.extend(buf)
                    seen += 1
                buf = [line]
                if seen >= n_frames:
                    break
            else:
                buf.append(line)
        else:
            if buf and seen < n_frames:
                kept.extend(buf)
                seen += 1
    if seen != n_frames:
        raise SystemExit(f"{src} yielded {seen} frames, wanted {n_frames}")
    dest.write_text("".join(kept))


def ingest_readcon(con: Path, corpus: Path, formula: str) -> tuple[float, int, int, int]:
    if corpus.exists():
        shutil.rmtree(corpus)
    db = ConCorpus(str(corpus))
    del db
    before = map_size(corpus)
    db = ConCorpus(str(corpus))
    t0 = time.perf_counter()
    n = int(db.append_trajectory(1, str(con)))
    keys = db.select(formula=formula, traj_id=1)
    if len(keys) != n:
        raise RuntimeError(f"composition check {len(keys)} != {n} for {formula}")
    seconds = time.perf_counter() - t0
    del db
    after = map_size(corpus)
    return seconds, n, before, after


def _images(con: Path):
    frames = readcon.read_con(str(con))
    return [frame.to_ase() for frame in frames], frames[0].composition_formula


def ingest_ase(con: Path, db_path: Path, mode: str) -> tuple[float, int]:
    images, formula = _images(con)
    if db_path.exists():
        db_path.unlink()
    db = connect(str(db_path))
    t0 = time.perf_counter()
    if mode == "ase_txn":
        with db:
            for index, atoms in enumerate(images):
                db.write(atoms, frame_idx=index)
    elif mode == "ase_commit":
        for index, atoms in enumerate(images):
            db.write(atoms, frame_idx=index)
    else:
        raise RuntimeError(mode)
    ase_formula = next(db.select()).formula
    rows = list(db.select(formula=ase_formula))
    if len(rows) != len(images):
        raise RuntimeError(
            f"ASE composition check {len(rows)} != {len(images)} ({ase_formula} vs {formula})"
        )
    return time.perf_counter() - t0, len(images)


def run_ingest() -> None:
    varying = WORK / "varying" / "frames.con"
    if not varying.exists():
        raise SystemExit(f"missing {varying}")
    info = environment_row()
    info["rayon_num_threads"] = os.environ["RAYON_NUM_THREADS"]
    formula = readcon.read_con(str(ROOT / "resources" / "test" / "cuh2.con"))[0].composition_formula
    raw = []
    corpus_root = WORK / "db"
    corpus_root.mkdir(exist_ok=True)
    for n_frames in (1000, 10000):
        con = corpus_root / f"frames-{n_frames}.con"
        print(f"slice {n_frames}", flush=True)
        slice_con(varying, con, n_frames)
        nbytes = con.stat().st_size
        for peer in ("ase_txn", "ase_commit"):
            for repeat in range(1, REPEATS + 1):
                print(f"db {n_frames} {peer} {repeat}", flush=True)
                seconds, n, before, after = ingest_readcon(
                    con, corpus_root / "readcon", formula
                )
                raw.append(
                    {
                        **info,
                        "n_frames": n_frames,
                        "peer": peer,
                        "repeat": repeat,
                        "role": "baseline",
                        "system": "readcon-db",
                        "seconds": f"{seconds:.9f}",
                        "status": "ok",
                        "frames_written": n,
                        "bytes": nbytes,
                        "map_before": before,
                        "map_after": after,
                        "data_mdb_bytes": data_bytes(corpus_root / "readcon"),
                    }
                )
                try:
                    peer_s, n_peer = ingest_ase(con, corpus_root / f"{peer}.db", peer)
                    status, detail = "ok", ""
                except BaseException as exc:
                    peer_s, n_peer = 0.0, 0
                    status, detail = "failure", f"{type(exc).__name__}: {exc}"
                raw.append(
                    {
                        **info,
                        "n_frames": n_frames,
                        "peer": peer,
                        "repeat": repeat,
                        "role": "peer",
                        "system": peer,
                        "seconds": f"{peer_s:.9f}" if status == "ok" else "",
                        "status": status,
                        "frames_written": n_peer,
                        "bytes": nbytes,
                        "map_before": "",
                        "map_after": "",
                        "data_mdb_bytes": "",
                        "detail": detail[:400],
                    }
                )
    write_csv(RESULTS / "clean_db_ingest.csv", raw)
    summarize_db(raw)
    grow_map(formula)


def summarize_db(rows: list[dict]) -> None:
    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((int(row["n_frames"]), row["peer"]), []).append(row)
    pending = []
    for (n_frames, peer), group in sorted(groups.items()):
        base = {int(r["repeat"]): r for r in group if r["role"] == "baseline"}
        peer_rows = {int(r["repeat"]): r for r in group if r["role"] == "peer"}
        ratios, base_t, peer_t = [], [], []
        for repeat, prow in sorted(peer_rows.items()):
            brow = base.get(repeat)
            if brow is None or brow["status"] != "ok" or prow["status"] != "ok":
                continue
            bt = float(brow["seconds"])
            pt = float(prow["seconds"])
            if bt <= 0 or pt <= 0:
                continue
            base_t.append(bt)
            peer_t.append(pt)
            ratios.append(bt / pt)
        item = {
            "n_frames": n_frames,
            "peer": peer,
            "n_pair_ok": len(ratios),
            "median_readcon_s": "",
            "median_peer_s": "",
            "median_ratio_readcon_over_peer": "",
            "bca_low": "",
            "bca_high": "",
            "p_raw": "",
            "holm_p": "",
            "readcon_frames_per_s": "",
            "peer_frames_per_s": "",
            "readcon_MB_per_s": "",
            "bytes": group[0]["bytes"],
        }
        if len(ratios) >= 2:
            arr = np.array(ratios)
            theta, lo, hi = bca_median(arr)
            p_raw = bootstrap_p(arr)
            med_b = float(np.median(base_t))
            med_p = float(np.median(peer_t))
            nbytes = float(group[0]["bytes"])
            item.update(
                {
                    "median_readcon_s": f"{med_b:.6g}",
                    "median_peer_s": f"{med_p:.6g}",
                    "median_ratio_readcon_over_peer": f"{theta:.6g}",
                    "bca_low": f"{lo:.6g}",
                    "bca_high": f"{hi:.6g}",
                    "p_raw": f"{p_raw:.6g}",
                    "readcon_frames_per_s": f"{n_frames / med_b:.6g}",
                    "peer_frames_per_s": f"{n_frames / med_p:.6g}",
                    "readcon_MB_per_s": f"{(nbytes / med_b) / 1e6:.6g}",
                    "_p": p_raw,
                }
            )
        pending.append(item)
    tested = [item for item in pending if "_p" in item]
    adjusted = holm([item["_p"] for item in tested]) if tested else []
    for item, adj in zip(tested, adjusted, strict=True):
        item["holm_p"] = f"{adj:.6g}"
        item.pop("_p", None)
    for item in pending:
        item.pop("_p", None)
    write_csv(RESULTS / "clean_db_summary.csv", pending)


def grow_map(formula: str) -> None:
    """Unique frames until the LMDB map is larger than the 2 GiB default."""
    template = (ROOT / "resources" / "test" / "cuh2.con").read_text()
    lines = template.splitlines(keepends=True)
    # First coordinate line is the first line that starts with a float after the header.
    coord_index = None
    for index, line in enumerate(lines):
        bits = line.split()
        if len(bits) >= 5:
            try:
                float(bits[0])
                float(bits[1])
                float(bits[2])
                int(bits[3])
            except ValueError:
                continue
            coord_index = index
            break
    if coord_index is None:
        raise SystemExit("no coordinate row in cuh2.con")
    target_frames = int(os.environ.get("CLEAN_GROW_FRAMES", "80000"))
    path = WORK / "db" / "grow.con"
    print(f"writing {target_frames} unique frames for map growth", flush=True)
    with path.open("w") as handle:
        for frame_index in range(target_frames):
            bits = lines[coord_index].split()
            bits[0] = f"{float(bits[0]) + frame_index * 1.0e-6:.16g}"
            bumped = lines.copy()
            bumped[coord_index] = " ".join(bits) + "\n"
            handle.writelines(bumped)
    nbytes = path.stat().st_size
    corpus = WORK / "db" / "grow"
    print(f"ingesting {nbytes} bytes", flush=True)
    seconds, n, before, after = ingest_readcon(path, corpus, formula)
    row = {
        "n_frames": n,
        "bytes": nbytes,
        "seconds": f"{seconds:.6g}",
        "frames_per_s": f"{n / seconds:.6g}",
        "map_before": before,
        "map_after": after,
        "map_grew": "yes" if after > before else "no",
        "default_map_bytes": str(2 * 1024 * 1024 * 1024),
        "above_default_cap": "yes" if after > 2 * 1024 * 1024 * 1024 else "no",
        "data_mdb_bytes": data_bytes(corpus),
        "readcon_db_sha": subprocess.check_output(
            ["git", "-C", "/tmp/readcon-db", "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    write_csv(RESULTS / "clean_db_map.csv", [row])
    print(row, flush=True)
    if after <= before:
        raise SystemExit("LMDB map did not grow")


if __name__ == "__main__":
    run_ingest()
