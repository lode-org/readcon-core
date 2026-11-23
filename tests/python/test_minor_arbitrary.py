"""Arbitrary-size con_spec_minor acceptance, regression, and BASE-oracle parity tests."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import readcon

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_ORACLE_PATH = REPO_ROOT / "tests" / "fixtures" / "base_oracle_9aff911e.json"
TWO_POW_64 = 2**64
TWO_POW_64_PLUS_1 = 2**64 + 1
FORTY_DIGITS = 10**39 + 7
THREE_HUNDRED_DIGITS = 10**299 + 7
FOUR_HUNDRED_DIGITS = 10**399 + 7
_F64_MAX_INT = (2**53 - 1) * 2**971
F64_MAX_PLUS_1 = _F64_MAX_INT + 1
F64_MAX_LAST_FINITE = _F64_MAX_INT + 2**970 - 1
F64_MAX_OVERFLOW = _F64_MAX_INT + 2**970


def _d14_minor_2pow64_text() -> str:
    return (
        "gen\n"
        f'{{"con_spec_version":3,"con_spec_minor":{TWO_POW_64},"units":{{"length":"angstrom","energy":"eV"}}}}\n'
        "10.0 10.0 10.0\n"
        "90.0 90.0 90.0\n"
        "\n"
        "\n"
        "1\n"
        "2\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
        "1.0 1.0 1.0 0 1\n"
    )


def _v2_minor_2pow64_text() -> str:
    return (
        "corpus31 version 2 con_spec_minor 2^64\n"
        f'{{"con_spec_version":2,"con_spec_minor":{TWO_POW_64}}}\n'
        "10.0 10.0 10.0\n"
        "90.0 90.0 90.0\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "2\n"
        "195.084\n"
        "Pt\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
        "2.5 2.5 0.0 0 1\n"
    )


def _v3_text(minor: int) -> str:
    return (
        "gen\n"
        f'{{"con_spec_version":3,"con_spec_minor":{minor},"units":{{"length":"angstrom","energy":"eV"}}}}\n'
        "10.0 10.0 10.0\n"
        "90.0 90.0 90.0\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
    )


def _json_value_eq(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if a == 0.0 and b == 0.0:
            return math.copysign(1.0, a) == math.copysign(1.0, b)
        return a == b
    if isinstance(a, list):
        return len(a) == len(b) and all(_json_value_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_json_value_eq(a[k], b[k]) for k in a)
    return a == b


@pytest.mark.parametrize(
    ("name", "text", "expected_major", "expected_minor", "expected_atoms"),
    [
        ("d14_minor_2pow64.con", _d14_minor_2pow64_text(), 3, TWO_POW_64, 2),
        ("v2_minor_2pow64.con", _v2_minor_2pow64_text(), 2, TWO_POW_64, 2),
        (
            "minor_2pow64_plus_1.con",
            _v3_text(TWO_POW_64_PLUS_1),
            3,
            TWO_POW_64_PLUS_1,
            1,
        ),
        ("minor_40_digits.con", _v3_text(FORTY_DIGITS), 3, FORTY_DIGITS, 1),
        (
            "minor_300_digits.con",
            _v3_text(THREE_HUNDRED_DIGITS),
            3,
            THREE_HUNDRED_DIGITS,
            1,
        ),
    ],
)
def test_every_python_read_path_accepts_and_roundtrips_arbitrary_minor(
    tmp_path, name, text, expected_major, expected_minor, expected_atoms
):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    p = str(path)

    for frames in (
        readcon.read_con(p),
        readcon.read_con(p, n_threads=1),
        readcon.read_con(p, n_threads=2),
        readcon.read_all_frames(p),
        readcon.read_con_phases(p, build="lazy")[0],
        readcon.read_con_phases(p, build="eager")[0],
        readcon.read_con_string(text),
    ):
        assert len(frames) == 1
        frame = frames[0]
        assert frame.spec_version == expected_major
        assert len(frame) == expected_atoms
        got_minor = frame.metadata["con_spec_minor"]
        assert type(got_minor) is int
        assert got_minor == expected_minor

    for frame in (
        readcon.read_first_frame(p),
        readcon.read_nth_frame(p, 0),
        *list(readcon.iter_con(p)),
        *list(readcon.iter_con(p, mmap=True)),
        *list(readcon.iter_con(p, stream=True)),
        readcon.ConTrajectory(p, write_index=False)[0],
    ):
        assert frame.spec_version == expected_major
        assert type(frame.metadata["con_spec_minor"]) is int
        assert frame.metadata["con_spec_minor"] == expected_minor

    assert readcon.count_frames(p) == 1
    assert readcon.read_positions(p).shape == (1, expected_atoms, 3)
    coords = readcon.read_coords(p)
    assert coords["positions"].shape == (1, expected_atoms, 3)

    # Borrow-path write_con_string / write_con keep exact digits.
    frames = readcon.read_con(p)
    rewritten_str = readcon.write_con_string(frames)
    line2 = json.loads(rewritten_str.splitlines()[1])
    assert line2["con_spec_version"] == (3 if expected_major == 3 else 4)
    assert type(line2["con_spec_minor"]) is int
    assert line2["con_spec_minor"] == expected_minor
    reread = readcon.read_con_string(rewritten_str)
    assert reread[0].metadata["con_spec_minor"] == expected_minor

    out_path = tmp_path / f"out_{name}"
    readcon.write_con(str(out_path), frames)
    assert (
        readcon.read_con(str(out_path))[0].metadata["con_spec_minor"] == expected_minor
    )

    # Materialized (.atoms accessed) write_con_string also preserves exact digits.
    _ = frames[0].atoms
    rewritten_mat = readcon.write_con_string(frames)
    assert (
        readcon.read_con_string(rewritten_mat)[0].metadata["con_spec_minor"]
        == expected_minor
    )

    # Direct ConFrame construction and set_metadata / set_metadata_json round-trip.
    manual = readcon.ConFrame(
        [10.0, 10.0, 10.0],
        [90.0, 90.0, 90.0],
        [readcon.Atom("H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0)],
        metadata={
            "con_spec_minor": expected_minor,
            "units": {"length": "angstrom", "energy": "eV"},
        },
    )
    assert (
        readcon.read_con_string(readcon.write_con_string([manual]))[0].metadata[
            "con_spec_minor"
        ]
        == expected_minor
    )

    manual.set_metadata_json(
        json.dumps(
            {
                "con_spec_version": 3,
                "con_spec_minor": expected_minor,
                "units": {"length": "angstrom", "energy": "eV"},
            }
        )
    )
    assert manual.metadata["con_spec_minor"] == expected_minor


def test_over_f64_max_minor_400_digits_rejected_like_base():
    with pytest.raises(
        readcon.InvalidMetadataJson,
        match="number out of range at line 1 column 439",
    ):
        readcon.read_con_string(_v3_text(FOUR_HUNDRED_DIGITS))

    with pytest.raises((OverflowError, ValueError)):
        readcon.ConFrame(
            [10.0, 10.0, 10.0],
            [90.0, 90.0, 90.0],
            [readcon.Atom("H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0)],
            metadata={
                "con_spec_minor": FOUR_HUNDRED_DIGITS,
                "units": {"length": "angstrom", "energy": "eV"},
            },
        )


def test_arbitrary_minor_ase_velocity_honors_units_time(tmp_path):
    pytest.importorskip("ase")
    template = (
        "gen\n"
        '{{"con_spec_version":{major},"con_spec_minor":{minor},"units":{{"length":"angstrom","energy":"eV","time":"fs"}},"sections":["velocities"]}}\n'
        "10.0 10.0 10.0\n"
        "90.0 90.0 90.0\n"
        "\n"
        "\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
        "\n"
        "H\n"
        "Velocities of Component 1\n"
        "1.0 0.0 0.0 0 0\n"
    )
    path_v4 = tmp_path / "vel_40_digits_v4.convel"
    path_v4.write_text(template.format(major=4, minor=FORTY_DIGITS), encoding="utf-8")
    atoms_v4 = readcon.read_con_as_ase(str(path_v4))
    assert len(atoms_v4) == 1
    assert atoms_v4[0].get_velocities()[0, 0] == pytest.approx(10.1805057, rel=1e-5)

    path_v3 = tmp_path / "vel_40_digits_v3.convel"
    path_v3.write_text(template.format(major=3, minor=FORTY_DIGITS), encoding="utf-8")
    with pytest.warns(UserWarning, match="units.time fs is not applied"):
        atoms_v3 = readcon.read_con_as_ase(str(path_v3))
    assert len(atoms_v3) == 1
    assert atoms_v3[0].get_velocities()[0, 0] == pytest.approx(1.0, rel=1e-5)


@pytest.mark.parametrize(
    "bad_raw",
    [
        "-1",
        f"-{TWO_POW_64}",
        "-0",
        "+1",
        "01",
        "1.0",
        "1.5",
        f"{TWO_POW_64}.0",
        "1e0",
        "1e2",
        '"1"',
        f'"{TWO_POW_64}"',
    ],
)
def test_invalid_con_spec_minor_rejected_in_python(bad_raw):
    text = (
        "gen\n"
        f'{{"con_spec_version":3,"con_spec_minor":{bad_raw},"units":{{"length":"angstrom","energy":"eV"}}}}\n'
        "10.0 10.0 10.0\n"
        "90.0 90.0 90.0\n"
        "\n"
        "\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
    )
    with pytest.raises(readcon.InvalidMetadataJson):
        readcon.read_con_string(text)


def test_v4_blockers_and_duplicate_semantics_in_python():
    # 1. neb_band.con and neb_band_3.con write -1.2 (not -1.20) on borrow & materialized paths.
    for rel in (
        "resources/examples/neb_band.con",
        "bench/fidelity/fixtures/neb_band_3.con",
    ):
        frames = readcon.read_con(str(REPO_ROOT / rel))
        borrow_out = readcon.write_con_string(frames)
        assert '"energy":-1.2' in borrow_out
        assert "-1.20" not in borrow_out
        _ = frames[0].atoms
        mat_out = readcon.write_con_string(frames)
        assert '"energy":-1.2' in mat_out
        assert "-1.20" not in mat_out

    # 2. energy: -0 remains float(-0.0), not int(0).
    neg_zero_energy = (
        'gen\n{"con_spec_version":2,"energy":-0}\n10 10 10\n90 90 90\n\n\n'
        "1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
    )
    f = readcon.read_con_string(neg_zero_energy)[0]
    e = f.metadata["energy"]
    assert type(e) is float and e == 0.0 and math.copysign(1.0, e) < 0

    # 3. Repeated object keys are rejected (CON-line2.23).
    for line2 in (
        '{"con_spec_version":3,"con_spec_minor":-0,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"}}',
        f'{{"con_spec_version":3,"con_spec_minor":-0,"con_spec_minor":{TWO_POW_64},"units":{{"length":"angstrom","energy":"eV"}}}}',
    ):
        txt = f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n0\n\n\n"
        with pytest.raises(
            readcon.InvalidMetadataJson, match="duplicate con_spec_minor key"
        ):
            readcon.read_con_string(txt)
    for line2 in (
        '{"con_spec_version":-0,"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}',
        '{"con_spec_version":2,"section_arity":{"widgets":-0,"widgets":2}}',
    ):
        txt = f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n0\n\n\n"
        with pytest.raises(readcon.InvalidMetadataJson, match="repeats a name"):
            readcon.read_con_string(txt)

    # 4. Last-key -0, frame_index:-0, section_arity >= 2^64, and major overflow match BASE.
    for line2 in (
        '{"con_spec_version":2,"sections":[],"validate":true,"frame_index":-0}',
        '{"con_spec_version":2,"section_arity":{"widgets":-0}}',
        f'{{"con_spec_version":2,"section_arity":{{"widgets":{TWO_POW_64}}}}}',
        f'{{"con_spec_version":3,"units":{{"length":"angstrom","energy":"eV"}},"section_arity":{{"velocities":{TWO_POW_64}}}}}',
        '{"con_spec_version":-0}',
        f'{{"con_spec_version":{TWO_POW_64}}}',
        '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}',
        f'{{"con_spec_version":3,"con_spec_minor":{TWO_POW_64},"con_spec_minor":-0,"units":{{"length":"angstrom","energy":"eV"}}}}',
    ):
        txt = f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n0\n\n\n"
        with pytest.raises(readcon.InvalidMetadataJson) as exc_info:
            readcon.read_con_string(txt)
        if line2.count("con_spec_minor") > 1:
            assert "duplicate con_spec_minor key" in str(exc_info.value)

    # 5. Exact column positions preserved after serde-valid huge con_spec_minor;
    #    400-digit minor (> f64::MAX) surfaces BASE's own column 418 error.
    for line2, want_msg in (
        (
            f'{{"con_spec_minor":{TWO_POW_64},"energy":1e999,"con_spec_version":2}}',
            "number out of range at line 1 column 53",
        ),
        (
            f'{{"con_spec_minor":{FORTY_DIGITS},"energy":1e999,"con_spec_version":2}}',
            "number out of range at line 1 column 73",
        ),
        (
            f'{{"con_spec_minor":{THREE_HUNDRED_DIGITS},"energy":1e999,"con_spec_version":2}}',
            "number out of range at line 1 column 333",
        ),
        (
            f'{{"con_spec_minor":{FOUR_HUNDRED_DIGITS},"energy":1e999,"con_spec_version":2}}',
            "number out of range at line 1 column 418",
        ),
        (
            f'{{"con_spec_version":1{"0" * 398}7}}',
            "number out of range at line 1 column 420",
        ),
    ):
        txt = f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n0\n\n\n"
        with pytest.raises(readcon.InvalidMetadataJson, match=want_msg):
            readcon.read_con_string(txt)


def test_python_v5_b1_b2_b3_b4_base_parity():
    atom = readcon.Atom("H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0)
    # B1: set_metadata_json keeps BASE's exact "invalid metadata JSON: ..." text for JSON errors
    # and "invalid metadata: ..." for schema errors.
    frame = readcon.ConFrame([10.0, 10.0, 10.0], [90.0, 90.0, 90.0], [atom])
    for bad_json in (
        '{"con_spec_version":2,"x":1e999}',
        '{"con_spec_version":2,"x":,}',
        "[1, 2, 3]",
        f'{{"con_spec_minor":{FOUR_HUNDRED_DIGITS},"con_spec_version":2}}',
    ):
        with pytest.raises(ValueError) as exc_info:
            frame.set_metadata_json(bad_json)
        msg = str(exc_info.value)
        assert msg.startswith("invalid metadata JSON: "), msg
        assert "line 2:" not in msg, msg

    with pytest.raises(ValueError) as exc_info:
        frame.set_metadata_json('{"pbc":"not-a-bool"}')
    assert str(exc_info.value).startswith("invalid metadata: "), str(exc_info.value)

    # B2: set_metadata_json does not trim, preserving exact line/column and rejecting Unicode WS.
    for bad, want_sub in (
        (
            '\n{"con_spec_version":2,"x":1e999}',
            "number out of range at line 2 column 31",
        ),
        ('\n\n{"con_spec_version":2,"x":,}', "expected value at line 3 column 27"),
        (
            '  {"con_spec_version":2,"x":1e999}',
            "number out of range at line 1 column 33",
        ),
        ('\u00a0{"con_spec_version":2}', "expected value at line 1 column 1"),
        ('{"con_spec_version":2}\u2028', "trailing characters at line 1 column 23"),
        ('{"con_spec_version":2}\u2003', "trailing characters at line 1 column 23"),
        ('\x0b{"con_spec_version":2}', "expected value at line 1 column 1"),
        (
            f'{{"con_spec_version":2,"con_spec_minor":{TWO_POW_64}}}\x0c',
            "trailing characters at line 1 column 61",
        ),
    ):
        with pytest.raises(ValueError) as exc_info:
            frame.set_metadata_json(bad)
        msg = str(exc_info.value)
        assert msg.startswith("invalid metadata JSON: "), msg
        assert want_sub in msg, f"{bad!r} -> {msg}"

    # B3: a repeated con_spec_minor is rejected.
    for line2 in (
        '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
        '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":2,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
        f'{{"con_spec_version":3,"con_spec_minor":{TWO_POW_64},"con_spec_minor":7,"units":{{"length":"angstrom","energy":"eV"}},"sections":["velocities"]}}',
        f'{{"con_spec_version":3,"con_spec_minor":{TWO_POW_64},"con_spec_minor":18446744073709551615,"units":{{"length":"angstrom","energy":"eV"}},"sections":["velocities"]}}',
        '{"con_spec_version":3,"con_spec_minor":1,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
        '{"con_spec_version":3,"con_spec_minor":2,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
    ):
        txt = (
            f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
            "Coordinates of Component 1\n0 0 0 0 0\n\n"
            "H\nVelocities of Component 1\n0.1 0 0 0 0\n"
        )
        with pytest.raises(
            readcon.InvalidMetadataJson, match="duplicate con_spec_minor key"
        ):
            readcon.read_con_string(txt)
    # CON-line2.10 says a missing minor is 0. A nested key does not
    # supply it.
    for line2 in (
        '{"con_spec_version":3,"x":{"con_spec_minor":1},"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
        '{"con_spec_version":3,"x":{"con_spec_minor":1},"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}',
    ):
        txt = (
            f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
            "Coordinates of Component 1\n0 0 0 0 0\n\n"
            "H\nVelocities of Component 1\n0.1 0 0 0 0\n"
        )
        frames = readcon.read_con_string(txt)
        assert len(frames) == 1

    with pytest.raises(ValueError, match="duplicate con_spec_minor key") as exc_info:
        frame.set_metadata_json(
            '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":1}'
        )
    set_msg = str(exc_info.value)
    assert set_msg.startswith("invalid metadata JSON: "), set_msg
    assert "line 2:" not in set_msg

    # B4: float minors >= 2^64 (1e20, 1e300, float(2**64)) stay floats like BASE.
    for fval in (1e20, 1e300, float(TWO_POW_64)):
        f = readcon.ConFrame(
            [10.0, 10.0, 10.0],
            [90.0, 90.0, 90.0],
            [atom],
            metadata={"con_spec_minor": fval},
        )
        written = readcon.write_con_string([f])
        parsed_line2 = json.loads(written.splitlines()[1])
        assert isinstance(parsed_line2["con_spec_minor"], float), written
        assert parsed_line2["con_spec_minor"] == fval, written
        with pytest.raises(readcon.InvalidMetadataJson):
            readcon.read_con_string(written)

    # int subclass with deceptive __str__ must use true int.__str__ value, not __str__.
    class DeceptiveInt(int):
        def __str__(self) -> str:
            return "12345678901234567890"

    d = DeceptiveInt(TWO_POW_64_PLUS_1)
    fd = readcon.ConFrame(
        [10.0, 10.0, 10.0],
        [90.0, 90.0, 90.0],
        [atom],
        metadata={"con_spec_minor": d},
    )
    fd_out = readcon.write_con_string([fd])
    assert json.loads(fd_out.splitlines()[1])["con_spec_minor"] == TWO_POW_64_PLUS_1


def _velocity_text(line2: str) -> str:
    return (
        f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
        "Coordinates of Component 1\n0 0 0 0 0\n\n"
        "H\nVelocities of Component 1\n0.1 0 0 0 0\n"
    )


def test_binary64_half_ulp_minor_matches_other_bindings():
    natural_symbol = "(u*Å^2/eV)^0.5"
    for minor in (F64_MAX_PLUS_1, F64_MAX_LAST_FINITE):
        with_time_v3 = (
            '{"con_spec_version":3,"con_spec_minor":'
            f"{minor}"
            ',"units":{"length":"angstrom","energy":"eV","time":"fs"},'
            '"sections":["velocities"]}'
        )
        frames = readcon.read_con_string(_velocity_text(with_time_v3))
        assert frames[0].metadata["con_spec_minor"] == minor
        written = readcon.write_con_string(frames)
        assert f'"con_spec_minor":{minor}' in written
        assert f'"time":"{natural_symbol}"' in written

        with_time_v4 = (
            '{"con_spec_version":4,"con_spec_minor":'
            f"{minor}"
            ',"units":{"length":"angstrom","energy":"eV","time":"fs"},'
            '"sections":["velocities"]}'
        )
        frames_v4 = readcon.read_con_string(_velocity_text(with_time_v4))
        assert frames_v4[0].metadata["con_spec_minor"] == minor
        written_v4 = readcon.write_con_string(frames_v4)
        assert f'"con_spec_minor":{minor}' in written_v4
        assert '"time":"fs"' in written_v4

        no_time_v3 = (
            '{"con_spec_version":3,"con_spec_minor":'
            f"{minor}"
            ',"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}'
        )
        assert len(readcon.read_con_string(_velocity_text(no_time_v3))) == 1

        no_time_v4 = (
            '{"con_spec_version":4,"con_spec_minor":'
            f"{minor}"
            ',"units":{"length":"angstrom","energy":"eV"},"sections":["velocities"]}'
        )
        with pytest.raises(readcon.InvalidUnits):
            readcon.read_con_string(_velocity_text(no_time_v4))

        frame = readcon.ConFrame(
            [10.0, 10.0, 10.0],
            [90.0, 90.0, 90.0],
            [readcon.Atom("H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0)],
        )
        frame.set_metadata_json(with_time_v3)
        assert frame.metadata["con_spec_minor"] == minor

    over = (
        '{"con_spec_version":3,"con_spec_minor":'
        f"{F64_MAX_OVERFLOW}"
        ',"units":{"length":"angstrom","energy":"eV","time":"fs"}}'
    )
    with pytest.raises(readcon.InvalidMetadataJson, match="number out of range"):
        readcon.read_con_string(
            "gen\n"
            f"{over}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
            "Coordinates of Component 1\n0 0 0 0 0\n"
        )
    frame = readcon.ConFrame(
        [10.0, 10.0, 10.0],
        [90.0, 90.0, 90.0],
        [readcon.Atom("H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0)],
    )
    with pytest.raises(ValueError, match="number out of range") as exc_info:
        frame.set_metadata_json(over)
    assert str(exc_info.value).startswith("invalid metadata JSON: ")


def test_differential_against_committed_base_oracle_in_python():
    oracle = json.loads(BASE_ORACLE_PATH.read_text(encoding="utf-8"))
    assert (
        oracle["provenance"]["base_commit"]
        == "9aff911e809390163d2d7b08671145ad99f24496"
    )

    # 1. All 70 tracked corpus files match the committed BASE oracle.
    tracked = oracle["tracked_corpus"]
    assert len(tracked) == 70
    for rel, expected in tracked.items():
        p = str(REPO_ROOT / rel)
        if expected["status"] == "ok":
            frames = readcon.read_con(p)
            exp_frames = expected["frames"]
            assert len(frames) == len(exp_frames), rel
            for fr, exp_fr in zip(frames, exp_frames):
                assert fr.spec_version == exp_fr["spec_version"], rel
                exp_meta = {
                    k: v
                    for k, v in json.loads(exp_fr["metadata_json"]).items()
                    if k not in ("con_spec_version", "sections")
                }
                assert _json_value_eq(dict(fr.metadata), exp_meta), rel
        else:
            with pytest.raises(Exception) as exc_info:
                readcon.read_con(p)
            if rel == "resources/conformance/invalid/unsupported_spec_version.con":
                assert str(exc_info.value) == "unsupported con_spec_version: 5", rel
            elif "file begins with a byte-order mark" in expected[
                "error_message"
            ] and "frame begins with a byte-order mark" in str(exc_info.value):
                pass
            else:
                assert str(exc_info.value) == expected["error_message"], rel

    # 2. All 105 adversarial lines. The oracle file stays the BASE record.
    plain_valid_2pow64_plus_1 = (
        f'{{"con_spec_version":2,"con_spec_minor":{TWO_POW_64_PLUS_1}}}'
    )
    plain_valid_40 = f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS}}}'
    unreserved_overflow_prefix = '{"con_spec_version":2,"other":'
    duplicate_minor_lines = {
        '{"con_spec_version":3,"con_spec_minor":-0,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"}}',
        '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}',
        '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}',
    }
    duplicate_object_lines = {
        '{"con_spec_version":2,"section_arity":{"widgets":-0,"widgets":2}}',
        '{"con_spec_version":2,"section_arity":{"widgets":2,"widgets":-0}}',
        '{"con_spec_version":-0,"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}',
    }
    adv_huge_diffs = []
    unreserved_overflow_diffs = []
    dup_minor_diffs = []
    dup_object_diffs = []
    assert len(oracle["adversarial_lines"]) == 105
    for entry in oracle["adversarial_lines"]:
        line2 = entry["line2"]
        txt = f"adv\n{line2}\n10 10 10\n90 90 90\n\n\n0\n\n\n"
        if line2 in duplicate_minor_lines:
            with pytest.raises(
                readcon.InvalidMetadataJson, match="duplicate con_spec_minor key"
            ):
                readcon.read_con_string(txt)
            dup_minor_diffs.append(line2)
            continue
        if line2 in duplicate_object_lines:
            with pytest.raises(readcon.InvalidMetadataJson, match="repeats a name"):
                readcon.read_con_string(txt)
            dup_object_diffs.append(line2)
            continue
        if line2 in (plain_valid_2pow64_plus_1, plain_valid_40):
            assert entry["status"] == "err"
            frames = readcon.read_con_string(txt)
            assert len(frames) == 1
            want = (
                TWO_POW_64_PLUS_1
                if line2 == plain_valid_2pow64_plus_1
                else FORTY_DIGITS
            )
            assert frames[0].metadata["con_spec_minor"] == want
            adv_huge_diffs.append(line2)
            continue
        if line2.startswith(unreserved_overflow_prefix):
            assert entry["status"] == "err"
            frames = readcon.read_con_string(txt)
            assert len(frames) == 1
            assert len(frames[0].metadata["other"]) == 400
            unreserved_overflow_diffs.append(line2)
            continue
        if entry["status"] == "ok":
            frames = readcon.read_con_string(txt)
            assert len(frames) == 1, line2
            assert frames[0].spec_version == entry["spec_version"], line2
            exp_meta = {
                k: v
                for k, v in json.loads(entry["metadata_json"]).items()
                if k not in ("con_spec_version", "sections")
            }
            assert _json_value_eq(dict(frames[0].metadata), exp_meta), line2
        else:
            try:
                frames = readcon.read_con_string(txt)
            except Exception as exc:
                assert type(exc).__name__ == entry["error_class"], line2
                expected_msg = entry["error_message"]
                if "number out of range" in expected_msg and "con_spec_minor" in str(
                    exc
                ):
                    continue
                if expected_msg.endswith(
                    "con_spec_minor must be a JSON integer >= 0"
                ) and str(exc).startswith(expected_msg):
                    continue
                assert str(exc) == expected_msg, line2
            else:
                assert "number out of range" in entry["error_message"], line2
    assert len(adv_huge_diffs) == 2
    assert len(unreserved_overflow_diffs) == 1
    assert len(dup_minor_diffs) == 3
    assert len(dup_object_diffs) == 3


def test_corpus31_differential_against_base_oracle_in_python(tmp_path):
    pytest.importorskip("zstandard")
    oracle = json.loads(BASE_ORACLE_PATH.read_text(encoding="utf-8"))
    assert (
        oracle["provenance"]["base_commit"]
        == "9aff911e809390163d2d7b08671145ad99f24496"
    )

    # All 143 corpus31 files. d14_minor_2pow64.con and v2_minor_2pow64.con
    # change from BASE rejection to accepted 2^64, and Python enables the zstd
    # files. Every other verdict that differs from BASE is the one
    # manifest.toml gives, except where CON 4 decides the file otherwise.
    con4_accepts = {
        # CON-units.9: a missing units.time does not reject any minor of major 3.
        "d02_legacy_velocity_no_time.convel": 3,
        "v31_convel_no_time.convel": 3,
        "v31_legacy_velocity_no_time.convel": 3,
        # Major 4 is the current major, so CON-line2.6 does not reject it.
        "json_version_4.con": 4,
    }
    bom = "CON validation failed: frame begins with a byte-order mark"
    con4_messages = {
        "v31_bom.con": bom,
        "v31_bom_later_frame.con": bom,
        "v31_minor_string.con": "invalid JSON metadata on line 2: con_spec_minor "
        "must be a JSON integer >= 0 that fits in an unsigned 64-bit integer",
        "v31_validate_bad_label.convel": "CON validation failed: expected section "
        'label "Velocities of Component 1", found "Velocity of Component 1"',
    }
    corpus_dir = tmp_path / "corpus31"
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "paper/cpc/scripts/make_corpus31.py"),
            "--out",
            str(corpus_dir),
        ],
        check=True,
    )
    labels = {
        entry["file"]: entry["expected"]
        for entry in tomllib.loads(
            (corpus_dir / "manifest.toml").read_text(encoding="utf-8")
        )["file"]
    }
    c31_oracle = oracle["corpus31"]
    assert len(c31_oracle) == 143

    huge_minor_diffs = []
    con4_diffs = []
    manifest_diffs = []
    for name, expected in c31_oracle.items():
        p = str(corpus_dir / name)
        if name in ("d14_minor_2pow64.con", "v2_minor_2pow64.con"):
            assert expected["status"] == "err"
            frames = readcon.read_con(p)
            assert len(frames) == 1
            assert frames[0].spec_version == (3 if name.startswith("d14") else 2)
            assert frames[0].metadata["con_spec_minor"] == TWO_POW_64
            out = readcon.write_con_string(frames)
            assert json.loads(out.splitlines()[1])["con_spec_minor"] == TWO_POW_64
            huge_minor_diffs.append(name)
            continue
        if name in con4_accepts:
            assert expected["status"] == "err", name
            assert labels[name] == "reject", name
            frames = readcon.read_con(p)
            assert len(frames) == 1, name
            assert frames[0].spec_version == con4_accepts[name], name
            con4_diffs.append(name)
            continue
        if name.endswith(".zst"):
            frames = readcon.read_con(p)
            assert len(frames) >= 1, name
            continue
        try:
            readcon.read_con(p)
            verdict = "ok"
        except Exception:
            verdict = "err"
        if verdict != expected["status"]:
            assert verdict == {"accept": "ok", "reject": "err"}[labels[name]], name
            manifest_diffs.append(name)
            continue
        if expected["status"] == "ok":
            frames = readcon.read_con(p)
            exp_frames = expected["frames"]
            assert len(frames) == len(exp_frames), name
            for fr, exp_fr in zip(frames, exp_frames):
                assert fr.spec_version == exp_fr["spec_version"], name
                exp_meta = {
                    k: v
                    for k, v in json.loads(exp_fr["metadata_json"]).items()
                    if k not in ("con_spec_version", "sections")
                }
                assert _json_value_eq(dict(fr.metadata), exp_meta), name
        else:
            with pytest.raises(Exception) as exc_info:
                readcon.read_con(p)
            message = con4_messages.get(name, expected["error_message"])
            assert str(exc_info.value) == message, name
    assert sorted(huge_minor_diffs) == ["d14_minor_2pow64.con", "v2_minor_2pow64.con"]
    assert sorted(con4_diffs) == sorted(con4_accepts)
    assert len(manifest_diffs) == 26


@pytest.mark.parametrize(
    "line2,expected_msg",
    [
        (
            '{"con_spec_version":2,"con_spec_minor":\x0c18446744073709551616}',
            "invalid JSON metadata on line 2: expected value at line 1 column 40",
        ),
        (
            '{"con_spec_version":2,"con_spec_minor":18446744073709551616\x0c}',
            "invalid JSON metadata on line 2: expected `,` or `}` at line 1 column 60",
        ),
        (
            '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":\x0c{"length":"angstrom","energy":"eV"}}',
            "invalid JSON metadata on line 2: expected value at line 1 column 69",
        ),
        (
            '{"con_spec_version":3,"units":\x0c{"length":"angstrom","energy":"eV"},"con_spec_minor":18446744073709551616}',
            "invalid JSON metadata on line 2: expected value at line 1 column 31",
        ),
        (
            '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"ang\tstrom","energy":"eV"}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 83",
        ),
        (
            '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom","energy":"\x0beV"}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 100",
        ),
        (
            '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom","energy":"eV","time":"fs\r"}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 114",
        ),
        (
            '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom\x0c","energy":"eV"}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 88",
        ),
        (
            f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS},"units":{{"length":"x\x0cy","energy":"z"}}}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
        (
            f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS},"units":{{"length":"x\x01y","energy":"z"}}}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
        (
            f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS},"units":{{"length":"x\x00y","energy":"z"}}}}',
            "invalid JSON metadata on line 2: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 101",
        ),
    ],
)
def test_huge_minor_form_feed_and_quoted_control_bytes_match_base(line2, expected_msg):
    txt = f"adv\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
    with pytest.raises(readcon.InvalidMetadataJson) as exc_info:
        readcon.read_con_string(txt)
    assert str(exc_info.value) == expected_msg

    if "\x00" not in line2:
        fr = readcon.ConFrame([10.0, 10.0, 10.0], [90.0, 90.0, 90.0], [])
        with pytest.raises(ValueError) as sm_exc:
            fr.set_metadata_json(line2)
        assert str(sm_exc.value).startswith("invalid metadata JSON:")


def _velocities_without_time(line2: str) -> str:
    return (
        f"gen\n{line2}\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
        "Coordinates of Component 1\n0 0 0 0 0\n\n"
        "H\nVelocities of Component 1\n0.1 0 0 0 0\n"
    )


def test_form_feed_between_line2_tokens_requires_units_time():
    # Form feed is whitespace the fast path skips. Major 4 rejects velocities
    # without units.time (CON-units.11), while major 3 accepts them (CON-units.9).
    ff = "\x0c"
    units = '{"length":"angstrom","energy":"eV"}'
    for line2 in (
        f'{{"con_spec_version":4,{ff}"con_spec_minor":0,"units":{units}}}',
        f'{{"con_spec_version":4,"con_spec_minor"{ff}:0,"units":{units}}}',
        f'{{{ff}"con_spec_version":4,"con_spec_minor":0,"units":{units}}}',
        f'{{"con_spec_version":4,"units":{ff}{units},"con_spec_minor":0}}',
    ):
        with pytest.raises(readcon.InvalidUnits):
            readcon.read_con_string(_velocities_without_time(line2))
    for line2 in (
        f'{{"con_spec_version":3,{ff}"con_spec_minor":1,"units":{units}}}',
        f'{{"con_spec_version":3,"units":{ff}{units},"con_spec_minor":1}}',
    ):
        assert len(readcon.read_con_string(_velocities_without_time(line2))) == 1


def test_escaped_top_level_con_spec_minor_is_the_minor():
    text = (
        'gen\n{"con_spec_version":2,"con_spec_\\u006dinor":5}\n'
        "10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\n"
        "Coordinates of Component 1\n0 0 0 0 0\n"
    )
    frame = readcon.read_con_string(text)[0]
    assert frame.metadata["con_spec_minor"] == 5
