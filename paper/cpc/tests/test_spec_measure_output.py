"""gen_spec_supp.py --measure adds a file and never rewrites a stored one."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "gen_spec_supp.py"


def _load(tmp: Path):
    spec = importlib.util.spec_from_file_location("gen_spec_supp", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp / "VERSION").write_text("9.9.9\n")
    module.ROOT = tmp
    module.SPEC_DATA = tmp / "paper" / "cpc" / "data" / "spec"
    module.SPEC_DATA.mkdir(parents=True)
    module.git = lambda *args, check=True: subprocess.CompletedProcess(
        args, 0, stdout="b" * 40 + "\n", stderr=""
    )
    module.versions_record = lambda: {
        "spec": "docs/orgmode/spec.org",
        "tags": [],
        "tree": {"release": "9.9.9", "tagged": False, "spec_blob": "c" * 40},
    }
    return module


def test_a_rerun_keeps_the_measured_file(tmp_path: Path) -> None:
    module = _load(tmp_path)
    data = module.SPEC_DATA
    stored = data / "spec-measurement-9.9.9.json"
    measured = data / "spec-measurement-9.9.9-measured.json"
    stored.write_text('{"spec": "docs/orgmode/spec.org"}\n')
    measured_text = json.dumps(
        {
            "supersedes": "paper/cpc/data/spec/spec-measurement-9.9.9.json",
            "measured_at": {"commit": "a" * 40},
        }
    )
    measured.write_text(measured_text)
    module.measure()
    assert measured.read_text() == measured_text
    fresh = json.loads((data / "spec-measurement-9.9.9-measured-2.json").read_text())
    assert fresh["supersedes"] == (
        "paper/cpc/data/spec/spec-measurement-9.9.9-measured.json"
    )
    assert fresh["measured_at"] == {"commit": "b" * 40}


def test_the_first_rerun_supersedes_the_stored_file(tmp_path: Path) -> None:
    module = _load(tmp_path)
    stored = module.SPEC_DATA / "spec-measurement-9.9.9.json"
    stored.write_text('{"spec": "docs/orgmode/spec.org"}\n')
    module.measure()
    assert stored.read_text() == '{"spec": "docs/orgmode/spec.org"}\n'
    fresh = json.loads(
        (module.SPEC_DATA / "spec-measurement-9.9.9-measured.json").read_text()
    )
    assert fresh["supersedes"] == "paper/cpc/data/spec/spec-measurement-9.9.9.json"
