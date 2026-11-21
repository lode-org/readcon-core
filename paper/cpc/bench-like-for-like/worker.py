"""One timed read in a fresh process. The clock starts after the import."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

import arms


def main() -> int:
    arm, path, threads_s = sys.argv[1:4]
    threads = int(threads_s)
    prefix = os.environ.get("READCON_PREFIX", "")
    eon_root = os.environ.get("EON_ROOT", "")
    if prefix:
        sys.path.insert(0, prefix)
    if eon_root:
        sys.path.insert(0, eon_root)
    version = arms.prepare(arm)
    print("READY", flush=True)
    sys.stdin.readline()
    if arm == "eon_svn_binary":
        payload, seconds = arms.measure_eon_binary(path)
    else:
        started = time.perf_counter()
        payload = arms.run_arm(arm, path, threads)
        seconds = time.perf_counter() - started
    n_frames, n_atoms, checksum = arms.digest(arm, payload)
    print(
        json.dumps(
            {
                "seconds": seconds,
                "n_frames": n_frames,
                "n_atoms": n_atoms,
                "checksum": checksum,
                "version": version,
                "error": "",
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(
            json.dumps(
                {
                    "seconds": None,
                    "n_frames": 0,
                    "n_atoms": 0,
                    "checksum": "",
                    "version": "",
                    "error": traceback.format_exc().replace("\n", " ")[-500:],
                }
            ),
            flush=True,
        )
        raise SystemExit(1)
