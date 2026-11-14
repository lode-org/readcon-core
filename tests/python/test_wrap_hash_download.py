"""A published tag whose asset cannot be downloaded is a failed check."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_wrap_hash.sh"


def test_a_failed_asset_download_is_not_success() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "could not be downloaded" in text
    assert "not published yet" not in text
