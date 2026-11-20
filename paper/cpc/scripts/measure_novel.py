#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Measure the supplementary novel records from this tip's evidence files.

Restart movies, the velocity fixture, the conformance corpus and a
readcon-db hash of the bands that this tip actually wrote are the inputs.
Scratch files stay on the bench disk. Records go to ``--out``.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import tomllib

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
sys.path.insert(0, str(REPO / "bench" / "h2h"))

from bench_disk import bench_scratch  # noqa: E402

E1 = CPC / "evidence" / "work" / "e1"
E5_HELD = CPC / "evidence" / "work" / "e5" / "bands" / "held" / "neb.con"
E5_FROZEN = CPC / "evidence" / "work" / "e5" / "bands" / "frozen" / "neb.con"
CORPUS = REPO / "resources" / "conformance"
DEFAULT_OUT = CPC / "campaign" / "acbb1d100bc1" / "data" / "novel"
ANATOMY_COPIES = 400
ANATOMY_REPEATS = 31


def _write(out: Path, name: str, payload: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(payload, indent=2) + "\n")
    print(name, "ok")


def _positions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import readcon

    frames = readcon.read_con(str(path))
    coords = np.stack(
        [np.asarray(frame.coords_array(), dtype=float) for frame in frames]
    )
    lengths = np.asarray(frames[0].cell[:3], dtype=float)
    return coords, lengths


def _mic_max(a: np.ndarray, b: np.ndarray, lengths: np.ndarray) -> float:
    """Maximum absolute minimum-image component. z is not periodic."""
    delta = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    wrapped = delta.copy()
    for axis in (0, 1):
        length = float(lengths[axis])
        wrapped[..., axis] = delta[..., axis] - length * np.round(
            delta[..., axis] / length
        )
    return float(np.max(np.abs(wrapped)))


def _column(
    full_frames: np.ndarray, other: np.ndarray, lengths: np.ndarray
) -> list[float]:
    n = min(len(full_frames), len(other))
    return [_mic_max(other[i], full_frames[i], lengths) for i in range(n)]


def _movie_matrix(full_dir: Path, other_dir: Path) -> dict:
    """Per-image minimum-image gap between an uninterrupted band and a resume.

    When eOn left ``neb_path_*.con`` movies, resume index k is the
    uninterrupted movie ``neb_path_{3+k}``. This tip's client keeps the
    final ``neb.con`` and the ``image_*.con`` files instead, and those are
    the columns.
    """
    full_band, lengths = _positions(full_dir / "neb.con")
    columns: list[str] = []
    matrix: list[list[float]] = []
    movies = sorted(other_dir.glob("neb_path_*.con"))
    if movies:
        full_movies = {
            int(path.stem.rsplit("_", 1)[1]): path
            for path in full_dir.glob("neb_path_*.con")
        }
        other = {int(path.stem.rsplit("_", 1)[1]): path for path in movies}
        first = min(other)
        resume0, _ = _positions(other[first])
        offset = min(
            full_movies,
            key=lambda index: max(
                _column(_positions(full_movies[index])[0], resume0, lengths)
            ),
        )
        for resume_index in sorted(other):
            full_index = offset + (resume_index - first)
            if full_index not in full_movies:
                continue
            got, _ = _positions(other[resume_index])
            ref, _ = _positions(full_movies[full_index])
            matrix.append(_column(ref, got, lengths))
            columns.append(str(full_index))
        alignment = (
            "resume movie k against uninterrupted "
            f"neb_path_{{offset+k}}, offset {offset}"
        )
    else:
        alignment = "checkpoint image and the final band against uninterrupted neb.con"
        checkpoint = []
        for path in sorted(other_dir.glob("image_*.con")):
            index = int(path.stem.rsplit("_", 1)[1])
            got, _ = _positions(path)
            checkpoint.append(_mic_max(got[0], full_band[index], lengths))
        if checkpoint:
            matrix.append(checkpoint)
            columns.append("checkpoint")
    if (other_dir / "neb.con").is_file():
        got, _ = _positions(other_dir / "neb.con")
        matrix.append(_column(full_band, got, lengths))
        columns.append("final")
    n_images = min(len(column) for column in matrix)
    rows = [[column[image] for column in matrix] for image in range(n_images)]
    return {
        "columns": columns,
        "images": list(range(n_images)),
        "mic_max_abs_A": rows,
        "alignment": alignment,
    }


def restart_diff(out: Path) -> None:
    full = E1 / "neb" / "full"
    routes = {
        "round_trip": E1 / "neb" / "resume_round",
        "six_decimal": E1 / "neb" / "resume_fixed6",
    }
    if not (E1 / "neb" / "resume_round").is_dir():
        routes["round_trip"] = E1 / "neb" / "resume_roundtrip"
    payload = {}
    for name, path in routes.items():
        if not (path / "neb.con").is_file():
            raise SystemExit(f"missing resume band {path}")
        payload[name] = _movie_matrix(full, path)
    _write(out, "restart_diff.json", payload)


def _field_snapshot(frame) -> dict:
    return {
        "positions": np.asarray(frame.coords_array(), dtype=float),
        "ids": np.asarray(frame.atom_ids_array(), dtype=int),
        "masks": np.array([list(atom.fixed) for atom in frame.atoms], dtype=bool),
        "time_unit": (frame.metadata.get("units") or {}).get("time"),
        "has_velocity": bool(frame.has_velocities),
        "has_id": True,
    }


def _grade(reference: dict, got: dict | None, note: str) -> dict:
    if got is None:
        return {
            "mask": "lost",
            "id": "lost",
            "time_unit": "lost",
            "binary64": "lost",
            "max_abs_A": None,
            "note": note,
        }
    pos = got["positions"]
    ref = reference["positions"]
    n = min(len(pos), len(ref))
    max_abs = float(np.max(np.abs(pos[:n] - ref[:n]))) if n else None
    if max_abs == 0.0:
        binary = "exact"
    elif max_abs is not None and max_abs < 5e-6:
        binary = "approx"
    else:
        binary = "lost"
    mask = "exact" if np.array_equal(got["masks"], reference["masks"]) else "lost"
    if got.get("has_id") is False:
        ids = "lost"
    else:
        ids = "exact" if np.array_equal(got["ids"], reference["ids"]) else "lost"
    if reference["time_unit"] is None:
        unit = "absent"
    elif got["time_unit"] == reference["time_unit"]:
        unit = "exact"
    else:
        unit = "lost"
    return {
        "mask": mask,
        "id": ids,
        "time_unit": unit,
        "binary64": binary,
        "max_abs_A": max_abs,
        "note": note,
    }


def _from_readcon(path: Path) -> dict:
    import readcon

    return _field_snapshot(readcon.read_con(str(path))[0])


def _ase_snapshot(atoms) -> dict:
    masks = np.zeros((len(atoms), 3), dtype=bool)
    from ase.constraints import FixAtoms, FixCartesian

    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            for index in constraint.index:
                masks[int(index)] = True
        elif isinstance(constraint, FixCartesian):
            frozen = np.asarray(constraint.mask, dtype=bool)
            for index in np.atleast_1d(np.asarray(constraint.index)):
                masks[int(index)] = frozen
    has_id = False
    ids = np.zeros(len(atoms), dtype=int)
    for key in ("atom_id", "atom_ids"):
        if key in atoms.arrays:
            ids = np.asarray(atoms.arrays[key], dtype=int)
            has_id = True
            break
    info = atoms.info or {}
    unit = None
    units = info.get("units")
    if isinstance(units, dict):
        unit = units.get("time")
    unit = unit or info.get("time_unit")
    return {
        "positions": np.asarray(atoms.positions, dtype=float),
        "ids": ids,
        "has_id": has_id,
        "masks": masks,
        "time_unit": unit,
        "has_velocity": atoms.has("momenta") or "velocities" in atoms.arrays,
    }


def _time_unit_roundtrip() -> dict:
    import readcon

    source = E1 / "velocity" / "natural.con"
    reference = _from_readcon(source)
    with bench_scratch("novel-time") as tmp:
        native = Path(tmp) / "round.con"
        readcon.write_con(str(native), readcon.read_con(str(source)))
        got = _from_readcon(native)
    return {
        "source": "e1 velocity fixture, unmodified",
        "time_unit": reference["time_unit"],
        "round_trip": got["time_unit"] == reference["time_unit"]
        and got["time_unit"] is not None,
    }


def _mask_note(reference: dict) -> str:
    masks = reference["masks"]
    z_only = [
        index
        for index, row in enumerate(masks)
        if bool(row[2]) and not bool(row[0]) and not bool(row[1])
    ]
    if z_only:
        return f"z-only atoms {z_only[0]}"
    return "no z-only atom"


def fidelity(out: Path) -> None:
    import readcon
    from ase.io import read as ase_read
    from ase.io import write as ase_write

    source = E5_HELD
    if not source.is_file():
        raise SystemExit("missing height-held band")
    frame = readcon.read_con(str(source))[0]
    reference = _field_snapshot(frame)
    with bench_scratch("novel-fidelity") as tmp:
        work = Path(tmp)
        rows = []
        native = work / "round.con"
        readcon.write_con(str(native), [frame])
        rows.append(
            {
                "format": "CON 3.1",
                **_grade(reference, _from_readcon(native), "readcon write"),
            }
        )
        six = work / "six.con"
        readcon.write_con(str(six), [frame], precision=6)
        rows.append(
            {
                "format": "CON six decimals",
                **_grade(reference, _from_readcon(six), "precision 6"),
            }
        )
        velocity = E1 / "velocity" / "natural.con"
        velocity_frame = readcon.read_con(str(velocity))[0]
        velocity_ref = _field_snapshot(velocity_frame)
        velocity_path = work / "velocity-round.con"
        readcon.write_con(str(velocity_path), [velocity_frame])
        rows.append(
            {
                "format": "CON 3.1, velocity file",
                **_grade(
                    velocity_ref,
                    _from_readcon(velocity_path),
                    "unmodified velocity fixture",
                ),
            }
        )
        atoms = frame.to_ase()
        trials = ("extxyz", "traj", "json", "vasp", "xyz", "cif")
        for fmt in trials:
            suffix = "poscar" if fmt == "vasp" else fmt
            path = work / f"round.{suffix}"
            try:
                ase_write(str(path), atoms, format=fmt)
                back = ase_read(str(path), format=fmt)
                rows.append(
                    {
                        "format": fmt,
                        **_grade(reference, _ase_snapshot(back), "ASE write then read"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "format": fmt,
                        "mask": "lost",
                        "id": "lost",
                        "time_unit": "absent",
                        "binary64": "lost",
                        "max_abs_A": None,
                        "note": f"{type(exc).__name__}: {exc}".split("\n", 1)[0][:180],
                    }
                )
    _write(
        out,
        "fidelity.json",
        {
            "source": source.relative_to(CPC).as_posix(),
            "adatom_mask": _mask_note(reference),
            "file_edited": False,
            "ase_note": "ASE 3.29 write then read of the first uninterrupted image",
            "time_unit_fixture": _time_unit_roundtrip(),
            "rows": rows,
        },
    )


def _numeric_row(line: str) -> tuple[str, str, str] | None:
    body = line.rstrip("\r\n")
    newline = line[len(body) :]
    if not body or body.lstrip()[:1] not in "0123456789-":
        return None
    tokens: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == " ":
            index += 1
            continue
        end = index
        while end < len(body) and body[end] != " ":
            end += 1
        trail = end
        while trail < len(body) and body[trail] == " ":
            trail += 1
        tokens.append(body[index:trail])
        index = trail
    if len(tokens) != 5:
        return None
    numbers = "".join(tokens[:3]) + newline
    return numbers, tokens[3], tokens[4]


def _split_frame_bytes(text: str) -> dict:
    lines = text.splitlines(keepends=True)
    buckets = {
        "preamble": 0,
        "coordinates": 0,
        "mask": 0,
        "id": 0,
        "velocity header": 0,
        "velocity numbers": 0,
        "time unit": 0,
    }
    vel_header = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("Velocities of Component")
        ),
        None,
    )
    if vel_header is None:
        raise SystemExit("velocity header is missing from the anatomy frame")
    time_key = "(amu*angstrom^2/eV)^0.5"
    header_rows = {vel_header, vel_header - 1}
    if vel_header >= 2 and lines[vel_header - 2].strip() == "":
        header_rows.add(vel_header - 2)
    for index, line in enumerate(lines):
        if index in header_rows:
            buckets["velocity header"] += len(line.encode())
            continue
        if time_key in line:
            before, _, after = line.partition(time_key)
            buckets["preamble"] += len(before.encode()) + len(after.encode())
            buckets["time unit"] += len(time_key.encode())
            continue
        number_key = "velocity numbers" if index > vel_header else "coordinates"
        split = _numeric_row(line)
        in_coordinates = any(
            earlier.startswith("Coordinates of Component") for earlier in lines[:index]
        )
        if split is not None and number_key == "coordinates" and not in_coordinates:
            split = None
        if split is not None:
            numbers, mask, ident = split
            buckets[number_key] += len(numbers.encode())
            buckets["mask"] += len(mask.encode())
            buckets["id"] += len(ident.encode())
            continue
        if index > vel_header:
            buckets["velocity header"] += len(line.encode())
        else:
            buckets["preamble"] += len(line.encode())
    buckets["total"] = sum(buckets.values())
    encoded = len(text.encode())
    if buckets["total"] != encoded:
        raise SystemExit(
            f"byte buckets sum to {buckets['total']}, file is {encoded}: {buckets}"
        )
    return buckets


def _paired_reads(full: Path, bare: Path, repeats: int) -> tuple[float, float, float]:
    import readcon

    full_samples = []
    bare_samples = []
    differences = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        readcon.read_con(str(full))
        full_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        readcon.read_con(str(bare))
        bare_s = time.perf_counter() - t0
        full_samples.append(full_s)
        bare_samples.append(bare_s)
        differences.append(full_s - bare_s)
    full_samples.sort()
    bare_samples.sort()
    differences.sort()
    mid = len(differences) // 2
    return float(full_samples[mid]), float(bare_samples[mid]), float(differences[mid])


def anatomy(out: Path) -> None:
    import readcon

    source_path = E1 / "velocity" / "natural.con"
    source = source_path.read_text()
    widths = _split_frame_bytes(source)
    readcon.read_con(str(source_path))
    marker = "\n\nPt\nVelocities of Component"
    if marker not in source:
        raise SystemExit("anatomy split marker is missing")
    bare_text = source.split(marker, 1)[0] + "\n"
    bare_text = bare_text.replace(',"sections":["velocities"]', "")
    repeats = max(12, int(os.environ.get("BENCH_ROUNDS", str(ANATOMY_REPEATS))))
    with bench_scratch("novel-anatomy") as tmp:
        work = Path(tmp)
        full = work / "full.con"
        bare = work / "coords.con"
        full.write_text(source * ANATOMY_COPIES)
        bare.write_text(bare_text * ANATOMY_COPIES)
        full_s, bare_s, extra = _paired_reads(full, bare, repeats)
    _write(
        out,
        "anatomy.json",
        {
            "bytes": widths,
            "copies": ANATOMY_COPIES,
            "repeats": repeats,
            "full_median_s": full_s,
            "coords_median_s": bare_s,
            "velocity_extra_s": extra,
            "per_copy_full_s": full_s / ANATOMY_COPIES,
            "per_copy_coords_s": bare_s / ANATOMY_COPIES,
            "per_copy_velocity_s": extra / ANATOMY_COPIES,
        },
    )


def velocity(out: Path) -> None:
    import readcon
    from ase import Atoms
    from ase.calculators.emt import EMT
    from ase.geometry import cellpar_to_cell

    frame = readcon.read_con(str(E1 / "velocity" / "natural.con"))[0]
    positions = np.asarray(frame.coords_array(), dtype=float)
    velocities = np.asarray(frame.velocities_array(), dtype=float)
    masses = np.array([float(atom.mass) for atom in frame.atoms], dtype=float)
    symbols = [atom.symbol for atom in frame.atoms]
    factor = 10.180505710759414
    vel_fs = velocities / factor
    ke_true = float(0.5 * np.sum(masses[:, None] * vel_fs**2))
    ke_misread = float(0.5 * np.sum(masses[:, None] * velocities**2))
    cell = cellpar_to_cell([*frame.cell, *frame.angles])
    atoms = Atoms(
        symbols=symbols,
        positions=positions,
        masses=masses,
        cell=cell,
        pbc=frame.metadata.get("pbc"),
    )
    atoms.calc = EMT()
    forces = atoms.get_forces()
    acc = forces / masses[:, None] / (factor**2)
    dt = 1.0
    pos_true = positions + dt * vel_fs + 0.5 * (dt**2) * acc
    pos_misread = positions + dt * velocities + 0.5 * (dt**2) * acc
    delta = pos_misread - pos_true
    _write(
        out,
        "velocity.json",
        {
            "positions": positions.tolist(),
            "symbols": symbols,
            "displacement": delta.tolist(),
            "ke_true_eV": ke_true,
            "ke_misread_eV": ke_misread,
            "ratio": ke_misread / ke_true,
            "rmsd_A": float(np.sqrt(np.mean(delta**2))),
            "max_A": float(np.max(np.abs(delta))),
            "atom_norm_A": np.linalg.norm(delta, axis=1).tolist(),
        },
    )


def _library() -> Path:
    env = os.environ.get("READCON_LIB")
    if env:
        return Path(env)
    release = REPO / "target" / "release" / "libreadcon_core.so"
    if release.is_file():
        return release
    import readcon

    found = sorted(Path(readcon.__file__).parent.glob("*.so"))
    if not found:
        raise SystemExit("no readcon shared library")
    return found[0]


def _c_null(path: Path) -> bool:
    lib_path = _library()
    lib = ctypes.CDLL(str(lib_path))
    if not hasattr(lib, "read_con_file_iterator") or not hasattr(
        lib, "rkr_read_all_frames"
    ):
        raise SystemExit(
            f"{lib_path} lacks C ABI symbols; "
            "rebuild with cargo build --release --features capi,benchmark"
        )
    lib.read_con_file_iterator.argtypes = [ctypes.c_char_p]
    lib.read_con_file_iterator.restype = ctypes.c_void_p
    lib.con_frame_iterator_next.argtypes = [ctypes.c_void_p]
    lib.con_frame_iterator_next.restype = ctypes.c_void_p
    lib.free_con_frame_iterator.argtypes = [ctypes.c_void_p]
    lib.free_rkr_frame.argtypes = [ctypes.c_void_p]
    iterator = lib.read_con_file_iterator(str(path).encode())
    if not iterator:
        return True
    frame = lib.con_frame_iterator_next(iterator)
    if frame:
        lib.free_rkr_frame(frame)
        lib.free_con_frame_iterator(iterator)
        return False
    lib.free_con_frame_iterator(iterator)
    return True


def _error_class(message: str) -> str:
    rules = (
        ("unsupported con_spec_version", "UnsupportedVersion"),
        ('must be a JSON object containing "con_spec_version"', "MissingSpecVersion"),
        ("invalid units:", "InvalidUnits"),
        ("is not valid for quantity", "InvalidUnits"),
        ("column 4 flag", "InvalidFixedFlag"),
        ("not_a_real_section", "UnknownSection"),
        ("validate=true requires a sections array", "InvalidMetadataJson"),
        ("per-type count must be", "InvalidCount"),
    )
    for phrase, name in rules:
        if phrase in message:
            return name
    return "unclassified"


def errors(out: Path) -> None:
    import readcon
    from ase.io import read as ase_read

    manifest = tomllib.loads((CORPUS / "manifest.toml").read_text())
    cases = []
    for fields in manifest["invalid"]:
        path = CORPUS / fields["path"]
        try:
            readcon.read_con(str(path))
            py = "accepted"
            classified = "accepted"
        except Exception as exc:  # noqa: BLE001
            py = str(exc).split("\n", 1)[0]
            classified = _error_class(py)
        try:
            ase_read(str(path), format="eon")
            ase = "accepted"
        except Exception as exc:  # noqa: BLE001
            ase = f"{type(exc).__name__}: {exc}".split("\n", 1)[0][:160]
        cases.append(
            {
                "id": fields["id"],
                "readcon_class": classified,
                "readcon": py,
                "c_null_handle": _c_null(path),
                "ase": ase,
            }
        )
    _write(out, "errors.json", {"cases": cases})


def _db_version() -> str:
    from importlib.metadata import version

    return version("readcon-db")


def dedup(out: Path) -> None:
    from readcon_db import ConCorpus

    runs = {
        "uninterrupted": E1 / "neb" / "full" / "neb.con",
        "round trip": E1 / "neb" / "resume_round" / "neb.con",
        "six decimals": E1 / "neb" / "resume_fixed6" / "neb.con",
        "height held": E5_HELD,
        "adatom frozen": E5_FROZEN,
    }
    for path in runs.values():
        if not path.is_file():
            raise SystemExit(f"missing band {path}")
    with bench_scratch("novel-dedup") as tmp:
        db = ConCorpus(str(Path(tmp) / "campaign.lmdb"))
        edges = []
        counts: dict[str, int] = {}
        for index, (run, path) in enumerate(runs.items()):
            db.append_trajectory(index, str(path))
            frame_index = 0
            while True:
                try:
                    digest = db.frame_hash(index, frame_index)
                except Exception:  # noqa: BLE001
                    break
                text = (
                    digest.hex()
                    if isinstance(digest, (bytes, bytearray))
                    else str(digest)
                )
                counts[text] = counts.get(text, 0) + 1
                hits = db.find_by_hash(bytes(digest))
                edges.append(
                    {
                        "run": run,
                        "hash": text,
                        "image": frame_index,
                        "query_hits": 0 if hits is None else 1,
                    }
                )
                frame_index += 1

        def _nbytes(value) -> int:
            if isinstance(value, str):
                return len(value.encode())
            return len(bytes(value))

        paired = []
        texts = []
        image = 0
        while True:
            try:
                left = np.asarray(db.get_positions(0, image), dtype=float)
                right = np.asarray(db.get_positions(1, image), dtype=float)
                stored_left = db.get_frame_text(0, image)
                stored_right = db.get_frame_text(1, image)
            except Exception:  # noqa: BLE001
                break
            paired.append(float(np.max(np.abs(left - right))))
            texts.append(
                {
                    "image": image,
                    "bytes_uninterrupted": _nbytes(stored_left),
                    "bytes_round_trip": _nbytes(stored_right),
                    "text_equal": stored_left == stored_right,
                }
            )
            image += 1
        endpoint = {
            "reactant_max_A": paired[0],
            "product_max_A": paired[-1],
            "max_over_images_A": float(max(paired)),
            "stored_text": texts,
        }
    _write(
        out,
        "dedup_graph.json",
        {
            "source": f"readcon-db {_db_version()} frame_hash and find_by_hash",
            "runs": list(runs),
            "edges": edges,
            "multiplicity": counts,
            "n_images": len(edges),
            "n_hashes": len(counts),
            "endpoint_geometry": endpoint,
        },
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    restart_diff(args.out)
    fidelity(args.out)
    anatomy(args.out)
    velocity(args.out)
    errors(args.out)
    dedup(args.out)


if __name__ == "__main__":
    main()
