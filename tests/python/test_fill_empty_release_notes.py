"""Empty GitHub Release bodies are filled from the changelog section."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fill-empty-release-notes.sh"

FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os
    import pathlib
    import sys

    log = pathlib.Path(os.environ["GH_LOG"])
    with log.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(sys.argv[1:]) + "\\n")
    cmd = sys.argv[1:]
    if cmd[:2] == ["release", "view"]:
        sys.stdout.write(os.environ.get("GH_BODY", ""))
        raise SystemExit(0)
    if cmd[:2] == ["release", "edit"] and "--notes-file" in cmd:
        notes = pathlib.Path(cmd[cmd.index("--notes-file") + 1])
        pathlib.Path(os.environ["GH_NOTES"]).write_text(
            notes.read_text(encoding="utf-8"), encoding="utf-8"
        )
        raise SystemExit(0)
    raise SystemExit("unexpected gh " + " ".join(cmd))
    """
)

CHANGELOG = textwrap.dedent(
    """\
    # Changelog

    ## v9.9.9 - 2026-01-01

    ### Features

    - The notes body.

    ## v9.9.8 - 2025-12-01

    - Older.
    """
)


class FillEmptyReleaseNotesTest(unittest.TestCase):
    def test_empty_body_is_replaced_with_the_version_section(self) -> None:
        notes = self._run("")
        self.assertTrue(notes.startswith("## v9.9.9 - 2026-01-01\n"))
        self.assertIn("The notes body.", notes)
        self.assertNotIn("v9.9.8", notes)

    def test_existing_body_is_left_alone(self) -> None:
        notes = self._run("already written\n")
        self.assertEqual(notes, "")

    def _run(self, body: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "gh.log"
            written = root / "notes-out.md"
            changelog = root / "CHANGELOG.md"
            changelog.write_text(CHANGELOG, encoding="utf-8")
            bindir = root / "bin"
            bindir.mkdir()
            gh = bindir / "gh"
            gh.write_text(FAKE_GH, encoding="utf-8")
            gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
            env = os.environ.copy()
            env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
            env["GH_LOG"] = str(log)
            env["GH_BODY"] = body
            env["GH_NOTES"] = str(written)
            env["GITHUB_REPOSITORY"] = "lode-org/readcon-core"
            done = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--tag",
                    "v9.9.9",
                    "--changelog",
                    str(changelog),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            text = log.read_text(encoding="utf-8")
            self.assertIn("--repo lode-org/readcon-core", text)
            self.assertNotIn("release create", text)
            return written.read_text(encoding="utf-8") if written.exists() else ""
