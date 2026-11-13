#!/usr/bin/env python3
"""Write the HCN table fragment from ``bench/results/hcn_loss.csv``."""

from __future__ import annotations

import csv
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
OUT = CPC / "src" / "figures" / "generated"
RESULTS = CPC / "bench" / "results"
HEADER = "% Written by paper/cpc/scripts/gen_tables.py.\n"


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


def mask_integer(bits_xyz: str) -> str:
    return str(sum(int(bit) << axis for axis, bit in enumerate(bits_xyz)))


def gen_hcn(rows: list[dict[str, str]]) -> str:
    body = [
        r"\begin{table}[tbp]",
        r"\centering",
        r"\small",
        (
            r"\caption{Per-atom mask, id and velocity returned by readcon-core. "
            r"A mask is the integer \(m\) of Eq.~\eqref{eq:mask}. "
            r"The probe stores ids 2, 0 and 1 and fixes hydrogen on x only.}"
        ),
        r"\label{tab:hcn}",
        r"\begin{tabular}{llll}",
        r"\toprule",
        r"Atom & Mask & Id & Velocity \\",
        r"\midrule",
    ]
    symbols = ("C", "N", "H")
    names = {"0": "HCN", "1": "HNC", "2": "probe"}
    for row in rows:
        if row["reader"] == "readcon-core" and row["frame"] in names:
            masks = [mask_integer(bits) for bits in row["masks_xyz"].split()]
            idents = row["ids"].split()
            vel = "absent" if row["velocities"] in ("", "None None None") else "present"
            for symbol, mask, ident in zip(symbols, masks, idents, strict=True):
                body.append(
                    rf"{names[row['frame']]} {symbol} & "
                    rf"{tex(mask)} & {tex(ident)} & {vel} \\"
                )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def main() -> None:
    require(RESULTS / "hcn_loss.csv")
    write("hcn_table.tex", gen_hcn(read_csv(RESULTS / "hcn_loss.csv")))
    print(f"wrote hcn_table.tex under {OUT}")


if __name__ == "__main__":
    main()
