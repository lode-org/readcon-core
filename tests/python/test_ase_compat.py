"""ASE 3.29 read_eon against the conformance corpus.

The compatibility table says ASE stores line 2 as text, reads column 4 with
bool(int), reads a 4-column line, has no gzip decoder in ase/io/eon.py, and
does not parse a section that follows a blank line. Multi-frame reads use
index=":". Rows below are the measured ASE 3.29.0 result for each fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ase = pytest.importorskip("ase")
from ase.io import read

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "resources" / "conformance"

# path -> (image count, or None when read raises). Exception type is separate.
READ_COUNTS = {
    "valid/ase_multi.con": 2,
    "valid/ase_single.con": 1,
    "valid/big_id.con": 1,
    "valid/blank_then_eof.con": 1,
    "valid/bonds_loose.con": 1,
    "valid/bonds_preserved.con": 1,
    "valid/cell_angles.con": 1,
    "valid/column4_spec1_all_fixed.con": 1,
    "valid/column4_spec2_all_fixed.con": 1,
    "valid/column4_spec2_x_only.con": 1,
    "valid/column4_spec2_xz.con": 1,
    "valid/column4_spec2_y_only.con": 1,
    "valid/crlf.con": 1,
    "valid/energies.con": 1,
    "valid/eon_slab.con": 1,
    "valid/exponent.con": 1,
    "valid/four_column.con": 1,
    "valid/gzip_multi.con.gz": 2,
    "valid/header_lines.con": 1,
    "valid/label_case.con": 1,
    "valid/lattice_vectors.con": 1,
    "valid/legacy_velocity.con": 1,
    "valid/pbc_partial.con": 1,
    "valid/repeated_ids.con": 1,
    "valid/sections_empty.con": 1,
    "valid/tabs.con": 1,
    "valid/trailing_blanks.con": 1,
    "valid/trailing_spaces.con": 1,
    "valid/two_frames.con": 2,
    "valid/two_types.con": 1,
    "valid/unit_names.con": 1,
    "valid/unknown_key.con": 1,
    "valid/unknown_minor_skip.con": 1,
    "valid/v1_plain.con": 1,
    "valid/v2_minimal.con": 1,
    "valid/v2_with_units.con": 1,
    "valid/v30_fs_label.con": 1,
    "valid/v31_velocities.con": 1,
    "valid/v3_units.con": 1,
    "valid/zero_atom.con": 1,
    "valid/zero_atom_eof.con": 0,
    "valid/zero_atom_then_frame.con": 2,
    "invalid/atom_energies.con": 1,
    "invalid/bad_bonds.con": 1,
    "invalid/bad_id.con": 1,
    "invalid/bad_json.con": 1,
    "invalid/bad_minor.con": 1,
    "invalid/bad_pbc.con": 1,
    "invalid/bom.con": 1,
    "invalid/column4_out_of_range.con": 1,
    "invalid/incomplete_section.con": 1,
    "invalid/infinity.con": 1,
    "invalid/missing_spec_version.con": 1,
    "invalid/missing_time.con": 1,
    "invalid/negative_spread.con": 1,
    "invalid/nonfinite.con": 1,
    "invalid/reserved_arity.con": 1,
    "invalid/sections_type.con": 1,
    "invalid/spec1_mask_2.con": 1,
    "invalid/spec1_mask_6.con": 1,
    "invalid/truncated_header.con": 0,
    "invalid/truncated_multiframe.con": 1,
    "invalid/unknown_minor_no_arity.con": 1,
    "invalid/unknown_section.con": 1,
    "invalid/unsupported_spec_version.con": 1,
    "invalid/v3_bad_units.con": 1,
    "invalid/v3_missing_units.con": 1,
    "invalid/validate_true_missing_sections.con": 1,
    "invalid/validate_type.con": 1,
    "invalid/version_zero.con": 1,
}

FAILS = {
    "valid/eon_forces.con": ValueError,
    "valid/eon_slab.convel": ValueError,
    "valid/gzip_magic.con": UnicodeDecodeError,
    "valid/zstd_multi.con.zst": UnicodeDecodeError,
    "invalid/bad_number.con": ValueError,
    "invalid/bad_symbol.con": KeyError,
    "invalid/float_column4.con": ValueError,
    "invalid/per_type_zero.con": RuntimeError,
    "invalid/short_row.con": IndexError,
    "invalid/signed_count.con": IndexError,
    "invalid/truncated_rows.con": RuntimeError,
}


def _corpus_files():
    found = []
    for kind in ("valid", "invalid"):
        for path in sorted((CORPUS / kind).iterdir()):
            if path.is_file():
                found.append(f"{kind}/{path.name}")
    return found


def test_ase_map_covers_the_corpus():
    files = set(_corpus_files())
    assert set(READ_COUNTS).isdisjoint(FAILS)
    assert set(READ_COUNTS) | set(FAILS) == files


@pytest.mark.parametrize("rel", sorted(READ_COUNTS))
def test_ase_reads_with_index_slice(rel):
    images = read(CORPUS / rel, format="eon", index=":")
    assert isinstance(images, list)
    assert len(images) == READ_COUNTS[rel]


@pytest.mark.parametrize("rel", sorted(FAILS))
def test_ase_rejects_with_index_slice(rel):
    with pytest.raises(FAILS[rel]):
        read(CORPUS / rel, format="eon", index=":")


def test_table_rules_that_ase_329_follows():
    # bool(int(tokens[3])): a float column 4 fails, integer masks 2 and 6 read.
    with pytest.raises(ValueError):
        read(CORPUS / "invalid/float_column4.con", format="eon", index=":")
    assert len(read(CORPUS / "invalid/spec1_mask_2.con", format="eon", index=":")) == 1
    assert len(read(CORPUS / "invalid/spec1_mask_6.con", format="eon", index=":")) == 1
    # Four columns are enough for the ASE reader.
    assert len(read(CORPUS / "valid/four_column.con", format="eon", index=":")) == 1
    # Line 2 is stored as text, so invalid JSON still returns a frame.
    assert len(read(CORPUS / "invalid/bad_json.con", format="eon", index=":")) == 1
    # eon.py has no gzip or zstd decoder. A .con name keeps the magic bytes.
    with pytest.raises(UnicodeDecodeError):
        read(CORPUS / "valid/gzip_magic.con", format="eon", index=":")
    with pytest.raises(UnicodeDecodeError):
        read(CORPUS / "valid/zstd_multi.con.zst", format="eon", index=":")
    # A section label after the coordinate block is not a numeric header.
    with pytest.raises(ValueError, match="Forces"):
        read(CORPUS / "valid/eon_forces.con", format="eon", index=":")
    with pytest.raises(ValueError, match="Velocities"):
        read(CORPUS / "valid/eon_slab.convel", format="eon", index=":")
