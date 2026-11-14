#!/usr/bin/env python3
"""Version and unit safety: header variants given to every reader on the box.

Each variant changes line 2 of one velocity frame. Readers are the
readcon-core Python binding and the readcon-core C interface (ctypes). The
Julia and Fortran bindings run the same files in a separate job.

For the Python binding the record keeps the read (class and line of a
rejection, the time unit applied to the velocities, the time-unit override
warning) apart from the rewrite (the version and units.time that
write_con_string writes back, and an unknown key it keeps).

Writes data/failure/version_safety.csv and its JSON sidecar with the build,
host and the C library that was loaded; --out DIR writes them to DIR.
"""

from __future__ import annotations
import argparse
import csv
import ctypes
import json
import os
import sys
import warnings
from pathlib import Path


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "failure"
sys.path.insert(0, str(Path(__file__).resolve().parent))
SRC = REPO / "resources" / "test" / "tiny_cuh2.convel"
NAT = "(amu*angstrom^2/eV)^0.5"
U = {"energy": "eV", "length": "angstrom", "mass": "amu"}
UNKNOWN = "band_optimizer_state"

VARIANTS = {
    "3.1, natural unit declared": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": dict(U, time=NAT),
        },
        "accept",
    ),
    "3.1, no time unit": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": U,
        },
        "reject",
    ),
    "3.0, labelled fs": (
        {
            "con_spec_version": 3,
            "sections": ["velocities"],
            "units": dict(U, time="fs"),
        },
        "accept, natural unit",
    ),
    "3.3, unknown key": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 3,
            "sections": ["velocities"],
            "units": dict(U, time=NAT),
            UNKNOWN: {"kind": "lbfgs"},
        },
        "accept, keep key",
    ),
    "4.0": (
        {
            "con_spec_version": 4,
            "con_spec_minor": 0,
            "sections": ["velocities"],
            "units": dict(U, time=NAT),
        },
        "reject",
    ),
    "missing version": (
        {"sections": ["velocities"], "units": dict(U, time=NAT)},
        "reject",
    ),
    "3.1, mask 9": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": dict(U, time=NAT),
        },
        "reject",
    ),
}


def make(path, header, mask9=False):
    lines = SRC.read_text().splitlines()
    lines[1] = json.dumps(header)
    if mask9:
        lines[11] = lines[11].replace(" 7    0", " 9    0")
    path.write_text("\n".join(lines) + "\n")


def lib_path():
    raw = os.environ.get("READCON_LIB", "")
    p = Path(raw) if raw else REPO / "target/release/libreadcon_core.so"
    if raw and not p.is_absolute():
        p = (REPO / p).resolve()
    return p


def lib():
    L = ctypes.CDLL(str(lib_path()))
    L.rkr_read_all_frames.restype = ctypes.c_void_p
    L.rkr_read_all_frames.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
    return L


def applied_unit(frame):
    value = getattr(frame, "velocity_time_unit", None)
    return value() if callable(value) else value


def python_row(readcon, classify, p, hdr):
    row = dict(
        python="reject",
        python_class="-",
        python_line="-",
        python_time_unit="-",
        python_override_warning="-",
        python_rewrite="-",
        python_rewrite_time_unit="-",
        python_kept_unknown_key="-",
    )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fr = readcon.read_con(str(p))
    except Exception as e:
        cls, line, _ = classify(e)
        row.update(python_class=cls, python_line=line or "-")
        return row
    warned = any(w.category.__name__ == "TimeUnitOverrideWarning" for w in caught)
    row.update(
        python="accept",
        python_time_unit=applied_unit(fr[0]) or "-",
        python_override_warning="yes" if warned else "no",
    )
    try:
        out = json.loads(readcon.write_con_string(fr).splitlines()[1])
    except Exception as e:
        row["python_rewrite"] = "refused: " + classify(e)[0]
        return row
    row.update(
        python_rewrite=f"{out.get('con_spec_version')}.{out.get('con_spec_minor', 0)}",
        python_rewrite_time_unit=out.get("units", {}).get("time", "-"),
    )
    if UNKNOWN in hdr:
        row["python_kept_unknown_key"] = "yes" if UNKNOWN in out else "no"
    return row


def main(out_dir):
    import readcon
    from error_class import classify

    L = lib()
    rows = []
    with bench_scratch("scratch") as td:
        for name, (hdr, rule) in VARIANTS.items():
            p = Path(td) / "v.con"
            make(p, hdr, mask9="mask 9" in name)
            row = dict(variant=name, rule=rule, **python_row(readcon, classify, p, hdr))
            n = ctypes.c_size_t(0)
            row["c_abi"] = (
                "accept"
                if L.rkr_read_all_frames(str(p).encode(), ctypes.byref(n))
                else "reject"
            )
            rows.append(row)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "version_safety.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    import provenance

    (out_dir / "version_safety.json").write_text(
        json.dumps(
            dict(
                provenance=provenance.record(),
                c_abi=provenance.binary_build(lib_path()),
                source=str(SRC.relative_to(REPO)),
            ),
            indent=1,
        )
        + "\n"
    )
    for r in rows:
        print(r)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--dump",
        type=Path,
        metavar="DIR",
        help="write the variant files to DIR and stop",
    )
    ap.add_argument(
        "--out", type=Path, default=OUT, help="record directory (default: %(default)s)"
    )
    args = ap.parse_args()
    if args.dump:
        args.dump.mkdir(parents=True, exist_ok=True)
        for i, (name, (hdr, _)) in enumerate(VARIANTS.items()):
            make(args.dump / f"variant{i}.con", hdr, mask9="mask 9" in name)
            print(args.dump / f"variant{i}.con", name)
    else:
        main(args.out)
