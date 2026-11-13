"""Fidelity and timing head-to-head on the checked-in CON fixtures.

One core, one warmup, six samples. The median and the interquartile range
use the type-7 percentile (NumPy ``linear``). A field is ``exact`` when the
values match, ``within_tolerance`` when the tool's writer rounds them inside
the tolerance named on the row, and ``not_representable`` when that tool has
no place for the field. A missing import of chemfiles, ASE, or eOn is
``unavailable``. The citation is a file and line in that tool.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"
WORK = HERE / "work"
RESULTS = HERE / "results"
LOGS = HERE / "logs"

WARMUP = 1
REPEATS = int(os.environ.get("READCON_CAMPAIGN_REPEATS", "6"))
NATURAL = "(amu*angstrom^2/eV)^0.5"

# Tolerances are the writer's documented rounding, not a fit to the output.
# readcon's text is ryu, so the tolerance is zero. ASE's eon writer prints
# the cell with %-10.6f (ase/io/eon.py:257) and coordinates with 17 digits
# (ase/io/eon.py:303). A path through a 3x3 cell matrix uses 1e-8.
TOL = {
    "readcon": {"cell": 0.0, "mass": 0.0, "position": 0.0, "velocity": 0.0},
    "ase-readcon-con": {
        "cell": 1e-8,
        "mass": 1e-9,
        "position": 1e-8,
        "velocity": 1e-8,
    },
    "ase-readcon-convel": {
        "cell": 1e-8,
        "mass": 1e-9,
        "position": 1e-8,
        "velocity": 1e-8,
    },
    "ase-eon": {"cell": 5e-7, "mass": 1e-6, "position": 1e-12, "velocity": 0.0},
    "eon-python": {"cell": 1e-8, "mass": 0.0, "position": 1e-12, "velocity": 1e-12},
    "chemfiles": {"cell": 0.0, "mass": 0.0, "position": 0.0, "velocity": 0.0},
}

CITE_ASE_COL4 = "ase/io/eon.py:139 bool(int(tokens[3])); FixAtoms at :146"
CITE_ASE_COL5 = "ase/io/eon.py:138 reads xyz and tokens[3], not column 5"
CITE_ASE_ID_WRITE = "ase/io/eon.py:281 atom_id starts at 0 and increments"
CITE_ASE_FIX = "ase/io/eon.py:288 only FixAtoms is written"
CITE_ASE_VEL = "ase/io/eon.py:302 writes the coordinate line; no velocity block"
CITE_ASE_SECTION = "ase/io/eon.py:174 the next lines are read as the next header"
CITE_ASE_CELL = "ase/io/eon.py:257 lengths and angles use %-10.6f"
CITE_CF = (
    "chemfiles 0.10.4 src/FormatFactory.cpp:139 by_name throws; "
    ":208 formats the message 'can not find a format named'"
)
CITE_EON_LOAD = "eon/fileio.py:170 loadcons calls readcon.read_con"
CITE_EON_ORDER = "eon/structure.py:284 structure_order sorts unique atom ids"
CITE_EON_UNIT = "eon/structure.py:378 to_conframe does not copy units"
CITE_EON_CPP = (
    "client/ConFileIO.cpp:612 readcon::read_all_frames; "
    "meson is not on PATH, so the C++ client was not built"
)
CITE_UNITS = (
    "src/units.rs:406 versions below 3 and minor 0 use the natural unit, "
    "ignoring a units.time label"
)
CITE_PARSE_VEL = "src/parser.rs:1984 set_velocity stores the parsed numbers"
CITE_FROM_ASE = "src/python.rs:3616 from_ase writes the natural time unit"
CITE_TO_ASE = "src/python.rs:3274 to_ase scales file velocities into that unit"
CITE_PLUGIN_BULK = (
    "ase-readcon/ase_readcon/io.py:155 _read_bulk builds Atoms without an atom_id array"
)
CITE_PLUGIN_CON = "ase-readcon/ase_readcon/io.py:63 write_readcon_con omits velocities"
CITE_PLUGIN_VEL = "ase-readcon/ase_readcon/io.py:68 write_readcon_convel writes them"

FIELDS = (
    "atom_ids",
    "fixed_mask",
    "masses",
    "cell",
    "positions",
    "velocities",
    "velocity_unit",
    "frame_order",
    "positional_zip_error",
)

FIXTURE_NAMES = (
    "claisen.con",
    "neb_band_3.con",
    "pt100_slab.con",
    "tiny_multi_cuh2.convel",
    "v30_fs_label.convel",
)


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def _pin() -> None:
    allowed = ""
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    for line in status.splitlines():
        if line.startswith("Cpus_allowed_list:"):
            allowed = line.split(":", 1)[1].strip()
    if allowed == "0":
        return
    if os.environ.get("FIDELITY_PINNED") == "1":
        return
    os.environ["FIDELITY_PINNED"] = "1"
    os.execvp("taskset", ["taskset", "-c", "0", sys.executable, *sys.argv])


def _threads() -> None:
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[key] = "1"


def quantile(values: list[float], probability: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    return float(np.quantile(ordered, probability))


def stats(samples: list[float]) -> dict:
    q25 = quantile(samples, 0.25)
    med = quantile(samples, 0.5)
    q75 = quantile(samples, 0.75)
    return {
        "median_s": med,
        "iqr_s": q75 - q25,
        "q25_s": q25,
        "q75_s": q75,
        "samples_s": samples,
    }


def hardware() -> str:
    model = "unknown"
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    memory = 0
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            memory = int(line.split()[1])
    return f"{model} {os.uname().machine} nproc {os.cpu_count()} memory_kib {memory}"


def _meta(frame) -> dict:
    raw = dict(frame.metadata)
    units = raw.get("units")
    if not isinstance(units, dict):
        units = {}
    minor = raw.get("con_spec_minor")
    return {
        "spec": int(frame.spec_version),
        "minor": None if minor is None else int(minor),
        "time_label": units.get("time"),
    }


def _legacy_natural_stamp(labels_got: list, auth_ref: list, auth_got: list) -> bool:
    """True when a legacy file's round trip only records the natural unit.

    Versions below 3 and minor 0 already store velocities in that unit.
    The writer writes the label and minor 1 so the label becomes authoritative.
    """
    return (
        auth_ref == auth_got
        and bool(auth_ref)
        and all(unit == NATURAL for unit in auth_ref)
        and all(label == NATURAL for label in labels_got)
    )


def authoritative_time(spec: int, minor: int | None, label) -> str:
    if spec < 3 or (minor or 0) == 0:
        return NATURAL
    if label:
        return str(label)
    return ""


def record_from_readcon(frame) -> dict:
    meta = _meta(frame)
    atoms = []
    for atom in frame.atoms:
        vel = None
        if atom.vx is not None:
            vel = [float(atom.vx), float(atom.vy), float(atom.vz)]
        atoms.append(
            {
                "symbol": str(atom.symbol),
                "atom_id": int(atom.atom_id),
                "fixed": [
                    bool(atom.fixed[0]),
                    bool(atom.fixed[1]),
                    bool(atom.fixed[2]),
                ],
                "mass": None if atom.mass is None else float(atom.mass),
                "pos": [float(atom.x), float(atom.y), float(atom.z)],
                "vel": vel,
            }
        )
    return {
        "cell": [float(v) for v in frame.cell],
        "angles": [float(v) for v in frame.angles],
        "atoms": atoms,
        "ids_known": True,
        **meta,
    }


def read_readcon(path: Path) -> list[dict]:
    import readcon

    return [record_from_readcon(frame) for frame in readcon.read_con(os.fspath(path))]


def _cell6(frame: dict) -> np.ndarray:
    return np.asarray([*frame["cell"], *frame["angles"]], dtype=np.float64)


def _pair(ref: dict, got: dict) -> tuple[list[tuple[dict, dict]], str]:
    ref_ids = [atom["atom_id"] for atom in ref["atoms"]]
    if got.get("ids_known") and len(set(ref_ids)) == len(ref_ids):
        got_by = {atom["atom_id"]: atom for atom in got["atoms"]}
        if set(got_by) == set(ref_ids) and len(got_by) == len(ref_ids):
            pairs = [(atom, got_by[atom["atom_id"]]) for atom in ref["atoms"]]
            # The same integers are not the same atoms when the element differs.
            # ASE's eon writer issues a fresh 0..n-1 that can reuse the old numbers.
            if all(left["symbol"] == right["symbol"] for left, right in pairs):
                return pairs, "atom_id"
    n = min(len(ref["atoms"]), len(got["atoms"]))
    return list(zip(ref["atoms"][:n], got["atoms"][:n], strict=False)), "index"


def _max_abs(pairs, key: str) -> float | None:
    worst = 0.0
    any_value = False
    for left, right in pairs:
        a = left[key]
        b = right[key]
        if a is None and b is None:
            continue
        if a is None or b is None:
            return None
        any_value = True
        diff = np.max(
            np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))
        )
        worst = max(worst, float(diff))
    if not any_value:
        return 0.0
    return worst


def _numeric(max_abs: float | None, tol: float) -> str:
    if max_abs is None:
        return "mismatch"
    if max_abs == 0.0:
        return "exact"
    if max_abs <= tol:
        return "within_tolerance"
    return "mismatch"


def _blank(field: str, reader: str, trip: str, **extra) -> dict:
    row = {
        "field": field,
        "reader": reader,
        "round_trip": trip,
        "max_abs": None,
        "n_differ": None,
        "tolerance": None,
        "detail": "",
        "citation": "",
    }
    row.update(extra)
    return row


def compare_frames(
    ref: list[dict],
    got: list[dict] | None,
    tol: dict,
    *,
    ids: bool,
    per_axis: bool,
    velocities: bool,
    unit: bool,
    id_cite: str,
    mask_cite: str,
    vel_cite: str,
    unit_cite: str,
) -> list[dict]:
    if got is None:
        return [
            _blank(field, "read_error", "read_error", detail="no frames")
            for field in FIELDS
            if field != "positional_zip_error"
        ]
    missing = abs(len(ref) - len(got))
    id_differ = 0
    mask_differ = 0
    order_same = True
    mass_abs = 0.0
    pos_abs = 0.0
    vel_abs = 0.0
    vel_missing = False
    cell_abs = 0.0
    paired_by = "index"
    for left, right in zip(ref, got, strict=False):
        pairs, how = _pair(left, right)
        paired_by = how
        if [a["atom_id"] for a in left["atoms"]] != [
            a["atom_id"] for a in right["atoms"]
        ]:
            order_same = False
        if how == "atom_id":
            id_differ += 0
        else:
            id_differ += abs(len(left["atoms"]) - len(right["atoms"]))
            if [a["atom_id"] for a in left["atoms"]] != [
                a["atom_id"] for a in right["atoms"] if "atom_id" in a
            ]:
                id_differ += 1
        for a, b in pairs:
            if a["fixed"] != b["fixed"]:
                mask_differ += 1
        mass = _max_abs(pairs, "mass")
        pos = _max_abs(pairs, "pos")
        if mass is not None:
            mass_abs = max(mass_abs, mass)
        if pos is not None:
            pos_abs = max(pos_abs, pos)
        cell_abs = max(cell_abs, float(np.max(np.abs(_cell6(left) - _cell6(right)))))
        ref_vel = any(atom["vel"] is not None for atom in left["atoms"])
        got_vel = any(atom["vel"] is not None for atom in right["atoms"])
        if ref_vel and not got_vel:
            vel_missing = True
        elif ref_vel and got_vel:
            vel = _max_abs(pairs, "vel")
            if vel is None:
                vel_missing = True
            else:
                vel_abs = max(vel_abs, vel)
    frame_keys_ref = [
        tuple(sorted(tuple(np.round(atom["pos"], 8)) for atom in frame["atoms"]))
        for frame in ref
    ]
    frame_keys_got = [
        tuple(sorted(tuple(np.round(atom["pos"], 8)) for atom in frame["atoms"]))
        for frame in got
    ]
    labels_ref = [frame["time_label"] for frame in ref]
    labels_got = [frame["time_label"] for frame in got]
    auth_ref = [
        authoritative_time(frame["spec"], frame["minor"], frame["time_label"])
        for frame in ref
    ]
    auth_got = [
        authoritative_time(frame["spec"], frame["minor"], frame["time_label"])
        for frame in got
    ]
    has_vel = any(atom["vel"] is not None for frame in ref for atom in frame["atoms"])

    if not ids or not got[0].get("ids_known", False):
        id_row = _blank(
            "atom_ids",
            "not_representable",
            "not_representable",
            citation=id_cite,
            detail="this reader does not keep CON column 5",
        )
    elif id_differ == 0 and order_same and missing == 0:
        id_row = _blank(
            "atom_ids", "exact", "exact", n_differ=0, detail="column 5 sequence matches"
        )
    elif id_differ == 0 and missing == 0:
        id_row = _blank(
            "atom_ids",
            "reordered",
            "reordered",
            n_differ=0,
            detail="the same ids, in a different storage order",
            citation=id_cite,
        )
    else:
        id_row = _blank(
            "atom_ids",
            "mismatch",
            "mismatch",
            n_differ=id_differ + missing,
            detail="column 5 does not match the input ids",
            citation=id_cite,
        )

    if not per_axis:
        # A boolean flag can still match an all-or-nothing mask. Count the
        # atoms whose three axes are not the boolean the reader stored.
        mask_status = "exact" if mask_differ == 0 and missing == 0 else "mismatch"
        mask_row = _blank(
            "fixed_mask",
            mask_status,
            mask_status,
            n_differ=mask_differ,
            citation=mask_cite,
            detail="column 4 is one boolean, stored as the same flag on x, y and z",
        )
    else:
        mask_status = "exact" if mask_differ == 0 and missing == 0 else "mismatch"
        mask_row = _blank(
            "fixed_mask",
            mask_status,
            mask_status,
            n_differ=mask_differ,
            detail=f"atoms whose per-axis mask differs: {mask_differ}",
        )

    mass_sorted = 0.0
    pos_sorted = 0.0
    sortable = True
    for left, right in zip(ref, got, strict=False):
        left_m = _sorted_rows(left, "mass")
        right_m = _sorted_rows(right, "mass")
        left_p = _sorted_rows(left, "pos")
        right_p = _sorted_rows(right, "pos")
        if left_m.shape != right_m.shape or left_p.shape != right_p.shape:
            sortable = False
            break
        if left_m.size:
            mass_sorted = max(mass_sorted, float(np.max(np.abs(left_m - right_m))))
        if left_p.size:
            pos_sorted = max(pos_sorted, float(np.max(np.abs(left_p - right_p))))
    mass_status = _numeric(mass_abs, tol["mass"])
    if missing:
        mass_status = "mismatch"
    elif mass_status == "mismatch" and sortable and mass_sorted <= tol["mass"]:
        mass_status = "reordered"
    mass_row = _blank(
        "masses",
        mass_status,
        mass_status,
        max_abs=mass_abs if mass_status != "reordered" else mass_sorted,
        tolerance=tol["mass"],
        detail=f"paired by {paired_by}; sorted max abs {mass_sorted}",
    )

    cell_status = _numeric(cell_abs, tol["cell"])
    if missing:
        cell_status = "mismatch"
    same_input = all(np.array_equal(_cell6(ref[0]), _cell6(frame)) for frame in ref)
    cell_row = _blank(
        "cell",
        cell_status,
        cell_status,
        max_abs=cell_abs,
        tolerance=tol["cell"],
        detail=(
            f"per-frame cell+angles, n_frames {len(got)} of {len(ref)}, "
            f"input cells equal across frames: {bool(same_input)}"
        ),
        citation=CITE_ASE_CELL if tol["cell"] == 5e-7 else "",
    )

    pos_status = _numeric(pos_abs, tol["position"])
    if missing:
        pos_status = "mismatch"
    elif pos_status == "mismatch" and sortable and pos_sorted <= tol["position"]:
        pos_status = "reordered"
    pos_row = _blank(
        "positions",
        pos_status,
        pos_status,
        max_abs=pos_abs if pos_status != "reordered" else pos_sorted,
        tolerance=tol["position"],
        detail=f"paired by {paired_by}; sorted max abs {pos_sorted}",
    )

    if not has_vel:
        vel_row = _blank(
            "velocities", "absent", "absent", detail="this file has no velocity section"
        )
        unit_row = _blank(
            "velocity_unit",
            "absent",
            "absent",
            detail="no velocity section",
        )
    elif not velocities or vel_missing:
        vel_row = _blank(
            "velocities",
            "not_representable",
            "not_representable",
            citation=vel_cite,
            detail="the reader has no velocity block",
        )
        unit_row = _blank(
            "velocity_unit",
            "not_representable",
            "not_representable",
            citation=unit_cite or vel_cite,
            detail="no velocity block, so no time unit",
        )
    else:
        vel_status = _numeric(vel_abs, tol["velocity"])
        vel_row = _blank(
            "velocities",
            vel_status,
            vel_status,
            max_abs=vel_abs,
            tolerance=tol["velocity"],
            citation=CITE_PARSE_VEL,
            detail="file numbers, not a converted unit",
        )
        if not unit:
            unit_row = _blank(
                "velocity_unit",
                "not_representable",
                "not_representable",
                citation=unit_cite,
                detail=f"authoritative input unit {auth_ref[0]!r}; the tool does not store the label",
            )
        elif labels_ref != labels_got and _legacy_natural_stamp(
            labels_got, auth_ref, auth_got
        ):
            # Spec 1, 2, and 3.0 ignore a units.time label. The writer
            # records the natural unit and minor 1, which is the unit the
            # numbers already used.
            unit_row = _blank(
                "velocity_unit",
                "exact",
                "exact",
                citation=CITE_UNITS,
                detail=(
                    f"label {labels_ref!r} -> {labels_got!r}; "
                    f"authoritative {auth_ref!r} stays the natural unit"
                ),
            )
        elif labels_ref != labels_got:
            unit_row = _blank(
                "velocity_unit",
                "label_changed",
                "label_changed",
                citation=unit_cite or CITE_UNITS,
                detail=(
                    f"label {labels_ref!r} -> {labels_got!r}; "
                    f"authoritative {auth_ref!r} -> {auth_got!r}"
                ),
            )
        else:
            unit_row = _blank(
                "velocity_unit",
                "exact",
                "exact",
                citation=CITE_UNITS,
                detail=f"label {labels_ref!r}; authoritative {auth_ref!r}",
            )

    if frame_keys_ref == frame_keys_got and missing == 0:
        order_row = _blank(
            "frame_order",
            "exact",
            "exact",
            detail=f"{len(ref)} frames, positions matched in file order",
        )
    else:
        order_row = _blank(
            "frame_order",
            "mismatch",
            "mismatch",
            n_differ=missing or 1,
            detail=f"got {len(got)} frames, expected {len(ref)}",
        )
    return [id_row, mask_row, mass_row, cell_row, pos_row, vel_row, unit_row, order_row]


def _error_rows(detail: str, citation: str, reader: str, trip: str) -> list[dict]:
    rows = []
    for field in FIELDS:
        if field == "positional_zip_error":
            continue
        rows.append(_blank(field, reader, trip, detail=detail, citation=citation))
    return rows


def zip_case(path: Path) -> dict:
    import readcon

    frames = readcon.read_con(os.fspath(path))
    reactant, product = frames[0], frames[1]
    perm = [int(i) for i in readcon.atom_id_permutation(reactant, product)]
    ordered = readcon.reorder_like(reactant, product)
    zip_disp = np.asarray(product.xyz, dtype=np.float64) - np.asarray(
        reactant.xyz, dtype=np.float64
    )
    matched = np.asarray(
        readcon.minimum_image_displacements(reactant, product), dtype=np.float64
    )
    err = np.linalg.norm(zip_disp - matched, axis=1)
    ids = [int(atom.atom_id) for atom in reactant.atoms]
    oxygen = ids.index(2)
    c5 = ids.index(5)
    ordered_ids = [int(atom.atom_id) for atom in ordered.atoms]
    return {
        "max_A": float(np.max(err)),
        "c5_A": float(err[c5]),
        "oxygen_index_A": float(err[oxygen]),
        "oxygen_slot_norm_A": float(np.linalg.norm(zip_disp[oxygen])),
        "permutation": perm,
        "ordered_ids_match_reactant": ordered_ids == ids,
        "reactant_ids": ids,
        "product_ids": [int(atom.atom_id) for atom in product.atoms],
    }


def _zip_row(reference: dict, again: dict | None, citation: str) -> dict:
    if again is None:
        return _blank(
            "positional_zip_error",
            "not_representable",
            "not_representable",
            citation=citation,
            detail="column 5 did not survive, so atom_id_permutation has nothing to match",
            max_abs=reference["max_A"],
        )
    delta = abs(again["max_A"] - reference["max_A"])
    same_ids = again["reactant_ids"] == reference["reactant_ids"] and (
        again["product_ids"] == reference["product_ids"]
    )
    same_set = set(again["reactant_ids"]) == set(reference["reactant_ids"]) and set(
        again["product_ids"]
    ) == set(reference["product_ids"])
    if same_ids and delta == 0.0 and again["ordered_ids_match_reactant"]:
        status = "exact"
    elif same_ids and delta <= 1e-8:
        status = "within_tolerance"
    elif same_set and again["ordered_ids_match_reactant"]:
        status = "reordered"
    else:
        status = "mismatch"
    return _blank(
        "positional_zip_error",
        status,
        status,
        max_abs=again["max_A"],
        tolerance=1e-8,
        citation="" if status == "exact" else citation,
        detail=(
            f"max {again['max_A']:.6g} A, C5 {again['c5_A']:.6g} A, "
            f"oxygen index {again['oxygen_index_A']:.6g} A, "
            f"oxygen slot norm {again['oxygen_slot_norm_A']:.6g} A, "
            f"id_sequence_kept {same_ids}"
        ),
    )


class ToolError(Exception):
    def __init__(self, detail: str, citation: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.citation = citation


def _require_plugin(fmt: str) -> None:
    try:
        from ase.io.formats import ioformats
    except ModuleNotFoundError as exc:
        raise ToolError(f"ase did not import: {exc}") from exc
    try:
        found = ioformats[fmt]
    except KeyError as exc:
        raise ToolError(f"ase format {fmt} is not installed") from exc
    module = getattr(found, "module", "")
    name = getattr(module, "__name__", module)
    if name != "ase_readcon.io":
        raise ToolError(f"{fmt} resolved to {name!r}, not ase_readcon.io")


def _ase_record(atoms, ids_known: bool) -> dict:
    mask = np.zeros((len(atoms), 3), dtype=bool)
    for constraint in atoms.constraints:
        name = type(constraint).__name__
        index = np.asarray(getattr(constraint, "index", []))
        if name == "FixAtoms":
            if index.dtype == bool:
                mask[index] = True
            else:
                mask[np.asarray(index, dtype=int)] = True
        elif name == "FixCartesian":
            bit = np.asarray(constraint.mask, dtype=bool)
            mask[np.asarray(index, dtype=int).reshape(-1)] = bit
    ids = None
    if ids_known and "atom_id" in atoms.arrays:
        ids = [int(v) for v in np.asarray(atoms.arrays["atom_id"]).reshape(-1)]
    elif ids_known:
        ids_known = False
    symbols = list(atoms.get_chemical_symbols())
    pos = np.asarray(atoms.positions, dtype=np.float64)
    masses = np.asarray(atoms.get_masses(), dtype=np.float64)
    vel = None
    got = atoms.get_velocities()
    if got is not None:
        vel = np.asarray(got, dtype=np.float64)
    cellpar = np.asarray(atoms.cell.cellpar(), dtype=np.float64)
    atoms_out = []
    for i, symbol in enumerate(symbols):
        atoms_out.append(
            {
                "symbol": symbol,
                "atom_id": None if ids is None else ids[i],
                "fixed": [bool(bit) for bit in mask[i]],
                "mass": float(masses[i]),
                "pos": [float(v) for v in pos[i]],
                "vel": None if vel is None else [float(v) for v in vel[i]],
            }
        )
    info = dict(atoms.info)
    units = info.get("units") if isinstance(info.get("units"), dict) else {}
    spec = info.get("con_spec_version")
    minor = info.get("con_spec_minor")
    return {
        "cell": [float(v) for v in cellpar[:3]],
        "angles": [float(v) for v in cellpar[3:]],
        "atoms": atoms_out,
        "ids_known": ids is not None,
        "spec": int(spec) if spec is not None else 0,
        "minor": None if minor is None else int(minor),
        "time_label": units.get("time"),
    }


def _read_ase(path: Path, fmt: str):
    try:
        import ase.io
    except ModuleNotFoundError as exc:
        raise ToolError(f"ase did not import: {exc}") from exc

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        images = ase.io.read(os.fspath(path), index=":", format=fmt)
    if not isinstance(images, list):
        images = [images]
    notes = [str(item.message) for item in caught]
    return images, notes


def _write_ase(path: Path, images, fmt: str) -> list[str]:
    try:
        import ase.io
    except ModuleNotFoundError as exc:
        raise ToolError(f"ase did not import: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ase.io.write(os.fspath(path), images, format=fmt)
    return [str(item.message) for item in caught]


def eon_root() -> Path | None:
    env = os.environ.get("EON_ROOT", "")
    if env and (Path(env) / "eon" / "fileio.py").is_file():
        return Path(env)
    return None


def eon_commit() -> str:
    root = eon_root()
    if root is None or not (root / ".git").exists():
        return ""
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (done.stdout or "").strip()


_EON = None
_OBJECT_CACHE: dict[tuple[str, str], object] = {}


def eon_api():
    global _EON
    if _EON is not None:
        return _EON
    root = eon_root()
    if root is None:
        raise ToolError(
            "eon.fileio is not installed; set EON_ROOT to a checkout of eOn",
            CITE_EON_LOAD,
        )
    sys.path.insert(0, str(root))
    try:
        from eon.fileio import loadcons, savecon
        from eon.geometry.cell import box_to_length_angle
    except ModuleNotFoundError as exc:
        raise ToolError(
            f"eon.fileio did not import: {exc}",
            CITE_EON_LOAD,
        ) from exc
    _EON = (loadcons, savecon, box_to_length_angle)
    return _EON


def _eon_record(structure, box_to_length_angle) -> dict:
    lengths, angles = box_to_length_angle(structure.box)
    free = np.asarray(structure.free, dtype=np.float64)
    ids = [int(v) for v in np.asarray(structure.atom_ids).reshape(-1)]
    masses = np.asarray(structure.mass, dtype=np.float64)
    pos = np.asarray(structure.r, dtype=np.float64)
    vel = getattr(structure, "velocities", None)
    if vel is not None:
        vel = np.asarray(vel, dtype=np.float64)
    atoms = []
    for i, name in enumerate(structure.names):
        atoms.append(
            {
                "symbol": str(name),
                "atom_id": ids[i],
                "fixed": [bool(free[i, k] < 0.5) for k in range(3)],
                "mass": float(masses[i]),
                "pos": [float(v) for v in pos[i]],
                "vel": None if vel is None else [float(v) for v in vel[i]],
            }
        )
    return {
        "cell": [float(v) for v in lengths],
        "angles": [float(v) for v in angles],
        "atoms": atoms,
        "ids_known": True,
        "spec": 0,
        "minor": None,
        "time_label": None,
    }


def chemfiles_con_error(path: Path) -> str:
    try:
        import chemfiles
    except ModuleNotFoundError as exc:
        raise ToolError(f"chemfiles did not import: {exc}", CITE_CF) from exc

    chemfiles.set_warnings_callback(lambda _message: None)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            chemfiles.Trajectory(os.fspath(path), "r", "CON").read()
    except BaseException as exc:  # noqa: BLE001 - ChemfilesError is a BaseException
        return f"{type(exc).__name__}: {exc}"
    return ""


def _sorted_rows(frame: dict, key: str) -> np.ndarray:
    values = []
    for atom in frame["atoms"]:
        raw = atom[key]
        if raw is None:
            return np.zeros((0, 1))
        if isinstance(raw, (int, float)):
            values.append((float(raw),))
        else:
            values.append(tuple(float(item) for item in raw))
    return np.asarray(sorted(values), dtype=np.float64)


def _out_path(tool: str, name: str) -> Path:
    suffix = Path(name).suffix
    safe = tool.replace("/", "-")
    return WORK / "roundtrip" / f"{Path(name).stem}-{safe}{suffix}"


class Arms:
    """One read and one write per tool. The clocked helpers call these."""

    def __init__(self) -> None:
        self.cache: dict[tuple[str, str], object] = {}
        self.notes: list[str] = []

    def read_object(self, tool: str, name: str):
        path = fixture_path(name)
        if tool == "readcon":
            import readcon

            return readcon.read_con(os.fspath(path))
        if tool == "ase-readcon-con":
            _require_plugin("readcon-con")
            images, notes = _read_ase(path, "readcon-con")
            self.notes.extend(notes)
            return images
        if tool == "ase-readcon-convel":
            _require_plugin("readcon-convel")
            images, notes = _read_ase(path, "readcon-convel")
            self.notes.extend(notes)
            return images
        if tool == "ase-eon":
            try:
                images, notes = _read_ase(path, "eon")
            except Exception as exc:
                raise ToolError(
                    f"{type(exc).__name__}: {exc}", CITE_ASE_SECTION
                ) from exc
            self.notes.extend(notes)
            return images
        if tool == "eon-python":
            loadcons, _savecon, _box = eon_api()
            return loadcons(os.fspath(path))
        if tool == "chemfiles":
            message = chemfiles_con_error(path)
            raise ToolError(message or "chemfiles opened CON", CITE_CF)
        raise ToolError(f"unknown tool {tool}")

    def ensure(self, tool: str, name: str):
        key = (tool, name)
        if key not in self.cache:
            self.cache[key] = self.read_object(tool, name)
        return self.cache[key]

    def write_object(self, tool: str, name: str, obj, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Same open as a readcon write: drop the previous inode so create
        # does not wait on its writeback.
        dest.unlink(missing_ok=True)
        if tool == "readcon":
            import readcon

            readcon.write_con(os.fspath(dest), obj)
            return
        if tool in ("ase-readcon-con", "ase-readcon-convel", "ase-eon"):
            fmt = {
                "ase-readcon-con": "readcon-con",
                "ase-readcon-convel": "readcon-convel",
                "ase-eon": "eon",
            }[tool]
            notes = _write_ase(dest, obj, fmt)
            self.notes.extend(notes)
            return
        if tool == "eon-python":
            _loadcons, savecon, _box = eon_api()
            savecon(os.fspath(dest), obj[0], "w")
            for structure in obj[1:]:
                savecon(os.fspath(dest), structure, "a")
            return
        raise ToolError(f"{tool} has no CON writer", CITE_CF)


def tool_for(name: str, family: str) -> str:
    if family == "readcon":
        return "readcon"
    if family == "ase-readcon":
        if name.endswith(".convel"):
            return "ase-readcon-convel"
        return "ase-readcon-con"
    if family == "ase-eon":
        return "ase-eon"
    if family == "eon-python":
        return "eon-python"
    if family == "chemfiles":
        return "chemfiles"
    raise KeyError(family)


def reader_view(tool: str, obj) -> list[dict]:
    if tool == "readcon":
        return [record_from_readcon(frame) for frame in obj]
    if tool in ("ase-readcon-con", "ase-readcon-convel"):
        return [_ase_record(image, True) for image in obj]
    if tool == "ase-eon":
        return [_ase_record(image, False) for image in obj]
    if tool == "eon-python":
        _loadcons, _savecon, box_to_length_angle = eon_api()
        return [_eon_record(structure, box_to_length_angle) for structure in obj]
    raise ToolError(f"no reader view for {tool}")


def _flags(tool: str) -> dict:
    if tool == "readcon":
        return {
            "ids": True,
            "per_axis": True,
            "velocities": True,
            "unit": True,
            "id_cite": "",
            "mask_cite": "",
            "vel_cite": CITE_PARSE_VEL,
            "unit_cite": CITE_UNITS,
        }
    if tool == "ase-readcon-con":
        return {
            "ids": True,
            "per_axis": True,
            "velocities": False,
            "unit": False,
            "id_cite": CITE_PLUGIN_BULK,
            "mask_cite": "",
            "vel_cite": CITE_PLUGIN_CON,
            "unit_cite": CITE_PLUGIN_CON,
        }
    if tool == "ase-readcon-convel":
        return {
            "ids": True,
            "per_axis": True,
            "velocities": True,
            "unit": True,
            "id_cite": CITE_PLUGIN_BULK,
            "mask_cite": "",
            "vel_cite": CITE_TO_ASE,
            "unit_cite": CITE_FROM_ASE,
        }
    if tool == "ase-eon":
        return {
            "ids": False,
            "per_axis": False,
            "velocities": False,
            "unit": False,
            "id_cite": CITE_ASE_COL5,
            "mask_cite": CITE_ASE_COL4,
            "vel_cite": CITE_ASE_VEL,
            "unit_cite": CITE_ASE_VEL,
        }
    if tool == "eon-python":
        return {
            "ids": True,
            "per_axis": True,
            "velocities": True,
            "unit": False,
            "id_cite": CITE_EON_ORDER,
            "mask_cite": "",
            "vel_cite": CITE_EON_LOAD,
            "unit_cite": CITE_EON_UNIT,
        }
    return {
        "ids": False,
        "per_axis": False,
        "velocities": False,
        "unit": False,
        "id_cite": CITE_CF,
        "mask_cite": CITE_CF,
        "vel_cite": CITE_CF,
        "unit_cite": CITE_CF,
    }


def round_trip(arms: Arms, tool: str, name: str):
    """Return the reader view, the written records, and a write error.

    A write failure leaves the reader view in place. The caller records
    that view and marks the round-trip columns with the write error.
    """
    obj = arms.read_object(tool, name)
    view = reader_view(tool, obj)
    dest = _out_path(tool, name)
    try:
        arms.write_object(tool, name, obj, dest)
        written = read_readcon(dest)
    except ToolError as exc:
        return view, None, exc.detail
    except Exception as exc:  # noqa: BLE001 - the writer may raise its own type
        return view, None, f"write {type(exc).__name__}: {exc}"
    return view, written, None


def families() -> list[str]:
    return ["readcon", "ase-readcon", "ase-eon", "eon-python", "chemfiles"]


def run_fidelity() -> dict:
    import readcon

    arms = Arms()
    claisen = zip_case(fixture_path("claisen.con"))
    rows = []
    for name in FIXTURE_NAMES:
        reference = read_readcon(fixture_path(name))
        for family in families():
            tool = tool_for(name, family)
            flags = _flags(tool)
            tol = TOL[tool]
            try:
                if tool == "chemfiles":
                    raise ToolError(chemfiles_con_error(fixture_path(name)), CITE_CF)
                view, written, write_error = round_trip(arms, tool, name)
            except ToolError as exc:
                missing = (
                    "not installed" in exc.detail or "did not import" in exc.detail
                )
                trip = "unavailable" if missing else "not_representable"
                if not missing and tool != "chemfiles":
                    trip = "read_error"
                for row in _error_rows(exc.detail, exc.citation, trip, trip):
                    row["tool"] = tool
                    row["fixture"] = name
                    rows.append(row)
                rows.append(
                    {
                        **_blank(
                            "positional_zip_error",
                            trip,
                            trip,
                            detail=exc.detail,
                            citation=exc.citation,
                            max_abs=claisen["max_A"] if name == "claisen.con" else None,
                        ),
                        "tool": tool,
                        "fixture": name,
                    }
                )
                continue
            # Reader view and the written file are separate passes. The
            # table's reader column is the in-memory object. round_trip is
            # readcon's parse of what the tool wrote.
            reader_rows = compare_frames(reference, view, tol, **flags)
            if write_error:
                for row in reader_rows:
                    row["round_trip"] = "write_error"
                    row["detail"] = (
                        f"reader: {row['detail']}; round_trip: {write_error}"
                    )
                    row["tool"] = tool
                    row["fixture"] = name
                    rows.append(row)
                kept = any(
                    row["field"] == "atom_ids" and row["reader"] == "exact"
                    for row in reader_rows
                )
                rows.append(
                    {
                        **_blank(
                            "positional_zip_error",
                            "exact" if kept else "not_representable",
                            "write_error",
                            max_abs=claisen["max_A"] if name == "claisen.con" else None,
                            detail=write_error,
                            citation="" if kept else flags["id_cite"],
                        ),
                        "tool": tool,
                        "fixture": name,
                    }
                )
                continue
            # The written file is parsed by readcon, so a field that came
            # back is representable there even when the tool's object was not.
            file_flags = dict(flags)
            file_flags.update(ids=True, per_axis=True, velocities=True, unit=True)
            trip_rows = compare_frames(reference, written, tol, **file_flags)
            # ase-eon writes sequential ids even though the reader dropped
            # column 5. Judge the written ids on their own, with the writer cite.
            if tool == "ase-eon":
                for row in trip_rows:
                    if row["field"] == "atom_ids":
                        row["citation"] = CITE_ASE_ID_WRITE
                        row["round_trip"] = row["reader"]
                    if row["field"] == "fixed_mask":
                        row["citation"] = CITE_ASE_FIX
            for reader_row, trip_row in zip(reader_rows, trip_rows, strict=True):
                merged = dict(reader_row)
                merged["reader"] = reader_row["reader"]
                merged["round_trip"] = trip_row["round_trip"]
                if trip_row["max_abs"] is not None:
                    merged["max_abs"] = trip_row["max_abs"]
                cites = []
                for item in (reader_row["citation"], trip_row["citation"]):
                    if item and item not in cites:
                        cites.append(item)
                merged["citation"] = "; ".join(cites)
                merged["detail"] = (
                    f"reader: {reader_row['detail']}; round_trip: {trip_row['detail']}"
                )
                merged["tool"] = tool
                merged["fixture"] = name
                rows.append(merged)
            if name != "claisen.con":
                rows.append(
                    {
                        **_blank(
                            "positional_zip_error",
                            "absent",
                            "absent",
                            detail="the Claisen correspondence case is claisen.con",
                        ),
                        "tool": tool,
                        "fixture": name,
                    }
                )
                continue
            cite = flags["id_cite"]
            reader_zip = "exact" if flags["ids"] else "not_representable"
            try:
                again = zip_case(_out_path(tool, name))
            except Exception as exc:  # noqa: BLE001
                row = _blank(
                    "positional_zip_error",
                    reader_zip if flags["ids"] else "not_representable",
                    "mismatch",
                    max_abs=claisen["max_A"],
                    citation=cite,
                    detail=(
                        f"input max {claisen['max_A']:.6g} A, C5 {claisen['c5_A']:.6g} A, "
                        f"oxygen index {claisen['oxygen_index_A']:.6g} A; "
                        f"round-trip atom_id_permutation failed: {type(exc).__name__}: {exc}"
                    ),
                )
            else:
                row = _zip_row(claisen, again, cite)
                if not flags["ids"]:
                    row["reader"] = "not_representable"
                    row["citation"] = cite or row["citation"]
            row["tool"] = tool
            row["fixture"] = name
            rows.append(row)
    versions = _versions()
    return {
        "hardware": hardware(),
        "protocol": (
            "same input file for every tool; round_trip is readcon's parse "
            "of the file that tool wrote"
        ),
        "tolerances": TOL,
        "citations": {
            "ase_column_4": CITE_ASE_COL4,
            "ase_column_5": CITE_ASE_COL5,
            "ase_sections": CITE_ASE_SECTION,
            "chemfiles": CITE_CF,
            "eon_python": CITE_EON_LOAD,
            "eon_reorder": CITE_EON_ORDER,
            "eon_cpp_not_built": CITE_EON_CPP,
            "velocity_numbers": CITE_PARSE_VEL,
            "velocity_unit_rule": CITE_UNITS,
        },
        "claisen_positional_zip": claisen,
        "versions": versions,
        "notes": sorted(set(arms.notes)),
        "rows": rows,
        "readcon": readcon.__version__,
    }


def _module_version(name: str) -> str:
    try:
        module = __import__(name)
    except ModuleNotFoundError:
        return ""
    return str(getattr(module, "__version__", ""))


def _chemfiles_info() -> tuple[str, list[str], bool]:
    try:
        import chemfiles
    except ModuleNotFoundError:
        return "", [], False
    names = sorted(item.name for item in chemfiles.formats_list())
    has_con = any(name.upper() == "CON" for name in names)
    return str(getattr(chemfiles, "__version__", "")), names, has_con


def _versions() -> dict:
    import readcon

    chem_version, names, has_con = _chemfiles_info()
    return {
        "readcon": readcon.__version__,
        "ase": _module_version("ase"),
        "chemfiles": chem_version,
        "chemfiles_formats": names,
        "chemfiles_has_con": has_con,
        "numpy": np.__version__,
        "eon_commit": eon_commit(),
        "eon_root": str(eon_root() or ""),
        "eon_cpp": CITE_EON_CPP,
    }


def read_once(tool: str, name: str) -> None:
    Arms().read_object(tool, name)


def write_once(tool: str, name: str) -> None:
    key = (tool, name)
    if key not in _OBJECT_CACHE:
        _OBJECT_CACHE[key] = Arms().read_object(tool, name)
    dest = WORK / "timed" / f"{tool}-{name}"
    Arms().write_object(tool, name, _OBJECT_CACHE[key], dest)


def _time_call(fn) -> tuple[float, list[float]]:
    started = time.perf_counter()
    fn()
    warmup_s = time.perf_counter() - started
    samples = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return warmup_s, samples


def run_timing() -> dict:
    """Serial warmup plus six samples for every read and write that succeeds."""
    _threads()
    jobs = []
    for name in FIXTURE_NAMES:
        for family in ("readcon", "ase-readcon", "ase-eon", "eon-python"):
            tool = tool_for(name, family)
            for op, fn in (
                ("read", lambda tool=tool, name=name: read_once(tool, name)),
                ("write", lambda tool=tool, name=name: write_once(tool, name)),
            ):
                try:
                    if op == "write":
                        key = (tool, name)
                        if key not in _OBJECT_CACHE:
                            _OBJECT_CACHE[key] = Arms().read_object(tool, name)
                    warmup_s, samples = _time_call(fn)
                except Exception as exc:  # noqa: BLE001 - a writer raises its own type
                    if isinstance(exc, ToolError):
                        detail = exc.detail
                        citation = exc.citation
                    else:
                        detail = f"{type(exc).__name__}: {exc}"
                        citation = ""
                    if "not installed" in detail or "did not import" in detail:
                        status = "unavailable"
                    elif "can not find a format" in detail:
                        status = "not_representable"
                    elif op == "write":
                        status = "write_error"
                    else:
                        status = "read_error"
                    jobs.append(
                        {
                            "tool": tool,
                            "op": op,
                            "fixture": name,
                            "status": status,
                            "detail": detail,
                            "citation": citation,
                        }
                    )
                    continue
                jobs.append(
                    {
                        "tool": tool,
                        "op": op,
                        "fixture": name,
                        "status": "ok",
                        "warmup_s": warmup_s,
                        "n": REPEATS,
                        **stats(samples),
                    }
                )
    return {
        "hardware": hardware(),
        "protocol": f"serial, warmup {WARMUP}, samples {REPEATS}, percentile type 7",
        "versions": _versions(),
        "rows": jobs,
    }


def _csv_fidelity(path: Path, rows: list[dict]) -> None:
    fields = [
        "tool",
        "fixture",
        "field",
        "reader",
        "round_trip",
        "max_abs",
        "n_differ",
        "tolerance",
        "detail",
        "citation",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _csv_timing(path: Path, rows: list[dict]) -> None:
    fields = [
        "tool",
        "op",
        "fixture",
        "status",
        "median_s",
        "iqr_s",
        "q25_s",
        "q75_s",
        "warmup_s",
        "n",
        "detail",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _log_timing(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"hardware {payload['hardware']}",
        payload["protocol"],
        f"eon_commit {payload['versions'].get('eon_commit', '')}",
    ]
    for row in payload["rows"]:
        if row.get("status") != "ok":
            lines.append(
                f"skip tool={row['tool']} op={row['op']} fixture={row['fixture']} "
                f"status={row['status']} detail={row.get('detail', '')}"
            )
            continue
        lines.append(
            f"warmup tool={row['tool']} op={row['op']} fixture={row['fixture']} "
            f"warmup_s={row['warmup_s']:.9e}"
        )
        for sample in row["samples_s"]:
            lines.append(
                f"sample tool={row['tool']} op={row['op']} fixture={row['fixture']} "
                f"sample_s={sample:.9e}"
            )
        lines.append(
            f"summary tool={row['tool']} op={row['op']} fixture={row['fixture']} "
            f"median_s={row['median_s']:.9e} iqr_s={row['iqr_s']:.9e}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(fidelity: dict, timing: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "fidelity.json").write_text(
        json.dumps(fidelity, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "timing.json").write_text(
        json.dumps(timing, indent=2) + "\n", encoding="utf-8"
    )
    _csv_fidelity(RESULTS / "fidelity.csv", fidelity["rows"])
    _csv_timing(RESULTS / "timing.csv", timing["rows"])
    _log_timing(LOGS / "timing.log", timing)


def main(argv: list[str] | None = None) -> None:
    _pin()
    _threads()
    WORK.mkdir(parents=True, exist_ok=True)
    args = list(sys.argv[1:] if argv is None else argv)
    which = args[0] if args else "all"
    if which in ("fidelity", "all"):
        fidelity = run_fidelity()
    else:
        fidelity = json.loads((RESULTS / "fidelity.json").read_text(encoding="utf-8"))
    if which in ("timing", "all"):
        timing = run_timing()
    else:
        timing = json.loads((RESULTS / "timing.json").read_text(encoding="utf-8"))
    if which == "read-once":
        read_once(args[1], args[2])
        return
    if which == "write-once":
        write_once(args[1], args[2])
        return
    write_outputs(fidelity, timing)
    print(f"wrote {RESULTS / 'fidelity.csv'}")
    print(f"wrote {RESULTS / 'timing.csv'}")


if __name__ == "__main__":
    main()
