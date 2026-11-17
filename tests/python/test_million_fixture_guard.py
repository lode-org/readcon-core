"""Regression guards for the pinned 1M CON fixture and its published table."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))

import cross_format


def _load_format_h2h_tables():
    script = ROOT / "paper" / "cpc" / "scripts" / "format_h2h_tables.py"
    spec = importlib.util.spec_from_file_location("format_h2h_tables", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pinned_million_spec() -> dict:
    return cross_format.make_spec(1_000_000, 1)


def _wrong_million_spec(pinned_million_spec: dict) -> dict:
    wrong_positions = pinned_million_spec["positions"].copy()
    wrong_positions[0, 0, 0] += 0.1234567
    return {
        **pinned_million_spec,
        "positions": wrong_positions,
    }


def test_wrong_gzip_and_zstd_million_con_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_million_spec: dict
) -> None:
    """Compressed 1M CON variants must enforce the pinned thermal SHA-256."""
    wrong_spec = _wrong_million_spec(pinned_million_spec)
    with pytest.raises(SystemExit, match="pinned"):
        cross_format.write_readcon(tmp_path / "wrong.con.gz", wrong_spec, "gzip")
    with pytest.raises(SystemExit, match="pinned"):
        cross_format.write_readcon(tmp_path / "wrong.con.zst", wrong_spec, "zstd")

    ok_gz = tmp_path / "ok.con.gz"
    cross_format.write_readcon(ok_gz, pinned_million_spec, "gzip")
    raw_gz = gzip.decompress(ok_gz.read_bytes())
    assert len(raw_gz) == cross_format.MILLION_CON_BYTES
    assert hashlib.sha256(raw_gz).hexdigest() == cross_format.MILLION_CON_SHA256
    assert ok_gz.stat().st_size < 10_000_000

    ok_zst = tmp_path / "ok.con.zst"
    cross_format.write_readcon(ok_zst, pinned_million_spec, "zstd")
    assert ok_zst.is_file() and ok_zst.stat().st_size > 0

    import readcon

    real_write_con = readcon.write_con

    def tampered_gzip(dest: str, frames, compression=None, n_threads=1):
        if compression == "gzip":
            Path(dest).write_bytes(gzip.compress(b"wrong-1m-payload\n"))
            return
        real_write_con(dest, frames, compression=compression, n_threads=n_threads)

    monkeypatch.setattr(readcon, "write_con", tampered_gzip)
    with pytest.raises(SystemExit, match="pinned"):
        cross_format.write_readcon(
            tmp_path / "tampered.con.gz", pinned_million_spec, "gzip"
        )


def test_lying_n_atoms_does_not_bypass_million_con_guard(
    tmp_path: Path, pinned_million_spec: dict
) -> None:
    """A mismatched spec['n_atoms'] with 1M positions cannot bypass the 1M guard."""
    lying_spec = _wrong_million_spec(pinned_million_spec)
    lying_spec["n_atoms"] = 999_999
    with pytest.raises(SystemExit, match="pinned"):
        cross_format.write_readcon(tmp_path / "lying.con", lying_spec, None)

    lying_gz = _wrong_million_spec(pinned_million_spec)
    lying_gz["n_atoms"] = 999_999
    with pytest.raises(SystemExit, match="pinned"):
        cross_format.write_readcon(tmp_path / "lying.con.gz", lying_gz, "gzip")


def test_corrupted_cached_plain_con_is_refused(
    tmp_path: Path, pinned_million_spec: dict
) -> None:
    """Reusing a cached plain CON validates its SHA-256 before returning or converting."""
    import readcon

    wrong_spec = _wrong_million_spec(pinned_million_spec)

    # Syntactically valid 1M CON whose contents do not match the pinned thermal file.
    chem_dir = tmp_path / "chem"
    chem_dir.mkdir()
    readcon.write_columns(
        str(chem_dir / "readcon.con"),
        cross_format._columns(wrong_spec),
        n_threads=1,
    )
    with pytest.raises(SystemExit):
        cross_format.convert_arm("chemfiles-con", pinned_million_spec, chem_dir)

    conbin_dir = tmp_path / "conbin"
    conbin_dir.mkdir()
    readcon.write_columns(
        str(conbin_dir / "readcon.con"),
        cross_format._columns(wrong_spec),
        n_threads=1,
    )
    with pytest.raises(SystemExit):
        cross_format.convert_arm("readcon-conbin", pinned_million_spec, conbin_dir)

    # Corrupted non-1M cache is also refused.
    small_spec = cross_format.make_spec(4, 2)
    small_dir = tmp_path / "small"
    small_dir.mkdir()
    (small_dir / "readcon.con").write_bytes(b"corrupted\n")
    with pytest.raises(SystemExit):
        cross_format.convert_arm("chemfiles-con", small_spec, small_dir)

    # Valid cached 1M plain CON is accepted and converted to CON-bin.
    valid_dir = tmp_path / "valid"
    cross_format.convert_arm("readcon-con", pinned_million_spec, valid_dir)
    assert (
        cross_format.convert_arm("chemfiles-con", pinned_million_spec, valid_dir)
        == valid_dir / "readcon.con"
    )
    conbin = cross_format.convert_arm("readcon-conbin", pinned_million_spec, valid_dir)
    assert conbin.is_file()


def test_format_h2h_tables_refuses_stale_one_million_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table builder refuses stale 1M records whose input hash is not pinned."""
    tables = _load_format_h2h_tables()
    with pytest.raises(SystemExit):
        tables.table()
    with pytest.raises(SystemExit):
        tables.macros()

    # Validating against a clean 1M record derived from million/v0.23.3 succeeds,
    # while changing its input hash or file bytes is refused.
    records = tmp_path / "v0.23.3"
    shutil.copytree(ROOT / "bench" / "h2h" / "formats" / "v0.23.3", records)
    old_1m = json.loads((records / "1m" / "cross-format.json").read_text())
    valid_1m = json.loads(
        (
            ROOT / "bench" / "h2h" / "million" / "v0.23.3" / "cross-format.json"
        ).read_text()
    )
    valid_1m["repeats_by_structure"] = old_1m["repeats_by_structure"]
    (records / "1m" / "cross-format.json").write_text(json.dumps(valid_1m))
    mmcif = json.loads((records / "1m-mmcif" / "cross-format.json").read_text())
    mmcif["frames"][0]["frame_sha256"] = [tables.MILLION_FRAME_SHA256]
    (records / "1m-mmcif" / "cross-format.json").write_text(json.dumps(mmcif))

    monkeypatch.setattr(tables, "RECORDS", records)
    assert r"\label{tab:format-h2h}" in tables.table()
    assert r"\hhfReadconConBytesOneM" in tables.macros()

    bad_con_sha = json.loads(json.dumps(valid_1m))
    bad_con_sha["frames"][0]["con_sha256"] = "0" * 64
    (records / "1m" / "cross-format.json").write_text(json.dumps(bad_con_sha))
    with pytest.raises(SystemExit):
        tables.table()

    bad_bytes = json.loads(json.dumps(valid_1m))
    for row in bad_bytes["rows"]:
        if row.get("arm") == "readcon-con":
            row["file_bytes"] = 85_299_756
    (records / "1m" / "cross-format.json").write_text(json.dumps(bad_bytes))
    with pytest.raises(SystemExit):
        tables.table()
