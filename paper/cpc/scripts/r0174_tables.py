#!/usr/bin/env python3
"""Write the readcon-core 0.17.4 performance tables and macros from the timing, memray and Cachegrind records.

Inputs (``R0174``, default ``bench/results/r0174``):

* ``reads.json``, written by ``bench/reads.py``: the Python cells of ``bench/readers.py`` and the C++ cells of
  ``bench/cpp_reads.py``, timed in one campaign;
* ``memray.json``, written by ``bench/memray_peaks.py``;
* ``cachegrind/cachegrind_results.json``, written by ``bench/cachegrind.py``;
* ``cpp/checks.json`` and ``cpp/build.json``, written by ``bench/cpp_reads.py``;
* ``provenance.json`` (``bench/r0174.py``) and ``payloads.json`` (``bench/make_payloads.py``).

Every record must name the build and the hardware line of ``provenance.json``
and run the protocol of ``reads.json`` (``bench/interleave.py``): one seed, one
count of rounds of at least ``MIN_ROUNDS`` and one count of warm-up rounds.
The Cachegrind harness must have run at the commit ``provenance.json`` names,
and the C++ programs that ran must be those ``cpp/build.json`` hashed.

Outputs (``BENCH_GENERATED``, default ``src/figures/generated``):

* ``r0174_table.tex``       Table ``tab:perf``, time and peak heap of each Python read;
* ``r0174_cpp.tex``         Table ``tab:cpp``, time of each C++ process;
* ``r0174_cachegrind.tex``  SI table ``tab:cachegrind``, instruction counts;
* ``r0174_macros.tex``      every number the prose quotes from these records.

A time, a peak or a count is the median of the runs of its cell, with the
interquartile range of the same runs (``statistics.quantiles`` with method
``inclusive``).  A ratio is the readcon median over the other reader's median;
``scripts/ordering_tests.py`` gives each ratio its distribution-free interval.
"""

from __future__ import annotations

import json
import os
import re
from math import floor, log10
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("R0174", ROOT / "bench" / "results" / "r0174"))
OUT = Path(os.environ.get("BENCH_GENERATED", ROOT / "src" / "figures" / "generated"))
MIB = 1024 * 1024
MIN_ROUNDS = 6

READERS = {
    "readcon": ("Rc", "readcon-core", "CON 3.1"),
    "readcon_fields": ("RcFrames", "readcon-core, frames only", "CON 3.1"),
    "readcon_coords": ("RcCoords", "readcon-core", "CON 3.1, no velocities"),
    "ase_eon": ("AseEon", "ASE \\texttt{eon}", "CON 3.1, no velocities"),
    "ase_extxyz": ("AseExtxyz", "ASE", "extended XYZ"),
    "extxyz_c": ("ExtxyzC", "\\texttt{extxyz} (C)", "extended XYZ"),
    "ovito": ("Ovito", "OVITO", "extended XYZ"),
    "ase_traj": ("AseTraj", "ASE", "ASE trajectory"),
    "h5py": ("Hfivepy", "h5py", "H5MD"),
    "mda_h5md": ("Mda", "MDAnalysis", "H5MD"),
    "chemfiles_py": ("Chemfiles", "chemfiles", "XYZ"),
    "ovito_xyz": ("OvitoXyz", "OVITO", "XYZ"),
}
THREADS = {1: "One", 8: "Eight"}
CPP = {
    "readcon_cpp_moc_1": ("ReadconMocOne", "readcon-core C++", "CON 3.1"),
    "readcon_cpp_moc_8": ("ReadconMocEight", "readcon-core C++", "CON 3.1"),
    "chemfiles_cpp_moc_1": ("ChemfilesMocOne", "chemfiles C++", "extended XYZ"),
    "readcon_cpp_coords_1": (
        "ReadconCoordsOne",
        "readcon-core C++",
        "CON 3.1, no velocities",
    ),
    "chemfiles_cpp_coords_1": ("ChemfilesCoordsOne", "chemfiles C++", "XYZ"),
}
CPP_GROUPS = [
    (
        "Positions, velocities, masks, identifiers, atomic numbers, cell and periodic flags",
        "readcon_cpp_moc_1",
        ["readcon_cpp_moc_1", "readcon_cpp_moc_8", "chemfiles_cpp_moc_1"],
    ),
    (
        "Positions and atomic numbers",
        "readcon_cpp_coords_1",
        ["readcon_cpp_coords_1", "chemfiles_cpp_coords_1"],
    ),
]
GROUPS = [
    (
        "Positions, velocities, masks, identifiers, atomic numbers, cell and periodic flags",
        "readcon",
        ["readcon", "ase_extxyz", "extxyz_c", "ovito", "ase_traj", "h5py"],
    ),
    ("Positions and velocities in binary32", None, ["mda_h5md"]),
    (
        "Positions and atomic numbers",
        "readcon_coords",
        ["readcon_coords", "ase_eon", "chemfiles_py", "ovito_xyz"],
    ),
    ("Frames only, no field copied out", None, ["readcon_fields"]),
]
CACHEGRIND = [
    ("parse_cuh2_218", "parse one 218-atom frame"),
    ("parse_100_frames", "parse 100 frames"),
    ("forward_100_frames", "skip 100 frames"),
    ("parse_multi_2x4", "parse a two-frame file of four atoms"),
    ("forward_multi_2x4", "skip in that file"),
    ("convel_multi", "parse a velocity file"),
    ("write_100_frames", "write 100 frames"),
    ("float_fast_float2", "parse floats, fast-float2"),
    ("float_std_parse", "parse floats, Rust standard library"),
    ("chemfiles_xyz_path", "chemfiles C++, XYZ file"),
    ("chemfiles_xyz_memory", "chemfiles C++, XYZ in memory"),
    ("chemfiles_select_name_O", "chemfiles C++, selection"),
]
# The fields of a host that every campaign of section Performance must share with ``provenance.json``; the memory
# total is not one, since the balloon of a guest changes it between boots.
HOST_KEYS = ("cpu_model", "family", "model", "nproc", "kernel")
# The fields of a protocol that every timing record must share with ``reads.json``; the metric, the order of the
# rounds and the load averages belong to each campaign.
PROTOCOL_KEYS = ("schedule", "seed", "rounds", "warmup_rounds", "quartiles", "process")
# The fields of a build that every record of these tables must share with ``provenance.json``.
BUILD_KEYS = (
    "release",
    "commit",
    "readcon_version",
    "readcon_module_sha256",
    "library_digest",
)


def other_host(host: dict, reference: dict) -> list[str]:
    """The fields of ``HOST_KEYS`` in which ``host`` differs from ``reference``."""
    return [key for key in HOST_KEYS if host.get(key) != reference.get(key)]


def same_protocol(
    name: str, doc: dict, reads: dict, protocol: str = "protocol"
) -> None:
    """Stop unless the record ``doc`` ran the protocol and the hardware line of ``reads.json``."""
    ran, ours = doc[protocol], reads["protocol"]
    for key in PROTOCOL_KEYS:
        if ran.get(key) != ours.get(key):
            raise SystemExit(
                f"{name} ran {key} {ran.get(key)!r}; reads.json ran {ours.get(key)!r}"
            )
    if doc["hardware"] != reads["hardware"]:
        raise SystemExit(
            f"{name} names the hardware line {doc['hardware']}; reads.json {reads['hardware']}"
        )


def sig(x: float, n: int = 3) -> str:
    if x == 0:
        return "0"
    digits = n - 1 - floor(log10(abs(x)))
    return f"{x:.{max(digits, 0)}f}"


def ratio(x: float) -> str:
    """Two significant figures: every timing comes from one host."""
    if x == 0:
        return "0"
    decimals = max(0, 1 - floor(log10(abs(x))))
    if floor(log10(abs(round(x, decimals)))) > floor(log10(abs(x))):
        decimals = max(0, decimals - 1)
    return f"{x:.{decimals}f}"


def grouped(n: int) -> str:
    return f"{n:,}".replace(",", "{,}")


def count(x: float) -> str:
    """An instruction count, or the interquartile range of counts, which can end in a fraction."""
    whole = grouped(int(x))
    return whole if x == int(x) else whole + f"{x % 1:.2f}".rstrip("0")[1:]


def mib(n: float) -> str:
    return str(round(n / MIB))


def cache(name: str, lscpu: str) -> list[tuple[str, str]]:
    """The total size and the instance count of an lscpu cache field such as ``16 MiB (8 instances)``."""
    size, count = re.fullmatch(r"(\d+ [KMG]iB) \((\d+) instances?\)", lscpu).groups()
    return [(name, size), (name + "Instances", count)]


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def check(
    prov: dict,
    reads: dict,
    memray: dict,
    grind: dict,
    cpp_build: dict,
    cpp_checks: list,
) -> None:
    build = prov["build"]
    if build["readcon_version"] != build["release"]:
        raise SystemExit(
            f"module {build['readcon_version']} is not release {build['release']}"
        )
    for name, doc in (("reads.json", reads), ("memray.json", memray)):
        theirs = doc["provenance"]["build"]
        for key in BUILD_KEYS:
            if theirs.get(key) != build.get(key):
                raise SystemExit(
                    f"{name} and provenance.json differ on {key}: {theirs.get(key)} != {build.get(key)}"
                )
        other = other_host(doc["provenance"]["host"], prov["host"])
        if other:
            raise SystemExit(
                f"{name} ran on another host than provenance.json names: {other}"
            )
    if reads["protocol"]["rounds"] < MIN_ROUNDS:
        raise SystemExit(
            f"reads.json ran {reads['protocol']['rounds']} rounds, fewer than {MIN_ROUNDS}"
        )
    if reads["hardware"] != prov["hardware"]:
        raise SystemExit(
            f"reads.json names the hardware line {reads['hardware']}; provenance.json {prov['hardware']}"
        )
    same_protocol("memray.json", memray, reads)
    same_protocol("cachegrind_results.json", grind, reads)
    if (
        not build["commit"].startswith(grind["git_sha"])
        or grind["provenance"]["source_commit"] != build["commit"]
    ):
        raise SystemExit(
            f"the Cachegrind harness ran at commit {grind['git_sha']}; provenance.json names "
            f"{build['commit'][:12]}"
        )
    if grind["provenance"]["newer_sources"]:
        raise SystemExit(
            f"the Cachegrind harness is older than {grind['provenance']['newer_sources'][:5]}"
        )
    if cpp_build["library_digest"] != build["library_digest"]:
        raise SystemExit(
            "cpp/build.json built the C++ programs from other library sources than provenance.json names"
        )
    if reads["cpp_artifacts"] != cpp_build["artifacts"]:
        raise SystemExit(
            "reads.json timed other C++ programs than cpp/build.json hashed"
        )
    bad = [c["cell"] for c in cpp_checks if c["disagreements"]]
    if bad or sorted(c["cell"] for c in cpp_checks) != sorted(CPP):
        raise SystemExit(f"C++ checksum runs disagree or are missing: {bad}")
    python = {
        f"python:{reader}:{threads}"
        for reader in READERS
        for threads in THREADS
        if threads == 1 or reader.startswith("readcon")
    }
    if set(reads["cells"]) != python | {f"cpp:{name}" for name in CPP}:
        raise SystemExit(f"reads.json holds the cells {sorted(reads['cells'])}")
    if {f"{c['reader']}:{c['threads']}" for c in memray["cells"]} != {
        name.removeprefix("python:") for name in python
    }:
        raise SystemExit("memray.json and reads.json cover different Python cells")
    for name, cell in reads["cells"].items():
        if cell["mismatches"]:
            raise SystemExit(
                f"{name} disagrees with payloads.json: {cell['mismatches']}"
            )
    for cell in memray["cells"]:
        if cell["mismatches"]:
            raise SystemExit(
                f"memray cell {cell['reader']} {cell['threads']} disagrees with payloads.json: "
                f"{cell['mismatches']}"
            )
    unknown = sorted(set(grind["scenarios"]) - {name for name, _ in CACHEGRIND})
    if unknown:
        raise SystemExit(f"Cachegrind scenarios without a label: {unknown}")


LEDGER = Path(
    os.environ.get("R0174_LEDGER", ROOT / "data" / "trace" / "r0174_numbers.tsv")
)
# macro-name prefix, record under R0174, field the value is computed from; the first prefix that matches wins
SOURCES = [
    (
        "rcCppUs",
        "reads.json",
        "cells.cpp:<cell>.median_s over trajectory.frames of payloads.json",
    ),
    ("rcCppIqr", "reads.json", "cells.cpp:<cell>.iqr_s"),
    (
        "rcCppRatio",
        "reads.json",
        "cells.cpp:<cell>.median_s, readcon-core cell over chemfiles cell",
    ),
    (
        "rcCppSpeedup",
        "reads.json",
        "cells.cpp:<cell>.median_s, one-thread cell over eight-thread cell",
    ),
    ("rcCpp", "reads.json", "cells.cpp:<cell>.median_s"),
    ("rcVerChemfilesCpp", "cpp/build.json", "chemfiles_version"),
    ("rcCxx", "cpp/build.json", "cxx"),
    (
        "rcPeakAtom",
        "memray.json",
        "cells.median_bytes over atoms_per_frame and frames of payloads.json",
    ),
    ("rcPeak", "memray.json", "cells.median_bytes, in MiB"),
    ("rcGrind", "cachegrind/cachegrind_results.json", "scenarios"),
    ("rcSeed", "reads.json", "protocol.seed"),
    ("rcRounds", "reads.json", "protocol.rounds"),
    ("rcWarmup", "reads.json", "protocol.warmup_rounds"),
    ("rcCells", "reads.json", "cells, count"),
    ("rcTime", "reads.json", "cells.python:<reader>:<threads>.median_s"),
    ("rcIqr", "reads.json", "cells.python:<reader>:<threads>.iqr_s"),
    (
        "rcUs",
        "reads.json",
        "cells.python:<reader>:<threads>.median_s over trajectory.frames of payloads.json",
    ),
    (
        "rcRatio",
        "reads.json",
        "cells.python:<reader>:1.median_s, readcon-core cell over the other reader's cell",
    ),
    (
        "rcSpeedup",
        "reads.json",
        "cells.python:<reader>:<threads>.median_s, one thread over eight",
    ),
    ("rcFrames", "payloads.json", "trajectory.frames"),
    ("rcAtoms", "payloads.json", "trajectory.atoms_per_frame"),
    ("rcHeld", "payloads.json", "trajectory.held_atoms"),
    ("rcTemperature", "payloads.json", "trajectory.temperature_K"),
    ("rcTraj", "payloads.json", "files.traj.con.bytes"),
    ("rcCoordsBytes", "payloads.json", "files.traj_coords.con.bytes"),
    ("rcExtxyzBytes", "payloads.json", "files.traj.extxyz.bytes"),
    ("rcXyzBytes", "payloads.json", "files.traj.xyz.bytes"),
    ("rcConVersion", "payloads.json", "files.traj.con.con_version"),
    ("rcWarmFrames", "payloads.json", "files.warm.con.frames"),
    ("rcRelease", "provenance.json", "build.release"),
    ("rcBaseCommit", "provenance.json", "build.base"),
    ("rcModuleVersion", "provenance.json", "build.readcon_version"),
    ("rcRustc", "provenance.json", "build.rustc"),
    ("rcVer", "provenance.json", "peers"),
    ("rcPython", "provenance.json", "tools.python"),
    ("rcMemray", "provenance.json", "tools.memray"),
    ("rcValgrind", "provenance.json", "tools.valgrind"),
    ("rcArch", "provenance.json", "hardware.uname_m"),
    ("rcCores", "provenance.json", "hardware.nproc"),
    ("rcCpu", "provenance.json", "hardware.cpu_model"),
    ("rc", "provenance.json", "host"),
]


def write_ledger(macros: list[tuple[str, str]]) -> None:
    lines = ["macro\tvalue\trecord\tfield"]
    for name, value in macros:
        record, field = next(
            (rec, fld) for prefix, rec, fld in SOURCES if name.startswith(prefix)
        )
        lines.append(f"\\{name}\t{value}\tbench/results/r0174/{record}\t{field}")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("\n".join(lines) + "\n")


def main() -> None:
    prov = load("provenance.json")
    reads = load("reads.json")
    memray = load("memray.json")
    grind = load("cachegrind/cachegrind_results.json")
    payloads = load("payloads.json")
    cpp_build = load("cpp/build.json")
    check(prov, reads, memray, grind, cpp_build, load("cpp/checks.json"))
    cells = {
        (c["reader"], c["threads"]): c
        for c in reads["cells"].values()
        if c["kind"] == "python"
    }
    cpp = {c["reader"]: c for c in reads["cells"].values() if c["kind"] == "cpp"}
    peaks = {(c["reader"], c["threads"]): c for c in memray["cells"]}
    frames = payloads["trajectory"]["frames"]
    atoms = payloads["trajectory"]["atoms_per_frame"]

    macros: list[tuple[str, str]] = []
    for (reader, threads), cell in sorted(cells.items()):
        stem = READERS[reader][0] + THREADS[threads]
        peak = peaks[(reader, threads)]
        macros += [
            (f"rcTime{stem}", sig(cell["median_s"])),
            (f"rcIqr{stem}", sig(cell["iqr_s"], 2)),
            (f"rcUs{stem}", sig(cell["median_s"] / frames * 1e6)),
            (f"rcPeak{stem}", mib(peak["median_bytes"])),
            (f"rcPeakAtom{stem}", str(round(peak["median_bytes"] / (frames * atoms)))),
        ]
    ratios = {}
    for _, ref, members in GROUPS:
        if ref is None:
            continue
        for reader in members:
            if reader != ref:
                ratios[reader] = (
                    cells[(ref, 1)]["median_s"] / cells[(reader, 1)]["median_s"]
                )
                macros.append((f"rcRatio{READERS[reader][0]}", ratio(ratios[reader])))
    macros.append(
        (
            "rcRatioMda",
            ratio(
                cells[("readcon", 1)]["median_s"] / cells[("mda_h5md", 1)]["median_s"]
            ),
        )
    )
    for stem, reader in (
        ("Rc", "readcon"),
        ("RcCoords", "readcon_coords"),
        ("RcFrames", "readcon_fields"),
    ):
        macros.append(
            (
                f"rcSpeedup{stem}",
                f"{cells[(reader, 1)]['median_s'] / cells[(reader, 8)]['median_s']:.2f}",
            )
        )

    for name, cell in cpp.items():
        stem = CPP[name][0]
        macros += [
            (f"rcCpp{stem}", sig(cell["median_s"])),
            (f"rcCppIqr{stem}", sig(cell["iqr_s"], 2)),
            (f"rcCppUs{stem}", sig(cell["median_s"] / frames * 1e6)),
        ]
    cpp_ratios = {}
    for _, ref, members in CPP_GROUPS:
        for name in members:
            if not name.startswith("readcon"):
                cpp_ratios[name] = cpp[ref]["median_s"] / cpp[name]["median_s"]
                macros.append((f"rcCppRatio{CPP[name][0]}", ratio(cpp_ratios[name])))
    macros += [
        (
            "rcCppSpeedup",
            f"{cpp['readcon_cpp_moc_1']['median_s'] / cpp['readcon_cpp_moc_8']['median_s']:.2f}",
        ),
        ("rcVerChemfilesCpp", cpp_build["chemfiles_version"]),
        ("rcCxx", cpp_build["cxx"].split()[-1]),
    ]

    host, tools, build, peers, hardware = (
        prov["host"],
        prov["tools"],
        prov["build"],
        prov["peers"],
        prov["hardware"],
    )
    protocol = reads["protocol"]
    files = payloads["files"]
    macros += [
        ("rcSeed", str(protocol["seed"])),
        ("rcRounds", str(protocol["rounds"])),
        ("rcWarmup", str(protocol["warmup_rounds"])),
        ("rcCells", str(len(reads["cells"]))),
        ("rcRelease", build["release"]),
        ("rcBaseCommit", build["base"][:8]),
        ("rcModuleVersion", build["readcon_version"]),
        ("rcRustc", build["rustc"].split()[0]),
        ("rcFrames", grouped(frames)),
        ("rcAtoms", str(atoms)),
        ("rcHeld", str(payloads["trajectory"]["held_atoms"])),
        ("rcTrajBytes", grouped(files["traj.con"]["bytes"])),
        ("rcTrajMiB", mib(files["traj.con"]["bytes"])),
        ("rcCoordsBytes", grouped(files["traj_coords.con"]["bytes"])),
        ("rcExtxyzBytes", grouped(files["traj.extxyz"]["bytes"])),
        ("rcXyzBytes", grouped(files["traj.xyz"]["bytes"])),
        ("rcConVersion", files["traj.con"]["con_version"]),
        ("rcWarmFrames", str(files["warm.con"]["frames"])),
        ("rcTemperature", f"{payloads['trajectory']['temperature_K']:g}"),
        ("rcArch", hardware["uname_m"].replace("_", "\\_")),
        ("rcCores", str(hardware["nproc"])),
        ("rcCpu", hardware["cpu_model"]),
        ("rcFamily", host["family"]),
        ("rcModel", host["model"]),
        ("rcStepping", host["stepping"]),
        ("rcMemGiB", str(round(host["mem_kb"] / 1024 / 1024))),
        *cache("rcLtwo", host["l2_cache"]),
        *cache("rcLthree", host["l3_cache"]),
        ("rcHypervisor", host["hypervisor_vendor"]),
        ("rcOs", host["os"]),
        ("rcKernel", host["kernel"]),
        ("rcPython", tools["python"]),
        ("rcMemray", tools["memray"]),
        ("rcValgrind", tools["valgrind"].removeprefix("valgrind-")),
        ("rcVerAse", peers["ase"]),
        ("rcVerChemfiles", peers["chemfiles"]),
        ("rcVerMda", peers["MDAnalysis"]),
        ("rcVerHfivepy", peers["h5py"]),
        ("rcVerOvito", peers["ovito"]),
        ("rcVerNumpy", peers["numpy"]),
        ("rcGrindParseFrame", grouped(grind["scenarios"]["parse_cuh2_218"])),
        ("rcGrindParseHundred", grouped(grind["scenarios"]["parse_100_frames"])),
        ("rcGrindForwardHundred", grouped(grind["scenarios"]["forward_100_frames"])),
        ("rcGrindWriteHundred", grouped(grind["scenarios"]["write_100_frames"])),
        ("rcGrindChemPath", grouped(grind["scenarios"]["chemfiles_xyz_path"])),
    ]
    names = [name for name, _ in macros]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate macro names")
    write_ledger(macros)

    OUT.mkdir(parents=True, exist_ok=True)
    head = (
        "% Written by paper/cpc/scripts/r0174_tables.py from bench/results/r0174 (reads.json, memray.json, "
        "cachegrind/cachegrind_results.json, cpp/build.json, provenance.json, payloads.json).\n"
    )
    (OUT / "r0174_macros.tex").write_text(
        head + "".join(f"\\newcommand{{\\{n}}}{{{v}}}\n" for n, v in macros)
    )

    rows = []
    for title, _, members in GROUPS:
        rows.append(f"\\multicolumn{{7}}{{@{{}}l@{{}}}}{{\\textit{{{title}}}}}\\\\")
        for reader in members:
            for threads in THREADS:
                if (reader, threads) not in cells:
                    continue
                cell, peak = cells[(reader, threads)], peaks[(reader, threads)]
                rel = ratio(ratios[reader]) if reader in ratios else "--"
                _, label, fmt = READERS[reader]
                rows.append(
                    f"{label} & {fmt} & {threads} & {sig(cell['median_s'])} & {sig(cell['iqr_s'], 2)} & "
                    f"{mib(peak['median_bytes'])} & {rel}\\\\"
                )
        rows.append("\\addlinespace")
    rows.pop()
    (OUT / "r0174_table.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                "\\setlength{\\tabcolsep}{3pt}",
                "\\begin{tabular}{@{}p{0.21\\linewidth}p{0.18\\linewidth}rrrrr@{}}",
                "\\toprule",
                "Reader & File & Threads & Median & IQR & Peak heap & readcon/\\\\",
                " & & & (s) & (s) & (MiB) & reader\\\\",
                "\\midrule",
                *rows,
                "\\bottomrule",
                "\\end{tabular}",
                "",
            ]
        )
    )

    crows = []
    for title, _, members in CPP_GROUPS:
        crows.append(f"\\multicolumn{{6}}{{@{{}}l@{{}}}}{{\\textit{{{title}}}}}\\\\")
        for name in members:
            cell = cpp[name]
            _, label, fmt = CPP[name]
            rel = ratio(cpp_ratios[name]) if name in cpp_ratios else "--"
            crows.append(
                f"{label} & {fmt} & {cell['threads']} & {sig(cell['median_s'])} & "
                f"{sig(cell['iqr_s'], 2)} & {rel}\\\\"
            )
        crows.append("\\addlinespace")
    crows.pop()
    (OUT / "r0174_cpp.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                "\\setlength{\\tabcolsep}{3pt}",
                "\\begin{tabular}{@{}p{0.21\\linewidth}p{0.18\\linewidth}rrrr@{}}",
                "\\toprule",
                "Reader & File & Threads & Median & IQR & readcon/\\\\",
                " & & & (s) & (s) & reader\\\\",
                "\\midrule",
                *crows,
                "\\bottomrule",
                "\\end{tabular}",
                "",
            ]
        )
    )

    tex_underscore = "\\_"
    grows = [
        f"{label} & \\texttt{{{name.replace('_', tex_underscore)}}} & {count(grind['scenarios'][name])} & "
        f"{count(grind['cells'][name]['iqr_irefs'])}\\\\"
        for name, label in CACHEGRIND
        if name in grind["scenarios"]
    ]
    (OUT / "r0174_cachegrind.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                "\\begin{tabular}{@{}llrr@{}}",
                "\\toprule",
                "Work & Scenario & Instructions & IQR\\\\",
                "\\midrule",
                *grows,
                "\\bottomrule",
                "\\end{tabular}",
                "",
            ]
        )
    )
    print(
        f"wrote {len(macros)} macros, {len(rows)} table rows, {len(crows)} C++ rows, {len(grows)} Cachegrind rows"
    )


if __name__ == "__main__":
    main()
