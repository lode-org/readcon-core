"""The host log refuses a ratio of arms that are not the same work."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "host_from_log.py"

ARMS = (
    "readcon_tip",
    "readcon_v0173",
    "readcon_base",
    "ase_eon",
    "eon_py",
    "readcon_eon_api",
    "readcon_db",
    "readcon_first",
    "eon",
    "chemfiles",
    "ovito",
    "h5py",
    "conbin",
)

RATIO_MACROS = (
    "rcTipOverRelease",
    "rcTipOverAse",
    "rcTipOverEon",
    "rcTipOverDb",
)

LIKE = {
    "work": "full-frame",
    "threads": "1",
    "input": "synthetic",
    "input_kind": "synthetic",
    "input_sha256": "abc",
}


def _load():
    spec = importlib.util.spec_from_file_location("host_from_log_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _summary(arm: str, median: str = "1", drop: tuple[str, ...] = ()) -> str:
    fields = {
        "arm": arm,
        "median_s": median,
        "iqr_s": "0.1",
        "mib_median": "1",
        "matched": "1",
        "requested": "1",
        "failed": "0",
        "exit": "0",
    }
    for key in drop:
        fields.pop(key, None)
    body = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"summary {body}"


def _log(lines: list[str], rev: str = "rev_parse abcdef01") -> str:
    return rev + "\n" + "\n".join(lines) + "\n"


def _run(module, text: str, tmp_path: Path):
    log = tmp_path / "reader-exchange.log"
    log.write_text(text, encoding="utf-8", newline="\n")
    generated = tmp_path / "generated"
    generated.mkdir()
    module.LOG = log
    module.GEN = generated
    return module.main(), generated


def test_historical_unmatched_arms_are_refused(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm, median="2" if arm != "readcon_tip" else "1") for arm in ARMS]
    code, generated = _run(module, _log(lines), tmp_path)
    assert code == 0
    text = (generated / "host_macros.tex").read_text(encoding="utf-8")
    for name in RATIO_MACROS:
        assert name not in text
    assert "rcBaseMedian" in text


def test_equal_work_emits_the_ratio(tmp_path: Path) -> None:
    module = _load()
    lines = []
    for arm in ARMS:
        median = "2" if arm == "readcon_v0173" else "1"
        fields = _summary(arm, median=median)
        extra = " ".join(f"{key}={value}" for key, value in LIKE.items())
        lines.append(f"{fields} {extra}")
    code, generated = _run(module, _log(lines), tmp_path)
    assert code == 0
    text = (generated / "host_macros.tex").read_text(encoding="utf-8")
    assert r"\newcommand{\rcTipOverRelease}{2}" in text


def test_a_missing_arm_names_the_arm(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS if arm != "readcon_base"]
    with pytest.raises(SystemExit, match="has no summary for readcon_base"):
        _run(module, _log(lines), tmp_path)


def test_a_missing_median_names_the_field(tmp_path: Path) -> None:
    module = _load()
    lines = [
        _summary(arm, drop=("median_s",)) if arm == "h5py" else _summary(arm)
        for arm in ARMS
    ]
    with pytest.raises(SystemExit, match="summary for h5py has no median_s"):
        _run(module, _log(lines), tmp_path)


def test_a_bare_rev_parse_line_names_the_line(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS]
    with pytest.raises(SystemExit, match="rev_parse line has no revision"):
        _run(module, _log(lines, rev="rev_parse "), tmp_path)


def test_a_nonzero_exit_is_a_failure(tmp_path: Path) -> None:
    module = _load()
    lines = []
    for arm in ARMS:
        line = _summary(arm)
        if arm == "readcon_tip":
            line = line.replace("exit=0", "exit=1")
        lines.append(line)
    with pytest.raises(SystemExit, match="reports exit=1"):
        _run(module, _log(lines), tmp_path)


def test_a_nonzero_failed_count_is_a_failure(tmp_path: Path) -> None:
    module = _load()
    lines = []
    for arm in ARMS:
        line = _summary(arm)
        if arm == "ase_eon":
            line = line.replace("failed=0", "failed=1")
        lines.append(line)
    with pytest.raises(SystemExit, match="reports failed=1"):
        _run(module, _log(lines), tmp_path)


def test_a_nan_median_is_rejected(tmp_path: Path) -> None:
    module = _load()
    lines = [
        _summary(arm, median="nan") if arm == "readcon_v0173" else _summary(arm)
        for arm in ARMS
    ]
    with pytest.raises(SystemExit, match="readcon_v0173 median_s is not finite"):
        _run(module, _log(lines), tmp_path)


def test_an_infinite_median_is_rejected(tmp_path: Path) -> None:
    module = _load()
    lines = [
        _summary(arm, median="inf") if arm == "eon_py" else _summary(arm)
        for arm in ARMS
    ]
    with pytest.raises(SystemExit, match="eon_py median_s is not finite"):
        _run(module, _log(lines), tmp_path)


def test_duplicate_arm_is_rejected(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS]
    lines.append(_summary("readcon_tip"))
    with pytest.raises(SystemExit, match="duplicate summary for readcon_tip"):
        _run(module, _log(lines), tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("iqr_s", "not-a-number", "iqr_s is not a number"),
        ("mib_median", "not-a-number", "mib_median is not a number"),
        ("matched", "1.5", "matched is not an integer"),
        ("requested", "many", "requested is not an integer"),
    ),
)
def test_non_numeric_table_fields_are_rejected(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS]
    current = "0.1" if field == "iqr_s" else "1"
    lines[0] = lines[0].replace(f"{field}={current}", f"{field}={value}")
    with pytest.raises(SystemExit, match=message):
        _run(module, _log(lines), tmp_path)


def test_late_validation_failure_writes_no_partial_output(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS]
    index = ARMS.index("chemfiles")
    lines[index] = lines[index].replace("iqr_s=0.1", "iqr_s=bad")
    generated = tmp_path / "generated"
    with pytest.raises(SystemExit, match="chemfiles iqr_s is not a number"):
        _run(module, _log(lines), tmp_path)
    assert list(generated.iterdir()) == []


def test_successful_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    module = _load()
    lines = [_summary(arm) for arm in ARMS]
    _code, generated = _run(module, _log(lines), tmp_path)
    assert not list(generated.glob("*.tmp"))
