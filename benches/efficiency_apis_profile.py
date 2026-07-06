#!/usr/bin/env python3
"""Wall-clock profile of efficiency APIs (release build, equal fixtures)."""
from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

import readcon

REPO = Path(__file__).resolve().parent if False else Path(".")
# overridden below


def med(xs):
    return float(statistics.median(xs))


def timeit(fn, repeats=11, warmup=2):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return times


def ladder_con(fixture: Path, n_frames: int, out: Path):
    out.write_text(fixture.read_text() * n_frames)


def main():
    import sys

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    tiny = root / "resources/test/tiny_cuh2.con"
    cuh2 = root / "resources/test/cuh2.con"
    results = {
        "host": "rg.terra",
        "readcon": getattr(readcon, "__file__", None),
        "protocol": "median of 11 timed runs after 2 warmups; equal geometry ladders",
        "cases": [],
    }

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cases = [
            ("tiny_n20", tiny, 20),   # small multi-frame (<48KiB likely)
            ("tiny_n200", tiny, 200), # larger multi-frame
            ("cuh2_n20", cuh2, 20),   # large cells, parallel candidate
            ("cuh2_n50", cuh2, 50),
        ]
        for name, fixture, n in cases:
            path = td / f"{name}.con"
            ladder_con(fixture, n, path)
            size = path.stat().st_size
            # APIs
            t_batch = timeit(lambda p=str(path): readcon.read_all_frames(p))
            t_stream = timeit(
                lambda p=str(path): [f for f in readcon.iter_con(p)]
            )
            t_count = timeit(lambda p=str(path): readcon.count_frames(p))
            t_pos = timeit(lambda p=str(path): readcon.read_all_positions(p))
            # first frame only
            t_first = timeit(lambda p=str(path): readcon.read_first_frame(p))

            m_batch = med(t_batch)
            row = {
                "case": name,
                "n_frames": n,
                "bytes": size,
                "parallel_gate_48kib": size >= 48 * 1024,
                "read_all_frames_median_s": m_batch,
                "iter_con_materialize_median_s": med(t_stream),
                "count_frames_median_s": med(t_count),
                "read_all_positions_median_s": med(t_pos),
                "read_first_frame_median_s": med(t_first),
                "ratio_count_vs_batch": med(t_count) / m_batch if m_batch else None,
                "ratio_positions_vs_batch": med(t_pos) / m_batch if m_batch else None,
                "ratio_stream_vs_batch": med(t_stream) / m_batch if m_batch else None,
                "batch_frames_per_s": n / m_batch if m_batch else None,
            }
            results["cases"].append(row)
            print(
                f"{name} bytes={size} par={row['parallel_gate_48kib']} "
                f"batch={m_batch*1e3:.3f}ms stream={med(t_stream)*1e3:.3f}ms "
                f"count={med(t_count)*1e3:.3f}ms pos={med(t_pos)*1e3:.3f}ms "
                f"first={med(t_first)*1e3:.3f}ms "
                f"count/batch={row['ratio_count_vs_batch']:.3f} "
                f"pos/batch={row['ratio_positions_vs_batch']:.3f}",
                flush=True,
            )

    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("eff_profile.json")
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
