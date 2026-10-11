#!/usr/bin/env python3
"""Write the clause-keyed CON fixtures and their manifest rows.

The files under resources/conformance/ are the corpus. This script
regenerates the rows added for the foreign-reader and clause fixtures.
Existing Phase A files stay where they are; their clause ids are filled
in when a row does not already name them.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "resources" / "conformance"
MANIFEST = CORPUS / "manifest.toml"

CU = ("Cu", 63.546, [(0.0, 0.0, 0.0, 0, 0)])


def groups(*items):
    return list(items)


def coord_block(gs, label="Coordinates of Component {i}"):
    lines = [
        str(len(gs)),
        " ".join(str(len(rows)) for _, _, rows in gs),
        " ".join(f"{mass:.6f}" for _, mass, _ in gs),
    ]
    for i, (sym, _mass, rows) in enumerate(gs, 1):
        lines.append(sym)
        lines.append(label.format(i=i))
        for x, y, z, mask, aid in rows:
            if aid is None:
                lines.append(f"{x} {y} {z} {mask}")
            else:
                lines.append(f"{x} {y} {z} {mask} {aid}")
    return lines


def frame(
    meta,
    gs,
    line1="conformance",
    box=(10.0, 10.0, 10.0),
    angles=(90.0, 90.0, 90.0),
    line5="",
    line6="",
    spec1_line2=None,
):
    line2 = (
        spec1_line2
        if spec1_line2 is not None
        else json.dumps(meta, separators=(",", ":"))
    )
    lines = [
        line1,
        line2,
        f"{box[0]} {box[1]} {box[2]}",
        f"{angles[0]} {angles[1]} {angles[2]}",
        line5,
        line6,
        *coord_block(gs),
    ]
    return "\n".join(lines) + "\n"


def section_block(name, gs, scalar=False):
    label = name[:1].upper() + name[1:]
    lines = [""]
    for i, (sym, _mass, rows) in enumerate(gs, 1):
        lines.append(sym)
        lines.append(f"{label} of Component {i}")
        for x, y, z, mask, aid in rows:
            if scalar:
                cell = f"{x} {mask} {aid}"
            elif aid is None:
                cell = f"{x} {y} {z} {mask}"
            else:
                cell = f"{x} {y} {z} {mask} {aid}"
            lines.append(cell)
    return "\n".join(lines) + "\n"


def with_sections(text, name, gs, scalar=False):
    base = text.rstrip("\n")
    block = section_block(name, gs, scalar=scalar).lstrip("\n")
    return base + "\n\n" + block


V3 = {
    "con_spec_version": 3,
    "con_spec_minor": 1,
    "units": {"length": "angstrom", "energy": "eV"},
}
V3_TIME = {
    "con_spec_version": 3,
    "con_spec_minor": 1,
    "units": {
        "length": "angstrom",
        "energy": "eV",
        "mass": "amu",
        "time": "(amu*angstrom^2/eV)^0.5",
    },
    "sections": ["velocities"],
}
V2 = {"con_spec_version": 2}


def gz_member(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as handle:
        handle.write(payload)
    return buf.getvalue()


def write(rel, data: bytes | str):
    path = CORPUS / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_bytes(data.encode("utf-8"))
    else:
        path.write_bytes(data)
    return rel


def build():
    simple = frame(V3, groups(CU))
    two = groups(
        ("Pt", 195.084, [(0.0, 0.0, 0.0, 0, 2), (1.0, 0.0, 0.0, 3, 0)]),
        ("H", 1.00794, [(0.0, 0.0, 2.0, 7, 1)]),
    )
    out = {}

    out["valid/crlf.con"] = simple.replace("\n", "\r\n")
    spaced = simple.replace("0.0 0.0 0.0 0 0\n", "0.0 0.0 0.0 0 0   \n")
    out["valid/trailing_spaces.con"] = spaced
    out["valid/label_case.con"] = frame(V3, groups(CU)).replace(
        "Coordinates of Component 1", "coordinates of component   1"
    )
    out["valid/trailing_blanks.con"] = simple + "\n  \n\n"
    out["valid/two_frames.con"] = simple + simple
    out["valid/blank_then_eof.con"] = simple + "\n   \n"
    out["valid/sections_empty.con"] = frame(
        {**V3, "sections": [], "validate": True}, groups(CU)
    )
    out["valid/unknown_key.con"] = frame({**V3, "campaign": "slab-42"}, groups(CU))
    out["valid/pbc_partial.con"] = frame(
        {**V3, "pbc": [False, True, False]}, groups(CU)
    )
    out["valid/lattice_vectors.con"] = frame(
        {
            **V3,
            "lattice_vectors": [[10.0, 0.0, 0.0], [0.0, 12.0, 0.0], [0.0, 0.0, 14.0]],
        },
        groups(CU),
        box=(10.0, 12.0, 14.0),
    )
    out["valid/cell_angles.con"] = frame(V3, groups(CU), angles=(80.0, 90.0, 70.0))
    vel_rows = groups(("Cu", 63.546, [(0.1, -0.2, 0.3, 0, 0)]))
    legacy = frame(V2, vel_rows)
    out["valid/legacy_velocity.con"] = (
        legacy.rstrip("\n")
        + "\n\n"
        + section_block("velocities", vel_rows).lstrip("\n")
    )
    out["valid/four_column.con"] = frame(
        V3, groups(("Cu", 63.546, [(1.0, 2.0, 3.0, 0, None), (4.0, 5.0, 6.0, 1, None)]))
    )
    big = 9007199254740993
    out["valid/big_id.con"] = frame(
        V3, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 0, big)]))
    )
    out["valid/repeated_ids.con"] = frame(
        V3, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 0, 5), (1.0, 0.0, 0.0, 0, 5)]))
    )
    out["valid/tabs.con"] = simple.replace("0.0 0.0 0.0 0 0", "0.0\t0.0\t0.0\t0\t0")
    out["valid/exponent.con"] = frame(
        V3, groups(("Cu", 63.546, [(0.1, -0.25, 1e-1, 0, 3)]))
    )
    out["valid/two_types.con"] = frame(V3, two)
    energies = groups(("Cu", 63.546, [(0.5, 0.0, 0.0, 0, 0)]))
    out["valid/energies.con"] = with_sections(
        frame(
            {**V3, "sections": ["energies"], "energy": 0.5, "validate": True}, energies
        ),
        "energies",
        energies,
        scalar=True,
    )
    out["valid/v31_velocities.con"] = with_sections(
        frame(V3_TIME, vel_rows), "velocities", vel_rows
    )
    v30 = {
        "con_spec_version": 3,
        "units": {"length": "angstrom", "energy": "eV", "time": "fs"},
        "sections": ["velocities"],
    }
    out["valid/v30_fs_label.con"] = with_sections(
        frame(v30, vel_rows), "velocities", vel_rows
    )
    out["valid/v1_plain.con"] = frame({}, groups(CU), spec1_line2="0.0000 TIME")
    out["valid/v2_with_units.con"] = frame(
        {"con_spec_version": 2, "units": {"length": "angstrom", "energy": "eV"}},
        groups(CU),
    )
    out["valid/unit_names.con"] = frame(
        {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "units": {
                "length": "metre",
                "energy": "joule",
                "mass": "dalton",
                "time": "fs",
            },
        },
        groups(CU),
    )
    out["valid/unknown_minor_skip.con"] = with_sections(
        frame(
            {
                "con_spec_version": 3,
                "con_spec_minor": 99,
                "units": {"length": "angstrom", "energy": "eV"},
                "sections": ["widgets"],
                "section_arity": {"widgets": 3},
            },
            groups(CU),
        ),
        "widgets",
        groups(CU),
    )
    bonds_ok = frame(
        {**V3, "bonds": [[0, 0]], "sections": [], "validate": True}, groups(CU)
    )
    out["valid/bonds_preserved.con"] = bonds_ok
    # validate false keeps a bonds shape the strict checker would reject
    out["valid/bonds_loose.con"] = frame(
        {**V3, "bonds": ["not-a-pair"], "sections": []}, groups(CU)
    )
    out["valid/header_lines.con"] = frame(
        V3, groups(CU), line1="user line", line5="post a", line6="post b"
    )

    out["invalid/truncated_header.con"] = 'only\n{"con_spec_version":2}\n10 10 10\n'
    out["invalid/truncated_rows.con"] = frame(
        V3, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 0, 0), (1.0, 0.0, 0.0, 0, 1)]))
    ).replace("1.0 0.0 0.0 0 1\n", "")
    # Header declares two atoms; drop the second row by rewriting the count block.
    declared = frame(V2, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 0, 0)])))
    declared = declared.replace("\n1\n1\n", "\n1\n2\n", 1)
    out["invalid/truncated_rows.con"] = declared
    out["invalid/truncated_multiframe.con"] = (
        simple + 'next\n{"con_spec_version":2}\n10 10 10\n'
    )
    out["invalid/incomplete_section.con"] = (
        frame({**V2, "sections": ["forces"]}, groups(CU)).rstrip("\n") + "\n\nCu\n"
    )
    out["invalid/spec1_mask_2.con"] = frame(
        {}, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 2, 0)])), spec1_line2="0.0000 TIME"
    )
    out["invalid/spec1_mask_6.con"] = frame(
        {}, groups(("Cu", 63.546, [(0.0, 0.0, 0.0, 6, 0)])), spec1_line2="0.0000 TIME"
    )
    out["invalid/float_column4.con"] = simple.replace(
        "0.0 0.0 0.0 0 0", "0.0 0.0 0.0 0.0 0"
    )
    out["invalid/nonfinite.con"] = simple.replace("0.0 0.0 0.0 0 0", "nan 0.0 0.0 0 0")
    out["invalid/infinity.con"] = simple.replace("0.0 0.0 0.0 0 0", "Inf 0.0 0.0 0 0")
    out["invalid/bom.con"] = "\ufeff" + simple
    out["invalid/atom_energies.con"] = with_sections(
        frame({**V3, "sections": ["atom_energies"]}, energies),
        "atom_energies",
        energies,
        scalar=True,
    )
    out["invalid/unknown_minor_no_arity.con"] = with_sections(
        frame(
            {
                "con_spec_version": 3,
                "con_spec_minor": 99,
                "units": {"length": "angstrom", "energy": "eV"},
                "sections": ["widgets"],
            },
            groups(CU),
        ),
        "widgets",
        groups(CU),
    )
    out["invalid/bad_json.con"] = frame({}, groups(CU), spec1_line2="{")
    out["invalid/version_zero.con"] = frame(
        {"con_spec_version": 0, "units": {"length": "angstrom", "energy": "eV"}},
        groups(CU),
    )
    out["invalid/bad_minor.con"] = frame(
        {
            "con_spec_version": 3,
            "con_spec_minor": -1,
            "units": {"length": "angstrom", "energy": "eV"},
        },
        groups(CU),
    )
    out["invalid/validate_type.con"] = frame(
        {**V3, "validate": "yes", "sections": []}, groups(CU)
    )
    out["invalid/sections_type.con"] = frame(
        {**V3, "sections": "velocities"}, groups(CU)
    )
    out["invalid/signed_count.con"] = frame(V2, groups(CU)).replace(
        "\n1\n1\n", "\n-1\n1\n", 1
    )
    out["invalid/bad_id.con"] = simple.replace("0.0 0.0 0.0 0 0", "0.0 0.0 0.0 0 -1")
    out["invalid/bad_number.con"] = simple.replace(
        "0.0 0.0 0.0 0 0", "0.0 0.0 nope 0 0"
    )
    out["invalid/short_row.con"] = simple.replace("0.0 0.0 0.0 0 0", "0.0 0.0")
    out["invalid/missing_time.con"] = with_sections(
        frame(
            {
                "con_spec_version": 3,
                "con_spec_minor": 1,
                "units": {"length": "angstrom", "energy": "eV"},
                "sections": ["velocities"],
            },
            vel_rows,
        ),
        "velocities",
        vel_rows,
    )
    out["invalid/bad_pbc.con"] = frame(
        {**V3, "pbc": [True, False], "sections": [], "validate": True}, groups(CU)
    )
    out["invalid/bad_bonds.con"] = frame(
        {**V3, "bonds": ["nope"], "sections": [], "validate": True}, groups(CU)
    )
    out["invalid/bad_symbol.con"] = frame(
        {**V3, "sections": [], "validate": True},
        groups(("NotAnElement", 1.0, [(0.0, 0.0, 0.0, 0, 0)])),
    )
    out["invalid/negative_spread.con"] = with_sections(
        frame({**V3, "sections": ["spreads"]}, groups(CU)),
        "spreads",
        groups(("Cu", 63.546, [(-1.0, 0.0, 0.0, 0, 0)])),
    )
    out["invalid/reserved_arity.con"] = frame(
        {
            **V3,
            "sections": ["forces"],
            "section_arity": {"forces": 1},
            "validate": True,
        },
        groups(CU),
    )

    payload = simple.encode("utf-8")
    out["valid/gzip_multi.con.gz"] = gz_member(payload) + gz_member(payload)
    out["valid/gzip_magic.con"] = gz_member(payload)

    for rel, data in out.items():
        write(rel, data)
    return out


CASES = [
    (
        "valid",
        "crlf",
        "valid/crlf.con",
        "CON-file.3",
        ["CON-file.1", "CON-file.3"],
        None,
        "CRLF line endings.",
    ),
    (
        "valid",
        "trailing-spaces",
        "valid/trailing_spaces.con",
        "CON-file.4",
        ["CON-file.4"],
        None,
        "Trailing spaces on the coordinate row.",
    ),
    (
        "valid",
        "label-case",
        "valid/label_case.con",
        "CON-file.5",
        ["CON-file.5", "CON-section.15"],
        None,
        "Label case and collapsed spaces.",
    ),
    (
        "valid",
        "trailing-blanks",
        "valid/trailing_blanks.con",
        "CON-frame.1",
        ["CON-frame.1"],
        None,
        "Whitespace after the last frame.",
    ),
    (
        "valid",
        "two-frames",
        "valid/two_frames.con",
        "CON-frame.7",
        ["CON-frame.7", "CON-file.6"],
        2,
        "Two frames with no blank line between them.",
    ),
    (
        "valid",
        "blank-then-eof",
        "valid/blank_then_eof.con",
        "CON-frame.5",
        ["CON-frame.5"],
        1,
        "A blank line and whitespace are not a velocity block.",
    ),
    (
        "valid",
        "sections-empty",
        "valid/sections_empty.con",
        "CON-validate.3",
        ["CON-section.1", "CON-validate.3", "CON-line2.11", "CON-line2.12"],
        None,
        "validate true with an empty sections array.",
    ),
    (
        "valid",
        "unknown-key",
        "valid/unknown_key.con",
        "CON-line2.8",
        ["CON-line2.8"],
        None,
        "An unknown line-2 key survives a rewrite.",
    ),
    (
        "valid",
        "pbc-partial",
        "valid/pbc_partial.con",
        "CON-cell.4",
        ["CON-cell.3", "CON-cell.4"],
        None,
        "pbc is a length-3 boolean array. A missing key is fully periodic.",
    ),
    (
        "valid",
        "lattice-vectors",
        "valid/lattice_vectors.con",
        "CON-cell.1",
        ["CON-cell.1", "CON-cell.2", "CON-cell.5"],
        None,
        "lattice_vectors is preferred over lines 3-4.",
    ),
    (
        "valid",
        "cell-angles",
        "valid/cell_angles.con",
        "CON-cell.6",
        ["CON-cell.6", "CON-header.3"],
        None,
        "The cell matrix comes from lines 3-4.",
    ),
    (
        "valid",
        "legacy-velocity",
        "valid/legacy_velocity.con",
        "CON-section.1",
        ["CON-section.1", "CON-section.2", "CON-units.8"],
        None,
        "Legacy velocity fallback, no sections key.",
    ),
    (
        "valid",
        "four-column",
        "valid/four_column.con",
        "CON-id.9",
        ["CON-id.8", "CON-id.9"],
        None,
        "A 4-column row takes the 0-based position as its id.",
    ),
    (
        "valid",
        "big-id",
        "valid/big_id.con",
        "CON-id.1",
        ["CON-id.1", "CON-id.2"],
        None,
        "An id above 2^53 is an integer, not binary64.",
    ),
    (
        "valid",
        "repeated-ids",
        "valid/repeated_ids.con",
        "CON-id.4",
        ["CON-id.4", "CON-id.5", "CON-id.6"],
        None,
        "Repeated ids stay in file order.",
    ),
    (
        "valid",
        "tabs",
        "valid/tabs.con",
        "CON-token.3",
        ["CON-token.3"],
        None,
        "Tab-separated cells.",
    ),
    (
        "valid",
        "exponent",
        "valid/exponent.con",
        "CON-token.2",
        ["CON-token.2", "CON-num.5"],
        None,
        "A leading dot and an exponent are finite decimals.",
    ),
    (
        "valid",
        "two-types",
        "valid/two_types.con",
        "CON-count.6",
        [
            "CON-count.6",
            "CON-count.7",
            "CON-count.8",
            "CON-id.3",
            "CON-id.7",
            "CON-mask.4",
            "CON-mask.6",
            "CON-mask.7",
        ],
        None,
        "Two types, unique ids, masks 0, 3, and 7.",
    ),
    (
        "valid",
        "energies",
        "valid/energies.con",
        "CON-section.5",
        ["CON-section.4", "CON-section.5", "CON-section.18", "CON-section.19"],
        None,
        "The energies section, with a matching total.",
    ),
    (
        "valid",
        "v31-velocities",
        "valid/v31_velocities.con",
        "CON-units.5",
        [
            "CON-units.2",
            "CON-units.3",
            "CON-units.4",
            "CON-units.5",
            "CON-units.10",
            "CON-units.12",
            "CON-units.13",
            "CON-units.14",
            "CON-units.15",
            "CON-num.6",
            "CON-num.7",
        ],
        None,
        "Minor 1 velocities use the natural time spelling.",
    ),
    (
        "valid",
        "v30-fs-label",
        "valid/v30_fs_label.con",
        "CON-units.9",
        ["CON-units.8", "CON-units.9"],
        None,
        "A v3.0 time label is not trusted.",
    ),
    (
        "valid",
        "v1-plain",
        "valid/v1_plain.con",
        "CON-units.6",
        ["CON-units.6", "CON-mask.2", "CON-token.1"],
        None,
        "Version 1 has no units object.",
    ),
    (
        "valid",
        "v2-with-units",
        "valid/v2_with_units.con",
        "CON-units.7",
        ["CON-units.7"],
        None,
        "Version 2 may carry units.",
    ),
    (
        "valid",
        "unit-names",
        "valid/unit_names.con",
        "CON-units.16",
        ["CON-units.16", "CON-units.1"],
        None,
        "metre, joule, dalton, and fs are accepted names.",
    ),
    (
        "valid",
        "unknown-minor-skip",
        "valid/unknown_minor_skip.con",
        "CON-section.8",
        [
            "CON-status.1",
            "CON-line2.7",
            "CON-section.8",
            "CON-section.10",
            "CON-section.11",
            "CON-section.12",
            "CON-section.14",
            "CON-section.16",
            "CON-token.4",
        ],
        None,
        "A newer minor may skip a section declared in section_arity.",
    ),
    (
        "valid",
        "bonds-preserved",
        "valid/bonds_preserved.con",
        "CON-bonds.1",
        ["CON-bonds.1"],
        None,
        "bonds stays out of sections.",
    ),
    (
        "valid",
        "bonds-loose",
        "valid/bonds_loose.con",
        "CON-bonds.3",
        ["CON-bonds.3", "CON-validate.2", "CON-section.17"],
        None,
        "validate false keeps an unknown bonds shape.",
    ),
    (
        "valid",
        "header-lines",
        "valid/header_lines.con",
        "CON-header.2",
        ["CON-header.1", "CON-header.2"],
        None,
        "Lines 1, 5, and 6 are preserved.",
    ),
    (
        "valid",
        "gzip-multi",
        "valid/gzip_multi.con.gz",
        "CON-compress.1",
        ["CON-compress.1"],
        2,
        "Both gzip members are CON text, in order.",
    ),
    (
        "valid",
        "gzip-magic",
        "valid/gzip_magic.con",
        "CON-compress.3",
        ["CON-compress.3"],
        1,
        "Gzip is detected from the magic bytes.",
    ),
    (
        "valid",
        "zstd-multi",
        "valid/zstd_multi.con.zst",
        "CON-compress.2",
        ["CON-compress.2"],
        2,
        "Every zstd frame in the stream is CON text.",
    ),
    (
        "invalid",
        "truncated-header",
        "invalid/truncated_header.con",
        "CON-frame.3",
        ["CON-frame.2", "CON-frame.3"],
        None,
        "One to eight header lines are IncompleteHeader.",
    ),
    (
        "invalid",
        "truncated-rows",
        "invalid/truncated_rows.con",
        "CON-frame.4",
        ["CON-frame.4"],
        None,
        "Fewer coordinate rows than declared.",
    ),
    (
        "invalid",
        "truncated-multiframe",
        "invalid/truncated_multiframe.con",
        "CON-frame.2",
        ["CON-frame.2", "CON-error.4"],
        None,
        "A partial frame after a complete one is not dropped.",
    ),
    (
        "invalid",
        "incomplete-section",
        "invalid/incomplete_section.con",
        "CON-frame.6",
        ["CON-frame.6", "CON-section.3"],
        None,
        "A partial declared section.",
    ),
    (
        "invalid",
        "spec1-mask-2",
        "invalid/spec1_mask_2.con",
        "CON-mask.3",
        ["CON-mask.1", "CON-mask.3"],
        None,
        "Spec 1 column 4 value 2 is InvalidFixedFlag.",
    ),
    (
        "invalid",
        "spec1-mask-6",
        "invalid/spec1_mask_6.con",
        "CON-mask.3",
        ["CON-mask.5"],
        None,
        "Spec 1 column 4 value 6 is InvalidFixedFlag.",
    ),
    (
        "invalid",
        "float-column4",
        "invalid/float_column4.con",
        "CON-mask.5",
        ["CON-mask.5", "CON-error.3"],
        None,
        "A float spelling in column 4.",
    ),
    (
        "invalid",
        "nonfinite",
        "invalid/nonfinite.con",
        "CON-num.1",
        ["CON-num.1", "CON-num.2", "CON-num.3", "CON-num.4"],
        None,
        "NaN is NonFiniteValue in every mode.",
    ),
    (
        "invalid",
        "infinity",
        "invalid/infinity.con",
        "CON-num.1",
        ["CON-num.1"],
        None,
        "Inf is NonFiniteValue.",
    ),
    (
        "invalid",
        "bom",
        "invalid/bom.con",
        "CON-file.2",
        ["CON-file.2"],
        None,
        "A leading byte-order mark is rejected.",
    ),
    (
        "invalid",
        "atom-energies",
        "invalid/atom_energies.con",
        "CON-section.6",
        ["CON-section.6", "CON-section.7"],
        None,
        "atom_energies is not a section name.",
    ),
    (
        "invalid",
        "unknown-minor-no-arity",
        "invalid/unknown_minor_no_arity.con",
        "CON-section.9",
        ["CON-section.9"],
        None,
        "A newer minor without section_arity is UnknownSection.",
    ),
    (
        "invalid",
        "bad-json",
        "invalid/bad_json.con",
        "CON-line2.2",
        ["CON-line2.2"],
        None,
        "Malformed JSON on line 2.",
    ),
    (
        "invalid",
        "version-zero",
        "invalid/version_zero.con",
        "CON-line2.5",
        ["CON-line2.5", "CON-line2.6"],
        None,
        "JSON major 0 is UnsupportedVersion.",
    ),
    (
        "invalid",
        "bad-minor",
        "invalid/bad_minor.con",
        "CON-line2.9",
        ["CON-line2.9", "CON-line2.13"],
        None,
        "con_spec_minor must be an integer >= 0.",
    ),
    (
        "invalid",
        "validate-type",
        "invalid/validate_type.con",
        "CON-line2.12",
        ["CON-line2.12"],
        None,
        "validate must be a boolean.",
    ),
    (
        "invalid",
        "sections-type",
        "invalid/sections_type.con",
        "CON-line2.11",
        ["CON-line2.11"],
        None,
        "sections must be an array of strings.",
    ),
    (
        "invalid",
        "signed-count",
        "invalid/signed_count.con",
        "CON-error.3",
        ["CON-error.3", "CON-count.3"],
        None,
        "A signed count is InvalidCount.",
    ),
    (
        "invalid",
        "bad-id",
        "invalid/bad_id.con",
        "CON-id.1",
        ["CON-error.3"],
        None,
        "A signed column 5 is InvalidNumberFormat.",
    ),
    (
        "invalid",
        "bad-number",
        "invalid/bad_number.con",
        "CON-num.8",
        ["CON-num.8"],
        None,
        "A token that is not a decimal is InvalidNumberFormat.",
    ),
    (
        "invalid",
        "short-row",
        "invalid/short_row.con",
        "CON-num.9",
        ["CON-num.9"],
        None,
        "The wrong number of fields is InvalidVectorLength.",
    ),
    (
        "invalid",
        "missing-time",
        "invalid/missing_time.con",
        "CON-units.11",
        ["CON-units.11"],
        None,
        "Minor 1 velocities require units.time.",
    ),
    (
        "invalid",
        "bad-pbc",
        "invalid/bad_pbc.con",
        "CON-cell.4",
        ["CON-validate.1", "CON-validate.4"],
        None,
        "validate true rejects a short pbc array.",
    ),
    (
        "invalid",
        "bad-bonds",
        "invalid/bad_bonds.con",
        "CON-bonds.2",
        ["CON-bonds.2"],
        None,
        "validate true rejects a malformed bonds entry.",
    ),
    (
        "invalid",
        "bad-symbol",
        "invalid/bad_symbol.con",
        "CON-validate.4",
        ["CON-validate.4"],
        None,
        "validate true rejects an unrecognized symbol.",
    ),
    (
        "invalid",
        "negative-spread",
        "invalid/negative_spread.con",
        "CON-section.20",
        ["CON-section.20"],
        None,
        "A negative spread is rejected.",
    ),
    (
        "invalid",
        "reserved-arity",
        "invalid/reserved_arity.con",
        "CON-section.13",
        ["CON-section.13"],
        None,
        "A reserved section arity must match the row shape.",
    ),
    (
        "valid",
        "eon-slab",
        "valid/eon_slab.con",
        "CON-units.8",
        ["CON-units.8"],
        None,
        "eOn 3.6.0 Pt slab with 17-digit coordinates.",
    ),
    (
        "valid",
        "eon-convel",
        "valid/eon_slab.convel",
        "CON-units.9",
        ["CON-units.9", "CON-num.7"],
        None,
        "eOn 3.6.0 convel. Six-decimal velocities under a fs label.",
    ),
    (
        "valid",
        "eon-forces",
        "valid/eon_forces.con",
        "CON-section.2",
        ["CON-section.2"],
        None,
        "eOn 3.6.0 frame written with forces.",
    ),
    (
        "valid",
        "ase-single",
        "valid/ase_single.con",
        "CON-id.9",
        ["CON-id.9"],
        None,
        "ASE 3.29 write_eon, one frame.",
    ),
    (
        "valid",
        "ase-multi",
        "valid/ase_multi.con",
        "CON-frame.7",
        ["CON-frame.7"],
        2,
        "ASE 3.29 write_eon, two frames.",
    ),
]

EXISTING = {
    "v2-minimal": [
        "CON-status.2",
        "CON-line2.1",
        "CON-line2.4",
        "CON-line2.10",
        "CON-header.1",
    ],
    "v3-units": ["CON-units.1", "CON-line2.10"],
    "column-4-spec2-x-only": ["CON-mask.4"],
    "column-4-spec1-all-fixed": ["CON-mask.2"],
    "column-4-spec2-all-fixed": ["CON-mask.7"],
    "column-4-spec2-y-only": ["CON-mask.4"],
    "column-4-spec2-xz": ["CON-mask.4"],
    "zero-atom": ["CON-count.1", "CON-count.2", "CON-count.5"],
    "zero-atom-eof": ["CON-count.4"],
    "zero-atom-then-frame": ["CON-count.1", "CON-frame.7"],
    "missing-spec-version": ["CON-line2.3", "CON-error.1", "CON-error.2"],
    "v3-missing-units": ["CON-units.1"],
    "v3-bad-units": ["CON-units.13"],
    "column-4-out-of-range": ["CON-mask.5"],
    "unsupported-spec-version": ["CON-line2.6"],
    "unknown-section": ["CON-section.7"],
    "validate-true-missing-sections": ["CON-validate.3"],
    "per-type-zero": ["CON-count.3"],
}

ERRORS = {
    "truncated-header": "IncompleteHeader",
    "truncated-rows": "IncompleteFrame",
    "truncated-multiframe": "IncompleteHeader",
    "incomplete-section": "IncompleteSection",
    "spec1-mask-2": "InvalidFixedFlag",
    "spec1-mask-6": "InvalidFixedFlag",
    "float-column4": "InvalidFixedFlag",
    "nonfinite": "NonFiniteValue",
    "infinity": "NonFiniteValue",
    "bom": "ValidationError",
    "atom-energies": "UnknownSection",
    "unknown-minor-no-arity": "UnknownSection",
    "bad-json": "InvalidMetadataJson",
    "version-zero": "UnsupportedVersion",
    "bad-minor": "InvalidMetadataJson",
    "validate-type": "InvalidMetadataJson",
    "sections-type": "InvalidMetadataJson",
    "signed-count": "InvalidCount",
    "bad-id": "InvalidNumberFormat",
    "bad-number": "InvalidNumberFormat",
    "short-row": "InvalidVectorLength",
    "missing-time": "InvalidUnits",
    "bad-pbc": "InvalidMetadataJson",
    "bad-bonds": "InvalidMetadataJson",
    "bad-symbol": "ValidationError",
    "negative-spread": "ValidationError",
    "reserved-arity": "InvalidVectorLength",
}


def toml_array(ids):
    return "[" + ", ".join(f'"{item}"' for item in ids) + "]"


def render_case(kind, cid, path, clause, clauses, frames, notes):
    lines = [
        f"[[{kind}]]",
        f'id = "{cid}"',
        f'path = "{path}"',
        f'clause = "{clause}"',
        f"clauses = {toml_array(clauses)}",
    ]
    if frames is not None:
        lines.append(f"frames = {frames}")
    if kind == "invalid":
        lines.append(f'error = "{ERRORS[cid]}"')
    lines.append(f'notes = "{notes}"')
    lines.append("")
    return "\n".join(lines)


def inject_existing(text: str) -> str:
    blocks = []
    current = []
    cid = None
    for line in text.splitlines(keepends=True):
        if line.startswith("[[valid]]") or line.startswith("[[invalid]]"):
            if current:
                blocks.append((cid, current))
            current = [line]
            cid = None
            continue
        if line.startswith("id = "):
            cid = line.split("=", 1)[1].strip().strip('"')
        current.append(line)
    if current:
        blocks.append((cid, current))
    rebuilt = []
    for cid, chunk in blocks:
        body = "".join(chunk)
        if cid in EXISTING and "clauses =" not in body:
            extra = f"clauses = {toml_array(EXISTING[cid])}\n"
            # Place the clauses line after the clause line.
            body = body.replace('clause = "', 'clause = "', 1)
            lines = body.splitlines(keepends=True)
            out_lines = []
            inserted = False
            for line in lines:
                out_lines.append(line)
                if not inserted and line.startswith("clause = "):
                    out_lines.append(extra)
                    inserted = True
            body = "".join(out_lines)
        rebuilt.append(body)
    return "".join(rebuilt)


def main():
    build()
    text = MANIFEST.read_text()
    # Drop a previous generated tail so the script is repeatable.
    marker = "\n# Clause fixtures generated by scripts/gen_conformance_fixtures.py\n"
    if marker in text:
        text = text.split(marker, 1)[0]
    if not text.endswith("\n"):
        text += "\n"
    text = inject_existing(text)
    tail = [marker]
    for row in CASES:
        tail.append(render_case(*row))
    MANIFEST.write_text(text + "".join(tail))
    print(f"wrote {len(CASES)} cases")


if __name__ == "__main__":
    main()
