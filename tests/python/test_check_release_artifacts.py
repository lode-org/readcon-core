"""Negative fixtures for tag and artifact version agreement."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_release_artifacts.py"


def run(
    tag: str, version: str, files: dict[str, str], manifest: dict | None = None
) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        dist = root / "dist"
        dist.mkdir()
        for name, body in files.items():
            (dist / name).write_text(body, encoding="utf-8")
        cmd = [
            sys.executable,
            str(SCRIPT),
            "--tag",
            tag,
            "--version-file",
            str(root / "VERSION"),
            "--dist",
            str(dist),
        ]
        if manifest is not None:
            path = dist / "dist-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            cmd.extend(["--manifest", str(path)])
        return subprocess.call(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


class ReleaseArtifactGuard(unittest.TestCase):
    def test_matching_wheel_and_cxx_pass(self) -> None:
        self.assertEqual(
            run(
                "v0.18.1",
                "0.18.1",
                {
                    "readcon-0.18.1-cp312-cp312-manylinux_2_17_x86_64.whl": "w",
                    "readcon_chemfiles-0.18.1.tar.gz": "s",
                    "readcon-core-cxx-0.18.1.tar.gz": "c",
                    "readcon-core-clib-0.18.1-x86_64-unknown-linux-gnu.tar.gz": "l",
                },
            ),
            0,
        )

    def test_old_wheel_name_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.18.1",
                "0.18.1",
                {"readcon-0.17.3-cp312-cp312-manylinux_2_17_x86_64.whl": "w"},
            ),
            0,
        )

    def test_version_file_must_match_the_tag(self) -> None:
        self.assertNotEqual(
            run("v0.18.1", "0.17.3", {"readcon-0.17.3.tar.gz": "s"}),
            0,
        )

    def test_dist_binary_without_manifest_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.18.1",
                "0.18.1",
                {"readcon-core-x86_64-unknown-linux-gnu.tar.xz": "b"},
            ),
            0,
        )

    def test_dist_manifest_version_must_match_the_tag(self) -> None:
        manifest = {
            "announcement_tag": "v0.17.3",
            "releases": [
                {
                    "app_version": "0.17.3",
                    "artifacts": ["readcon-core-x86_64-unknown-linux-gnu.tar.xz"],
                }
            ],
            "artifacts": {},
        }
        self.assertNotEqual(
            run(
                "v0.18.1",
                "0.18.1",
                {"readcon-core-x86_64-unknown-linux-gnu.tar.xz": "b"},
                manifest,
            ),
            0,
        )

    def test_dist_binary_passes_when_manifest_version_matches(self) -> None:
        name = "readcon-core-x86_64-unknown-linux-gnu.tar.xz"
        manifest = {
            "announcement_tag": "v0.18.1",
            "releases": [
                {"app_version": "0.18.1", "artifacts": [name, "source.tar.gz"]}
            ],
            "artifacts": {name: {"name": name}},
        }
        self.assertEqual(
            run("v0.18.1", "0.18.1", {name: "b", "source.tar.gz": "s"}, manifest),
            0,
        )


if __name__ == "__main__":
    unittest.main()
