"""Rules for the numbers printed in the captions of the generated tables."""

from __future__ import annotations

from numbers_lib import Rule, h5md_version, jget, row

MAIN = "figures/generated/restart_main.tex"
SIZES = "figures/generated/sizes_table.tex"
PAYLOADS_PY = "bench/make_payloads.py"
RF = "data/failure/restart_formats.csv"
BANDS = "data/failure/restart_bands.json"
WALLS = "data/restart_walls/restart_walls.json"


def route(name: str, column: str) -> float:
    return float(row(RF, route=name)[column])


SCALED = "POSCAR (ASE), FixScaled z"

RULES: list[Rule] = [
    Rule(
        "8.771",
        max(jget(BANDS, "energies_eV.uninterrupted")),
        BANDS,
        "highest image energy of the uninterrupted band",
        (MAIN,),
    ),
    Rule(
        "29",
        route(SCALED, "file_dpos_ulp"),
        RF,
        f"file_dpos_ulp of route '{SCALED}'",
        (MAIN,),
    ),
    Rule(
        "0.009423",
        abs(route(SCALED, "file_dpos_coord_A")),
        RF,
        f"|file_dpos_coord_A| of route '{SCALED}'",
        (MAIN,),
    ),
    Rule(
        "21",
        route(SCALED, "d_barrier_ulp"),
        RF,
        f"d_barrier_ulp of route '{SCALED}'",
        (MAIN,),
    ),
    Rule(
        "9.855",
        route(SCALED, "max_disp_coord_A"),
        RF,
        f"max_disp_coord_A of route '{SCALED}'",
        (MAIN,),
    ),
    Rule(
        "11",
        jget(WALLS, "wall_repeats"),
        WALLS,
        "wall_repeats, the wall-clock repeats of each route",
        (MAIN,),
    ),
    Rule(
        "1.1",
        h5md_version(PAYLOADS_PY),
        PAYLOADS_PY,
        "h5md version attribute written by write_h5md",
        (SIZES,),
    ),
]
