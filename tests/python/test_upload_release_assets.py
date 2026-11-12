"""cxx and clib release assets upload onto an existing tag.

The uploader's only write is `gh release upload --clobber`. A backfill must
not create a release, move a tag, or publish crates or wheels.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "upload-release-assets.sh"
WORKFLOWS = (
    ROOT / ".github/workflows/cxx_tarball.yml",
    ROOT / ".github/workflows/c_lib_tarball.yml",
)

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
        state = pathlib.Path(os.environ["GH_STATE"])
        seen = int(state.read_text(encoding="utf-8") or "0")
        state.write_text(str(seen + 1), encoding="utf-8")
        if seen < int(os.environ.get("GH_VIEW_FAILS", "0")):
            sys.stderr.write("release not found\\n")
            sys.exit(1)
        print(os.environ.get("GH_TAG", "v0.20.0"))
        sys.exit(0)
    if cmd[:2] == ["release", "upload"]:
        if "--clobber" not in cmd:
            sys.stderr.write("missing --clobber\\n")
            sys.exit(3)
        if "--target" in cmd or "create" in cmd:
            sys.stderr.write("upload must not retarget\\n")
            sys.exit(4)
        sys.exit(0)
    if cmd[:1] == ["api"]:
        state = pathlib.Path(os.environ["GH_API_STATE"])
        seen = int(state.read_text(encoding="utf-8") or "0")
        state.write_text(str(seen + 1), encoding="utf-8")
        shas = os.environ.get("GH_SHAS", "abc,abc").split(",")
        print(shas[min(seen, len(shas) - 1)])
        sys.exit(0)
    sys.stderr.write("unexpected gh args: %s\\n" % cmd)
    sys.exit(9)
    """
)


def run_upload(
    args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("GH_TOKEN", None)
    merged.pop("GITHUB_TOKEN", None)
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


class UploadReleaseAssetsTest(unittest.TestCase):
    def test_dry_run_is_clobber_upload_and_does_not_call_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "readcon-core-cxx-0.20.0.tar.gz"
            asset.write_text("archive", encoding="utf-8")
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
            gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
            done = run_upload(
                ["--tag", "v0.20.0", "--dry-run", str(asset)],
                {
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "GITHUB_REPOSITORY": "lode-org/readcon-core",
                },
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            "would run: gh release upload v0.20.0 --repo lode-org/readcon-core --clobber",
            done.stdout,
        )
        self.assertIn("readcon-core-cxx-0.20.0.tar.gz", done.stdout)
        self.assertIn("would require existing release v0.20.0", done.stdout)
        self.assertNotIn("would wait", done.stdout)

    def test_dry_run_wait_is_still_only_an_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "readcon-core-clib-0.20.0.tar.gz"
            asset.write_text("archive", encoding="utf-8")
            done = run_upload(
                ["--tag", " v0.20.0\n", "--wait", "--dry-run", str(asset)],
                {"GITHUB_REPOSITORY": "lode-org/readcon-core"},
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            "gh release upload v0.20.0 --repo lode-org/readcon-core --clobber",
            done.stdout,
        )
        self.assertIn("would wait for existing release v0.20.0", done.stdout)
        for banned in (
            "release create",
            "cargo publish",
            "git tag",
            "git push",
            "--target",
        ):
            self.assertNotIn(banned, done.stdout)

    def test_tag_must_be_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "asset.tar.gz"
            asset.write_text("archive", encoding="utf-8")
            for tag in ("main", "v0.20", "refs/tags/v0.20.0", ""):
                done = run_upload(["--tag", tag, "--dry-run", str(asset)])
                self.assertNotEqual(done.returncode, 0, tag)
            ok = run_upload(
                ["--tag", "v0.20.0-rc.1", "--dry-run", str(asset)],
                {"GITHUB_REPOSITORY": "lode-org/readcon-core"},
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_backfill_refuses_a_missing_release(self) -> None:
        done, log = self._with_fake_gh(
            ["--tag", "v0.20.0", str(self.asset)], view_fails=1
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("release not found", done.stderr)
        self.assertIn("does not exist", done.stderr)
        self.assertIn("release view v0.20.0 --repo lode-org/readcon-core", log)
        self.assertNotIn("release upload", log)
        self.assertNotIn("api ", log)

    def test_wait_uploads_without_moving_the_tag(self) -> None:
        done, log = self._with_fake_gh(
            ["--tag", "v0.20.0", "--wait", str(self.asset)],
            view_fails=1,
            shas="abc,abc",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            "release upload v0.20.0 --repo lode-org/readcon-core --clobber",
            log,
        )
        self.assertEqual(log.count("api "), 2)

    def test_moved_tag_fails_the_upload(self) -> None:
        done, log = self._with_fake_gh(
            ["--tag", "v0.20.0", str(self.asset)],
            shas="abc,def",
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("moved during upload", done.stderr)
        self.assertIn(
            "release upload v0.20.0 --repo lode-org/readcon-core --clobber",
            log,
        )

    def test_gh_release_calls_pass_repo(self) -> None:
        done, log = self._with_fake_gh(["--tag", "v0.20.0", str(self.asset)])
        self.assertEqual(done.returncode, 0, done.stderr)
        view = "release view v0.20.0 --repo lode-org/readcon-core"
        upload = "release upload v0.20.0 --repo lode-org/readcon-core --clobber"
        self.assertIn(view, log)
        self.assertIn(upload, log)
        self.assertEqual(log.count("--repo lode-org/readcon-core"), 2)

    def test_wait_gives_up_without_creating_a_release(self) -> None:
        done, log = self._with_fake_gh(
            ["--tag", "v0.20.0", "--wait", str(self.asset)],
            view_fails=99,
            extra_env={"UPLOAD_POLL_SECONDS": "0", "UPLOAD_WAIT_TIMEOUT": "1"},
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not creating one", done.stderr)
        self.assertNotIn("release upload", log)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.asset = Path(self._tmp.name) / "readcon-core-cxx-0.20.0.tar.gz"
        self.asset.write_text("archive", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _with_fake_gh(
        self,
        args: list[str],
        view_fails: int = 0,
        shas: str = "abc,abc",
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        root = Path(self._tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        log = root / "gh.log"
        state = root / "views"
        api_state = root / "apis"
        state.write_text("0", encoding="utf-8")
        api_state.write_text("0", encoding="utf-8")
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GH_LOG": str(log),
            "GH_STATE": str(state),
            "GH_API_STATE": str(api_state),
            "GH_VIEW_FAILS": str(view_fails),
            "GH_SHAS": shas,
            "GH_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "lode-org/readcon-core",
            "UPLOAD_POLL_SECONDS": "0",
            "UPLOAD_WAIT_TIMEOUT": "5",
        }
        if extra_env:
            env.update(extra_env)
        done = run_upload(args, env)
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        return done, text


class TarballWorkflowTriggerTest(unittest.TestCase):
    def test_uploader_cannot_publish_or_move_tags(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("gh release upload", text)
        self.assertIn("--clobber", text)
        self.assertIn('--repo "$repo"', text)
        self.assertNotIn("2>&1", text)
        for banned in (
            "gh release create",
            "gh release edit",
            "git tag",
            "git push",
            "cargo publish",
            "twine",
            "--target",
        ):
            self.assertNotIn(banned, text)

    def test_workflows_follow_v_tags_and_dispatch(self) -> None:
        for path in WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("push:", text)
            self.assertIn("- 'v*'", text)
            self.assertIn("workflow_dispatch:", text)
            self.assertIn("tag:", text)
            self.assertIn("upload-release-assets.sh", text)
            self.assertIn("persist-credentials: false", text)
            self.assertNotIn("types: [published]", text)
            self.assertNotIn("action-gh-release", text)
            self.assertNotIn("cargo publish", text)
            active = "\n".join(
                line for line in text.splitlines() if not line.strip().startswith("#")
            )
            for banned in ("gh release create", "git tag", "git push", "twine upload"):
                self.assertNotIn(banned, active, path.name)

    def test_backfill_uses_the_workflow_ref_uploader(self) -> None:
        cxx = (ROOT / ".github/workflows/cxx_tarball.yml").read_text(encoding="utf-8")
        clib = (ROOT / ".github/workflows/c_lib_tarball.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("uploader/scripts/upload-release-assets.sh", cxx)
        self.assertIn("packager/scripts/upload-release-assets.sh", clib)
        self.assertIn("github.event_name != 'workflow_dispatch'", cxx)
        self.assertIn("github.event_name != 'workflow_dispatch'", clib)

    def test_workflow_gh_release_calls_pass_repo(self) -> None:
        for path in (
            ROOT / ".github/workflows/dist_backfill.yml",
            ROOT / ".github/workflows/release.yml",
            SCRIPT,
        ):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "gh release " not in stripped:
                    continue
                self.assertIn("--repo", stripped, f"{path.name}: {stripped}")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
