#!/usr/bin/env python3
"""Write the table and macros of the native binary readers from the records of ``bench/binary_formats.py``.

Inputs (``BF``, default ``bench/results/r0174/binary_formats``): ``build.json``,
``payloads.json``, ``checks.json``, ``timings.json`` and ``settle.json``.  They
must name one library digest, one ``readcon_read`` binary and the host of the
``provenance.json`` beside them, every file must have rerun byte for byte, the
timings must run the protocol and the hardware line of the ``reads.json``
beside them and the settle period, hardware line and SHA-256 of the
``settle.json`` beside them, that period must be the longest settle of the
trials of ``settle.json``, its window and gap the cells the prose names, every
timed run must print the frames, atoms and checksum of the check run of its
cell, and the checks must come out as the prose states them: every cell within
the tolerance of its format but the libxtc cells, libxtc equal to its own
``pep.npy`` and xdrfile equal to MDAnalysis on ``pep.xtc``, and the all-frames
TNG reader killed by a signal on two frame sets that the frame reader reads.

Outputs (``BENCH_GENERATED``, default ``src/figures/generated``):

* ``bf_table.tex``   Table ``tab:binary-formats``, every cell;
* ``bf_ratios.tex``  Table ``tab:binary-ratios``, every one-thread readcon-core
  cell over every one-thread native cell of the same read but libxtc's;
* ``bf_macros.tex``  every number the prose quotes from these records.

A time is the median of the timed runs of a cell, with their interquartile
range.  A rate is frames over the median time.  A ratio is the readcon-core
median over the median of a native reader in the same mode on one thread, to
two significant figures.

    python paper/cpc/scripts/binary_formats_tables.py           # write the three files and the ledger
    python paper/cpc/scripts/binary_formats_tables.py --check   # exit 1 unless they are what the records give
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from pathlib import Path

from r0174_tables import other_host, same_protocol
from sinum import num

ROOT = Path(__file__).resolve().parents[1]
BF = Path(os.environ.get("BF", ROOT / "bench" / "results" / "r0174" / "binary_formats"))
OUT = Path(os.environ.get("BENCH_GENERATED", ROOT / "src" / "figures" / "generated"))
LEDGER = Path(os.environ.get("BF_LEDGER", ROOT / "data" / "trace" / "bf_numbers.tsv"))
RECORDS = ("build.json", "payloads.json", "checks.json", "timings.json", "settle.json")
OUTPUTS = ("bf_macros.tex", "bf_table.tex", "bf_ratios.tex")
# The cells of settle.json's window and gap, which the prose names
SETTLE_CELLS = {"window_cell": "libxtc-frames-8", "gap_cell": "tng-frames"}

# cell: macro stem, reader, file as the table names them
CELLS = {
    "readcon-frames": ("RcFrames", "readcon-core", "CON"),
    "readcon-frames-six": ("RcFramesSix", "readcon-core", "CON, six decimals"),
    "readcon-frames-two": ("RcFramesTwo", "readcon-core", "CON, two decimals"),
    "readcon-all": ("RcAll", "readcon-core", "CON"),
    "readcon-all-six": ("RcAllSix", "readcon-core", "CON, six decimals"),
    "readcon-all-two": ("RcAllTwo", "readcon-core", "CON, two decimals"),
    "readcon-all-8": ("RcAllEight", "readcon-core", "CON"),
    "readcon-all-six-8": ("RcAllSixEight", "readcon-core", "CON, six decimals"),
    "readcon-all-two-8": ("RcAllTwoEight", "readcon-core", "CON, two decimals"),
    "readcon-columns": ("RcColumns", "readcon-core", "CON"),
    "readcon-columns-six": ("RcColumnsSix", "readcon-core", "CON, six decimals"),
    "readcon-columns-two": ("RcColumnsTwo", "readcon-core", "CON, two decimals"),
    "readcon-image": ("RcImage", "readcon-core", r"\texttt{.rcbin}"),
    "xdrfile-xtc-frames": ("XtcFrames", "xdrfile", "XTC"),
    "xdrfile-xtc-all": ("XtcAll", "xdrfile", "XTC"),
    "xdrfile-trr-frames": ("TrrFrames", "xdrfile", "TRR"),
    "xdrfile-trr-all": ("TrrAll", "xdrfile", "TRR"),
    "libxtc-frames": ("LibxtcFrames", "libxtc", "XTC"),
    "libxtc-all": ("LibxtcAll", "libxtc", "XTC"),
    "libxtc-frames-8": ("LibxtcFramesEight", "libxtc", "XTC"),
    "libxtc-all-8": ("LibxtcAllEight", "libxtc", "XTC"),
    "molfile-dcd-frames": ("DcdFrames", "molfile", "DCD"),
    "molfile-dcd-all": ("DcdAll", "molfile", "DCD"),
    "tng-frames": ("TngFrames", "TNG", "TNG"),
    "tng-all": ("TngAll", "TNG", "TNG"),
}
FAILING = {"libxtc-frames", "libxtc-all", "libxtc-frames-8", "libxtc-all-8"}
MODES = {
    "frames": "by frame",
    "all": "all frames",
    "columns": "columns",
    "image": "image",
}
# Every one-thread native cell but libxtc's against every one-thread readcon-core cell of the same mode, the image
# against the reads that hold every frame: the rows and columns of Table tab:binary-ratios.
NATIVE = {
    "xdrfile-xtc": "xdrfile, XTC",
    "xdrfile-trr": "xdrfile, TRR",
    "molfile-dcd": "molfile, DCD",
    "tng": "TNG",
}
OURS = {
    "frames": ("readcon-frames", "readcon-frames-six", "readcon-frames-two", None),
    "all": ("readcon-all", "readcon-all-six", "readcon-all-two", "readcon-image"),
}
RATIOS = [
    (ours, f"{native}-{mode}")
    for native in NATIVE
    for mode, row in OURS.items()
    for ours in row
    if ours
]
FILES = {
    "traj.con": "Con",
    "traj_six.con": "ConSix",
    "traj_two.con": "ConTwo",
    "traj.rcbin": "Rcbin",
    "traj.xtc": "Xtc",
    "traj.trr": "Trr",
    "traj.dcd": "Dcd",
    "traj.tng": "Tng",
}
# The decimals the labels of CELLS name
DECIMALS = {"traj.con": None, "traj_six.con": 6, "traj_two.con": 2}


def seconds(x: float) -> str:
    return f"{x:.3f}"


def rate(x: float) -> str:
    return f"{x:.0f}" if x >= 100 else f"{x:.1f}"


def figures(x: float, digits: int = 2) -> str:
    """``x`` to ``digits`` significant figures, in fixed notation."""
    if x == 0:
        return "0"
    decimals = max(0, digits - 1 - math.floor(math.log10(abs(x))))
    if math.floor(math.log10(abs(round(x, decimals)))) > math.floor(math.log10(abs(x))):
        decimals = max(0, decimals - 1)
    return f"{x:.{decimals}f}"


def error(x: float) -> str:
    """An error in angstrom as math: 0, or two significant figures, in powers of ten below 0.01."""
    if x == 0:
        return "0"
    if x >= 0.01:
        return figures(x)
    mantissa, exponent = f"{x:.1e}".split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def grouped(n: int) -> str:
    return f"{n:,}".replace(",", "{,}")


def over(a: dict, b: dict) -> float:
    return a["median_s"] / b["median_s"]


def records() -> dict:
    return {
        name.removesuffix(".json"): json.loads((BF / name).read_text())
        for name in RECORDS
    }


def check_settle(rec: dict) -> None:
    """timings.json ran the period of the settle.json beside it, and each settle of settle.json is the start of the
    first window in which the pass counts of its trial put every CPU level, as ``bench/settle_period.py`` defines."""
    settle, ran = rec["settle"], rec["timings"]["protocol"]
    protocol, trials = settle["protocol"], settle["trials"]
    sha = hashlib.sha256((BF / "settle.json").read_bytes()).hexdigest()
    if (ran.get("settle_ms"), ran.get("settle_sha256")) != (settle["settle_ms"], sha):
        raise SystemExit(
            f"timings.json ran settle_ms {ran.get('settle_ms')} of the settle.json with SHA-256 "
            f"{ran.get('settle_sha256')}; the one beside it gives {settle['settle_ms']}, SHA-256 {sha}"
        )
    if settle["hardware"] != rec["timings"]["hardware"]:
        raise SystemExit(
            f"settle.json names the hardware line {settle['hardware']}; timings.json "
            f"{rec['timings']['hardware']}"
        )
    one = sorted(
        name for name, cell in rec["timings"]["cells"].items() if cell["threads"] == 1
    )
    cells = {key: protocol[key] for key in SETTLE_CELLS}
    if protocol["band_cells"] != one or cells != SETTLE_CELLS:
        raise SystemExit(
            f"settle.json takes its band from {protocol['band_cells']} and its window and gap from "
            f"{cells}; the prose names the one-thread cells and {SETTLE_CELLS}"
        )
    windows = protocol["windows"]
    if protocol["busy_ms"] != 1e3 * protocol["gap_s"] or windows != int(
        protocol["busy_ms"] // protocol["window_ms"]
    ):
        raise SystemExit(
            f"settle.json: {windows} windows of {protocol['window_ms']} ms in a busy time of "
            f"{protocol['busy_ms']} ms after a gap of {protocol['gap_s']} s"
        )
    if len(trials) != protocol["trials"] or protocol["trials"] != ran["rounds"]:
        raise SystemExit(
            f"settle.json holds {len(trials)} trials of {protocol['trials']}; timings.json ran "
            f"{ran['rounds']} rounds"
        )
    for n, trial in enumerate(trials, 1):
        counts = trial["counts"]
        per_pass = [
            {cpu: 1 / c[k] if c[k] else math.inf for cpu, c in counts.items()}
            for k in range(windows)
        ]
        ratio = {
            cpu: [p[cpu] / statistics.median(p.values()) for p in per_pass]
            for cpu in counts
        }
        steady = {cpu: statistics.median(r[windows // 2 :]) for cpu, r in ratio.items()}
        level = next(
            (
                k
                for k in range(windows)
                if all(
                    ratio[cpu][k] <= steady[cpu] * (1 + protocol["band"])
                    for cpu in counts
                )
            ),
            None,
        )
        if (
            steady != trial["steady"]
            or level is None
            or level >= windows // 2
            or level != trial["level_window"]
            or trial["settle_ms"] != level * protocol["window_ms"]
        ):
            raise SystemExit(
                f"settle.json: trial {n} settles at {trial['settle_ms']} ms in window "
                f"{trial['level_window']}; its counts put every CPU level from window {level}"
            )
    times = [trial["settle_ms"] for trial in trials]
    if settle["settle_ms"] != max(times) or settle["settle_trial"] != 1 + times.index(
        max(times)
    ):
        raise SystemExit(
            f"settle.json: {settle['settle_ms']} ms in trial {settle['settle_trial']} is not the longest "
            f"settle of the trials, {times}"
        )


def check(rec: dict) -> None:
    libraries = {
        json.dumps(
            {
                k: rec[r]["provenance"]["build"][k]
                for k in ("library_digest", "binary_sha256")
            }
        )
        for r in ("build", "payloads", "checks", "timings", "settle")
    }
    if len(libraries) != 1:
        raise SystemExit(
            f"the binary-format records name {len(libraries)} readcon_read builds: {sorted(libraries)}"
        )
    if (
        rec["build"]["binaries"]["readcon_read"]["sha256"]
        != rec["timings"]["provenance"]["build"]["binary_sha256"]
    ):
        raise SystemExit(
            "timings.json timed another readcon_read than build.json built"
        )
    if not rec["build"]["readcon_read"]["locked_as_library"]:
        raise SystemExit(
            "build.json: readcon_read locks other versions than the library"
        )
    performance = json.loads((BF.parent / "provenance.json").read_text())["host"]
    for name in RECORDS:
        other = other_host(
            rec[name.removesuffix(".json")]["provenance"]["host"], performance
        )
        if other:
            raise SystemExit(
                f"{name} ran on another host than {BF.parent / 'provenance.json'} names: {other}"
            )
    same_protocol(
        "timings.json",
        rec["timings"],
        json.loads((BF.parent / "reads.json").read_text()),
    )
    if not all(rec["payloads"]["rerun_identical"].values()):
        raise SystemExit(
            f"payloads.json: files that did not rerun byte for byte: {rec['payloads']['rerun_identical']}"
        )
    if rec["payloads"]["writers"]["con_decimals"] != DECIMALS:
        raise SystemExit(
            f"payloads.json: the CON files carry {rec['payloads']['writers']['con_decimals']} decimals, "
            f"the table labels {DECIMALS}"
        )
    system = rec["payloads"]["system"]
    checks, timings = rec["checks"]["cells"], rec["timings"]["cells"]
    if set(checks) != set(CELLS) or set(timings) != set(CELLS):
        raise SystemExit(f"the records hold other cells than {sorted(CELLS)}")
    check_settle(rec)
    for name in CELLS:
        printed = checks[name]["printed"]
        if printed["frames"] != system["frames"] or printed["atoms"] != system["atoms"]:
            raise SystemExit(f"{name}: the check run printed {printed}")
        if timings[name]["printed"] != printed:
            raise SystemExit(
                f"{name}: the timed runs printed {timings[name]['printed']}, the check run {printed}"
            )
        if checks[name]["passes"] == (name in FAILING):
            raise SystemExit(
                f"{name}: the check {'passes' if checks[name]['passes'] else 'fails'}, which the "
                "prose does not state"
            )
    pep = rec["checks"]["libxtc_pep"]
    if (
        pep["read_libxtc"]["max_nm_from_pep_npy"] != 0
        or pep["read_xdrfile"]["max_nm_from_mdanalysis"] != 0
    ):
        raise SystemExit(f"checks.json: libxtc_pep is not what the prose states: {pep}")
    if not pep["read_libxtc"]["atoms_off_mdanalysis"]:
        raise SystemExit("checks.json: libxtc reads pep.xtc as MDAnalysis does")
    sets = rec["checks"]["tng_two_sets"]
    frames_ok = (
        sets["frames"]["returncode"] == 0
        and sets["frames"]["max_position_error_A"]
        <= checks["tng-frames"]["position_tolerance_A"]
    )
    if not frames_ok or sets["all"]["returncode"] >= 0:
        raise SystemExit(
            f"checks.json: tng_two_sets is not what the prose states: {sets}"
        )


def macros_and_rows(rec: dict) -> tuple[list[tuple[str, str]], list[str]]:
    system, files = rec["payloads"]["system"], rec["payloads"]["files"]
    checks, timings = rec["checks"]["cells"], rec["timings"]["cells"]
    build = rec["build"]
    frames = system["frames"]
    gcc = build["compilers"]["gcc"].split()[-1]
    macros = [
        ("bfAtoms", grouped(system["atoms"])),
        ("bfFrames", str(frames)),
        ("bfSide", str(system["side"])),
        ("bfSpacing", f"{system['spacing_A']:g}"),
        ("bfJitter", f"{system['jitter_A']:g}"),
        ("bfGcc", gcc),
        ("bfRustc", build["compilers"]["rustc"].split()[1]),
        ("bfXdrfile", build["sources"]["xdrfile"]["release"]),
        ("bfTngVersion", build["tng_version_h"]["TNG_IO_VERSION"]),
        ("bfTngCommit", build["sources"]["tng"]["commit"][:7]),
        ("bfLibxtcCommit", build["sources"]["libxtc"]["commit"][:7]),
        ("bfMolfileCommit", build["sources"]["molfile"]["commit"][:7]),
        ("bfMdaVersion", rec["checks"]["libxtc_pep"]["mdanalysis"]),
        ("bfXtcPrecision", f"{rec['payloads']['writers']['xtc_precision_nm']:g}"),
        ("bfTngPrecision", f"{rec['payloads']['writers']['tng_precision_nm']:g}"),
        ("bfConTwoStep", f"{10.0 ** -DECIMALS['traj_two.con']:g}"),
    ]
    for file, stem in FILES.items():
        macros.append((f"bfMb{stem}", figures(files[file]["bytes"] / 1e6, 3)))
    for stem, cells in (("Libxtc", [c for c in CELLS if c in FAILING]),):
        worst = max(checks[c]["max_position_error_A"] for c in cells)
        off = {checks[c]["atom_positions_beyond_tolerance"] for c in cells}
        if len(off) != 1:
            raise SystemExit(
                f"the libxtc cells disagree on the positions they get wrong: {sorted(off)}"
            )
        count = off.pop()
        macros += [
            (f"bf{stem}MaxError", figures(worst, 3)),
            (f"bf{stem}Off", grouped(count)),
            (f"bf{stem}OffPercent", f"{100 * count / (frames * system['atoms']):.0f}"),
        ]
    pep = rec["checks"]["libxtc_pep"]
    macros += [
        ("bfPepFrames", str(pep["frames"])),
        ("bfPepAtoms", str(pep["atoms"])),
        ("bfPepOff", str(pep["read_libxtc"]["atoms_off_mdanalysis"])),
        ("bfPepPositions", str(pep["frames"] * pep["atoms"])),
        ("bfPepFirstAtom", str(pep["read_libxtc"]["first_off"][1])),
        ("bfTngSetFrames", str(rec["checks"]["tng_two_sets"]["frames_per_set"])),
    ]
    for file, stem in FILES.items():
        errs = [
            checks[c]["max_position_error_A"]
            for c in CELLS
            if checks[c]["file"] == file and c not in FAILING
        ]
        if errs:
            macros.append((f"bfErr{stem}", error(max(errs))))
    rows = []
    previous = None
    for name, (stem, reader, label) in CELLS.items():
        t = timings[name]
        macros += [
            (f"bfT{stem}", seconds(t["median_s"])),
            (f"bfTIqr{stem}", seconds(t["iqr_s"])),
            (f"bfRate{stem}", rate(frames / t["median_s"])),
        ]
        if previous is not None and reader != previous:
            rows.append(r"\addlinespace")
        previous = reader
        mark = r"\textsuperscript{a}" if name in FAILING else ""
        rows.append(
            f"{reader}{mark} & {label} & {MODES[t['mode']]} & {t['threads']} & {seconds(t['median_s'])} & "
            f"{seconds(t['iqr_s'])} & {rate(frames / t['median_s'])} & "
            f"{num(error(checks[name]['max_position_error_A']))}\\\\"
        )
    shown = {}
    for ours, peer in RATIOS:
        if (
            peer in FAILING
            or timings[ours]["threads"] != 1
            or timings[peer]["threads"] != 1
        ):
            raise SystemExit(
                f"{ours} over {peer} is not a ratio of two one-thread cells that pass their checks"
            )
        r = over(timings[ours], timings[peer])
        macros.append((f"bfRatio{CELLS[ours][0]}{CELLS[peer][0]}", figures(r)))
        shown[(ours, peer)] = figures(r)
    ratio_rows = []
    for native, label in NATIVE.items():
        for mode, row in OURS.items():
            cells = [
                shown[(ours, f"{native}-{mode}")] if ours else "--" for ours in row
            ]
            ratio_rows.append(
                f"{label if mode == 'frames' else ''} & {MODES[mode]} & {' & '.join(cells)}\\\\"
            )
        ratio_rows.append(r"\addlinespace")
    ratio_rows.pop()
    settle, protocol = rec["settle"], rec["settle"]["protocol"]
    macros += [
        ("bfSettleMs", figures(settle["settle_ms"], 3)),
        ("bfSettleTrial", str(settle["settle_trial"])),
        ("bfSettleTrials", str(protocol["trials"])),
        ("bfSettleWindows", str(protocol["windows"])),
        ("bfSettleCells", str(len(protocol["band_cells"]))),
        ("bfSettleBand", figures(100 * protocol["band"], 3)),
        ("bfSettleWindow", figures(protocol["window_ms"], 3)),
        ("bfSettleGap", seconds(protocol["gap_s"])),
    ]
    names = [n for n, _ in macros]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate macro names")
    return macros, rows, ratio_rows


def write(out: Path, ledger: Path) -> tuple[int, int]:
    rec = records()
    check(rec)
    macros, rows, ratio_rows = macros_and_rows(rec)
    head = (
        "% Written by paper/cpc/scripts/binary_formats_tables.py from bench/results/r0174/binary_formats "
        f"({', '.join(RECORDS)}).\n"
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "bf_ratios.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                r"\begin{tabular}{@{}llcccc@{}}",
                r"\toprule",
                r"Native reader & Read & CON & CON, six decimals & CON, two decimals & \texttt{.rcbin}\\",
                r"\midrule",
                *ratio_rows,
                r"\bottomrule",
                r"\end{tabular}",
                "",
            ]
        )
    )
    (out / "bf_macros.tex").write_text(
        head + "".join(f"\\newcommand{{\\{n}}}{{{v}}}\n" for n, v in macros)
    )
    (out / "bf_table.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                r"\begin{tabular}{@{}lllrrrrr@{}}",
                r"\toprule",
                r"Reader & File & Read & Threads & Median (s) & IQR (s) & Frames/s & Error (\AA)\\",
                r"\midrule",
                *rows,
                r"\bottomrule",
                r"\end{tabular}",
                "",
            ]
        )
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("macro\tvalue\n" + "".join(f"\\{n}\t{v}\n" for n, v in macros))
    return len(macros), len(rows) + len(ratio_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 unless the table, macros and ledger are what the records give",
    )
    args = parser.parse_args()
    if not args.check:
        print("wrote {} macros and {} table rows".format(*write(OUT, LEDGER)))
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        counts = write(Path(tmp), Path(tmp) / LEDGER.name)
        pairs = [(Path(tmp) / n, OUT / n) for n in OUTPUTS] + [
            (Path(tmp) / LEDGER.name, LEDGER)
        ]
        stale = [
            kept
            for now, kept in pairs
            if not kept.is_file() or kept.read_bytes() != now.read_bytes()
        ]
    if stale:
        print(
            "binary-format files differ from the records; run scripts/binary_formats_tables.py: "
            + ", ".join(p.name for p in stale)
        )
        return 1
    print("{} binary-format macros and {} table rows are current".format(*counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
