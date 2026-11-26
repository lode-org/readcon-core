#!/usr/bin/env python3
"""Version and unit safety: header variants given to every reader on the box.

Each variant changes line 2 of one velocity frame. Readers are the
readcon-core Python binding and the readcon-core C interface (ctypes). The
Julia and Fortran bindings run the same files in a separate job.

For the Python binding the record keeps the read (class and line of a
rejection, the time unit to_ase applied, the time-unit override
warning) apart from the rewrite (the version and units.time that
write_con_string writes back, and an unknown key it keeps). The applied
unit is natural when the ASE velocities match the file and fs when they
are the file velocities times the natural-to-fs factor.

Writes data/failure/version_safety-<readcon version>.csv and its JSON sidecar
with the build, host and the C library that was loaded. The unversioned
version_safety.csv of an earlier readcon stays where it is. --out DIR writes
the versioned files into DIR.
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


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "failure"
sys.path.insert(0, str(Path(__file__).resolve().parent))
SRC = REPO / "resources" / "test" / "tiny_cuh2.convel"
# CON-units.5. Major 3 rewrites keep the historical spelling. A rewrite that
# emits major 4 uses the symbol spelling (CON-units.19).
HISTORICAL = "(amu*angstrom^2/eV)^0.5"
SYMBOL = "(u*\u00c5^2/eV)^0.5"
NATURAL = frozenset((HISTORICAL, SYMBOL))
# fs per natural time unit (src/units.rs, CODATA 2018). to_ase multiplies
# a file velocity labelled fs by this and leaves a natural-unit velocity.
NAT_FS = 10.180505710759414
U = {"energy": "eV", "length": "angstrom", "mass": "amu"}
UNKNOWN = "band_optimizer_state"

# Rules follow docs/orgmode/spec.org at 4.0.5: CON-status.1, CON-line2.7,
# CON-units.8 through CON-units.11. Major 3 accepts every minor, reads
# velocities in the natural unit, and does not reject an absent units.time.
# Major 4 is accepted and units.time is authoritative, so velocities without
# it are InvalidUnits. Major 5 is UnsupportedVersion. A binding rewrite of a
# 3.0 velocities frame labelled fs is major 4 with the symbol spelling.
VARIANTS = {
    "3.1, natural unit declared": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": dict(U, time=HISTORICAL),
        },
        "accept, natural unit",
    ),
    "3.1, no time unit": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": U,
        },
        "accept, natural unit",
    ),
    "3.0, labelled fs": (
        {
            "con_spec_version": 3,
            "sections": ["velocities"],
            "units": dict(U, time="fs"),
        },
        "accept, natural unit, rewrite 4.0.4",
    ),
    "3.3, unknown key": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 3,
            "sections": ["velocities"],
            "units": dict(U, time=HISTORICAL),
            UNKNOWN: {"kind": "lbfgs"},
        },
        "accept, keep key",
    ),
    "4.0": (
        {
            "con_spec_version": 4,
            "con_spec_minor": 0,
            "sections": ["velocities"],
            "units": dict(U, time=HISTORICAL),
        },
        "accept, authoritative unit",
    ),
    "4.0, no time unit": (
        {
            "con_spec_version": 4,
            "con_spec_minor": 0,
            "sections": ["velocities"],
            "units": U,
        },
        "reject InvalidUnits",
    ),
    "4.0, labelled fs": (
        {
            "con_spec_version": 4,
            "con_spec_minor": 0,
            "sections": ["velocities"],
            "units": dict(U, time="fs"),
        },
        "accept, authoritative unit",
    ),
    "5.0": (
        {
            "con_spec_version": 5,
            "con_spec_minor": 0,
            "sections": ["velocities"],
            "units": dict(U, time=HISTORICAL),
        },
        "reject UnsupportedVersion",
    ),
    "missing version": (
        {"sections": ["velocities"], "units": dict(U, time=HISTORICAL)},
        "reject MissingSpecVersion",
    ),
    "3.1, mask 9": (
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "sections": ["velocities"],
            "units": dict(U, time=HISTORICAL),
        },
        "reject InvalidFixedFlag",
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
    path = lib_path()
    L = ctypes.CDLL(str(path))
    if not hasattr(L, "rkr_read_all_frames"):
        raise SystemExit(
            f"{path} lacks rkr_read_all_frames; "
            "rebuild with cargo build --release --features capi,benchmark"
        )
    L.rkr_read_all_frames.restype = ctypes.c_void_p
    L.rkr_read_all_frames.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
    return L


def file_time(header):
    units = header.get("units") or {}
    return units.get("time")


def applied_unit(frame):
    """``natural`` or ``fs``, from the to_ase velocity scale.

    A ratio of one is the natural unit. A ratio of ``NAT_FS`` is fs. The
    header string is not the measurement.
    """
    file_v = frame.velocities_array().reshape(-1).tolist()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ase_v = frame.to_ase().get_velocities().reshape(-1).tolist()
    ratios = [
        got / stored
        for stored, got in zip(file_v, ase_v, strict=True)
        if abs(stored) > 1e-12
    ]
    if not ratios:
        return "-"
    ratios.sort()
    ratio = ratios[len(ratios) // 2]
    if abs(ratio - 1.0) <= 1e-6:
        return "natural"
    if abs(ratio - NAT_FS) <= 1e-6 * NAT_FS:
        return "fs"
    return f"{ratio:.8g}"


def rewrite_version(header):
    major = header.get("con_spec_version")
    minor = header.get("con_spec_minor", 0)
    if "con_spec_patch" in header:
        return f"{major}.{minor}.{header.get('con_spec_patch')}"
    return f"{major}.{minor}"


def assert_rule(name, header, rule, row):
    """Raise AssertionError when ``row`` misses the specification rule."""
    label = file_time(header)
    if rule.startswith("reject "):
        kind = rule.split(" ", 1)[1]
        if row["python"] != "reject" or row["c_abi"] != "reject":
            raise AssertionError(f"{name}: {rule} but {row['python']}/{row['c_abi']}")
        if row["python_class"] != kind:
            raise AssertionError(f"{name}: {kind} but {row['python_class']}")
        return
    if row["python"] != "accept" or row["c_abi"] != "accept":
        raise AssertionError(f"{name}: {rule} but {row['python']}/{row['c_abi']}")
    measured = row["python_time_unit"]
    if "natural unit" in rule and measured != "natural":
        raise AssertionError(f"{name}: natural unit but {measured}")
    if (
        "natural unit" in rule
        and label not in NATURAL
        and label is not None
        and measured == label
    ):
        raise AssertionError(f"{name}: applied {label}")
    if "authoritative unit" in rule and not _authoritative(label, measured):
        raise AssertionError(f"{name}: units.time {label} but applied {measured}")
    if "keep key" in rule and row["python_kept_unknown_key"] != "yes":
        raise AssertionError(f"{name}: dropped {UNKNOWN}")
    if "rewrite 4.0.4" in rule:
        if row["python_rewrite"] != "4.0.4":
            raise AssertionError(f"{name}: rewrite {row['python_rewrite']}")
        if row["python_rewrite_time_unit"] != SYMBOL:
            raise AssertionError(
                f"{name}: rewrite time {row['python_rewrite_time_unit']}"
            )


def _authoritative(label, measured):
    """A natural spelling measures as natural, and fs measures as fs."""
    if label in NATURAL:
        return measured == "natural"
    if label == "fs":
        return measured == "fs"
    return False


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
        python_rewrite=rewrite_version(out),
        python_rewrite_time_unit=out.get("units", {}).get("time", "-"),
    )
    if UNKNOWN in hdr:
        row["python_kept_unknown_key"] = "yes" if UNKNOWN in out else "no"
    return row


def measure_rows():
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
    return rows


def record_names(version):
    return f"version_safety-{version}.csv", f"version_safety-{version}.json"


def main(out_dir):
    import provenance
    import readcon

    rows = measure_rows()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_name, json_name = record_names(readcon.__version__)
    with open(out_dir / csv_name, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (out_dir / json_name).write_text(
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
