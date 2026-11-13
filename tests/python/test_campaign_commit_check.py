# Copyright (c) readcon-core developers
"""The final-campaign check rejects a file produced on another commit."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))
import campaign_protocol as protocol


HEAD = "a" * 40
OTHER = "b" * 40


def test_check_fails_when_an_output_names_another_commit(tmp_path: Path):
    (tmp_path / "rows.json").write_text(
        json.dumps({"commit": OTHER, "rows": []}) + "\n"
    )
    with pytest.raises(SystemExit, match="commit check failed"):
        protocol.check_directory(tmp_path, HEAD)


def test_check_fails_when_an_output_has_no_commit(tmp_path: Path):
    (tmp_path / "rows.json").write_text("{}\n")
    with pytest.raises(SystemExit, match="missing"):
        protocol.check_directory(tmp_path, HEAD)


def test_check_passes_when_every_output_matches_head(tmp_path: Path):
    (tmp_path / "rows.json").write_text(
        json.dumps({"commit": HEAD, "rows": [1]}) + "\n"
    )
    (tmp_path / "db.log").write_text(f"commit {HEAD}\nrev_parse {HEAD}\n")
    payload = tmp_path / "con-1e6.con.gz"
    payload.write_bytes(b"not a real gzip")
    payload.with_name(payload.name + ".commit").write_text(HEAD + "\n")
    protocol.check_directory(tmp_path, HEAD)
