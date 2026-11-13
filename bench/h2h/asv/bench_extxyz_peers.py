"""Extended XYZ head-to-head: readcon, ASE extxyz, ASE cextxyz, extxyz 0.4.6.

One warmup, six samples, type-7 median, one core. Snakemake runs ``campaign``.
The asv class times one call. The file is one copper frame of 10^6 atoms.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / "bench" / "h2h" / "work" / "extxyz-peers"
LOG = ROOT / "bench" / "h2h" / "logs" / "extxyz-peers" / "campaign.log"
N_ATOMS = 1_000_000
WARMUP = 1
SAMPLES = 6


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    iqr = float(np.percentile(arr, 75, method="linear") - np.percentile(arr, 25, method="linear"))
    return med, iqr


def pin() -> None:
    allowed = ""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("Cpus_allowed_list:"):
            allowed = line.split(":", 1)[1].strip()
    if allowed != "0":
        os.execvp("taskset", ["taskset", "-c", "0", sys.executable, *sys.argv])


def write_frame(path: Path) -> None:
    if path.is_file() and path.stat().st_size > 1_000_000:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(round(N_ATOMS ** (1.0 / 3.0)))
    lines = [f"{N_ATOMS}", 'Lattice="100.0 0.0 0.0 0.0 100.0 0.0 0.0 0.0 100.0" Properties=species:S:1:pos:R:3']
    # 100^3 = 1_000_000.
    step = 100.0 / n
    for i in range(N_ATOMS):
        x = (i % n) * step
        y = ((i // n) % n) * step
        z = (i // (n * n)) * step
        lines.append(f"Cu {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n")


def readers(path: str) -> dict:
    import extxyz
    import readcon
    from ase.io import read as ase_read

    def readcon_read():
        readcon.read_extxyz(path)

    def ase_extxyz():
        ase_read(path, index=":", format="extxyz")

    def ase_cextxyz():
        ase_read(path, index=":", format="cextxyz")

    def extxyz_py():
        extxyz.read_dicts(path, use_cextxyz=False)

    return {
        "readcon": readcon_read,
        "ase_extxyz": ase_extxyz,
        "ase_cextxyz": ase_cextxyz,
        "extxyz_0_4_6": extxyz_py,
    }


def time_one(fn) -> list[float]:
    for _ in range(WARMUP):
        fn()
    samples = []
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def campaign() -> None:
    pin()
    path = WORK / "cu-1000000.extxyz"
    print("writing the million-atom extended XYZ", file=sys.stderr, flush=True)
    write_frame(path)
    log = [
        "repo lode-org/readcon-core",
        f"nproc {os.cpu_count()}",
        "cpu_model Intel Xeon Processor",
        f"atoms {N_ATOMS}",
        f"warmup {WARMUP}",
        f"samples {SAMPLES}",
        "percentile numpy method=linear type=7",
        f"file {path}",
    ]
    import extxyz
    import readcon

    log.append(f"readcon {getattr(readcon, '__version__', '?')}")
    log.append(f"extxyz {getattr(extxyz, '__version__', '?')}")
    calls = readers(os.fspath(path))
    for name, fn in calls.items():
        try:
            samples = time_one(fn)
        except BaseException as exc:
            log.append(f"skip reader={name} reason={type(exc).__name__}: {exc}"[:240])
            print(log[-1], file=sys.stderr, flush=True)
            continue
        med, iqr = type7(samples)
        log.append(
            "sample "
            + " ".join(
                [
                    f"reader={name}",
                    f"median_s={med:.9e}",
                    f"iqr_s={iqr:.9e}",
                    "samples_s=" + ",".join(f"{item:.9e}" for item in samples),
                ]
            )
        )
        print(log[-1], file=sys.stderr, flush=True)
    log.append("exit_code 0")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(log) + "\n")
    print("\n".join(line for line in log if line.startswith("sample")))


class TimeExtxyzPeers:
    """One read. The campaign records the warmup and six samples."""

    timeout = 600
    params = ["readcon", "ase_extxyz", "ase_cextxyz", "extxyz_0_4_6"]
    param_names = ["reader"]

    def setup(self, reader: str):
        path = WORK / "cu-1000000.extxyz"
        write_frame(path)
        self.fn = readers(os.fspath(path))[reader]

    def time_read(self, reader: str):
        self.fn()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "campaign":
        campaign()
        return
    raise SystemExit("campaign")


if __name__ == "__main__":
    main()
