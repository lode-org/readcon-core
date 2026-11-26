"""The stored drift record names OVITO 3.17.2."""

from __future__ import annotations

import json
from pathlib import Path

DRIFT = Path(__file__).resolve().parents[1] / "data" / "referee" / "r1j" / "drift"


def test_the_drift_record_names_ovito_3_17_2() -> None:
    ext = json.loads((DRIFT / "drift_extxyz.json").read_text(encoding="utf-8"))
    con = json.loads((DRIFT / "drift_con.json").read_text(encoding="utf-8"))
    assert ext["provenance"]["peers"]["ovito"] == "3.17.2"
    assert con["provenance"]["peers"]["ovito"] == "3.17.2"
    assert (DRIFT / "drift_extxyz.csv").is_file()
    assert (DRIFT / "drift_con.csv").is_file()
