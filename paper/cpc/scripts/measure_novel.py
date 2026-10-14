#!/usr/bin/env python3
"""Measurements for the supplementary figures.

Numbers written here are computed in this process from the evidence
files, the conformance corpus, and the installed readers. The roofline
uses the thread sweep already stored with the layered benchmark.
"""

from __future__ import annotations

import ctypes
import json
import tempfile
import time
import tomllib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
E1 = EVIDENCE / "work" / "e1"
E2 = EVIDENCE / "results" / "e2_layered.json"
NOVEL = ROOT / "data" / "novel"
CORPUS = Path("/workspace/resources/conformance")
READCON_SO = Path(
    "/home/ubuntu/.local/lib/python3.12/site-packages/readcon/"
    "readcon.cpython-312-x86_64-linux-gnu.so"
)


def _write(name: str, payload: dict) -> None:
    NOVEL.mkdir(parents=True, exist_ok=True)
    (NOVEL / name).write_text(json.dumps(payload, indent=2) + "\n")
    print(name, "ok")


def _positions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import readcon

    frames = readcon.read_con(str(path))
    coords = np.stack([np.asarray(frame.coords_array(), dtype=float) for frame in frames])
    lengths = np.asarray(frames[0].cell[:3], dtype=float)
    return coords, lengths


def _mic_max(a: np.ndarray, b: np.ndarray, lengths: np.ndarray) -> float:
    """Maximum absolute minimum-image component. z is not periodic."""
    delta = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    wrapped = delta.copy()
    for axis in (0, 1):
        length = float(lengths[axis])
        wrapped[..., axis] = delta[..., axis] - length * np.round(delta[..., axis] / length)
    return float(np.max(np.abs(wrapped)))


def _movie_matrix(full_dir: Path, other_dir: Path) -> dict:
    """Align resume movies to the uninterrupted movie by checkpoint index.

    The checkpoint written at interruption is ``neb_path_003.con``.
    Resume iteration 0 rewrites that band, and each later resume movie
    is the next uninterrupted movie.
    """
    full_paths = sorted(full_dir.glob("neb_path_*.con"))
    other_paths = sorted(other_dir.glob("neb_path_*.con"))
    full = {int(path.stem.rsplit("_", 1)[1]): path for path in full_paths}
    other = {int(path.stem.rsplit("_", 1)[1]): path for path in other_paths}
    columns = []
    matrix = []
    n_images = None
    for resume_index in sorted(other):
        full_index = 3 + resume_index
        if full_index not in full:
            continue
        got, lengths = _positions(other[resume_index])
        ref, _ = _positions(full[full_index])
        n = min(len(got), len(ref))
        n_images = n if n_images is None else min(n_images, n)
        column = [_mic_max(got[i], ref[i], lengths) for i in range(n)]
        columns.append(full_index)
        matrix.append(column)
    # Final bands, which the manuscript compares after the five steps.
    if (other_dir / "neb.con").is_file() and (full_dir / "neb.con").is_file():
        got, lengths = _positions(other_dir / "neb.con")
        ref, _ = _positions(full_dir / "neb.con")
        n = min(len(got), len(ref))
        n_images = n if n_images is None else min(n_images, n)
        matrix.append([_mic_max(got[i], ref[i], lengths) for i in range(n)])
        columns.append("final")
    rows = []
    for image in range(n_images or 0):
        rows.append([column[image] for column in matrix])
    return {
        "columns": [str(item) for item in columns],
        "images": list(range(n_images or 0)),
        "mic_max_abs_A": rows,
        "alignment": "resume movie k against uninterrupted neb_path_{3+k}",
    }


def restart_diff() -> None:
    full = E1 / "neb" / "full"
    payload = {
        "round_trip": _movie_matrix(full, E1 / "neb" / "resume_round_matched"),
        "six_decimal": _movie_matrix(full, E1 / "neb" / "resume_fixed6_matched"),
    }
    _write("restart_diff.json", payload)


def _field_snapshot(frame) -> dict:
    return {
        "positions": np.asarray(frame.coords_array(), dtype=float),
        "ids": np.asarray(frame.atom_ids_array(), dtype=int),
        "masks": np.array([list(atom.fixed) for atom in frame.atoms], dtype=bool),
        "time_unit": (frame.metadata.get("units") or {}).get("time"),
        "has_velocity": bool(frame.has_velocities),
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
    # A missing id array is a loss. Numbering the rows 0..n-1 matches this
    # fixture and would report a false exact.
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
    """Unmodified velocity fixture. The file is not edited."""
    import readcon

    source = E1 / "velocity" / "natural.con"
    reference = _from_readcon(source)
    with tempfile.TemporaryDirectory(prefix="readcon-time-") as tmp:
        native = Path(tmp) / "round.con"
        readcon.write_con(str(native), readcon.read_con(str(source)))
        got = _from_readcon(native)
    return {
        "source": "e1 velocity fixture, unmodified",
        "time_unit": reference["time_unit"],
        "round_trip": got["time_unit"] == reference["time_unit"] and got["time_unit"] is not None,
    }


def fidelity() -> None:
    """First frame of the height-held EMT band. The file is not edited."""
    import readcon
    from ase.io import read as ase_read
    from ase.io import write as ase_write

    source = EVIDENCE / "work" / "e5" / "bands" / "held" / "neb.con"
    frame = readcon.read_con(str(source))[0]
    reference = _field_snapshot(frame)
    z_only = bool(reference["masks"][27, 2]) and not bool(reference["masks"][27, 0])
    if not z_only:
        raise SystemExit("the held band adatom is not a z-only mask")
    with tempfile.TemporaryDirectory(prefix="readcon-fidelity-") as tmp:
        out = Path(tmp)
        rows = []
        native = out / "round.con"
        readcon.write_con(str(native), [frame])
        rows.append({"format": "CON 3.1", **_grade(reference, _from_readcon(native), "readcon write")})

        six = out / "six.con"
        readcon.write_con(str(six), [frame], precision=6)
        rows.append(
            {"format": "CON six decimals", **_grade(reference, _from_readcon(six), "precision 6")}
        )

        velocity = E1 / "velocity" / "natural.con"
        velocity_frame = readcon.read_con(str(velocity))[0]
        velocity_ref = _field_snapshot(velocity_frame)
        velocity_path = out / "velocity-round.con"
        readcon.write_con(str(velocity_path), [velocity_frame])
        rows.append(
            {
                "format": "CON 3.1, velocity file",
                **_grade(velocity_ref, _from_readcon(velocity_path), "unmodified velocity fixture"),
            }
        )

        # readcon-core 0.17.0 passes energy and forces positionally.
        # ASE 3.29.0 accepts only keywords. The frame file is not edited.
        import ase.calculators.singlepoint as singlepoint

        original_init = singlepoint.SinglePointCalculator.__init__

        def _accept_positional(self, atoms, energy=None, forces=None, **results):
            if energy is not None:
                results["energy"] = energy
            if forces is not None:
                results["forces"] = forces
            original_init(self, atoms, **results)

        singlepoint.SinglePointCalculator.__init__ = _accept_positional
        atoms = frame.to_ase()
        trials = ("extxyz", "traj", "json", "vasp", "xyz", "cif")
        for fmt in trials:
            path = out / f"round.{fmt if fmt != 'vasp' else 'poscar'}"
            try:
                ase_write(path, atoms, format=fmt)
                back = ase_read(path, format=fmt)
                rows.append(
                    {"format": fmt, **_grade(reference, _ase_snapshot(back), "ASE write then read")}
                )
            except Exception as exc:
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
        "fidelity.json",
        {
            "source": "first frame of the height-held EMT band, unmodified",
            "adatom_mask": "z-only",
            "file_edited": False,
            "ase_note": "SinglePointCalculator positional energy and forces are passed as keywords",
            "time_unit_fixture": _time_unit_roundtrip(),
            "rows": rows,
        },
    )


def _numeric_row(line: str) -> tuple[str, str, str] | None:
    """Split one coordinate or velocity row into numbers, mask and id.

    Trailing spaces stay with the token they follow. The newline stays
    with the numeric fields, which are the wide part of the row.
    """
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
    """Byte widths of one CON 3.1 frame, counted on the file text."""
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
        (index for index, line in enumerate(lines) if line.startswith("Velocities of Component")),
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
        split = _numeric_row(line) if number_key == "velocity numbers" or line[:1] in "0123456789-" else None
        if split is None and number_key == "coordinates":
            split = _numeric_row(line)
        if split is not None and (number_key == "velocity numbers" or index > 0):
            # Coordinate rows are the only 5-token numeric rows before the velocity block.
            if number_key == "coordinates" and not any(
                earlier.startswith("Coordinates of Component") for earlier in lines[:index]
            ):
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
    buckets["total"] = sum(value for key, value in buckets.items() if key != "total")
    encoded = len(text.encode())
    if buckets["total"] != encoded:
        raise SystemExit(f"byte buckets sum to {buckets['total']}, file is {encoded}: {buckets}")
    if buckets["velocity numbers"] <= 0:
        raise SystemExit(f"velocity numbers were not counted: {buckets}")
    return buckets


def _paired_reads(full: Path, bare: Path, repeats: int = 31) -> tuple[float, float, float]:
    """Median full read, median coordinate read, and median paired difference."""
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


def anatomy() -> None:
    import readcon

    source = (E1 / "velocity" / "natural.con").read_text()
    widths = _split_frame_bytes(source)
    readcon.read_con(str(E1 / "velocity" / "natural.con"))
    copies = 400
    bare_text = source.split("\n\nPt\nVelocities of Component", 1)[0] + "\n"
    bare_text = bare_text.replace(',"sections":["velocities"]', "")
    with tempfile.TemporaryDirectory(prefix="readcon-anatomy-") as tmp:
        work = Path(tmp)
        full = work / "full.con"
        bare = work / "coords.con"
        full.write_text(source * copies)
        bare.write_text(bare_text * copies)
        full_s, bare_s, extra = _paired_reads(full, bare)
    _write(
        "anatomy.json",
        {
            "bytes": widths,
            "copies": copies,
            "full_median_s": full_s,
            "coords_median_s": bare_s,
            "velocity_extra_s": extra,
            "per_copy_full_s": full_s / copies,
            "per_copy_coords_s": bare_s / copies,
            "per_copy_velocity_s": extra / copies,
        },
    )


def velocity() -> None:
    """Same Verlet step as the stored 28-atom illustration."""
    import readcon
    from ase import Atoms
    from ase.calculators.emt import EMT
    from ase.geometry import cellpar_to_cell

    frame = readcon.read_con(str(E1 / "velocity" / "natural.con"))[0]
    positions = np.asarray(frame.coords_array(), dtype=float)
    velocities = np.asarray(frame.velocities_array(), dtype=float)
    masses = np.array([float(atom.mass) for atom in frame.atoms], dtype=float)
    symbols = [atom.symbol for atom in frame.atoms]
    # Same conversion the stored illustration used.
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


def _c_null(path: Path) -> bool:
    lib = ctypes.CDLL(str(READCON_SO))
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


def errors() -> None:
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
        except Exception as exc:
            py = str(exc).split("\n", 1)[0]
            classified = _error_class(py)
        try:
            ase_read(path, format="eon")
            ase = "accepted"
        except Exception as exc:
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
    _write("errors.json", {"cases": cases})


def _error_class(message: str) -> str:
    """Name the failure from the reader message. An unmatched message stays unclassified."""
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


def dedup() -> None:
    """Hash graph from a readcon-db query of the five campaign bands."""
    import tempfile

    from readcon_db import ConCorpus

    runs = {
        "uninterrupted": E1 / "neb" / "full" / "neb.con",
        "round trip": E1 / "neb" / "resume_round_matched" / "neb.con",
        "six decimals": E1 / "neb" / "resume_fixed6_matched" / "neb.con",
        "height held": EVIDENCE / "work" / "e5" / "bands" / "held" / "neb.con",
        "adatom frozen": EVIDENCE / "work" / "e5" / "bands" / "frozen" / "neb.con",
    }
    with tempfile.TemporaryDirectory(prefix="readcon-db-") as tmp:
        db = ConCorpus(str(Path(tmp) / "campaign.lmdb"))
        edges = []
        counts: dict[str, int] = {}
        for index, (run, path) in enumerate(runs.items()):
            db.append_trajectory(index, str(path))
            frame_index = 0
            while True:
                try:
                    digest = db.frame_hash(index, frame_index)
                except Exception:
                    break
                text = digest.hex() if isinstance(digest, (bytes, bytearray)) else str(digest)
                counts[text] = counts.get(text, 0) + 1
                hits = db.find_by_hash(digest)
                edges.append(
                    {
                        "run": run,
                        "hash": text,
                        "image": frame_index,
                        "query_hits": 1 if hits is not None else 0,
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
            except Exception:
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
        "dedup_graph.json",
        {
            "source": "readcon-db 0.1.8 frame_hash and find_by_hash",
            "runs": list(runs),
            "edges": edges,
            "multiplicity": counts,
            "n_images": len(edges),
            "n_hashes": len(counts),
            "endpoint_geometry": endpoint,
        },
    )


def main() -> None:
    restart_diff()
    fidelity()
    anatomy()
    velocity()
    errors()
    dedup()


if __name__ == "__main__":
    main()
