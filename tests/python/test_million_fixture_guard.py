"""Regression guards for the pinned 1M CON fixture and its published table."""

from __future__ import annotations

import ctypes
import ctypes.util
import gzip
import hashlib
import importlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))

import cross_format


def _load_format_h2h_tables(monkeypatch: pytest.MonkeyPatch):
    """The table builder imports its siblings, so the paper scripts are on the path for this test only."""
    scripts = ROOT / "paper" / "cpc" / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    script = scripts / "format_h2h_tables.py"
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


def _compress_zstd_bytes(raw: bytes) -> bytes:
    for mod_name in ("compression.zstd", "zstandard"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            mod = None
        if mod is not None and hasattr(mod, "ZstdCompressor"):
            compressor = mod.ZstdCompressor(level=1)
            # The stdlib compressor returns an unfinished frame unless the
            # call asks for FLUSH_FRAME. zstandard's compress() already
            # returns one complete frame and has no such mode.
            flush_frame = getattr(compressor, "FLUSH_FRAME", None)
            if flush_frame is None:
                return compressor.compress(raw)
            return compressor.compress(raw, flush_frame)
    lib_name = ctypes.util.find_library("zstd")
    assert lib_name is not None, "libzstd is required to build test zstd payload"
    lib = ctypes.CDLL(lib_name)
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_compress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    bound = lib.ZSTD_compressBound(len(raw))
    dst = (ctypes.c_ubyte * bound)()
    written = lib.ZSTD_compress(
        ctypes.cast(dst, ctypes.c_void_p), bound, raw, len(raw), 1
    )
    assert not lib.ZSTD_isError(written)
    return bytes(memoryview(dst)[:written])


def _disable_zstd_decoders(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def no_zstd_import(name: str, package: str | None = None):
        if name in ("compression.zstd", "zstandard"):
            raise ImportError(name)
        return real_import(name, package)

    real_which = shutil.which

    def no_zstd_which(cmd, *args, **kwargs):
        if cmd == "zstd":
            return None
        return real_which(cmd, *args, **kwargs)

    real_find_library = ctypes.util.find_library

    def no_zstd_library(name: str):
        if name == "zstd":
            return None
        return real_find_library(name)

    monkeypatch.setattr(importlib, "import_module", no_zstd_import)
    monkeypatch.setattr(shutil, "which", no_zstd_which)
    monkeypatch.setattr(ctypes.util, "find_library", no_zstd_library)


def test_wrong_gzip_and_zstd_million_con_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_million_spec: dict
) -> None:
    """Compressed 1M CON variants enforce the cross-format fixture SHA-256."""
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
    assert ok_gz.stat().st_size < 32_000_000

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


def test_zstd_hashes_raw_bytes_and_refuses_missing_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_million_spec: dict
) -> None:
    """Zstd validation hashes raw decompressed bytes and never normalizes."""
    plain = tmp_path / "pinned.con"
    cross_format.write_readcon(plain, pinned_million_spec, None)
    raw = plain.read_bytes()
    needle = b"0.03522115048934541 -0.03713679817953356 -0.033990805681918694 7 0"
    assert needle in raw
    alt_raw = raw.replace(needle, needle.replace(b"0.035", b"0.036", 1), 1)
    assert len(alt_raw) == len(raw)

    ok_zst = tmp_path / "ok.con.zst"
    ok_zst.write_bytes(_compress_zstd_bytes(raw))
    alt_zst = tmp_path / "alt.con.zst"
    alt_zst.write_bytes(_compress_zstd_bytes(alt_raw))

    # Byte-different representation of the same floats must be refused, not normalized.
    with pytest.raises(SystemExit, match="pinned"):
        cross_format._require_pinned_million_con(alt_zst, compression="zstd")

    # Without any raw zstd decoder, both pinned and byte-different zstd files are refused.
    _disable_zstd_decoders(monkeypatch)
    with pytest.raises(SystemExit, match="decoder"):
        cross_format._require_pinned_million_con(ok_zst, compression="zstd")
    with pytest.raises(SystemExit, match="decoder"):
        cross_format._require_pinned_million_con(alt_zst, compression="zstd")


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
    """The table builder pins the exact historical 1M campaign and fixture."""
    tables = _load_format_h2h_tables(monkeypatch)
    assert r"\label{tab:format-h2h}" in tables.table()
    assert r"\hhfReadconConBytesOneM" in tables.macros()

    records = tmp_path / "v0.23.3"
    shutil.copytree(ROOT / "bench" / "h2h" / "formats" / "v0.23.3", records)
    old_1m = json.loads((records / "1m" / "cross-format.json").read_text())
    valid_1m = json.loads(json.dumps(old_1m))

    monkeypatch.setattr(tables, "RECORDS", records)

    # `extra` has no frame payload, but its exact campaign commit and tree tie
    # those DCD rows to the same immutable input. Altered provenance is refused.
    assert r"\label{tab:format-h2h}" in tables.table()
    raw_extra = json.loads((records / "extra" / "cross-format.json").read_text())
    wrong_campaign = json.loads(json.dumps(raw_extra))
    wrong_campaign["measured_commit"] = "0" * 40
    (records / "extra" / "cross-format.json").write_text(json.dumps(wrong_campaign))
    with pytest.raises(SystemExit):
        tables.table()
    (records / "extra" / "cross-format.json").write_text(json.dumps(raw_extra))

    # Unsupported 1M rows in extra carry no measurement and may stay without frames.
    committed_extra_mdcompress = [
        row
        for row in raw_extra["rows"]
        if row.get("arm", "").startswith("mdcompress-")
        and row.get("cache") == "unsupported"
    ]
    assert committed_extra_mdcompress
    for row in committed_extra_mdcompress:
        assert tables._is_unsupported_row(row)

    unsupported_only_extra = dict(raw_extra)
    unsupported_only_extra["rows"] = [
        row
        for row in raw_extra["rows"]
        if not (row.get("structure") == "1M" and row.get("arm") == "chemfiles-dcd-012")
    ]
    (records / "extra" / "cross-format.json").write_text(
        json.dumps(unsupported_only_extra)
    )
    assert r"\label{tab:format-h2h}" in tables.table()
    assert r"\hhfReadconConBytesOneM" in tables.macros()

    # An 'unsupported' row carrying any non-allowlisted or measured field counts
    # as measured and must be refused without pinned hashes.
    for field, value in (
        ("iqr_s", 0.001),
        ("n", 6),
        ("rss_bytes", 1024),
        ("samples_s", [0.05]),
        ("median_s", 0.05),
        ("file_bytes", 1234),
        ("cold_median_s", 0.05),
        ("cold_iqr_s", 0.001),
        ("cold_n", 6),
        ("cold_samples_s", [0.05]),
        ("position_error", 0.0),
        ("cell_error", 0.0),
        ("checksum", 1.0),
        ("checksum_ok", True),
        ("precision", 0.01),
        ("unknown_key", "measured"),
        ("errors", {"position": 1.0}),
        ("nested_samples", [None, {"median": 0.1}]),
        ("timing_ns", 1_000_000),
        ("write_median_s", 0.05),
    ):
        spoofed_extra = json.loads(json.dumps(unsupported_only_extra))
        target = next(
            row
            for row in spoofed_extra["rows"]
            if row.get("structure") == "1M" and row.get("cache") == "unsupported"
        )
        target[field] = value
        (records / "extra" / "cross-format.json").write_text(json.dumps(spoofed_extra))
        with pytest.raises(SystemExit):
            tables.table()

    # A missing or zero count is not a measurement. None and 0 stay unsupported.
    for field, value in (
        ("n", None),
        ("cold_n", None),
        ("cold_n", 0),
    ):
        counted = json.loads(json.dumps(unsupported_only_extra))
        target = next(
            row
            for row in counted["rows"]
            if row.get("structure") == "1M" and row.get("cache") == "unsupported"
        )
        target[field] = value
        (records / "extra" / "cross-format.json").write_text(json.dumps(counted))
        assert tables._is_unsupported_row(target)
        assert r"\label{tab:format-h2h}" in tables.table()

    # Restore clean unsupported extra and confirm committed 1M mdcompress-mdc
    # unsupported rows also pass in a pinned 1m record.
    (records / "extra" / "cross-format.json").write_text(
        json.dumps(unsupported_only_extra)
    )
    valid_with_mdc = json.loads(json.dumps(valid_1m))
    old_mdc = next(
        row
        for row in old_1m["rows"]
        if row.get("structure") == "1M" and row.get("arm") == "mdcompress-mdc"
    )
    valid_with_mdc["rows"].append(old_mdc)
    (records / "1m" / "cross-format.json").write_text(json.dumps(valid_with_mdc))
    assert r"\label{tab:format-h2h}" in tables.table()
    (records / "1m" / "cross-format.json").write_text(json.dumps(valid_1m))

    # Measured 1M rows in extra are allowed once extra carries the pinned 1M hashes.
    pinned_extra = dict(raw_extra)
    pinned_extra["frames"] = [
        {
            "structure": "1M",
            "n_atoms": 1_000_000,
            "n_frames": 1,
            "frame_sha256": [tables.MILLION_FRAME_SHA256],
            "con_sha256": tables.MILLION_CON_SHA256,
        }
    ]
    (records / "extra" / "cross-format.json").write_text(json.dumps(pinned_extra))
    assert r"\label{tab:format-h2h}" in tables.table()

    # Mismatched input hash or byte count in 1m is still refused.
    bad_con_sha = json.loads(json.dumps(valid_1m))
    bad_con_sha["frames"][0]["con_sha256"] = "0" * 64
    (records / "1m" / "cross-format.json").write_text(json.dumps(bad_con_sha))
    with pytest.raises(SystemExit):
        tables.table()

    bad_bytes = json.loads(json.dumps(valid_1m))
    for row in bad_bytes["rows"]:
        if row.get("arm") == "readcon-con":
            row["file_bytes"] = 48_378_118
    (records / "1m" / "cross-format.json").write_text(json.dumps(bad_bytes))
    with pytest.raises(SystemExit):
        tables.table()
