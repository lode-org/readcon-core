#!/usr/bin/env python3
"""Write CPC table fragments and prose macros from committed CSVs."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
OUT = CPC / "src" / "figures" / "generated"
DATA = CPC / "data"
RESULTS = CPC / "bench" / "results"
HEADER = "% Written by paper/cpc/scripts/gen_tables.py.\n"

PAYLOAD = {
    "frames-1": "1 frame",
    "frames-100": "100 frames",
    "frames-10000": "10000 frames",
    "slab": "Pt slab",
}
PEER = {
    "ase_eon": "ASE eon",
    "chemfiles_xyz": "chemfiles XYZ",
    "mda_h5md": "MDAnalysis H5MD",
    "h5py": "h5py",
}


def _cpu_family_model() -> tuple[str | None, str | None]:
    """Family and model from /proc/cpuinfo, which is what lscpu reports."""
    family = model = None
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
    except OSError:
        return None, None
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key == "cpu family" and family is None:
            family = value.strip()
        elif key == "model" and model is None:
            model = value.strip()
        if family and model:
            break
    return family, model


def tex(text: str) -> str:
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
        .replace("#", r"\#")
        .replace("$", r"\$")
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, body: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(HEADER + body)


def require(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {path}")


def sig(value: float, n: int = 3) -> str:
    return f"{value:.{n}g}"


def gen_ratios(rows: list[dict[str, str]]) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\small",
        (
            r"\caption{Paired time ratios. "
            r"The ratio is the readcon-core time divided by the peer time, "
            r"so a value below 1 means readcon-core finished sooner. "
            r"The interval is a bias-corrected and accelerated 95 percent "
            r"interval of the median. "
            r"Failures stay in the table and are not converted into times.}"
        ),
        r"\label{tab:ratios}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Payload & Peer & OK & Fail & Ratio & Interval \\",
        r"\midrule",
    ]
    for row in rows:
        if row["bca_low"]:
            ratio = sig(float(row["median_ratio_readcon_over_peer"]))
            interval = (
                f"[{sig(float(row['bca_low']))}, {sig(float(row['bca_high']))}]"
            )
        else:
            ratio = ""
            interval = ""
        body.append(
            rf"{tex(PAYLOAD.get(row['payload'], row['payload']))} & "
            rf"{tex(PEER.get(row['peer'], row['peer']))} & {row['n_pair_ok']} & "
            rf"{row['n_failure']} & {tex(ratio)} & {tex(interval)} \\"
        )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def gen_compat(rows: list[dict[str, str]]) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\small",
        (
            r"\caption{What a restarted rare-event calculation needs, "
            r"and what each file actually stores. "
            r"The CON column is what readcon-core keeps.}"
        ),
        r"\label{tab:compat}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{1.45cm}"
        r">{\raggedright\arraybackslash}X>{\raggedright\arraybackslash}X"
        r">{\raggedright\arraybackslash}X>{\raggedright\arraybackslash}X"
        r">{\raggedright\arraybackslash}X@{}}",
        r"\toprule",
        r"Item & CON & ASE eon & ext.\ XYZ & H5MD & LAMMPS dump \\",
        r"\midrule",
    ]
    for row in rows:
        body.append(
            rf"{tex(row['feature'])} & {tex(row['readcon'])} & {tex(row['ase'])} & "
            rf"{tex(row['xyz'])} & {tex(row['h5md'])} & {tex(row['lammps'])} \\"
        )
    body += [r"\bottomrule", r"\end{tabularx}", r"\end{table}", ""]
    return "\n".join(body)


def _ase_bits(detail: str) -> tuple[str, str, str]:
    fixed = ""
    ident = ""
    vel = ""
    for part in detail.split(";"):
        if part.startswith("fixed="):
            fixed = part.split("=", 1)[1].replace(",", " ")
        elif part.startswith("id="):
            ident = "kept" if part.endswith("True") else "absent"
        elif part.startswith("velocity="):
            vel = "present" if part.endswith("True") else "absent"
    return fixed, ident, vel


def gen_hcn(rows: list[dict[str, str]], slab_rows: list[dict[str, str]]) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\small",
        (
            r"\caption{Per-atom mask, id and velocity. "
            r"A mask is three bits in order xyz. "
            r"The probe stores ids 2, 0 and 1 and fixes hydrogen on x only. "
            r"The slab rows are one buried atom, one surface atom and the adsorbate.}"
        ),
        r"\label{tab:hcn}",
        r"\begin{tabular}{lllll}",
        r"\toprule",
        r"Atom & Reader & Mask & Id & Velocity \\",
        r"\midrule",
    ]
    symbols = ("C", "N", "H")
    names = {"0": "HCN", "1": "HNC", "2": "probe"}
    for row in rows:
        if row["reader"] == "readcon-core" and row["frame"] in names:
            masks = row["masks_xyz"].split()
            idents = row["ids"].split()
            vel = "absent" if row["velocities"] in ("", "None None None") else "present"
            for symbol, mask, ident in zip(symbols, masks, idents, strict=True):
                body.append(
                    rf"{names[row['frame']]} {symbol} & readcon-core & "
                    rf"{tex(mask)} & {tex(ident)} & {vel} \\"
                )
        elif row["reader"] == "ASE eon" and row["frame"] == "coords-0" and row["status"] == "ok":
            fixed, ident, vel = _ase_bits(row["detail"])
            flags = fixed.split()
            for symbol, flag in zip(symbols, flags, strict=True):
                body.append(
                    rf"probe {symbol} & ASE eon & {tex(flag)} & {tex(ident)} & {tex(vel)} \\"
                )
    for row in slab_rows:
        body.append(
            rf"slab {tex(row['role'])} & readcon-core & {tex(row['mask_xyz'])} & "
            rf"{tex(row['atom_id'])} & {tex(row['velocity'])} \\"
        )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def _speedups(rows: list[dict[str, str]], peer: str) -> list[float]:
    out = []
    for row in rows:
        if row["peer"] != peer or not row["median_ratio_readcon_over_peer"]:
            continue
        ratio = float(row["median_ratio_readcon_over_peer"])
        if ratio > 0:
            out.append(1.0 / ratio)
    return out


def _cell(rows: list[dict[str, str]], payload: str, peer: str) -> float | None:
    for row in rows:
        if row["payload"] == payload and row["peer"] == peer and row["median_ratio_readcon_over_peer"]:
            return float(row["median_ratio_readcon_over_peer"])
    return None


def gen_macros(
    ratios: list[dict[str, str]],
    threads: list[dict[str, str]],
    velocity: list[dict[str, str]],
    host: dict[str, str],
    corpus: dict[str, str],
    roundtrip: dict[str, str],
    slab: dict[str, str],
) -> str:
    lines = []

    def add(name: str, value: str) -> None:
        lines.append("\\newcommand{\\" + name + "}{" + value + "}")

    for peer, lo_name, hi_name in (
        ("ase_eon", "aseLo", "aseHi"),
        ("chemfiles_xyz", "chemLo", "chemHi"),
        ("mda_h5md", "mdaLo", "mdaHi"),
    ):
        speeds = _speedups(ratios, peer)
        if speeds:
            add(lo_name, sig(min(speeds), 2))
            add(hi_name, sig(max(speeds), 2))
        else:
            add(lo_name, "?")
            add(hi_name, "?")

    def speed_macro(name: str, payload: str, peer: str) -> None:
        ratio = _cell(ratios, payload, peer)
        add(name, sig(1.0 / ratio, 2) if ratio else "?")

    def ratio_macro(name: str, payload: str, peer: str) -> None:
        ratio = _cell(ratios, payload, peer)
        add(name, sig(ratio, 2) if ratio else "?")

    speed_macro("spBandAse", "frames-10000", "ase_eon")
    speed_macro("spBandChem", "frames-10000", "chemfiles_xyz")
    ratio_macro("ratBandChem", "frames-10000", "chemfiles_xyz")
    speed_macro("spBandMda", "frames-10000", "mda_h5md")
    ratio_macro("ratBandHpy", "frames-10000", "h5py")
    speed_macro("spSlabAse", "slab", "ase_eon")
    ratio_macro("ratSlabHpy", "slab", "h5py")
    speed_macro("spOneHpy", "frames-1", "h5py")

    by_thr = {int(row["threads"]): row for row in threads}
    add("thrTwo", sig(float(by_thr[2]["speedup"]), 3) if 2 in by_thr else "?")
    add("thrFour", sig(float(by_thr[4]["speedup"]), 3) if 4 in by_thr else "?")
    add("thrEight", sig(float(by_thr[8]["speedup"]), 3) if 8 in by_thr else "?")
    if threads and threads[0].get("hashes_identical_1_2_3_4_8") == "yes":
        add("hashSentence", "The field hash is the same at 1, 2, 3, 4 and 8 threads.")
    else:
        add("hashSentence", "The field hash is not the same at every thread count.")

    cpu = host.get("cpu_model", "unknown").replace("(R)", "").replace("(TM)", "")
    cpu = " ".join(cpu.split())
    family, model = _cpu_family_model()
    if family and model and "family" not in cpu.lower():
        cpu = f"{cpu}, family {family}, model {model}"
    add("cpuName", cpu.replace("&", r"\&"))
    add("nCores", host.get("nproc", ""))
    add("nValid", corpus["n_valid"])
    add("nInvalid", corpus["n_invalid"])
    add("nBind", corpus["n_bindings"])
    add("nRound", roundtrip["n_atoms"])
    add("nSlab", slab["n_atoms"])
    vel = velocity[0]
    add("keNat", f"{float(vel['ke_natural_eV']):.1f}")
    ke_fs = float(vel["ke_if_read_as_fs_eV"])
    add("keFs", f"{ke_fs:.1f}")
    add("timeFac", f"{float(vel['readcon_natural_fs']):.7f}")
    add("timeFacSq", f"{float(vel['factor2']):.2f}")
    by_thr = {int(row["threads"]): row for row in threads}

    def add_ci(name: str, threads_n: int) -> None:
        row = by_thr.get(threads_n)
        if row and row.get("speedup_low"):
            add(name + "Lo", sig(float(row["speedup_low"]), 3))
            add(name + "Hi", sig(float(row["speedup_high"]), 3))
        else:
            add(name + "Lo", "?")
            add(name + "Hi", "?")

    add_ci("thrTwo", 2)
    add_ci("thrFour", 4)
    add_ci("thrEight", 8)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    for path in (
        RESULTS / "ratios.csv",
        RESULTS / "threads_summary.csv",
        RESULTS / "hcn_loss.csv",
        RESULTS / "velocity_case.csv",
        DATA / "compatibility.csv",
        DATA / "corpus_counts.csv",
        DATA / "roundtrip.csv",
        DATA / "slab_build.csv",
        DATA / "slab_masks.csv",
    ):
        require(path)
    ratios = read_csv(RESULTS / "ratios.csv")
    threads = read_csv(RESULTS / "threads_summary.csv")
    loss = read_csv(RESULTS / "hcn_loss.csv")
    velocity = read_csv(RESULTS / "velocity_case.csv")
    compat = read_csv(DATA / "compatibility.csv")
    host = read_csv(RESULTS / "repeats.csv")[0]
    corpus = read_csv(DATA / "corpus_counts.csv")[0]
    roundtrip = read_csv(DATA / "roundtrip.csv")[0]
    slab = read_csv(DATA / "slab_build.csv")[0]
    write("macros.tex", gen_macros(ratios, threads, velocity, host, corpus, roundtrip, slab))
    write("ratio_table.tex", gen_ratios(ratios))
    write("compat_table.tex", gen_compat(compat))
    write("hcn_table.tex", gen_hcn(loss, read_csv(DATA / "slab_masks.csv")))
    subprocess.check_call([sys.executable, str(CPC / "scripts" / "gen_figures.py")])
    print(f"wrote tables under {OUT}")


if __name__ == "__main__":
    main()
