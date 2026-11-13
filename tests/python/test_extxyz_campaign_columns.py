# Copyright (c) readcon-core developers
"""The campaign property list comes back for one element and for an alloy.

The serial reader must visit every atom. A file of one element keeps the
same columns as a file whose symbols change, including velocity, id, and
the fixed mask.
"""

import readcon


def _frame(symbols, rows):
    lines = [
        str(len(rows)),
        (
            'Lattice="100.0 0 0 0 100.0 0 0 0 100.0" '
            "Properties=species:S:1:pos:R:3:masses:R:1:vel:R:3:id:R:1:fixed:R:1 "
            'pbc="T T T"'
        ),
    ]
    lines.extend(rows)
    return "\n".join(lines) + "\n", symbols


def test_campaign_columns_match_for_one_element_and_an_alloy(tmp_path):
    copper, copper_symbols = _frame(
        ["Cu", "Cu"],
        [
            "Cu 0.0 1.0 2.0 63.546 0.125000 -0.250000 0.500000 2 0",
            "Cu 3.0 4.0 5.0 63.546 -0.125000 0.000000 -0.0 4 7",
        ],
    )
    alloy, alloy_symbols = _frame(
        ["Ag", "Au"],
        [
            "Ag 0.0 0.0 0.0 107.868 0.0 0.250000 0.500000 3 1",
            "Au 1.0 0.0 0.0 196.967 0.125000 0.000000 0.000000 4 4",
        ],
    )
    path = tmp_path / "campaign.extxyz"
    path.write_text(copper + alloy, encoding="utf-8")
    got = readcon.read_extxyz(str(path), n_threads=1)
    assert [list(row) for row in got["species"]] == [copper_symbols, alloy_symbols]
    assert got["species"][0] is not got["species"][1]
    assert got["positions"].shape == (2, 2, 3)
    assert got["positions"][0, 1].tolist() == [3.0, 4.0, 5.0]
    assert got["masses"][0].tolist() == [63.546, 63.546]
    assert got["masses"][1].tolist() == [107.868, 196.967]
    assert got["arrays"]["vel"][0, 0].tolist() == [0.125, -0.25, 0.5]
    assert got["arrays"]["vel"][0, 1, 0] == -0.125
    assert got["arrays"]["id"][0].tolist() == [2.0, 4.0]
    assert got["arrays"]["fixed"][0].tolist() == [0.0, 7.0]
    assert got["arrays"]["id"][1].tolist() == [3.0, 4.0]
    assert got["arrays"]["fixed"][1].tolist() == [1.0, 4.0]
    assert got["cell"][0, 0] == 100.0
    assert got["cell"][0, 3] == 90.0
    assert got["arrays"]["pos"] is got["positions"]
    assert got["arrays"]["masses"] is got["masses"]
    assert got["arrays"]["species"] is got["species"]
