"""Shared full-frame and coordinate-only reads for the like-for-like benchmark.

Each full-frame arm builds positions, cell, symbols, masses, and fixed flags.
Coordinate-only reads return positions and nothing else. The checksum covers
positions only, in file order.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parents[2]
PINS = json.loads((BENCH / "pins.json").read_text(encoding="utf-8"))
WORK = BENCH / "work"
REPEATS = int(PINS["protocol"]["repeats"])

_PREPARED: set[str] = set()


def machine_hash() -> str:
    raw = Path("/etc/machine-id").read_bytes()
    return hashlib.sha256(raw).hexdigest()


def nproc() -> int:
    count = os.cpu_count()
    if count is None or count < 1:
        raise RuntimeError("cpu count is unavailable")
    return int(count)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def position_checksum(positions: np.ndarray) -> tuple[int, int, str]:
    arr = np.ascontiguousarray(positions, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise RuntimeError(f"positions shape {arr.shape}")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise RuntimeError(f"empty positions {arr.shape}")
    digest = hashlib.sha256(arr.tobytes()).hexdigest()
    return int(arr.shape[0]), int(arr.shape[1]), digest


def reference_positions(n_frames: int, n_atoms: int) -> np.ndarray:
    frames = np.arange(n_frames, dtype=np.float64)[:, None, None]
    atoms = np.arange(n_atoms, dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    return np.round(((frames * 17.0 + atoms * 3.0 + axes) % 10000.0) / 1000.0, 8)


def write_synthetic(path: Path) -> None:
    spec = PINS["synthetic"]
    frames = reference_positions(int(spec["n_frames"]), int(spec["n_atoms"]))
    n_atoms = int(frames.shape[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n")
        for frame in frames:
            handle.write(
                '{"con_spec_version":3,"con_spec_minor":1,'
                '"units":{"length":"angstrom","energy":"eV"}}\n'
            )
            handle.write("20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n")
            handle.write(f"{n_atoms}\n63.546\nCu\nCoordinates of Component 1\n")
            for index, (x_coord, y_coord, z_coord) in enumerate(frame):
                handle.write(f"{x_coord:.8f} {y_coord:.8f} {z_coord:.8f} 0 {index}\n")
            handle.write("\n")


def ensure_synthetic() -> tuple[Path, str]:
    path = WORK / "synthetic.con"
    if not path.is_file():
        write_synthetic(path)
    digest = file_sha256(path)
    return path, digest


def ensure_real() -> tuple[Path, str]:
    spec = PINS["real"]
    path = REPO / spec["path"]
    digest = file_sha256(path)
    if digest != spec["sha256"]:
        raise RuntimeError(f"real input hash {digest} != pin {spec['sha256']}")
    return path, digest


def ensure_inputs() -> dict[str, dict[str, str]]:
    synthetic_path, synthetic_hash = ensure_synthetic()
    real_path, real_hash = ensure_real()
    synthetic = PINS["synthetic"]
    real = PINS["real"]
    return {
        synthetic["name"]: {
            "name": synthetic["name"],
            "kind": "synthetic",
            "sha256": synthetic_hash,
            "path": str(synthetic_path),
        },
        real["name"]: {
            "name": real["name"],
            "kind": "real",
            "sha256": real_hash,
            "path": str(real_path),
        },
    }


def fetch_eon(dest_root: Path) -> Path:
    pin = PINS["eon_reader"]
    package = dest_root / "eon"
    package.mkdir(parents=True, exist_ok=True)
    init = package / "__init__.py"
    if not init.is_file():
        init.write_text("", encoding="utf-8", newline="\n")
    commit = pin["commit"]
    for rel, expect in pin["files"].items():
        target = dest_root / rel
        if target.is_file() and file_sha256(target) == expect:
            continue
        url = f"https://raw.githubusercontent.com/TheochemUI/eOn/{commit}/{rel}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expect:
            raise RuntimeError(f"{rel} hash {digest} != pin {expect}")
        target.write_bytes(data)
    return dest_root


def _svn_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _eigen_manifest(root: Path) -> str:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        rows.append(f"{rel} {file_sha256(path)}")
    text = "\n".join(rows) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_eon_svn() -> Path:
    """Fetch the pinned SVN client reader and compile the thin driver."""
    pin = PINS["eon_svn_cxx"]
    root = WORK / "eon-svn-r1213"
    root.mkdir(parents=True, exist_ok=True)
    base = pin["base_url"]
    for rel, expect in pin["files"].items():
        target = root / rel
        if target.is_file() and file_sha256(target) == expect:
            continue
        data = _svn_bytes(base + rel)
        digest = hashlib.sha256(data).hexdigest()
        if digest != expect:
            raise RuntimeError(f"{rel} hash {digest} != pin {expect}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    eigen = root / "Eigen"
    if not eigen.is_dir() or _eigen_manifest(eigen) != pin["eigen_tree_sha256"]:
        if eigen.exists():
            import shutil

            shutil.rmtree(eigen)
        _fetch_eigen_tree(base + "Eigen/", eigen)
        found = _eigen_manifest(eigen)
        if found != pin["eigen_tree_sha256"]:
            raise RuntimeError(f"eigen tree {found} != pin {pin['eigen_tree_sha256']}")
    binary = WORK / "eon_svn_cxx"
    stamp = root / "built-sha256"
    source = BENCH / "eon_svn_driver.cpp"
    source_hash = file_sha256(source)
    if (
        binary.is_file()
        and stamp.is_file()
        and stamp.read_text(encoding="utf-8").strip() == source_hash
    ):
        return binary
    log_path = WORK / "eon-svn-build.log"
    command = [
        "g++",
        "-std=gnu++98",
        "-O3",
        "-I",
        str(root),
        "-ffunction-sections",
        "-fdata-sections",
        str(source),
        str(root / "Matter.cpp"),
        "-Wl,--gc-sections",
        "-o",
        str(binary),
    ]
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"eon_svn_cxx compile exited {completed.returncode}")
    stamp.write_text(source_hash + "\n", encoding="utf-8", newline="\n")
    return binary


def _fetch_eigen_tree(url: str, folder: Path) -> None:
    import re

    folder.mkdir(parents=True, exist_ok=True)
    page = _svn_bytes(url).decode("utf-8", "replace")
    for href in re.findall(r'href="([^"]+)"', page):
        if href in {"../"} or href.startswith("?") or "://" in href:
            continue
        if href.endswith("/"):
            _fetch_eigen_tree(url + href, folder / href[:-1])
            continue
        target = folder / href
        target.write_bytes(_svn_bytes(url + href))


def abba_order(items: list, rep: int) -> list:
    """Forward, reversed, reversed, forward, rotated by the repeat index."""
    seq = list(items)
    if not seq:
        return seq
    shift = rep % len(seq)
    seq = seq[shift:] + seq[:shift]
    if rep % 4 in (1, 2):
        seq = list(reversed(seq))
    return seq


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=np.float64)
    median = float(np.percentile(arr, 50, method="linear"))
    q1 = float(np.percentile(arr, 25, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return median, q3 - q1


def _frame_record(positions, cell, symbols, masses, fixed) -> dict:
    pos = np.array(positions, dtype=np.float64, copy=True)
    return {
        "positions": pos,
        "cell": np.array(cell, dtype=np.float64, copy=True),
        "symbols": list(symbols),
        "masses": np.array(masses, dtype=np.float64, copy=True),
        "fixed": np.array(fixed, dtype=np.uint8, copy=True),
    }


def _digest_frames(built: list[dict]) -> tuple[int, int, str]:
    if not built:
        raise RuntimeError("reader returned no frames")
    n_atoms = int(built[0]["positions"].shape[0])
    rows = []
    for frame in built:
        pos = frame["positions"]
        if pos.ndim != 2 or pos.shape[1] != 3 or pos.shape[0] != n_atoms:
            raise RuntimeError(f"frame positions {pos.shape}")
        if frame["cell"].shape != (6,):
            raise RuntimeError(f"cell {frame['cell'].shape}")
        if len(frame["symbols"]) != n_atoms or frame["masses"].shape != (n_atoms,):
            raise RuntimeError("symbols or masses do not match the atom count")
        if frame["fixed"].shape != (n_atoms, 3):
            raise RuntimeError(f"fixed {frame['fixed'].shape}")
        rows.append(pos)
    return position_checksum(np.stack(rows))


def prepare(arm: str) -> str:
    """Import the library for one arm. Returns its version string."""
    if arm.startswith("readcon"):
        import readcon

        _PREPARED.add("readcon")
        return str(readcon.__version__)
    if arm == "ase":
        import ase
        from ase.constraints import FixAtoms  # noqa: F401
        from ase.io import read  # noqa: F401

        _PREPARED.add("ase")
        return str(ase.__version__)
    if arm == "eon_legacy_python":
        from eon.fileio import loadcons  # noqa: F401

        _PREPARED.add("eon_legacy_python")
        return PINS["eon_reader"]["commit"]
    if arm == "eon_svn_cxx":
        ensure_eon_svn()
        _PREPARED.add("eon_svn_cxx")
        return str(PINS["eon_svn_cxx"]["revision"])
    raise RuntimeError(arm)


def run_arm(arm: str, path: str, threads: int):
    if arm in {"readcon_tip_a", "readcon_tip_b", "readcon_release"}:
        return _full_readcon(path, threads)
    if arm == "ase":
        return _full_ase(path)
    if arm == "eon_legacy_python":
        return _full_eon(path)
    if arm == "eon_svn_cxx":
        return _full_eon_svn(path)
    if arm in {"readcon_positions_1", "readcon_positions_all"}:
        return _coords_readcon(path, threads)
    raise RuntimeError(arm)


def digest(arm: str, payload) -> tuple[int, int, str]:
    if arm in {"readcon_positions_1", "readcon_positions_all"}:
        return position_checksum(payload)
    return _digest_frames(payload)


def _full_readcon(path: str, threads: int) -> list[dict]:
    import readcon

    frames = readcon.read_con(path, n_threads=threads)
    built = []
    for frame in frames:
        atoms = list(frame.atoms)
        pos = np.empty((len(atoms), 3), dtype=np.float64)
        symbols = []
        masses = np.empty(len(atoms), dtype=np.float64)
        fixed = np.empty((len(atoms), 3), dtype=np.uint8)
        for index, atom in enumerate(atoms):
            pos[index, 0] = atom.x
            pos[index, 1] = atom.y
            pos[index, 2] = atom.z
            symbols.append(atom.symbol)
            masses[index] = float(atom.mass) if atom.mass is not None else np.nan
            flags = atom.fixed
            fixed[index, 0] = 1 if flags[0] else 0
            fixed[index, 1] = 1 if flags[1] else 0
            fixed[index, 2] = 1 if flags[2] else 0
        cell = np.array([*frame.cell, *frame.angles], dtype=np.float64)
        built.append(_frame_record(pos, cell, symbols, masses, fixed))
    return built


def _coords_readcon(path: str, threads: int) -> np.ndarray:
    import readcon

    return np.asarray(readcon.read_positions(path, n_threads=threads), dtype=np.float64)


def _full_ase(path: str) -> list[dict]:
    from ase.constraints import FixAtoms
    from ase.io import read

    images = read(path, index=":", format="eon")
    if not isinstance(images, list):
        images = [images]
    built = []
    for atoms in images:
        pos = np.array(atoms.positions, dtype=np.float64, copy=True)
        cell = np.array(atoms.cell.cellpar(), dtype=np.float64, copy=True)
        symbols = list(atoms.get_chemical_symbols())
        masses = np.array(atoms.get_masses(), dtype=np.float64, copy=True)
        fixed = np.zeros((len(atoms), 3), dtype=np.uint8)
        for constraint in atoms.constraints:
            if isinstance(constraint, FixAtoms):
                index = np.asarray(constraint.index, dtype=int)
                fixed[index, :] = 1
        built.append(_frame_record(pos, cell, symbols, masses, fixed))
    return built


def _full_eon(path: str) -> list[dict]:
    from eon.fileio import loadcons

    frames = loadcons(path)
    built = []
    for frame in frames:
        pos = np.array(frame.r, dtype=np.float64, copy=True)
        lengths = np.linalg.norm(frame.box, axis=1)
        angles = np.zeros(3, dtype=np.float64)
        lengths_safe = np.where(lengths == 0.0, 1.0, lengths)
        angles[0] = np.degrees(
            np.arccos(
                np.clip(
                    np.dot(frame.box[0], frame.box[1])
                    / (lengths_safe[0] * lengths_safe[1]),
                    -1.0,
                    1.0,
                )
            )
        )
        angles[1] = np.degrees(
            np.arccos(
                np.clip(
                    np.dot(frame.box[0], frame.box[2])
                    / (lengths_safe[0] * lengths_safe[2]),
                    -1.0,
                    1.0,
                )
            )
        )
        angles[2] = np.degrees(
            np.arccos(
                np.clip(
                    np.dot(frame.box[1], frame.box[2])
                    / (lengths_safe[1] * lengths_safe[2]),
                    -1.0,
                    1.0,
                )
            )
        )
        cell = np.concatenate([lengths, angles])
        symbols = list(frame.names)
        masses = np.array(frame.mass, dtype=np.float64, copy=True)
        fixed = np.zeros((len(frame), 3), dtype=np.uint8)
        frozen = np.asarray(frame.free) == 0
        fixed[frozen, :] = 1
        built.append(_frame_record(pos, cell, symbols, masses, fixed))
    return built


def _full_eon_svn(path: str) -> list[dict]:
    binary = ensure_eon_svn()
    completed = subprocess.run(
        [str(binary), path],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[-400:]
        raise RuntimeError(detail or f"eon_svn_cxx exited {completed.returncode}")
    return _parse_eon_svn(completed.stdout)


_SVN_SYMBOLS = (
    "Unknown",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
)


def _parse_eon_svn(blob: bytes) -> list[dict]:
    if not blob.startswith(b"EONSVN1\n"):
        raise RuntimeError("eon_svn_cxx output is not a frame record")
    offset = 8
    n_frames, n_atoms = struct.unpack_from("<II", blob, offset)
    offset += 8
    if n_frames < 1 or n_atoms < 1:
        raise RuntimeError(f"eon_svn_cxx counts {n_frames} {n_atoms}")
    count = n_frames * n_atoms
    cells = np.frombuffer(blob, dtype="<f8", count=n_frames * 6, offset=offset).copy()
    offset += n_frames * 6 * 8
    masses = np.frombuffer(blob, dtype="<f8", count=count, offset=offset).copy()
    offset += count * 8
    numbers = np.frombuffer(blob, dtype="<u2", count=count, offset=offset).copy()
    offset += count * 2
    fixed_flat = np.frombuffer(blob, dtype=np.uint8, count=count, offset=offset).copy()
    offset += count
    positions = np.frombuffer(blob, dtype="<f8", count=count * 3, offset=offset).copy()
    offset += count * 3 * 8
    if offset != len(blob):
        raise RuntimeError(f"eon_svn_cxx trailing bytes {len(blob) - offset}")
    if int(numbers.max()) >= len(_SVN_SYMBOLS):
        raise RuntimeError("eon_svn_cxx atomic number is outside the client table")
    built = []
    for frame in range(n_frames):
        start = frame * n_atoms
        pos = positions[start * 3 : (start + n_atoms) * 3].reshape(n_atoms, 3)
        cell = cells[frame * 6 : frame * 6 + 6]
        frame_symbols = [
            _SVN_SYMBOLS[int(number)] for number in numbers[start : start + n_atoms]
        ]
        frame_masses = masses[start : start + n_atoms]
        flags = np.zeros((n_atoms, 3), dtype=np.uint8)
        flags[fixed_flat[start : start + n_atoms] != 0, :] = 1
        built.append(_frame_record(pos, cell, frame_symbols, frame_masses, flags))
    return built


def assert_schedule() -> None:
    order = ["a", "b", "c"]
    expect = {
        0: ["a", "b", "c"],
        1: ["a", "c", "b"],
        2: ["b", "a", "c"],
        3: ["a", "b", "c"],
        4: ["b", "c", "a"],
        5: ["b", "a", "c"],
    }
    for rep, wanted in expect.items():
        got = abba_order(order, rep)
        if got != wanted:
            raise RuntimeError(f"schedule rep {rep} {got} != {wanted}")
