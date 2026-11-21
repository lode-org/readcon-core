"""con_spec_minor token probes shared by the Rust, C, RPC, Python, and Julia tests.

The cases and expected results live in tests/fixtures/minor_token_probes.json,
written by tests/fixtures/generate_minor_token_probes.py. Julia reads the same
data from the TOML copy.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import readcon

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
PROBES = json.loads((FIXTURES / "minor_token_probes.json").read_text(encoding="utf-8"))
CASES = PROBES["cases"]
VELOCITY_BODY = (
    "\n10 10 10\n90 90 90\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n"
    "\nH\nVelocities of Component 1\n0.1 0.2 0.3 0 0\n"
)


def _velocity_text(line2: str) -> str:
    return "gen\n" + line2[:-1] + ',"sections":["velocities"]}' + VELOCITY_BODY


def _constructed(line2: str) -> readcon.ConFrame:
    atom = readcon.Atom(
        "H", 0.0, 0.0, 0.0, [False, False, False], 0, 1.0, vx=0.1, vy=0.2, vz=0.3
    )
    frame = readcon.ConFrame([10.0, 10.0, 10.0], [90.0, 90.0, 90.0], [atom])
    frame.set_metadata_json(line2)
    return frame


def _line2(text: str) -> str:
    return text.split("\n")[1]


def _assert_error(err: BaseException, tag: str) -> None:
    message = str(err)
    if tag == "dup":
        assert "duplicate con_spec_minor key" in message, message
    elif tag == "invalid":
        assert isinstance(err, ValueError), repr(err)
        assert "metadata" in message, message
        assert "duplicate" not in message, message
    elif tag == "units":
        assert "units.time" in message, message
    else:
        raise AssertionError(f"unknown tag {tag}")


def test_fixture_matches_generator_and_toml(tmp_path: Path) -> None:
    toml = tomllib.loads(
        (FIXTURES / "minor_token_probes.toml").read_text(encoding="utf-8")
    )
    assert toml == PROBES
    script = (FIXTURES / "generate_minor_token_probes.py").read_text(encoding="utf-8")
    out = tmp_path / "generate_minor_token_probes.py"
    out.write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, str(out)], check=True)
    for name in ("minor_token_probes.json", "minor_token_probes.toml"):
        assert (tmp_path / name).read_bytes() == (FIXTURES / name).read_bytes(), name


def test_fixture_covers_the_probe_tokens() -> None:
    names = {case["name"] for case in CASES}
    for name in (
        "lead00",
        "lead000",
        "lead01",
        "lead0P1",
        "neg1",
        "negzero",
        "frac1.5",
        "frac1.0",
        "exp1e0",
        "exp1e20",
        "true_minor",
        "exp1e309",
        "exp1E400",
        "fmax+2^970",
        "fmax+1",
        "fmax+2^970-1",
        "esc_single_0",
        "esc_single_1",
        "esc_single_P1",
        "nested_only1",
        "nested2_top0",
        "nested_deep_dup",
        "false_minor",
        "null_minor",
        "strval_minor",
        "arrval_minor",
        "objval_minor",
    ):
        assert name in names
    assert len(CASES) == 59


def test_fixture_holds_every_r2_probe_input() -> None:
    rows = (
        (FIXTURES / "dupkey_r2_probe_inputs.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    inputs = set()
    for row in rows:
        _name, line_w, line_n = row.split("\t")
        inputs.add((line_w, line_n))
    assert len(rows) == 52
    assert len(inputs) == 52
    lines = {(case["line2_w"], case["line2_n"]) for case in CASES}
    assert sorted(inputs - lines) == []


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_read(case: dict) -> None:
    for line2, expected in (
        (case["line2_w"], case["read_w"]),
        (case["line2_n"], case["read_n"]),
    ):
        if expected == "ok":
            frames = readcon.read_con_string(_velocity_text(line2))
            assert len(frames) == 1
            continue
        with pytest.raises(readcon.ConError) as info:
            readcon.read_con_string(_velocity_text(line2))
        if expected == "invalid":
            assert isinstance(info.value, readcon.InvalidMetadataJson), repr(info.value)
        elif expected == "units":
            assert isinstance(info.value, readcon.InvalidUnits), repr(info.value)
        _assert_error(info.value, expected)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_write_matches_julia(case: dict) -> None:
    for line2, expected in (
        (case["line2_w"], case["binding_w"]),
        (case["line2_n"], case["binding_n"]),
    ):
        if expected in ("dup", "invalid"):
            with pytest.raises(ValueError) as info:
                _constructed(line2)
            _assert_error(info.value, expected)
            continue
        frame = _constructed(line2)
        if expected == "units":
            with pytest.raises(Exception) as info:
                readcon.write_con_string([frame])
            _assert_error(info.value, expected)
            continue
        assert _line2(readcon.write_con_string([frame])) == expected


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["read_w"] == "ok"], ids=lambda c: c["name"]
)
def test_round_trip_matches_julia(case: dict) -> None:
    frames = readcon.read_con_string(_velocity_text(case["line2_w"]))
    written = readcon.write_con_string(frames)
    assert _line2(written) == case["binding_w"]
    assert len(readcon.read_con_string(written)) == 1
