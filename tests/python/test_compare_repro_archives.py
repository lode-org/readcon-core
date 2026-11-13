"""The clib reproducibility check fails only when the bytes differ."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "compare-repro-archives.py"


def compare(first: Path, second: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), str(first), str(second)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class CompareReproArchivesTest(unittest.TestCase):
    def test_matching_bytes_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.tar.gz"
            second = root / "b.tar.gz"
            first.write_bytes(b"same-archive")
            second.write_bytes(b"same-archive")
            done = compare(first, second)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("reproducible sha256 matches", done.stdout)

    def test_different_bytes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.tar.gz"
            second = root / "b.tar.gz"
            first.write_bytes(b"published")
            second.write_bytes(b"rebuilt")
            done = compare(first, second)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("sha256 differs", done.stderr)
        self.assertIn("not a gzip tarball", done.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
