#!/usr/bin/env python3
"""Rewrite the public HCN/HNC endpoints as CON 3.1 and compare readers."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(__file__).resolve().parents[1] / "data"
RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"
CRATE = Path(__file__).resolve().parents[1] / "bench" / "readcon-bench"
BINARY = CRATE / "target" / "release" / "readcon-bench"

META = (
    '{"con_spec_version":3,"con_spec_minor":1,'
    '"units":{"length":"angstrom","energy":"eV","mass":"amu",'
    '"time":"(amu*angstrom^2/eV)^0.5"},'
    '"sections":["velocities"]}'
)
META_COORDS = (
    '{"con_spec_version":3,"con_spec_minor":1,'
    '"units":{"length":"angstrom","energy":"eV","mass":"amu",'
    '"time":"(amu*angstrom^2/eV)^0.5"},"sections":[]}'
)


def atoms(path: Path) -> list[tuple[str, str, str, str, str, str]]:
    lines = path.read_text().splitlines()
    # header is 9 lines, then symbol / label / one coordinate, repeated.
    out = []
    i = 9
    while i < len(lines):
        symbol = lines[i].strip()
        if not symbol:
            break
        coord = lines[i + 2].split()
        out.append((symbol, coord[0], coord[1], coord[2], coord[3], coord[4]))
        i += 3
    if len(out) != 3:
        raise SystemExit(f"{path} parsed {len(out)} atoms")
    return out


def frame(
    title: str,
    meta: str,
    rows: list[tuple[str, str, str, str, str, str]],
    velocities: bool,
) -> str:
    lines = [
        title,
        meta,
        "25.0 25.0 25.0",
        "90.0 90.0 90.0",
        "postBox_header_1",
        "postBox_header_2",
        "3",
        "1 1 1",
        "12.011 14.007 1.008",
    ]
    for index, (symbol, x, y, z, flag, ident) in enumerate(rows, start=1):
        lines.append(symbol)
        lines.append(f"Coordinates of Component {index}")
        lines.append(f"{x} {y} {z} {flag} {ident}")
    if velocities:
        lines.append("")
        for index, (symbol, _x, _y, _z, flag, ident) in enumerate(rows, start=1):
            vx = "0.01" if symbol == "H" else "0.0"
            lines.append(symbol)
            lines.append(f"Velocities of Component {index}")
            lines.append(f"{vx} 0.0 0.0 {flag} {ident}")
    return "\n".join(lines) + "\n"


def binary() -> Path:
    if not BINARY.is_file():
        subprocess.check_call(
            [
                "cargo",
                "build",
                "--release",
                "--manifest-path",
                str(CRATE / "Cargo.toml"),
            ],
            cwd=ROOT,
        )
    return BINARY


def dump(path: Path) -> list[dict]:
    proc = subprocess.run(
        [str(binary()), "dump", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr)
    return json.loads(proc.stdout)


def ase_read(path: Path) -> tuple[str, str]:
    try:
        import ase.io
    except ImportError as exc:
        return "import", str(exc)
    try:
        images = ase.io.read(path, index=":", format="eon")
    except Exception as exc:  # noqa: BLE001
        return "failure", f"{type(exc).__name__}: {exc}"
    bits = []
    for image in images:
        fixed = []
        for atom in image:
            # ASE FixAtoms, when present, lists indices that are fully fixed.
            fixed.append("free")
        constrained = set()
        for constraint in image.constraints:
            index = getattr(constraint, "index", None)
            if index is not None:
                constrained.update(int(i) for i in index)
        for i in range(len(image)):
            fixed[i] = "all-fixed" if i in constrained else "free"
        has_id = "atom_id" in image.arrays
        # get_velocities() returns zeros when the file stored none.
        has_vel = "momenta" in image.arrays
        bits.append(
            "fixed="
            + ",".join(fixed)
            + f";id={has_id};velocity={bool(has_vel)};symbols={','.join(image.get_chemical_symbols())}"
        )
    return "ok", " || ".join(bits)


def units_row() -> dict[str, str]:
    proc = subprocess.run(
        [str(binary()), "units"], text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr)
    data = json.loads(proc.stdout)
    inputs = {}
    with (DATA / "velocity_inputs.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            inputs[row["quantity"]] = row
    eon = float(inputs["eon_time_unit"]["value"])
    ke = float(inputs["ke_natural"]["value"])
    factor2 = eon * eon
    return {
        "readcon_natural_fs": f"{data['fs']:.12g}",
        "readcon_canonical": data["canonical"],
        "eon_fs": f"{eon}",
        "relative_fs": f"{abs(data['fs'] - eon) / eon:.3g}",
        "ke_natural_eV": f"{ke}",
        "ke_if_read_as_fs_eV": f"{ke * factor2:.6g}",
        "factor2": f"{factor2:.6g}",
        "ke_relative_loss_6dp": inputs["ke_relative_loss_6dp"]["value"],
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    hcn = atoms(DATA / "hcn.con")
    hnc = atoms(DATA / "hnc.con")
    # Probe: same HCN coordinates, column 4 on H is 1 (x only from spec 2),
    # and the ids are 2, 0, 1 in file order.
    probe = []
    id_cycle = {"C": "2", "N": "0", "H": "1"}
    for symbol, x, y, z, _flag, _ident in hcn:
        flag = "1" if symbol == "H" else "0"
        probe.append((symbol, x, y, z, flag, id_cycle[symbol]))
    published = frame(
        "HCN endpoint from eon_orchestrator 669a58ef",
        META,
        hcn,
        True,
    )
    product = frame(
        "HNC endpoint from eon_orchestrator 669a58ef",
        META,
        hnc,
        True,
    )
    probed = frame(
        "HCN coordinates with an x-only mask on H",
        META,
        probe,
        True,
    )
    path = DATA / "hcn_v31.con"
    path.write_text(published + product + probed)
    coords = frame(
        "HCN coordinates with an x-only mask on H",
        META_COORDS,
        probe,
        False,
    )
    coords_path = DATA / "hcn_v31_coords.con"
    coords_path.write_text(coords)
    parsed = dump(path)
    loss_rows = []
    for index, frame_obj in enumerate(parsed):
        masks = [
            "".join("1" if bit else "0" for bit in atom["fixed"])
            for atom in frame_obj["atoms"]
        ]
        ids = [str(atom["id"]) for atom in frame_obj["atoms"]]
        vels = [str(atom["velocity"]) for atom in frame_obj["atoms"]]
        loss_rows.append(
            {
                "file": path.name,
                "frame": index,
                "reader": "readcon-core 0.16.2",
                "status": "ok",
                "masks_xyz": " ".join(masks),
                "ids": " ".join(ids),
                "velocities": " ".join(vels),
                "time_unit": str(frame_obj["units"].get("time")),
                "detail": "",
            }
        )
    for label, file_path in (("velocities", path), ("coords", coords_path)):
        status, detail = ase_read(file_path)
        loss_rows.append(
            {
                "file": file_path.name,
                "frame": label,
                "reader": "ASE format=eon",
                "status": status,
                "masks_xyz": "",
                "ids": "",
                "velocities": "",
                "time_unit": "",
                "detail": detail,
            }
        )
    loss_rows.append(
        {
            "file": path.name,
            "frame": "source",
            "reader": "eOn 3.6.0",
            "status": "not-run",
            "masks_xyz": "",
            "ids": "",
            "velocities": "",
            "time_unit": "10.1805055 fs natural unit",
            "detail": (
                "No eOn binary was executed. "
                "client/ConFileIO.cpp:386 getFixedMask and :714 setFixedMask keep a mask. "
                "v2.17.10 client/ConFileIO.cpp:384-385 collapses any fixed bit to 1. "
                "include/eon/ParametersOptions.h:26 timeUnit is 10.1805055 fs."
            ),
        }
    )
    out = RESULTS / "hcn_loss.csv"
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(loss_rows[0].keys()))
        writer.writeheader()
        writer.writerows(loss_rows)
    units = units_row()
    unit_path = RESULTS / "velocity_case.csv"
    with unit_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(units.keys()))
        writer.writeheader()
        writer.writerow(units)
    print(f"wrote {path} {out} {unit_path}")


if __name__ == "__main__":
    main()
