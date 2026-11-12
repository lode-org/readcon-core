"""Windows link flags and path remaps for a second identical clib build.

The encoded flag list keeps backslashes. RUSTFLAGS would not.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reproducible-rustflags.sh"


def flags(env: dict[str, str]) -> tuple[list[str], str, str]:
    merged = os.environ.copy()
    for key in (
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CFLAGS",
        "CXXFLAGS",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "GITHUB_WORKSPACE",
        "USERPROFILE",
        "HOME",
    ):
        merged.pop(key, None)
    merged.update(env)
    script = f"""
set -euo pipefail
source "{SCRIPT}"
reproducible_rustflags "$ROOT_DIR" "$TARGET"
printf '%s\\n' "${{CARGO_ENCODED_RUSTFLAGS}}"
printf 'CFLAGS=%s\\n' "${{CFLAGS-}}"
printf 'RUSTFLAGS=%s\\n' "${{RUSTFLAGS-unset}}"
"""
    done = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    encoded, cflags, rustflags = done.stdout.splitlines()
    return encoded.split("\x1f"), cflags.removeprefix("CFLAGS="), rustflags


class ReproducibleRustflagsTest(unittest.TestCase):
    def test_windows_brepro_and_backslash_remap(self) -> None:
        words, cflags, rustflags = flags(
            {
                "ROOT_DIR": r"D:\a\readcon-core\readcon-core\src",
                "TARGET": "x86_64-pc-windows-msvc",
                "CARGO_HOME": r"C:\Users\runneradmin\.cargo",
                "GITHUB_WORKSPACE": r"D:\a\readcon-core\readcon-core",
                "RUSTFLAGS": "-C link-arg=-fuse-ld=bfd",
            }
        )
        self.assertEqual(rustflags, "RUSTFLAGS=unset")
        self.assertIn("/Brepro", cflags)
        self.assertEqual(words[0], "-C")
        self.assertEqual(words[1], "link-arg=-fuse-ld=bfd")
        remaps = [word for word in words if word.startswith("--remap-path-prefix=")]
        self.assertIn(
            r"--remap-path-prefix=C:\Users\runneradmin\.cargo\=/cargo-home/",
            remaps,
        )
        self.assertIn(
            "--remap-path-prefix=C:/Users/runneradmin/.cargo/=/cargo-home/",
            remaps,
        )
        self.assertIn(
            r"--remap-path-prefix=D:\a\readcon-core\readcon-core\src\=/src/",
            remaps,
        )
        cargo_at = remaps.index(
            r"--remap-path-prefix=C:\Users\runneradmin\.cargo\=/cargo-home/"
        )
        root_at = remaps.index(
            r"--remap-path-prefix=D:\a\readcon-core\readcon-core\src\=/src/"
        )
        workspace_at = remaps.index(
            r"--remap-path-prefix=D:\a\readcon-core\readcon-core\=/workspace/"
        )
        self.assertLess(root_at, workspace_at)
        self.assertNotEqual(cargo_at, root_at)
        brepro = [i for i, word in enumerate(words) if word == "link-arg=/Brepro"]
        alt = [
            i for i, word in enumerate(words) if word == "link-arg=/PDBALTPATH:%_PDB%"
        ]
        self.assertEqual(brepro, [words.index("link-arg=/Brepro")])
        self.assertEqual(words[brepro[0] - 1], "-C")
        self.assertEqual(words[alt[0] - 1], "-C")

    def test_linux_keeps_the_linker_flag_and_skips_brepro(self) -> None:
        words, cflags, _rustflags = flags(
            {
                "ROOT_DIR": "/io/src",
                "TARGET": "x86_64-unknown-linux-gnu",
                "CARGO_HOME": "/io/src/.ci-cargo",
                "RUSTUP_HOME": "/io/src/.ci-rustup",
                "CFLAGS": "-DHAVE_UNISTD_H",
                "RUSTFLAGS": "-C link-arg=-fuse-ld=bfd",
            }
        )
        self.assertEqual(cflags, "-DHAVE_UNISTD_H")
        self.assertNotIn("link-arg=/Brepro", words)
        remaps = [word for word in words if word.startswith("--remap-path-prefix=")]
        self.assertEqual(
            remaps[0],
            "--remap-path-prefix=/io/src/.ci-rustup/=/rustup/",
        )
        self.assertIn("--remap-path-prefix=/io/src/.ci-cargo/=/cargo-home/", remaps)
        self.assertIn("--remap-path-prefix=/io/src/=/src/", remaps)
        cargo_at = remaps.index("--remap-path-prefix=/io/src/.ci-cargo/=/cargo-home/")
        root_at = remaps.index("--remap-path-prefix=/io/src/=/src/")
        self.assertLess(cargo_at, root_at)

    def test_script_is_sourced(self) -> None:
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("source this script", done.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
