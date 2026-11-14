#!/usr/bin/env python3
"""Time every Python and C++ read of the 0.17.3 tables in one interleaved campaign.

A cell is one reader on one payload at one thread count: the Python cells of
``readers.py``, each run a fresh ``bench_child.py``, and the C++ cells of
``cpp_reads.py``, each run a fresh process of its program.
``interleave.campaign`` runs one untimed round and then the timed rounds, every
cell once per round in an order shuffled anew for each round from the recorded
seed.  For each run the parent waits for READY, reads the payload once so the
page cache holds it, and sends the line that starts the clock; the process
prints the seconds from that line until every frame it read is freed, with the
checksums of the read.  Every run of a cell must print the checksums of its
payload's reference in ``payloads.json``.

The readcon module must be newer than every library file, a commit must hold
those files (``r0174.build``), and the C++ programs must be those
``cpp/build.json`` hashed.  The record, with the provenance of ``r0174.record``,
goes to ``BENCH_RESULTS/reads.json``.

    python bench/reads.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import cpp_reads  # noqa: E402
import interleave  # noqa: E402
import portable  # noqa: E402
import r0174  # noqa: E402
import readers  # noqa: E402

RESULTS = Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174"))


def prime(path: Path) -> None:
    with path.open("rb") as handle:
        while handle.read(1 << 24):
            pass


def timed_run(argv: list[str], payload: Path, env: dict | None = None) -> dict:
    """One fresh process: READY, the payload read into the page cache, the line that starts its clock, its JSON."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    ready = proc.stdout.readline().strip()
    if ready != "READY":
        _, err = proc.communicate()
        raise SystemExit(
            f"{' '.join(argv)} printed {ready!r} instead of READY: {err[-2000:]}"
        )
    prime(payload)
    out, err = proc.communicate("\n")
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(argv)} exited {proc.returncode}: {err[-2000:]}")
    return json.loads(out.strip().splitlines()[-1])


def python_cell(reader: str, threads: int):
    argv = [sys.executable, str(HERE / "bench_child.py"), reader, str(threads)]
    payload = readers.PAYLOADS / readers.READERS[reader][2]
    return lambda: timed_run(argv, payload)


def cpp_cell(cell: tuple):
    payload = cpp_reads.PAYLOADS / cell[3]
    return lambda: timed_run(
        cpp_reads.argv(cell), payload, cpp_reads.environment(cell[5])
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    stamp = r0174.record()
    cpp_build = json.loads((RESULTS / "cpp" / "build.json").read_text())
    for program, path in cpp_reads.PROGRAMS.items():
        if sha256(path) != cpp_build["artifacts"][program]:
            raise SystemExit(
                f"{path} is not the {program} that cpp/build.json hashed; rerun bench/cpp_reads.py"
            )
    manifest = json.loads((RESULTS / "payloads.json").read_text())

    cells, meta = {}, {}
    for reader, threads in readers.cells():
        name = f"python:{reader}:{threads}"
        contract, _, payload, warm = readers.READERS[reader]
        cells[name] = python_cell(reader, threads)
        meta[name] = {
            "kind": "python",
            "reader": reader,
            "threads": threads,
            "contract": contract,
            "payload": payload,
            "warm": warm,
        }
    for cell in cpp_reads.CELLS:
        name = f"cpp:{cell[0]}"
        cells[name] = cpp_cell(cell)
        meta[name] = {
            "kind": "cpp",
            "reader": cell[0],
            "program": cell[1],
            "threads": cell[5],
            "contract": cell[2],
            "payload": cell[3],
            "warm": cell[4],
        }

    record = interleave.campaign(cells)
    bad = []
    for name, info in meta.items():
        cell = record["cells"][name]
        reference = manifest["references"][
            manifest["files"][info["payload"]]["payload"]
        ]
        if info["kind"] == "python":
            wrong = readers.mismatches(cell["printed"], reference)
        else:
            want = {key: reference[key] for key in cpp_reads.CHECKED[info["contract"]]}
            wrong = cpp_reads.disagreements(info["contract"], cell["printed"], want)
        record["cells"][name] = {**info, **cell, "mismatches": wrong}
        bad += [f"{name}: {wrong}"] if wrong else []
    if bad:
        raise SystemExit("reads disagree with payloads.json: " + "; ".join(bad))
    record["provenance"] = stamp
    record["cpp_artifacts"] = cpp_build["artifacts"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "reads.json").write_text(
        json.dumps(portable.portable(record), indent=2) + "\n"
    )
    print("wrote", RESULTS / "reads.json")


if __name__ == "__main__":
    main()
