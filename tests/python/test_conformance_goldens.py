"""Phase A corpus lock: Python reads the same goldens as the Rust harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import readcon

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "resources" / "conformance"
MANIFEST = CORPUS / "manifest.toml"


def _unquote(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def parse_manifest(text: str) -> list[dict]:
    cases: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in ("[[valid]]", "[[invalid]]"):
            if current:
                cases.append(current)
            current = {
                "kind": "valid" if line == "[[valid]]" else "invalid",
                "id": "",
                "path": "",
                "error": None,
            }
            continue
        if current is None or "=" not in line:
            continue
        key, val = [p.strip() for p in line.split("=", 1)]
        if key == "id":
            current["id"] = _unquote(val)
        elif key == "path":
            current["path"] = _unquote(val)
        elif key == "error":
            current["error"] = _unquote(val)
    if current:
        cases.append(current)
    return cases


def test_manifest_and_goldens_exist():
    cases = parse_manifest(MANIFEST.read_text())
    valids = [c for c in cases if c["kind"] == "valid"]
    invalids = [c for c in cases if c["kind"] == "invalid"]
    assert valids and invalids
    on_disk = {p.name for p in (CORPUS / "golden").glob("*.json")}
    assert on_disk == {f"{c['id']}.json" for c in valids}
    for case in invalids:
        assert not (CORPUS / "golden" / f"{case['id']}.json").exists()


@pytest.mark.parametrize(
    "case",
    parse_manifest(MANIFEST.read_text()),
    ids=lambda c: c["id"],
)
def test_python_matches_golden_or_rejects(case):
    body = (CORPUS / case["path"]).read_text()
    if case["kind"] == "invalid":
        with pytest.raises(Exception):
            readcon.read_con_string(body)
        return
    frames = readcon.read_con_string(body)
    assert len(frames) == 1
    frame = frames[0]
    golden = json.loads((CORPUS / "golden" / f"{case['id']}.json").read_text())
    assert golden["id"] == case["id"]
    assert golden["n_atoms"] == len(frame)
    assert golden["spec_version"] == frame.spec_version
    atoms = frame.atoms
    assert [a.symbol for a in atoms] == golden["symbols"]
    assert [a.atom_id for a in atoms] == golden["atom_ids"]
    assert [list(a.fixed) for a in atoms] == golden["fixed"]
    for atom, want in zip(atoms, golden["positions"]):
        assert atom.x == pytest.approx(want[0])
        assert atom.y == pytest.approx(want[1])
        assert atom.z == pytest.approx(want[2])
