"""``gen_version_map.py`` reads the build of every kind of record.

The readcon-db campaign records are copied verbatim from lode-org/readcon-db
and carry no readcon-core build. They name the readcon-db commit they
measured, and the version map says so. A ``host.json`` that holds the
hardware alone carries no build.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "gen_version_map.py"

COMMIT = "a584a28816c2"
TREE = "c1c761697b9a"
DB31_HOST = f"readcon-db commit \\texttt{{{COMMIT}}}, tree \\texttt{{{TREE}}}; "
XEON = "Intel(R) Xeon(R) Processor"
HEADINGS = {
    "data/db31/db24/ab.json": f"{DB31_HOST}{XEON}, 8 CPUs, 2700 MHz, kernel 6.12.113+",
    "data/db31/db25/ab.json": f"{DB31_HOST}{XEON}, 8 CPUs, 2700 MHz, kernel 6.12.113+",
    "data/db31/db26/ab.json": f"{DB31_HOST}{XEON}, 8 CPUs, 2700 MHz, kernel 6.12.113+",
    "data/db31/db28/ab.json": f"{DB31_HOST}{XEON}, 8 CPUs, 2700 MHz, kernel 6.12.113+",
    "data/db31/db29/ab.json": f"{DB31_HOST}{XEON}, 8 CPUs, 2700 MHz, kernel 6.12.113+",
    "data/db31/corpus-ops/readcon_db_bench.json": f"{DB31_HOST}{XEON}, 2700 MHz, kernel 6.12.113+",
    "data/db30/fair-db30/campaign.json": "readcon-db commit \\texttt{043c3091c960}",
    "data/db32/fair-db32/campaign.json": "readcon-db commit \\texttt{d8bf1cb567c4}; "
    f"{XEON}, 2700 MHz, kernel 6.12.113+",
}


@pytest.fixture
def version_map():
    spec = importlib.util.spec_from_file_location("gen_version_map_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    module.provenance_records.cache_clear()
    module.outputs.cache_clear()


@pytest.mark.parametrize("record", sorted(HEADINGS))
def test_a_readcon_db_record_names_its_own_commit(version_map, record: str) -> None:
    assert version_map.carrier(record) == ("external", record)
    build = version_map.build_of("external", record)
    assert build is not None
    assert build.readcon is None
    assert version_map.heading(build) == HEADINGS[record]
    assert "readcon-core" not in version_map.heading(build)


def test_a_readcon_db_record_without_a_commit_has_no_build(version_map) -> None:
    record = "data/db31/ase/ase_db_bench.json"
    assert version_map.carrier(record) == ("external", record)
    assert version_map.build_of("external", record) is None


def _tree(tmp_path: Path, host: dict) -> Path:
    cpc = tmp_path / "cpc"
    (cpc / "data" / "run").mkdir(parents=True)
    (cpc / "data" / "run" / "host.json").write_text(json.dumps(host))
    (cpc / "data" / "run" / "result.json").write_text(json.dumps({"value": 1}))
    return cpc


def test_a_host_json_with_the_hardware_alone_carries_no_build(
    version_map, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpc = _tree(tmp_path, {"cpu": "x", "kernel": "6", "serial": True})
    monkeypatch.setattr(version_map, "CPC", cpc)
    version_map.provenance_records.cache_clear()
    version_map.outputs.cache_clear()
    assert version_map.carrier("data/run/result.json") is None


def test_a_host_json_with_the_build_schema_is_a_carrier(
    version_map, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = {
        "readcon_core": "0.23.3",
        "readcon_sha": "0" * 40,
        "rustc": "rustc 1.88.0",
        "python": "Python 3.12.3",
    }
    cpc = _tree(tmp_path, host)
    monkeypatch.setattr(version_map, "CPC", cpc)
    version_map.provenance_records.cache_clear()
    version_map.outputs.cache_clear()
    assert version_map.carrier("data/run/result.json") == ("host", "data/run/host.json")
