"""Spec 4.0.4 version rules, checked against the readcon that is installed."""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

import pytest

CPC = Path(__file__).resolve().parents[1]
SCRIPTS = CPC / "scripts"
sys.path.insert(0, str(SCRIPTS))

import version_safety as vs  # noqa: E402


def _release_has_c_abi() -> bool:
    path = vs.lib_path()
    if not path.is_file():
        return False
    try:
        library = ctypes.CDLL(str(path))
    except OSError:
        return False
    return hasattr(library, "rkr_read_all_frames")


@pytest.mark.skipif(
    not _release_has_c_abi(),
    reason=(
        "needs target/release/libreadcon_core.so built with the capi,benchmark features"
    ),
)
def test_every_rule_matches_the_live_readers():
    pytest.importorskip("readcon")
    rows = vs.measure_rows()
    by_name = dict(vs.VARIANTS)
    assert [row["variant"] for row in rows] == list(by_name)
    for row in rows:
        header, rule = by_name[row["variant"]]
        assert row["rule"] == rule
        vs.assert_rule(row["variant"], header, rule, row)


def test_the_survey_writer_emits_spec_4_0_4(tmp_path):
    readcon = pytest.importorskip("readcon")
    import failure_matrix as fm

    path = tmp_path / "survey.con"
    fm.w_readcon(fm.fixture(), path)
    header = json.loads(path.read_text().splitlines()[1])
    assert header["con_spec_version"] == readcon.CON_SPEC_VERSION == 4
    assert header["con_spec_minor"] == 0
    assert header["con_spec_patch"] == 4
    assert header["units"]["time"] == vs.SYMBOL
    tracked = CPC / "src" / "figures" / "generated" / "survey_frame.con"
    tracked_header = json.loads(tracked.read_text().splitlines()[1])
    assert tracked_header["con_spec_version"] == 4
    assert tracked_header["con_spec_minor"] == 0
    assert tracked_header["con_spec_patch"] == 4
    assert tracked_header["units"]["time"] == vs.SYMBOL
