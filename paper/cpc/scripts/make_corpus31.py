#!/usr/bin/env python3
"""Write the CON 3.1 corpus paper/cpc/data/corpus31/ from explicit bytes.

No readcon writer is used: every file is the literal text below, wrapped in
gzip or zstd here where the name says so. manifest.toml gives per file the
expected outcome, the frame count of an accepted file or the error class and
1-based line of a rejected one, the clauses of docs/orgmode/spec.org that
decide it, the basis of the expectation and the reason. Every cited clause
must exist in that document; the script stops otherwise.

Optional keys: rewrite (the binding rewrite, write_con_string, keeps
con_spec_version, con_spec_minor and units of every frame of major 3 that
declares con_spec_minor or whose velocities carry a units.time label, which
pins the rewrite to minor 0, and writes a frame of major 1 or 2 as major 3
with every unit it declares and the same fields; a 3.0 frame with neither
comes back at minor 1, and no file with the key holds one), pbc (the
periodicity a reader reports for the first frame) and time_unit_override (the
first frame's velocities are read in the natural time unit although
units.time names another unit; read_con and iter_con do not warn, and the
conversion to ASE, ConFrame.to_ase or read_con_as_ase, warns that the label
is not applied).

Usage: make_corpus31.py [--out DIR] [--spec FILE]
"""

import argparse
import gzip
import json
import re
import shutil
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "corpus31"
SPEC = ROOT.parents[1] / "docs" / "orgmode" / "spec.org"
READER_MINOR = 1

BASES = {
    "explicit": "the clauses decide the outcome and, for a rejection, the class, by name or through the error table",
    "class-open": "the clauses require the rejection and name no class; the entry records the class the reader reports",
    "optional": "a MAY or SHOULD clause allows the outcome; the entry records the reader's choice",
    "open": "no clause decides the file, or two clauses name different classes; the reason gives the reading the "
    "reader follows",
}

NATURAL = "(amu*angstrom^2/eV)^0.5"
U31 = '"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}'
U31_NATURAL = '"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"(amu*angstrom^2/eV)^0.5"}'
U30 = '"units":{"length":"angstrom","energy":"eV","mass":"amu"}'
M31 = '"con_spec_version":3,"con_spec_minor":1'
M32 = '"con_spec_version":3,"con_spec_minor":2'
M33 = '"con_spec_version":3,"con_spec_minor":3'
PT2 = (
    "1\n2\n195.084\nPt\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n2.5 2.5 0.0 0 1\n"
)
PT1 = "1\n1\n195.084\nPt\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n"
PT_H = (
    "2\n1 1\n1.00794 195.084\nH\nCoordinates of Component 1\n2.5 2.5 0.0 0 0\n"
    "Pt\nCoordinates of Component 2\n0.0 0.0 0.0 0 1\n"
)
VEL2 = "\nPt\nVelocities of Component 1\n0.01 0.0 0.0 0 0\n0.0 -0.02 0.0 0 1\n"
FORCES2 = "\nPt\nForces of Component 1\n0.1 0.0 0.0 0 0\n0.0 0.2 0.0 0 1\n"
STRESS2 = "\nPt\nStress of Component 1\n1.0 2.0 3.0 4.0 5.0 6.0 0 0\n1.0 2.0 3.0 4.0 5.0 6.0 0 1\n"
MASKS8 = (
    "1\n8\n195.084\nPt\nCoordinates of Component 1\n"
    "0.0 0.0 0.0 0 0\n1.0 0.0 0.0 1 1\n2.0 0.0 0.0 2 2\n3.0 0.0 0.0 3 3\n"
    "4.0 0.0 0.0 4 4\n5.0 0.0 0.0 5 5\n6.0 0.0 0.0 6 6\n7.0 0.0 0.0 7 7\n"
)
IDS = (
    "2\n2 2\n195.084 1.00794\nPt\nCoordinates of Component 1\n"
    "{0} 0.0 0.0 0 41\n2.5 2.5 0.0 3 9007199254740993\n"
    "H\nCoordinates of Component 2\n1.0 1.0 1.0 7 18446744073709551615\n1.5 1.0 1.0 0 7\n"
)
MIXED_IDS = "1\n3\n195.084\nPt\nCoordinates of Component 1\n0.0 0.0 0.0 0 7\n1.0 0.0 0.0 0\n2.0 0.0 0.0 0 9\n"
FLOATS = (
    "1\n4\n195.084\nPt\nCoordinates of Component 1\n"
    "+1. .5 -0.0 0 0\n"
    "1E+01 2.5e-3 0.30000000000000004441 0 1\n"
    "3.141592653589793238462643383279 1e-400 -.25e2 0 2\n"
    "2.2250738585072011e-308 4.9406564584124654e-324 9007199254740993 0 3\n"
)

# Reproducers from the round-2 reports, byte for byte.
B_F20 = (
    'Random Number Seed\n{"con_spec_version": 3, "sections": ["velocities"], "units": {"energy": "eV", '
    '"length": "angstrom", "mass": "amu", "time": "fs"}}\n15.345600\t21.702000\t100.000000\n'
    "90.000000\t90.000000\t90.000000\n0 0\n218 0 1\n2\n2 2\n63.546000 1.007930\nCu\nCoordinates of Component 1\n"
    "   0.639400    0.904500    6.975300 7    0\n   3.196900    0.904500    6.975300 7    1\nH\n"
    "Coordinates of Component 2\n   8.682300    9.947000   11.733000 0  2\n"
    "   7.942100    9.947000   11.733000 0  3\n\nCu\nVelocities of Component 1\n"
    "   0.001234    0.002345   -0.003456 7    0\n   0.004567   -0.005678    0.006789 7    1\nH\n"
    "Velocities of Component 2\n  -0.012345    0.023456    0.034567 0  2\n"
    "   0.045678   -0.056789   -0.067890 0  3\n"
).encode()
B_F26 = (
    'PREBOX1\n{"con_spec_version":2,"sections":[],"validate":true}\n10.0 10.0 10.0\n10.0 10.0 170.0\n'
    "POSTBOX1\nPOSTBOX2\n1\n1\n63.546\nCu\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n"
).encode()
F27_META = (
    '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu",'
    '"time":"fs"},"sections":[]}'
)
B_F27 = (
    "\n".join(
        [
            "probe1",
            F27_META,
            "10 10 10",
            "90 90 90",
            "0 0",
            "0 0 0",
            "1",
            "2",
            "195.084",
            "Pt",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0",
            "2.5 2.5 0.0 0",
            "probe2",
            F27_META,
            "10 10 10",
            "90 90 90",
            "0 0",
            "0 0 0",
            "1",
            "2",
            "195.084",
            "Pt",
            "Coordinates of Component 1",
            "2.5 2.5 0.0 0",
            "0.0 0.0 0.0 0",
        ]
    )
    + "\n"
).encode()
EMPTY_SECTIONS_VELOCITY = (
    'frame1\n{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},'
    '"sections":[]}\n10 10 10\n90 90 90\na\nb\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 1\n\n'
    "H\nVelocities of Component 1\n0 0 0 0 1\n"
)
LEGAL_V2 = (
    'probe\n{"con_spec_version":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n63.546\nCu\n'
    "Coordinates of Component 1\n0.0 0.0 0.0 7 0\n"
)
BAD_V2 = (
    'probe\n{"con_spec_version":2,"sections":[]}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n63.546\nCu\n'
    "Coordinates of Component 1\n0.0 0.0 0.0 7 0\n\nCu\nVelocities of Component 1\n0.5 0.5 0.5 7 0\n"
)
PROBE_UNITS = {"length": "angstrom", "energy": "eV"}
PROBE_M31 = {"con_spec_version": 3, "con_spec_minor": 1}
PROBE_VEL = "\nH\nVelocities of Component 1\n0.1 0 0 0 0\n0 0.1 0 0 1\n"


def con(
    title: str,
    meta: str,
    body: str = PT2,
    tail: str = "",
    angles: str = "90.0 90.0 90.0",
) -> bytes:
    return (
        f"{title}\n{meta}\n10.0 10.0 10.0\n{angles}\n0 0\n0 0 0\n{body}{tail}".encode()
    )


def obj(*members: str) -> str:
    return "{" + ",".join(members) + "}"


def probe(
    meta,
    l4: str = "90.0 90.0 90.0",
    rows=("0.0 0.0 0.0 0 0", "1.0 1.0 1.0 0 1"),
    extra: str = "",
) -> bytes:
    """The frame of the round-2 acceptor probes D1-D15: two H atoms on lines 12 and 13."""
    m = meta if isinstance(meta, str) else json.dumps(meta, separators=(",", ":"))
    return (
        "\n".join(
            [
                "gen",
                m,
                "10.0 10.0 10.0",
                l4,
                "",
                "",
                "1",
                "2",
                "1.0",
                "H",
                "Coordinates of Component 1",
                *rows,
            ]
        )
        + "\n"
        + extra
    ).encode()


def probe_energies(symbol: str) -> str:
    return f"\n{symbol}\nEnergies of Component 1\n-1.0 0 0\n-2.0 0 1\n"


def deep(levels: int) -> str:
    return '{"con_spec_version":2,"x":' + "[" * levels + "]" * levels + "}"


def gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6, mtime=0)


def zst(data: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=3).compress(data)


CASES: list[dict] = []


def accept(
    name: str, data: bytes, frames: int, clause: str, basis: str, reason: str, **extra
) -> None:
    CASES.append(
        {
            "file": name,
            "data": data,
            "expected": "accept",
            "frames": frames,
            "clause": clause,
            "basis": basis,
            "reason": reason,
            **extra,
        }
    )


def reject(
    name: str, data: bytes, error: str, line: int, clause: str, basis: str, reason: str
) -> None:
    CASES.append(
        {
            "file": name,
            "data": data,
            "expected": "reject",
            "error": error,
            "line": line,
            "clause": clause,
            "basis": basis,
            "reason": reason,
        }
    )


S31 = obj(M31, U31, '"sections":[]')
V31 = obj(M31, U31, '"sections":["velocities"]')
V31_VALIDATE = obj(M31, U31, '"sections":["velocities"]', '"validate":true')
BASE = con("corpus31 minor-1 header with units.time", S31)
BASE_B = con("corpus31 second frame", S31)
CONVEL_FS = con("corpus31 minor-1 convel, time fs", V31, tail=VEL2)
CONVEL_FS_B = con("corpus31 second convel frame", V31, tail=VEL2)
REPEATED = con(
    "corpus31 repeated ids",
    S31,
    body=PT2.replace(" 0 0\n", " 0 5\n").replace(" 0 1\n", " 0 5\n"),
)
SPACES_TABS = (
    "The reader takes white space inside a line to be spaces and tabs, the separators of CON-token.3 and "
    "the trailing characters of CON-file.4; the text does not define whitespace or blank otherwise."
)
BLANK = (
    "The reader takes a line of Unicode White_Space characters to be blank before a section or a legacy "
    "velocity block. The ignored end of the file is one such line, then lines of spaces, tabs, form feeds and "
    "carriage returns only. The text does not define whitespace or blank otherwise."
)

# ---------------------------------------------------------------- units and velocities

accept(
    "v31_units_time.con",
    BASE,
    1,
    "CON-line2.9, CON-units.1, CON-units.2",
    "explicit",
    "Minor 1 header whose units carry length, energy, mass and time (fs).",
)
accept(
    "v31_convel_natural.convel",
    con(
        "corpus31 minor-1 convel, natural time",
        obj(M31, U31_NATURAL, '"sections":["velocities"]'),
        tail=VEL2,
    ),
    1,
    "CON-units.5, CON-units.10",
    "explicit",
    "Minor 1 velocities section with units.time spelled (amu*angstrom^2/eV)^0.5.",
)
accept(
    "v31_convel_fs.convel",
    CONVEL_FS,
    1,
    "CON-units.10",
    "explicit",
    "Minor 1 velocities section with units.time fs, which is authoritative from minor 1. The reference writer's "
    "rewrite keeps minor 1 and fs.",
    rewrite=True,
)
reject(
    "v31_convel_no_time.convel",
    con(
        "corpus31 minor-1 convel, no time",
        obj(M31, U30, '"sections":["velocities"]'),
        tail=VEL2,
    ),
    "InvalidUnits",
    2,
    "CON-units.11",
    "explicit",
    "Minor 1 frame whose line 2 declares a velocities section and carries no units.time.",
)
accept(
    "v31_legacy_velocity_time.convel",
    con("corpus31 minor-1 legacy velocity block, time fs", obj(M31, U31), tail=VEL2),
    1,
    "CON-section.1, CON-frame.7, CON-units.10",
    "explicit",
    "No sections key: the blank line that begins a complete velocity block opens the legacy velocity section "
    "(Sections), whose velocities are in units.time fs.",
)
reject(
    "v31_legacy_velocity_no_time.convel",
    con("corpus31 minor-1 legacy velocity block, no time", obj(M31, U30), tail=VEL2),
    "InvalidUnits",
    14,
    "CON-section.1, CON-units.11",
    "explicit",
    "No sections key and no units.time at minor 1. The blank line 14 begins a complete velocity block, so the "
    "frame has a velocities section from that line and fails CON-units.11 there.",
)
accept(
    "v30_convel_fs.convel",
    con(
        "corpus31 3.0 convel labelled fs",
        obj('"con_spec_version":3', U31, '"sections":["velocities"]'),
        tail=VEL2,
    ),
    1,
    "CON-units.8, CON-units.9",
    "explicit",
    "Version 3.0 velocities labelled time fs are read in angstrom per natural time unit and the label is not "
    "applied; the conversion to ASE warns that it is not. The reference writer's rewrite keeps version 3.0 and "
    "the fs label.",
    rewrite=True,
    time_unit_override=True,
)
accept(
    "v30_convel_fs_validate.convel",
    con(
        "corpus31 3.0 convel labelled fs, validate true",
        obj(
            '"con_spec_version":3', U31, '"sections":["velocities"]', '"validate":true'
        ),
        tail=VEL2,
    ),
    1,
    "CON-units.9, CON-validate.4",
    "explicit",
    "The 3.0 frame labelled fs with validate true: CON-validate.4 adds no time-unit check, and the velocities "
    "are read in the natural time unit; the conversion to ASE warns that the fs label is not applied.",
    time_unit_override=True,
)
accept(
    "v30_legacy_velocity_time_fs.convel",
    con(
        "corpus31 3.0 legacy velocity block labelled fs",
        obj('"con_spec_version":3', U31),
        tail=VEL2,
    ),
    1,
    "CON-section.1, CON-units.8, CON-units.9",
    "explicit",
    "A 3.0 legacy velocity block under units.time fs is read in the natural time unit; the conversion to ASE "
    "warns that the fs label is not applied.",
    time_unit_override=True,
)
accept(
    "v2_convel_time_fs.convel",
    con(
        "corpus31 version 2 convel labelled fs",
        obj(
            '"con_spec_version":2', '"units":{"time":"fs"}', '"sections":["velocities"]'
        ),
        tail=VEL2,
    ),
    1,
    "CON-units.7, CON-units.8, CON-units.9",
    "explicit",
    "Version 2 velocities labelled time fs are read in the natural time unit; the conversion to ASE warns that "
    "the fs label is not applied. A binding rewrite writes major 3 at minor 0, where the fs label is kept and not applied, so the velocities stay in "
    "the natural unit.",
    rewrite=True,
    time_unit_override=True,
)
accept(
    "f20_v30_time_fs.convel",
    B_F20,
    1,
    "CON-units.8, CON-units.9",
    "explicit",
    "Round-2 report B, item F20: resources/test/tiny_cuh2.convel with line 2 set to version 3.0, a velocities "
    "section and units.time fs. The read applies the natural time unit, the conversion to ASE warns that the "
    "fs label is not applied, and the rewrite keeps version 3.0 and the fs label.",
    rewrite=True,
    time_unit_override=True,
)
accept(
    "v1_convel.convel",
    con(
        "corpus31 version 1 convel",
        "0.0000 TIME",
        body=PT2.replace("2.5 2.5 0.0 0 1", "2.5 2.5 0.0 1 1"),
        tail=VEL2.replace("0.0 -0.02 0.0 0 1", "0.0 -0.02 0.0 1 1"),
    ),
    1,
    "CON-status.2, CON-section.1, CON-units.8",
    "explicit",
    "Implicit version 1 (line 2 not JSON) eOn convel with the legacy velocity block, read in the natural time "
    "unit.",
)
accept(
    "v2_minor1_velocity_no_time.convel",
    con(
        "corpus31 major 2 minor 1 velocities, no units",
        obj('"con_spec_version":2', '"con_spec_minor":1', '"sections":["velocities"]'),
        tail=VEL2,
    ),
    1,
    "CON-units.8, CON-units.11",
    "open",
    "Major 2 with con_spec_minor 1. CON-units.8 reads version 2 velocities in the natural time unit, and "
    "CON-units.11 rejects a frame of minor 1 or later without units.time. The reader takes a minor to refine "
    "major 3 only, so it reads the velocities in the natural time unit.",
)
accept(
    "v31_kcal_per_mol.con",
    con(
        "corpus31 energy kcal/mol",
        obj(M31, '"units":{"length":"angstrom","energy":"kcal/mol"}', '"sections":[]'),
    ),
    1,
    "CON-units.1, CON-units.16",
    "explicit",
    "mol is a count, so kcal/mol is an energy.",
)
accept(
    "v31_units_compound.convel",
    con(
        "corpus31 compound units",
        obj(
            M31,
            '"units":{"length":"nm","energy":"kJ / mol","mass":"kg/mol","time":"ps","velocity":"nm/ps",'
            '"force":"kJ/(mol*nm)"}',
            '"sections":["velocities"]',
        ),
        tail=VEL2,
    ),
    1,
    "CON-units.1, CON-units.2, CON-units.16",
    "open",
    "Products, quotients and parentheses of the matching dimensions (Units). The energy is written kJ / mol; "
    "the text does not say whether white space may stand inside an expression, and the reader removes it.",
)
reject(
    "v31_length_area.con",
    con(
        "corpus31 units.length angstrom^2",
        obj(M31, '"units":{"length":"angstrom^2","energy":"eV"}', '"sections":[]'),
    ),
    "InvalidUnits",
    2,
    "CON-units.1",
    "explicit",
    "units.length angstrom^2 is an area, not a length.",
)
reject(
    "v31_units_string.con",
    con("corpus31 units string", obj(M31, '"units":"angstrom"', '"sections":[]')),
    "InvalidUnits",
    2,
    "CON-units.1",
    "explicit",
    "units is a string, so the frame has no units.length and no units.energy.",
)
reject(
    "v31_mass_ev.con",
    con(
        "corpus31 units.mass eV",
        obj(
            M31,
            '"units":{"length":"angstrom","energy":"eV","mass":"eV","time":"fs"}',
            '"sections":[]',
        ),
    ),
    "InvalidUnits",
    2,
    "CON-units.2",
    "explicit",
    "units.mass eV is an energy, not a mass.",
)
reject(
    "v2_time_banana.con",
    con(
        "corpus31 version 2 units.time banana",
        obj('"con_spec_version":2', '"units":{"time":"banana"}'),
    ),
    "InvalidUnits",
    2,
    "CON-units.2, CON-units.7",
    "explicit",
    "Version 2 may carry units, and a present units.time must be a time; banana is no unit expression.",
)

# ---------------------------------------------------------------- columns 4 and 5

accept(
    "v31_masks_0to7.con",
    con("corpus31 masks 0-7", S31, body=MASKS8),
    1,
    "CON-mask.4",
    "explicit",
    "Column 4 values 0 through 7 read as the x, y, z bitmask.",
)
reject(
    "v31_mask_8.con",
    con("corpus31 mask 8", S31, body=PT2.replace("2.5 2.5 0.0 0 1", "2.5 2.5 0.0 8 1")),
    "InvalidFixedFlag",
    13,
    "CON-mask.5, CON-error.3",
    "explicit",
    "Column 4 value 8 is InvalidFixedFlag in every mode, validate absent.",
)
reject(
    "v31_mask_float.con",
    con(
        "corpus31 mask 7.0",
        S31,
        body=PT2.replace("2.5 2.5 0.0 0 1", "2.5 2.5 0.0 7.0 1"),
    ),
    "InvalidFixedFlag",
    13,
    "CON-mask.5",
    "explicit",
    "A float spelling of column 4 is InvalidFixedFlag in every mode.",
)
accept(
    "v31_ids_beyond_binary64.con",
    con("corpus31 large ids frame 1", S31, body=IDS.format("0.0"))
    + con("corpus31 large ids frame 2", S31, body=IDS.format("0.25")),
    2,
    "CON-id.1, CON-id.6",
    "explicit",
    "Two frames carrying the same out-of-order ids, including 2^53+1 and 2^64-1, which binary64 cannot hold.",
)
accept(
    "v31_repeated_ids.con",
    REPEATED,
    1,
    "CON-id.4",
    "explicit",
    "Two atoms share id 5 and validate is absent, so the frame is read.",
)
accept(
    "v32_repeated_ids.con",
    REPEATED.replace(b'"con_spec_minor":1', b'"con_spec_minor":2'),
    1,
    "CON-id.4, CON-line2.7",
    "explicit",
    "Two atoms share id 5 in a minor-2 frame without validate.",
)
accept(
    "v31_validate_repeated_ids.con",
    REPEATED.replace(b'"sections":[]', b'"sections":[],"validate":true'),
    1,
    "CON-id.4, CON-validate.4",
    "explicit",
    "The repeated ids with validate true: CON-validate.4 has no id-uniqueness check, and CON-id.4 accepts them.",
)
accept(
    "v32_validate_repeated_ids.con",
    REPEATED.replace(b'"con_spec_minor":1', b'"con_spec_minor":2').replace(
        b'"sections":[]', b'"sections":[],"validate":true'
    ),
    1,
    "CON-id.4, CON-line2.7, CON-validate.4",
    "explicit",
    "The repeated ids at minor 2 with validate true are accepted as at minor 1.",
)
accept(
    "v31_mixed_ids.con",
    con("corpus31 mixed ids", S31, body=MIXED_IDS),
    1,
    "CON-id.9",
    "explicit",
    "Minor 1: the middle row has no column 5 and takes its 0-based position in the frame, so the ids read 7, 1, 9.",
)
accept(
    "v32_mixed_ids.con",
    con("corpus31 mixed ids, minor 2", obj(M32, U31, '"sections":[]'), body=MIXED_IDS),
    1,
    "CON-id.9, CON-line2.7",
    "explicit",
    "Minor 2: the 4-column middle row takes its 0-based position as its id, as at minor 1.",
)
reject(
    "v31_id_2pow64.con",
    con(
        "corpus31 id 2^64",
        S31,
        body=PT2.replace("2.5 2.5 0.0 0 1", "2.5 2.5 0.0 0 18446744073709551616"),
    ),
    "InvalidNumberFormat",
    13,
    "CON-id.1, CON-error.3",
    "explicit",
    "Column 5 must be an integer in 0 through 2^64-1; 2^64 is InvalidNumberFormat.",
)
accept(
    "f27_minor1_no_ids.con",
    B_F27,
    2,
    "CON-id.9",
    "explicit",
    "Round-2 report B, item F27: two minor-1 frames of two Pt atoms with 4-column rows in swapped order; each row "
    "takes its 0-based position as its id.",
)
accept(
    "f27_minor2_no_ids.con",
    B_F27.replace(b'"con_spec_minor":1', b'"con_spec_minor":2'),
    2,
    "CON-id.9, CON-line2.7",
    "explicit",
    "The item F27 frames with con_spec_minor 2: each 4-column row takes its 0-based position as its id.",
)
V32_VALIDATE = obj(M32, U31, '"sections":[]', '"validate":true')
accept(
    "v31_validate_count_change.con",
    con("corpus31 validate, 2 atoms", obj(M31, U31, '"sections":[]', '"validate":true'))
    + con(
        "corpus31 validate, 1 atom",
        obj(M31, U31, '"sections":[]', '"validate":true'),
        body=PT1,
    ),
    2,
    "CON-count.7, CON-validate.4",
    "explicit",
    "Two validated minor-1 frames of 2 and 1 atoms: each frame declares its own count, and CON-validate.4 "
    "has no check across frames.",
)
accept(
    "v32_validate_count_change.con",
    con("corpus31 reference frame, minor 1, validate absent", S31)
    + con("corpus31 validate, minor 2, 1 atom", V32_VALIDATE, body=PT1),
    2,
    "CON-count.7, CON-line2.7, CON-validate.4",
    "explicit",
    "A minor-2 validated frame of 1 atom after a frame of 2 atoms is read like its minor-1 counterpart.",
)
accept(
    "v31_validate_symbol_change.con",
    con(
        "corpus31 validate, Pt ids 0 and 1",
        obj(M31, U31, '"sections":[]', '"validate":true'),
    )
    + con(
        "corpus31 validate, id 0 is H",
        obj(M31, U31, '"sections":[]', '"validate":true'),
        body=PT_H,
    ),
    2,
    "CON-validate.4",
    "explicit",
    "Id 0 is Pt in frame 1 and H in frame 2 with validate true: CON-validate.4 has no check across frames.",
)
accept(
    "v32_validate_symbol_change.con",
    con("corpus31 validate, minor 2, Pt ids 0 and 1", V32_VALIDATE)
    + con("corpus31 validate, minor 2, id 0 is H", V32_VALIDATE, body=PT_H),
    2,
    "CON-line2.7, CON-validate.4",
    "explicit",
    "Id 0 is Pt in frame 1 and H in frame 2 at minor 2 with validate true is read like its minor-1 counterpart.",
)

# ---------------------------------------------------------------- sections

reject(
    "v31_unknown_section.con",
    con(
        "corpus31 minor-1 unknown section with section_arity",
        obj(M31, U31, '"sections":["forces","stress"]', '"section_arity":{"stress":6}'),
        tail=FORCES2 + STRESS2,
    ),
    "UnknownSection",
    2,
    "CON-section.7",
    "explicit",
    "Frame minor 1 is not newer than the reader's minor 1, so the unknown section stress is UnknownSection even "
    "with section_arity.",
)
accept(
    "v32_unknown_section_arity.con",
    con(
        "corpus31 minor-2 unknown section with section_arity",
        obj(M32, U31, '"sections":["forces","stress"]', '"section_arity":{"stress":6}'),
        tail=FORCES2 + STRESS2,
    ),
    1,
    "CON-line2.7, CON-section.8, CON-section.14",
    "optional",
    "Frame minor 2 is newer than the reader's minor 1 and section_arity gives stress 6 value fields, so the "
    "reader may skip the stress section, and it does.",
)
accept(
    "v33_unknown_section_arity.con",
    con(
        "corpus31 minor-3 unknown section with section_arity",
        obj(M33, U31, '"sections":["forces","stress"]', '"section_arity":{"stress":6}'),
        tail=FORCES2 + STRESS2,
    ),
    1,
    "CON-line2.7, CON-section.8, CON-section.14",
    "optional",
    "Frame minor 3 is newer than the reader's minor 1 and section_arity gives stress 6 value fields, so the "
    "reader may skip the stress section, and it does.",
)
reject(
    "v33_unknown_section_no_arity.con",
    con(
        "corpus31 minor-3 unknown section without section_arity",
        obj(M33, U31, '"sections":["forces","stress"]'),
        tail=FORCES2 + STRESS2,
    ),
    "UnknownSection",
    2,
    "CON-section.9",
    "explicit",
    "Frame minor 3 is newer than the reader's minor 1, but section_arity does not give the stress arity.",
)
reject(
    "v31_reserved_arity_wrong.con",
    con(
        "corpus31 section_arity for a reserved section",
        obj(M31, U31, '"sections":["forces"]', '"section_arity":{"forces":1}'),
        tail=FORCES2,
    ),
    "InvalidVectorLength",
    2,
    "CON-section.13",
    "explicit",
    "A section_arity entry for the reserved vector section forces must be 3.",
)
reject(
    "v31_two_blanks_before_section.convel",
    con("corpus31 two blank lines before a section", V31, tail="\n" + VEL2),
    "IncompleteSection",
    16,
    "CON-section.2, CON-section.4, CON-section.15",
    "class-open",
    "Two blank lines before the velocities section: the first opens it, the second is its symbol line, and the "
    "line Pt fails as its label. Outside validate true no clause names the class of a wrong label; the reader "
    "reports the declared section as missing.",
)
accept(
    "v31_unicode_blank_before_section.convel",
    con("corpus31 U+2003 line before a section", V31, tail="\u2003" + VEL2),
    1,
    "CON-section.2, CON-file.4",
    "open",
    "The line before the velocities section holds U+2003 only. "
    + BLANK
    + " So the line is blank and opens the "
    "declared section.",
)
reject(
    "v31_spreads_negative.con",
    con(
        "corpus31 negative spread",
        obj(M31, U31, '"sections":["spreads"]'),
        tail="\nPt\nSpreads of Component 1\n-0.1 0.0 0.0 0 0\n0.0 0.0 0.0 0 1\n",
    ),
    "ValidationError",
    17,
    "CON-section.20",
    "class-open",
    "Each spreads value must be >= 0 in every mode; the clause names no class, and the reader reports "
    "ValidationError.",
)
reject(
    "v31_velocity_no_id.convel",
    con(
        "corpus31 velocity rows without id",
        V31,
        tail=VEL2.replace(" 0 0\n", " 0\n").replace(" 0 1\n", " 0\n"),
    ),
    "InvalidVectorLength",
    17,
    "CON-num.9",
    "explicit",
    "The coordinate rows carry ids, and identity columns repeat the coordinate flag and id (Sections), so a "
    "4-field velocity row has the wrong number of fields.",
)
accept(
    "v31_validate_ok.convel",
    con("corpus31 validate true", V31_VALIDATE, tail=VEL2),
    1,
    "CON-validate.4",
    "explicit",
    "validate true with matching labels, symbols and identity columns.",
)
reject(
    "v31_validate_bad_label.convel",
    con(
        "corpus31 validate true, bad section label",
        V31_VALIDATE,
        tail=VEL2.replace("Velocities of", "Velocity of"),
    ),
    "ValidationError",
    16,
    "CON-section.15, CON-validate.4",
    "explicit",
    "validate true and the velocities label reads Velocity of Component 1: a section label mismatch in that "
    "mode is ValidationError.",
)
accept(
    "v31_label_case.convel",
    con(
        "corpus31 validate true, label case and spaces",
        V31_VALIDATE,
        tail=VEL2.replace("Velocities of Component 1", "VELOCITIES   of  component 1"),
    ),
    1,
    "CON-file.5, CON-section.15",
    "explicit",
    "Labels compare case-insensitively after collapsing runs of spaces, also with validate true.",
)
reject(
    "v31_section_label_mismatch.convel",
    con(
        "corpus31 section label mismatch, validate absent",
        V31,
        tail=VEL2.replace("Velocities of", "Velocity of"),
    ),
    "IncompleteSection",
    16,
    "CON-section.15",
    "class-open",
    "The section label reads Velocity of Component 1 without validate. CON-section.15 applies in every mode and "
    "names no class; the reader reports the declared section as missing.",
)
for suffix, label in (
    ("no_index", "Velocities of Component"),
    ("xyz", "Velocities of Component xyz"),
    ("1_xyz", "Velocities of Component 1 xyz"),
    ("0", "Velocities of Component 0"),
    ("2", "Velocities of Component 2"),
    ("01", "Velocities of Component 01"),
):
    reject(
        f"v31_label_velocities_{suffix}.convel",
        con(
            f"corpus31 section label {label}",
            V31,
            tail=VEL2.replace("Velocities of Component 1", label),
        ),
        "IncompleteSection",
        16,
        "CON-section.15",
        "class-open",
        f"The label of component 1 of the velocities section reads {label}; the reader reports the declared "
        "section as missing.",
    )
reject(
    "v31_coord_label_mismatch.con",
    con(
        "corpus31 coordinate label mismatch, validate absent",
        S31,
        body=PT2.replace("Coordinates of", "Coords of"),
    ),
    "ValidationError",
    11,
    "CON-validate.4",
    "open",
    "The coordinate label reads Coords of Component 1 without validate. CON-validate.4 lists the coordinate label "
    "check under validate true, and no clause asks for it in other modes; the reader checks it in every mode.",
)
reject(
    "v31_label_coordinates_2.con",
    con(
        "corpus31 coordinate label Coordinates of Component 2",
        S31,
        body=PT2.replace("Coordinates of Component 1", "Coordinates of Component 2"),
    ),
    "ValidationError",
    11,
    "CON-count.8",
    "class-open",
    "The coordinate label of component 1 reads Coordinates of Component 2, and component numbers start at 1.",
)
reject(
    "v31_label_coordinates_1_xyz.con",
    con(
        "corpus31 coordinate label Coordinates of Component 1 xyz",
        S31,
        body=PT2.replace(
            "Coordinates of Component 1", "Coordinates of Component 1 xyz"
        ),
    ),
    "ValidationError",
    11,
    "CON-validate.4",
    "open",
    "The coordinate label of component 1 reads Coordinates of Component 1 xyz without validate; as for "
    "v31_coord_label_mismatch.con, the reader checks the label in every mode.",
)
reject(
    "v31_sections_out_of_order.convel",
    con(
        "corpus31 section blocks out of sections order",
        obj(M31, U31, '"sections":["forces","velocities"]'),
        tail=VEL2 + FORCES2,
    ),
    "IncompleteSection",
    16,
    "CON-section.1, CON-section.15",
    "open",
    "sections lists forces then velocities and the blocks are written velocities then forces. No clause fixes "
    "the order of the section blocks; the reader reads them in sections order, so the first label fails.",
)
accept(
    "v31_blank_symbol_velocities.convel",
    con(
        "corpus31 blank symbol line in a velocities block",
        V31,
        tail=VEL2.replace("\nPt\n", "\n\n", 1),
    ),
    1,
    "CON-section.4, CON-validate.4",
    "open",
    "The symbol line of the velocities block is blank. CON-validate.4 checks section symbols under validate "
    "true, and no clause says what a symbol line holds in other modes; the reader does not check it.",
)
reject(
    "v31_validate_symbol_mismatch.convel",
    con(
        "corpus31 validate, velocities symbol H",
        V31_VALIDATE,
        tail=VEL2.replace("\nPt\n", "\nH\n", 1),
    ),
    "ValidationError",
    15,
    "CON-validate.4",
    "explicit",
    "validate true and the velocities symbol line reads H for the Pt component.",
)
accept(
    "v31_section_row_id_mismatch.convel",
    con(
        "corpus31 velocity id differs, validate absent",
        V31,
        tail=VEL2.replace(" 0 0\n", " 0 5\n"),
    ),
    1,
    "CON-section.17",
    "optional",
    "A velocity row's id differs from its coordinate row and validate is absent; the reader may ignore the "
    "mismatch, and it does.",
)
reject(
    "v31_validate_row_id_mismatch.convel",
    con(
        "corpus31 velocity id differs, validate true",
        V31_VALIDATE,
        tail=VEL2.replace(" 0 0\n", " 0 5\n"),
    ),
    "ValidationError",
    17,
    "CON-validate.4",
    "explicit",
    "validate true and a velocity row's id differs from its coordinate row.",
)
reject(
    "sections_empty_velocity.con",
    EMPTY_SECTIONS_VELOCITY.encode(),
    "InvalidNumberFormat",
    15,
    "CON-section.1, CON-frame.7, CON-header.4, CON-num.8",
    "explicit",
    "Round-2 report K, item 1: sections [] and then an undeclared velocity block. The blank line after the frame "
    "is line 1 of the next frame, whose line 3 reads Velocities of Component 1 and is not a decimal.",
)
reject(
    "sections_empty_velocity_x300.con",
    (EMPTY_SECTIONS_VELOCITY * 300).encode(),
    "InvalidNumberFormat",
    15,
    "CON-section.1, CON-frame.7, CON-header.4, CON-num.8",
    "explicit",
    "The frame of sections_empty_velocity.con 300 times: the first copy fails at the same line in every reader "
    "path.",
)
reject(
    "sections_empty_velocity_6001_frames.con",
    (LEGAL_V2 * 3000 + BAD_V2 + LEGAL_V2 * 3000).encode(),
    "InvalidNumberFormat",
    36015,
    "CON-section.1, CON-frame.7, CON-header.4, CON-num.8",
    "explicit",
    "Round-2 report J, case A: 3000 legal frames, a frame with sections [] and then a velocity block, and 3000 "
    "legal frames.",
)

# ---------------------------------------------------------------- cell

CELL_ROOT = (
    "the radicand of the c vector of CON-cell.6 is negative, so no real cell exists; no clause names the "
    "class, and the reader rejects the angles line as ValidationError in every mode."
)
reject(
    "f26_cell_10_10_170.con",
    B_F26,
    "ValidationError",
    4,
    "CON-cell.6",
    "class-open",
    "Round-2 report B, item F26: validate true, lengths 10 10 10 and angles 10 10 170; "
    + CELL_ROOT,
)
for name, title, meta in (
    ("gram_170_v1.con", "version 1", "0.0000 TIME"),
    ("gram_170_v2.con", "version 2", '{"con_spec_version":2}'),
    ("gram_170_v30.con", "version 3.0", obj('"con_spec_version":3', U30)),
    (
        "gram_170_v31_validate.con",
        "minor 1, validate true",
        obj(M31, U31, '"sections":[]', '"validate":true'),
    ),
):
    reject(
        name,
        con(f"corpus31 angles 170 170 170, {title}", meta, angles="170.0 170.0 170.0"),
        "ValidationError",
        4,
        "CON-cell.6",
        "class-open",
        f"Angles 170 170 170 in a {title} frame: " + CELL_ROOT,
    )
accept(
    "gram_60_60_120.con",
    con("corpus31 angles 60 60 120", S31, angles="60.0 60.0 120.0"),
    1,
    "CON-cell.6",
    "explicit",
    "Angles 60 60 120: the radicand of the c vector of CON-cell.6 is 0, so the cell is built with c in "
    "the a-b plane.",
)
for suffix, meta, mode in (
    ("", S31, "validate absent"),
    ("_validate", obj(M31, U31, '"sections":[]', '"validate":true'), "validate true"),
):
    accept(
        f"gram_60_60_119_9{suffix}.con",
        con(f"corpus31 angles 60 60 119.9, {mode}", meta, angles="60.0 60.0 119.9"),
        1,
        "CON-cell.6",
        "explicit",
        f"Angles 60 60 119.9, {mode}: the radicand of CON-cell.6 is positive.",
    )
    reject(
        f"gram_60_60_120_1{suffix}.con",
        con(f"corpus31 angles 60 60 120.1, {mode}", meta, angles="60.0 60.0 120.1"),
        "ValidationError",
        4,
        "CON-cell.6",
        "class-open",
        f"Angles 60 60 120.1, {mode}: " + CELL_ROOT,
    )
accept(
    "v2_pbc_absent.con",
    con("corpus31 version 2 without pbc", '{"con_spec_version":2}'),
    1,
    "CON-cell.3",
    "explicit",
    "No pbc key: the frame is periodic in all three directions.",
    pbc=[True, True, True],
)
accept(
    "v31_pbc_slab.con",
    con("corpus31 pbc slab", obj(M31, U31, '"sections":[]', '"pbc":[true,true,false]')),
    1,
    "CON-cell.4",
    "explicit",
    "pbc [true, true, false] is an array of 3 booleans, one per axis.",
    pbc=[True, True, False],
)
reject(
    "v2_pbc_string.con",
    con("corpus31 version 2 pbc string", obj('"con_spec_version":2', '"pbc":"bad"')),
    "InvalidMetadataJson",
    2,
    "CON-cell.4, CON-line2.13",
    "explicit",
    "pbc bad is a string, not an array of 3 booleans, in every mode; a reserved key of the wrong type is "
    "InvalidMetadataJson.",
)
reject(
    "v31_pbc_two.con",
    con(
        "corpus31 pbc of 2 booleans",
        obj(M31, U31, '"sections":[]', '"pbc":[true,true]'),
    ),
    "InvalidMetadataJson",
    2,
    "CON-cell.4, CON-line2.13",
    "explicit",
    "pbc holds 2 booleans, not 3.",
)
reject(
    "v31_pbc_numbers.con",
    con("corpus31 pbc of numbers", obj(M31, U31, '"sections":[]', '"pbc":[1,1,1]')),
    "InvalidMetadataJson",
    2,
    "CON-cell.4, CON-line2.13",
    "explicit",
    "pbc holds numbers, not booleans.",
)
accept(
    "v31_lattice_ok.con",
    con(
        "corpus31 lattice_vectors",
        obj(
            M31,
            U31,
            '"sections":[]',
            '"lattice_vectors":[[10.0,0.0,0.0],[0.0,10.0,0.0],[0.0,0.0,10.0]]',
        ),
    ),
    1,
    "CON-cell.1, CON-cell.5",
    "explicit",
    "lattice_vectors is 3 arrays of 3 numbers.",
)
reject(
    "v31_lattice_two_rows.con",
    con(
        "corpus31 lattice_vectors of 2 rows",
        obj(
            M31,
            U31,
            '"sections":[]',
            '"lattice_vectors":[[10.0,0.0,0.0],[0.0,10.0,0.0]]',
        ),
    ),
    "InvalidMetadataJson",
    2,
    "CON-cell.5, CON-line2.13",
    "explicit",
    "lattice_vectors holds 2 rows, not 3.",
)
reject(
    "v31_lattice_string.con",
    con(
        "corpus31 lattice_vectors with a string",
        obj(
            M31,
            U31,
            '"sections":[]',
            '"lattice_vectors":[[10.0,0.0,0.0],[0.0,10.0,0.0],[0.0,0.0,"10.0"]]',
        ),
    ),
    "InvalidMetadataJson",
    2,
    "CON-cell.5, CON-line2.13",
    "explicit",
    "One lattice_vectors entry is a string, not a number.",
)

# ---------------------------------------------------------------- line 2

DEPTH = (
    "No clause bounds the nesting depth of line 2, and RFC 8259 section 9 lets a parser set one. The reader "
    "accepts 127 levels counting the outer object and rejects deeper nesting."
)
reject(
    "json_version_1.con",
    con("corpus31 JSON con_spec_version 1", '{"con_spec_version":1}'),
    "UnsupportedVersion",
    2,
    "CON-line2.5",
    "explicit",
    "JSON con_spec_version 0 or 1 is UnsupportedVersion; version 1 exists only as non-JSON line 2.",
)
reject(
    "json_version_4.con",
    con("corpus31 major 4", obj('"con_spec_version":4', '"con_spec_minor":0', U31)),
    "UnsupportedVersion",
    2,
    "CON-line2.6",
    "explicit",
    "Unknown major 4 is UnsupportedVersion.",
)
accept(
    "v31_version_float.con",
    con(
        "corpus31 con_spec_version 3.0",
        obj('"con_spec_version":3.0', '"con_spec_minor":1', U31, '"sections":[]'),
    ),
    1,
    "CON-line2.4",
    "explicit",
    "con_spec_version 3.0 is a JSON number equal to the major 3.",
)
accept(
    "v31_version_3e0.con",
    con(
        "corpus31 con_spec_version 3e0",
        obj('"con_spec_version":3e0', '"con_spec_minor":1', U31, '"sections":[]'),
    ),
    1,
    "CON-line2.4",
    "explicit",
    "con_spec_version 3e0 is a JSON number equal to the major 3.",
)
reject(
    "v31_version_string.con",
    con(
        "corpus31 con_spec_version string",
        obj('"con_spec_version":"3"', '"con_spec_minor":1', U31, '"sections":[]'),
    ),
    "InvalidMetadataJson",
    2,
    "CON-line2.4",
    "explicit",
    "con_spec_version is the string 3, not a number.",
)
reject(
    "v31_version_3_5.con",
    con(
        "corpus31 con_spec_version 3.5",
        obj('"con_spec_version":3.5', '"con_spec_minor":1', U31, '"sections":[]'),
    ),
    "InvalidMetadataJson",
    2,
    "CON-line2.4, CON-line2.6",
    "open",
    "con_spec_version 3.5 is a JSON number that names no integer major. CON-line2.6 makes an unknown major "
    "UnsupportedVersion, and the error table makes a reserved key of the wrong type InvalidMetadataJson; the "
    "reader takes a major to be an integer and reports InvalidMetadataJson.",
)
reject(
    "v31_minor_string.con",
    con(
        "corpus31 con_spec_minor string",
        obj('"con_spec_version":3,"con_spec_minor":"1"', U31),
    ),
    "InvalidMetadataJson",
    2,
    "CON-line2.9",
    "explicit",
    "con_spec_minor must be a JSON integer >= 0, not a string.",
)
accept(
    "v31_minor_2pow64_minus_1.con",
    con(
        "corpus31 con_spec_minor 2^64-1",
        obj(
            '"con_spec_version":3',
            '"con_spec_minor":18446744073709551615',
            U31,
            '"sections":[]',
        ),
    ),
    1,
    "CON-line2.7, CON-line2.9",
    "explicit",
    "con_spec_minor 2^64-1 is a legal minor, and a rewrite keeps it.",
    rewrite=True,
)
accept(
    "v2_minor_2pow64.con",
    con(
        "corpus31 version 2 con_spec_minor 2^64",
        obj('"con_spec_version":2', '"con_spec_minor":18446744073709551616'),
    ),
    1,
    "CON-line2.7, CON-line2.9",
    "explicit",
    "con_spec_minor 2^64 is a JSON integer >= 0, and no clause bounds a minor. A binding rewrite writes major 3 "
    "and keeps the digits of the minor.",
    rewrite=True,
)
accept(
    "v2_json_depth_127.con",
    con("corpus31 line 2 nested 127 deep", deep(126)),
    1,
    "CON-line2.1",
    "open",
    "Line 2 nests 127 deep counting the outer object. " + DEPTH,
)
reject(
    "v2_json_depth_128.con",
    con("corpus31 line 2 nested 128 deep", deep(127)),
    "InvalidMetadataJson",
    2,
    "CON-line2.1, CON-line2.2",
    "open",
    "Line 2 nests 128 deep counting the outer object. " + DEPTH,
)
reject(
    "v31_validate_string.con",
    con("corpus31 validate string", obj(M31, U31, '"sections":[]', '"validate":"yes"')),
    "InvalidMetadataJson",
    2,
    "CON-line2.12",
    "explicit",
    "validate is the string yes, not a boolean.",
)
reject(
    "v31_energy_string.con",
    con("corpus31 energy string", obj(M31, U31, '"sections":[]', '"energy":"-1.0"')),
    "InvalidMetadataJson",
    2,
    "CON-line2.13",
    "explicit",
    "energy is a string, not a number.",
)
accept(
    "v31_bonds_one_index.con",
    con("corpus31 bond of one index", obj(M31, U31, '"sections":[]', '"bonds":[[0]]')),
    1,
    "CON-bonds.3",
    "explicit",
    "A bonds entry of one index with validate absent: unknown bonds shapes are preserved.",
)

# ---------------------------------------------------------------- round-2 acceptor probes D1-D15

reject(
    "d01_time_unit_metre.convel",
    probe(
        {
            **PROBE_M31,
            "units": {**PROBE_UNITS, "time": "m"},
            "sections": ["velocities"],
        },
        extra=PROBE_VEL,
    ),
    "InvalidUnits",
    2,
    "CON-units.2",
    "explicit",
    "Probe D1: units.time m is a length, not a time.",
)
reject(
    "d02_legacy_velocity_no_time.convel",
    probe({**PROBE_M31, "units": PROBE_UNITS}, extra=PROBE_VEL),
    "InvalidUnits",
    14,
    "CON-section.1, CON-units.11",
    "explicit",
    "Probe D2: a minor-1 legacy velocity block without units.time fails on the blank line that opens it.",
)
reject(
    "d03_nbsp_after_id.con",
    probe(
        {**PROBE_M31, "units": PROBE_UNITS},
        rows=("0.0 0.0 0.0 0 0\u00a0", "1.0 1.0 1.0 0 1"),
    ),
    "InvalidNumberFormat",
    12,
    "CON-token.3, CON-file.4, CON-error.3",
    "explicit",
    "Probe D3: U+00A0 is neither a separator nor a trailing space or tab, so column 5 reads 0 followed by "
    "U+00A0.",
)
reject(
    "d04_vertical_tab_separator.con",
    probe(
        {**PROBE_M31, "units": PROBE_UNITS},
        rows=("0.0\x0b0.0 0.0 0 0", "1.0 1.0 1.0 0 1"),
    ),
    "InvalidNumberFormat",
    12,
    "CON-token.3, CON-num.8",
    "explicit",
    "Probe D4: a vertical tab separates no fields, so the first field 0.0, VT, 0.0 is no decimal.",
)
reject(
    "d05_lattice_nan.con",
    probe(
        '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},'
        '"lattice_vectors":[[10,0,0],[0,10,0],[0,0,NaN]]}'
    ),
    "InvalidMetadataJson",
    2,
    "CON-line2.2",
    "explicit",
    "Probe D5: NaN is not JSON.",
)
reject(
    "d06_lattice_1e999.con",
    probe(
        '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},'
        '"lattice_vectors":[[10,0,0],[0,10,0],[0,0,1e999]]}'
    ),
    "InvalidMetadataJson",
    2,
    "CON-cell.5, CON-line2.13",
    "open",
    "Probe D6: 1e999 is a JSON number whose binary64 value is infinite. CON-cell.5 asks for finite numbers, "
    "and the error table makes an Inf value NonFiniteValue. A reserved key must hold the type this document "
    "gives it (CON-line2.13), and the reader reports a reserved key with a number that is not a finite "
    "binary64 as InvalidMetadataJson on line 2.",
)
reject(
    "d07_sections_capital_velocities.convel",
    probe(
        {
            **PROBE_M31,
            "units": {**PROBE_UNITS, "time": NATURAL},
            "sections": ["Velocities"],
        },
        extra=PROBE_VEL,
    ),
    "UnknownSection",
    2,
    "CON-section.1, CON-section.7",
    "explicit",
    "Probe D7: sections lists Velocities. CON-file.5 folds case in labels only, so Velocities is not the reserved "
    "name velocities and is an unknown section at minor 1.",
)
reject(
    "d08_sections_null.con",
    probe({"con_spec_version": 2, "sections": None}),
    "InvalidMetadataJson",
    2,
    "CON-line2.11",
    "explicit",
    "Probe D8: sections null is not an array of strings.",
)
reject(
    "d09_arity_velocities_1.con",
    probe({"con_spec_version": 2, "section_arity": {"velocities": 1}}),
    "InvalidVectorLength",
    2,
    "CON-section.13",
    "explicit",
    "Probe D9: section_arity gives the reserved vector section velocities arity 1, not 3.",
)
reject(
    "d10_json_depth_129.con",
    probe(deep(128)),
    "InvalidMetadataJson",
    2,
    "CON-line2.1, CON-line2.2",
    "open",
    "Probe D10: line 2 nests 129 deep counting the outer object. " + DEPTH,
)
reject(
    "d11_validate_pbc_object.con",
    probe({"con_spec_version": 2, "sections": [], "validate": True, "pbc": {"a": 1}}),
    "InvalidMetadataJson",
    2,
    "CON-cell.4, CON-validate.4",
    "open",
    "Probe D11: validate true and pbc is an object. The error table makes a reserved key of the wrong type "
    "InvalidMetadataJson in every mode, and CON-validate.4 names ValidationError for a bad reserved-key type "
    "under validate true. The reader applies the check of every mode first.",
)
accept(
    "d12_length_trailing_space.con",
    probe({"con_spec_version": 3, "units": {"length": "angstrom ", "energy": "eV"}}),
    1,
    "CON-units.1, CON-units.16",
    "open",
    "Probe D12: units.length is angstrom with a trailing space. The text does not say whether white space may "
    "stand inside a unit expression; the reader removes it.",
)
accept(
    "d13_blank_symbol_energies.con",
    probe({"con_spec_version": 2, "sections": ["energies"]}, extra=probe_energies("")),
    1,
    "CON-section.4, CON-validate.4",
    "open",
    "Probe D13: the symbol line of the energies block is blank. As for v31_blank_symbol_velocities.convel, the "
    "reader does not check section symbols outside validate true.",
)
accept(
    "d14_minor_2pow64.con",
    probe({"con_spec_version": 3, "con_spec_minor": 2**64, "units": PROBE_UNITS}),
    1,
    "CON-line2.7, CON-line2.9",
    "explicit",
    "Probe D14: con_spec_minor 2^64 is a JSON integer >= 0 of the known major 3, and no clause bounds a minor.",
)
reject(
    "d15_json_depth_100001.con",
    probe(deep(100000)),
    "InvalidMetadataJson",
    2,
    "CON-line2.1, CON-line2.2",
    "open",
    "Probe D15: line 2 nests 100001 deep, and the reader rejects it without exhausting its stack. "
    + DEPTH,
)

# ---------------------------------------------------------------- counts

reject(
    "v31_type_count_2pow64_minus_1.con",
    con(
        "corpus31 type count 2^64-1",
        S31,
        body=PT2.replace("1\n2\n", "18446744073709551615\n2\n", 1),
    ),
    "InvalidVectorLength",
    8,
    "CON-num.9",
    "explicit",
    "Line 7 declares 2^64-1 atom types and line 8 holds one count.",
)
reject(
    "v31_type_count_2pow64.con",
    con(
        "corpus31 type count 2^64",
        S31,
        body=PT2.replace("1\n2\n", "18446744073709551616\n2\n", 1),
    ),
    "InvalidCount",
    7,
    "CON-error.3",
    "open",
    "The type count is 2^64. No clause bounds a count; the reader reads counts as integers in 0 through 2^64-1 "
    "and reports a larger one as InvalidCount.",
)
reject(
    "v31_atom_count_1e12.con",
    con(
        "corpus31 atom count 10^12",
        S31,
        body=PT2.replace("1\n2\n", "1\n1000000000000\n", 1),
    ),
    "IncompleteFrame",
    14,
    "CON-frame.4",
    "explicit",
    "Line 8 declares 10^12 atoms and the file ends after 2 coordinate rows.",
)

# ---------------------------------------------------------------- envelopes

accept(
    "v31_gzip.con.gz",
    gz(CONVEL_FS),
    1,
    "CON-compress.1",
    "explicit",
    "One gzip member holding a legal minor-1 convel frame.",
)
accept(
    "v31_gzip_two_members.con.gz",
    gz(CONVEL_FS) + gz(CONVEL_FS_B),
    2,
    "CON-compress.1",
    "explicit",
    "Two gzip members, one frame each; every member is exposed in order.",
)
accept(
    "v31_gzip_by_content.con",
    gz(BASE),
    1,
    "CON-compress.3",
    "optional",
    "Gzip bytes under a plain .con name; readers should detect gzip by its magic bytes, and this one does.",
)
accept(
    "v31_zstd.con.zst",
    zst(CONVEL_FS),
    1,
    "CON-compress.2",
    "explicit",
    "One zstd frame holding a legal minor-1 convel frame.",
)
accept(
    "v31_zstd_two_frames.con.zst",
    zst(CONVEL_FS) + zst(CONVEL_FS_B),
    2,
    "CON-compress.2",
    "explicit",
    "Two zstd frames, one CON frame each; every frame is exposed in order.",
)

# ---------------------------------------------------------------- text, white space, numbers

reject(
    "v31_bom.con",
    b"\xef\xbb\xbf" + BASE,
    "ValidationError",
    1,
    "CON-file.2",
    "class-open",
    "Begins with the UTF-8 byte-order mark EF BB BF; the clause names no class.",
)
accept(
    "v31_bom_later_frame.con",
    BASE + b"\xef\xbb\xbf" + BASE_B,
    2,
    "CON-file.2, CON-header.2",
    "explicit",
    "A U+FEFF begins line 1 of the second frame, which is text of that line.",
)
reject(
    "v31_utf8_line1.con",
    BASE.replace(b"corpus31 minor-1", b"corpus31 \xc0\xaf", 1),
    "ValidationError",
    1,
    "CON-file.1",
    "class-open",
    "Line 1 holds the bytes C0 AF, which are not UTF-8; the clause names no class.",
)
reject(
    "v31_utf8_number_token.con",
    BASE.replace(b"0.0 0.0 0.0 0 0\n", b"0\xc0.0 0.0 0.0 0 0\n", 1),
    "InvalidNumberFormat",
    12,
    "CON-file.1, CON-num.8",
    "class-open",
    "The byte C0 inside the first coordinate of line 12 is not UTF-8, and the token is not a decimal. CON-num.8 "
    "names InvalidNumberFormat and CON-file.1 names no class; the reader reports InvalidNumberFormat.",
)
reject(
    "v31_utf8_separator_line.convel",
    CONVEL_FS.replace(b"0 1\n\nPt\nVelocities", b"0 1\n\xc0\xaf\nPt\nVelocities", 1),
    "ValidationError",
    14,
    "CON-file.1, CON-section.2",
    "class-open",
    "Line 14, where the velocities section needs its blank line, holds the bytes C0 AF, which are not UTF-8; "
    "neither clause names a class.",
)
accept(
    "v31_crlf.con",
    BASE.replace(b"\n", b"\r\n"),
    1,
    "CON-file.3",
    "explicit",
    "CRLF line endings.",
)
accept(
    "v31_trailing_ws.con",
    BASE.replace(b"\n", b" \t\n") + b"  \n\t\n",
    1,
    "CON-file.4, CON-frame.1",
    "explicit",
    "Trailing spaces and tabs on every line, then lines of spaces and tabs only after the last frame.",
)
reject(
    "v31_trailing_ff.con",
    BASE.replace(b"\n", b"\f\n"),
    "InvalidMetadataJson",
    2,
    "CON-file.4, CON-line2.1, CON-line2.2",
    "explicit",
    "A form feed ends every line. CON-file.4 ignores trailing spaces and tabs only, so line 2 is a JSON object "
    "followed by a form feed, which is not one JSON object and nothing else.",
)
reject(
    "v31_unicode_tail.con",
    BASE + "\u00a0\u3000\n\u2003\n".encode(),
    "IncompleteHeader",
    16,
    "CON-frame.1, CON-frame.3",
    "open",
    "Lines of U+00A0 U+3000 and of U+2003 follow the last frame. "
    + BLANK
    + " The second line holds U+2003, so "
    "the two lines are lines 1 and 2 of a further frame, which ends before its line 3.",
)
accept(
    "ff_tail_610_frames.con",
    (LEGAL_V2 * 610 + "\f\n").encode(),
    610,
    "CON-frame.1",
    "open",
    "610 legal frames and a last line holding a form feed. "
    + BLANK
    + " So the form feed line is the ignored "
    "end of the file.",
)
reject(
    "whitespace_only.con",
    " \n\t\n\u3000\n".encode(),
    "InvalidNumberFormat",
    3,
    "CON-frame.1, CON-num.8",
    "open",
    "Lines 1 and 2 hold a space and a tab, line 3 holds U+3000. "
    + BLANK
    + " Line 3 holds U+3000, so the file "
    "holds a frame whose line 3 is not a decimal.",
)
reject(
    "v31_zero_atom_unicode_blank.con",
    BASE
    + con(
        "corpus31 zero-atom frame, U+3000 and U+00A0 lines 8 and 9",
        S31,
        body="0\n\u3000\n\u00a0\n",
    ),
    "InvalidCount",
    21,
    "CON-count.1",
    "open",
    "A zero-atom frame whose lines 8 and 9 hold U+3000 and U+00A0. "
    + SPACES_TABS
    + " So line 8 holds a token, "
    "which CON-count.1 makes InvalidCount.",
)
reject(
    "v31_form_feed_separator.con",
    con(
        "corpus31 form feed field separator",
        S31,
        body=PT2.replace("0.0 0.0 0.0 0 0", "0.0\f0.0 0.0 0 0"),
    ),
    "InvalidNumberFormat",
    12,
    "CON-token.3, CON-num.8",
    "explicit",
    "A form feed stands between the first two fields of an atom line. Separators are spaces or tabs, so the "
    "first field 0.0, FF, 0.0 is no decimal.",
)
reject(
    "v31_cr_separator.con",
    con(
        "corpus31 carriage return field separator",
        S31,
        body=PT2.replace("2.5 2.5 0.0 0 1", "2.5\r2.5 0.0 0 1"),
    ),
    "InvalidNumberFormat",
    13,
    "CON-token.3, CON-file.3, CON-num.8",
    "explicit",
    "A carriage return that ends no line stands between the first two fields of an atom line. Separators are "
    "spaces or tabs, so the first field 2.5, CR, 2.5 is no decimal.",
)
accept(
    "v31_float_forms.con",
    con("corpus31 float spellings", S31, body=FLOATS),
    1,
    "CON-num.5, CON-token.2",
    "explicit",
    "Signs, leading and trailing dots, exponents, long significands, subnormals and underflow to 0; each must "
    "round correctly to binary64.",
)
reject(
    "v31_nan_coordinate.con",
    con(
        "corpus31 NaN coordinate",
        S31,
        body=PT2.replace("2.5 2.5 0.0 0 1", "NaN 2.5 0.0 0 1"),
    ),
    "NonFiniteValue",
    13,
    "CON-num.1",
    "explicit",
    "NaN coordinate is NonFiniteValue in every mode.",
)
reject(
    "v31_inf_velocity.convel",
    con(
        "corpus31 -Infinity velocity",
        V31,
        tail=VEL2.replace("0.0 -0.02 0.0", "0.0 -Infinity 0.0"),
    ),
    "NonFiniteValue",
    18,
    "CON-num.1",
    "explicit",
    "-Infinity in a velocity row is NonFiniteValue.",
)
reject(
    "v31_overflow_coordinate.con",
    con(
        "corpus31 1e400 coordinate",
        S31,
        body=PT2.replace("2.5 2.5 0.0 0 1", "1e400 2.5 0.0 0 1"),
    ),
    "NonFiniteValue",
    13,
    "CON-num.5, CON-num.1",
    "explicit",
    "1e400 is a decimal whose correctly rounded binary64 value is infinite, and the error table makes an Inf "
    "value NonFiniteValue in any mode.",
)
accept(
    "v31_label_case_coordinates.con",
    con(
        "corpus31 coordinate label case and spaces",
        S31,
        body=PT2.replace(
            "Coordinates of Component 1", "  COORDINATES\tof   component 1 "
        ),
    ),
    1,
    "CON-file.5, CON-validate.4",
    "open",
    "The coordinate label has leading spaces, a tab between words and upper case. CON-file.5 collapses runs of "
    "spaces; the reader compares labels word by word, splitting at spaces and tabs, with ASCII letters folded.",
)

# ---------------------------------------------------------------- frames

accept(
    "v1_then_json_frame_empty_title.con",
    con("corpus31 version 1 frame", "0.0000 TIME") + con("", '{"con_spec_version":2}'),
    2,
    "CON-section.1, CON-frame.7, CON-header.4",
    "explicit",
    "After a version 1 frame, a blank line followed by a line that starts with { begins no velocity block "
    "(Sections); it is the empty line 1 of a version 2 frame.",
)
reject(
    "two_frames_blank.con",
    BASE + b"\n" + BASE_B,
    "InvalidNumberFormat",
    16,
    "CON-frame.7, CON-num.8",
    "explicit",
    "Two legal frames separated by one blank line. The blank is line 1 of frame 2, so its JSON line is read as "
    "line 3; the first frame has sections [] so the legacy velocity block is off.",
)
accept(
    "empty.con",
    b"",
    0,
    "CON-frame.1",
    "open",
    "Zero bytes. No clause speaks to a file without a frame; the reader returns zero frames.",
)


def toml_str(value) -> str:
    return json.dumps(value)


def released_clauses(spec: Path) -> set[str]:
    return set(re.findall(r"^- (CON-[a-z0-9]+\.\d+) ::", spec.read_text(), flags=re.M))


def check_cases(cases: list[dict], clauses: set[str]) -> None:
    names = [case["file"] for case in cases]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SystemExit(f"duplicate corpus file names: {duplicates}")
    for case in cases:
        if case["basis"] not in BASES:
            raise SystemExit(f"{case['file']}: unknown basis {case['basis']}")
        missing = [c for c in case["clause"].split(", ") if c not in clauses]
        if missing:
            raise SystemExit(f"{case['file']}: {', '.join(missing)} not in the spec")


def manifest(cases: list[dict]) -> str:
    lines = [
        "# CON 3.1 corpus written by paper/cpc/scripts/make_corpus31.py from explicit bytes.",
        "# expected: accept (frames: the frame count) or reject (error: the class, line: the 1-based line).",
        "# line: the first line at which the text fails the cited clauses (CON-error.2, CON-error.4).",
        "# clause: the clauses of spec_doc that decide the file. reader_minor: the minor the reader implements.",
        "# basis:",
        *(f"#   {name}: {text}." for name, text in BASES.items()),
        "# rewrite: the binding rewrite (write_con_string) keeps con_spec_version, con_spec_minor and units of every",
        "# frame of major 3 that declares con_spec_minor or whose velocities carry a units.time label, which pins the",
        "# rewrite to minor 0, and writes a frame of major 1 or 2 as major 3 with every unit it declares and the same",
        "# fields. A 3.0 frame with neither comes back at minor 1, the minor the builder stamps (D15); no file with the",
        "# key holds one.",
        "# pbc: the periodicity a reader reports for the first frame (CON-cell.3, CON-cell.4).",
        "# time_unit_override: a frame's velocities are read in the natural time unit although units.time names",
        "# another unit (CON-units.8, CON-units.9); read_con and iter_con do not warn, and the conversion to ASE",
        "# (ConFrame.to_ase, read_con_as_ase) warns that the label is not applied. Without the key no frame of the",
        "# file is read that way.",
        f"spec_doc = {toml_str('docs/orgmode/spec.org')}",
        f"reader_minor = {READER_MINOR}",
        "",
    ]
    for case in cases:
        lines += [
            "[[file]]",
            f"file = {toml_str(case['file'])}",
            f"expected = {toml_str(case['expected'])}",
        ]
        if case["expected"] == "accept":
            lines.append(f"frames = {case['frames']}")
        else:
            lines += [f"error = {toml_str(case['error'])}", f"line = {case['line']}"]
        for key in ("rewrite", "time_unit_override"):
            if case.get(key):
                lines.append(f"{key} = true")
        if "pbc" in case:
            lines.append(
                "pbc = [" + ", ".join(toml_str(flag) for flag in case["pbc"]) + "]"
            )
        lines += [
            f"clause = {toml_str(case['clause'])}",
            f"basis = {toml_str(case['basis'])}",
            f"reason = {toml_str(case['reason'])}",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=OUT, help="corpus directory (default: %(default)s)"
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=SPEC,
        help="the spec whose clauses are cited (default: %(default)s)",
    )
    args = parser.parse_args()
    check_cases(CASES, released_clauses(args.spec))
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for case in CASES:
        (out / case["file"]).write_bytes(case["data"])
    (out / "manifest.toml").write_text(manifest(CASES))
    print(f"wrote {len(CASES)} files to {out}")


if __name__ == "__main__":
    main()
