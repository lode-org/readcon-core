"""The release smoke rejects a clib tarball that omits the version header."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "scripts" / "check_release_smoke.py"
INSTALL = ROOT / "scripts" / "check_install_docs.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseSmoke(unittest.TestCase):
    def test_self_test_catches_the_missing_version_header(self) -> None:
        ran = subprocess.run(
            [sys.executable, str(SMOKE), "--self-test"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("readcon-core-version.h", ran.stdout)

    def test_v0231_layout_is_rejected(self) -> None:
        smoke = load(SMOKE, "check_release_smoke")
        broken = smoke.fixture_tarball(False)
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.require_clib_headers(broken, "readcon-core-clib-0.23.1")
        self.assertIn("readcon-core-version.h", str(caught.exception))
        smoke.require_clib_headers(smoke.fixture_tarball(True), "complete")


class InstallDocs(unittest.TestCase):
    def test_pinned_and_repo_local_commands_are_recognized(self) -> None:
        docs = load(INSTALL, "check_install_docs")
        specs = docs.specs_in("pip install 'readcon==0.23.2' ase", "0.23.2")
        self.assertEqual(specs, [("pip", "readcon", "0.23.2")])
        cargo = docs.specs_in(
            "cargo add readcon-core@0.23.2 --features chemfiles", "0.23.2"
        )
        self.assertEqual(cargo, [("cargo", "readcon-core", "0.23.2")])
        ase = docs.specs_in("pip install -e ase-readcon", "0.23.2")
        self.assertEqual(ase, [("pip", "ase-readcon", None)])
        org = docs.specs_in("pip install 'readcon==@READCON_VERSION@'", "0.23.2")
        self.assertEqual(org, [("pip", "readcon", "0.23.2")])


if __name__ == "__main__":
    unittest.main()
