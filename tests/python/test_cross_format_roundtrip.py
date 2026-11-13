"""Each native file round-trips to the same positions and cell.

The tolerance is the format's own precision (PDB's 1e-3 Å, XTC's 1e-2 Å,
float32 trajectories, text CON and extended XYZ). A format that cannot
hold the structure is skipped with a reason, not given a fake pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import cross_format


def test_cross_format_roundtrip(tmp_path: Path) -> None:
    rows, notes = cross_format.roundtrip_report(tmp_path, n_atoms=4, n_frames=2)
    assert any("no native CON format" in note for note in notes)
    expected = {arm["id"] for arm in cross_format.arm_table(4)[0]}
    missing = expected - {row["arm"] for row in rows}
    assert not missing, (sorted(missing), notes)
    for row in rows:
        assert row["position_error"] <= row["precision"], row
        assert row["cell_error"] <= row["precision"], row
        assert row["file_bytes"] > 0


def test_pdb_above_serial_is_reported() -> None:
    arms, _notes = cross_format.arm_table(100_000)
    pdb = [arm for arm in arms if arm["id"] == "mda-pdb"]
    if not pdb:
        return
    assert pdb[0]["unsupported"] is True
    assert "five digits" in pdb[0]["drops"]
