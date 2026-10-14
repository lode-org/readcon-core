#!/usr/bin/env python3
"""Join the Python, C, Julia and Fortran drift logs.

The Python corpus log is the one ``drift.py`` writes. Header variants are
the seven files ``version_safety.py --dump`` materialises; this script
repeats the Python and C accept/reject and the Python rewrite digest on
those files so the merged table covers the corpus and the variants.

Columns:
file, expected, python, c_abi, julia, fortran,
sha_python, sha_julia, sha_fortran,
rewrite_stable_python, rewrite_stable_julia, rewrite_stable_fortran
"""
from __future__ import annotations

import csv
import ctypes
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def _lib():
    candidates = [
        os.environ.get("READCON_LIB", ""),
        "/workspace/target/release/libreadcon_core.so",
        "/workspace/.cargo-target/release/libreadcon_core.so",
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            lib = ctypes.CDLL(cand)
            lib.rkr_read_all_frames.restype = ctypes.c_void_p
            lib.rkr_read_all_frames.argtypes = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            if hasattr(lib, "free_rkr_frame_array"):
                lib.free_rkr_frame_array.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            return lib
    return None


def python_row(path: Path) -> dict[str, str]:
    import readcon

    try:
        frames = readcon.read_con(str(path))
        text = readcon.write_con_string(frames)
        again = readcon.write_con_string(readcon.read_con_string(text))
        return {
            "python": "accept",
            "sha_python": hashlib.sha256(text.encode()).hexdigest()[:12],
            "rewrite_stable_python": "yes" if again == text else "no",
        }
    except Exception:
        return {"python": "reject", "sha_python": "-", "rewrite_stable_python": "-"}


def c_decision(lib, path: Path) -> str:
    if lib is None:
        return "-"
    n = ctypes.c_size_t(0)
    handle = lib.rkr_read_all_frames(str(path).encode(), ctypes.byref(n))
    if not handle:
        return "reject"
    if hasattr(lib, "free_rkr_frame_array"):
        lib.free_rkr_frame_array(handle, n)
    return "accept"


def load_side(path: Path, prefix: str) -> dict[str, dict[str, str]]:
    rows = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            rows[row["file"]] = row
    return rows


def expected_for(name: str, variant_rules: dict[str, str]) -> str:
    if name in variant_rules:
        rule = variant_rules[name]
        return "accept" if rule.startswith("accept") else "reject"
    return "accept" if not name.startswith(
        (
            "validate_",
            "v3_bad",
            "v3_missing",
            "missing_",
            "column4_out",
            "per_type",
            "unknown_",
            "unsupported_",
        )
    ) else "reject"


def main() -> None:
    julia_csv = Path(sys.argv[1])
    fortran_csv = Path(sys.argv[2])
    corpus = sorted((REPO / "resources" / "conformance").glob("*/*.con"))
    variants = sorted(Path(sys.argv[3]).glob("variant*.con"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "version_safety", ROOT / "scripts" / "version_safety.py"
    )
    version_safety = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(version_safety)
    rules = {
        f"variant{i}.con": rule
        for i, (_name, (_hdr, rule)) in enumerate(version_safety.VARIANTS.items())
    }
    # Corpus expectation is the directory name, which is authoritative.
    corpus_expected = {path.name: "accept" if path.parent.name == "valid" else "reject" for path in corpus}

    lib = _lib()
    julia = load_side(julia_csv, "julia")
    fortran = load_side(fortran_csv, "fortran")
    out_rows = []
    for path in list(corpus) + list(variants):
        py = python_row(path)
        c = c_decision(lib, path)
        j = julia.get(path.name, {})
        f = fortran.get(path.name, {})
        if path.name in corpus_expected:
            expect = corpus_expected[path.name]
        else:
            expect = expected_for(path.name, rules)
        out_rows.append(
            {
                "file": path.name,
                "expected": expect,
                "python": py["python"],
                "c_abi": c,
                "julia": j.get("julia", "missing"),
                "fortran": f.get("fortran", "missing"),
                "sha_python": py["sha_python"],
                "sha_julia": j.get("sha_julia", "-"),
                "sha_fortran": f.get("sha_fortran", "-"),
                "rewrite_stable_python": py["rewrite_stable_python"],
                "rewrite_stable_julia": j.get("rewrite_stable_julia", "-"),
                "rewrite_stable_fortran": f.get("rewrite_stable_fortran", "-"),
            }
        )
    dest = ROOT / "data" / "failure" / "drift_bindings.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0])
    with dest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    bad = []
    for row in out_rows:
        decisions = [row["python"], row["c_abi"], row["julia"], row["fortran"]]
        if any(item != row["expected"] for item in decisions):
            bad.append(row["file"] + " decision")
        if row["expected"] == "accept":
            digests = {row["sha_python"], row["sha_julia"], row["sha_fortran"]}
            digests.discard("-")
            if len(digests) != 1:
                bad.append(row["file"] + " sha " + ",".join(sorted(digests)))
    print(f"wrote {dest} rows={len(out_rows)} disagreements={len(bad)}")
    for item in bad:
        print(" ", item)


if __name__ == "__main__":
    main()
