#!/usr/bin/env python3
"""Rewrite the public HCN/HNC endpoints as CON 3.1 and read back the mask, ids and velocities."""

from __future__ import annotations

import csv
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402

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


@functools.cache
def binary() -> Path:
    """Build readcon-bench on READCON_SRC; cargo rebuilds it when a source is newer than the last build."""
    src = Path(os.environ.get("READCON_SRC", str(ROOT))).resolve()
    manifest = CRATE / "Cargo.toml"
    original = manifest.read_text()
    lock_path = CRATE / "Cargo.lock"
    lock_original = lock_path.read_text() if lock_path.is_file() else None
    patched = re.sub(
        r'readcon-core = \{ path = "[^"]+"',
        f'readcon-core = {{ path = "{src}"',
        original,
        count=1,
    )
    manifest.write_text(patched)
    try:
        subprocess.check_call(
            [
                "cargo",
                "build",
                "--release",
                "--manifest-path",
                str(manifest),
                "--target-dir",
                str(CRATE / "target"),
            ],
            cwd=ROOT,
        )
    finally:
        manifest.write_text(original)
        if lock_original is not None:
            lock_path.write_text(lock_original)
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
        "HCN endpoint",
        META,
        hcn,
        True,
    )
    product = frame(
        "HNC endpoint",
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
                "reader": "readcon-core",
                "status": "ok",
                "masks_xyz": " ".join(masks),
                "ids": " ".join(ids),
                "velocities": " ".join(vels),
                "time_unit": str(frame_obj["units"].get("time")),
                "detail": "",
            }
        )
    out = RESULTS / "hcn_loss.csv"
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(loss_rows[0].keys()))
        writer.writeheader()
        writer.writerows(loss_rows)
    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "rows": len(loss_rows),
                "binary": str(BINARY.relative_to(ROOT)),
                "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
                "provenance": provenance.record(),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {path} {out}")


if __name__ == "__main__":
    main()
