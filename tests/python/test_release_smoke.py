"""The release smoke rejects a clib tarball that omits the version header."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
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


class TagPin(unittest.TestCase):
    def test_wrap_is_read_from_the_tag_not_the_worktree(self) -> None:
        smoke = load(SMOKE, "check_release_smoke_tag")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._commit_tag(root, "a" * 64)
            wrap = root / "packaging" / "wrapdb" / "readcon-core.wrap"
            wrap.write_text(
                wrap.read_text(encoding="utf-8").replace("a" * 64, "b" * 64)
            )
            version, pinned = smoke.pin_at_tag(root, "v1.2.3")
        self.assertEqual(version, "1.2.3")
        self.assertEqual(pinned, "a" * 64)

    def test_tag_and_wrap_version_must_agree(self) -> None:
        smoke = load(SMOKE, "check_release_smoke_disagree")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._commit_tag(root, "c" * 64, wrap_version="9.9.9")
            with self.assertRaises(smoke.SmokeError) as caught:
                smoke.pin_at_tag(root, "v1.2.3")
        self.assertIn("disagree", str(caught.exception))
        self.assertIn("v1.2.3", str(caught.exception))
        self.assertIn("9.9.9", str(caught.exception))

    def _commit_tag(self, root: Path, digest: str, wrap_version: str = "1.2.3") -> None:
        subprocess.run(["git", "init"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "core.hooksPath", "/dev/null"], cwd=root, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"], cwd=root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        wrap_dir = root / "packaging" / "wrapdb"
        wrap_dir.mkdir(parents=True)
        (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        (wrap_dir / "readcon-core.wrap").write_text(
            "\n".join(
                [
                    "[wrap-file]",
                    f"directory = readcon-core-cxx-{wrap_version}",
                    "source_url = https://github.com/lode-org/readcon-core/releases/download/"
                    f"v{wrap_version}/readcon-core-cxx-{wrap_version}.tar.gz",
                    f"source_filename = readcon-core-cxx-{wrap_version}.tar.gz",
                    f"source_hash = {digest}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (wrap_dir / "readcon-core.sha256").write_text(digest + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "pin"], cwd=root, check=True)
        subprocess.run(["git", "tag", "v1.2.3"], cwd=root, check=True)


class InstallDocs(unittest.TestCase):
    def test_pinned_and_repo_local_commands_are_recognized(self) -> None:
        docs = load(INSTALL, "check_install_docs")
        specs = docs.specs_in("pip install 'readcon==1.2.3' ase", "1.2.3")
        self.assertEqual(specs, [("pip", "readcon", "1.2.3")])
        cargo = docs.specs_in(
            "cargo add readcon-core@1.2.3 --features chemfiles", "1.2.3"
        )
        self.assertEqual(cargo, [("cargo", "readcon-core", "1.2.3")])
        ase = docs.specs_in("pip install -e ase-readcon", "1.2.3")
        self.assertEqual(ase, [("pip", "ase-readcon", None)])
        org = docs.specs_in("pip install 'readcon==@READCON_VERSION@'", "1.2.3")
        self.assertEqual(org, [("pip", "readcon", "1.2.3")])


if __name__ == "__main__":
    unittest.main()
