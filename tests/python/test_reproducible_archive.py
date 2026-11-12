"""SOURCE_DATE_EPOCH lookup and byte-stable tarballs.

The clib backfill packs a tag checkout from scripts that live on the
workflow ref. The tag may have no pin, and a manylinux mount is owned by
another user. macOS tar is bsdtar and rejects GNU --sort=name.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EPOCH_SCRIPT = ROOT / "scripts" / "source-date-epoch.sh"
TAR_SCRIPT = ROOT / "scripts" / "reproducible-tar.sh"
PIN = (
    (ROOT / "packaging" / "wrapdb" / "source-date-epoch")
    .read_text(encoding="utf-8")
    .strip()
)
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _run(
    script: Path, args: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("SOURCE_DATE_EPOCH", None)
    merged.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(
        ["git", "-C", str(repo), *args],
        cwd=repo,
        env=merged,
        check=True,
        capture_output=True,
        text=True,
    )


class SourceDateEpochTest(unittest.TestCase):
    def test_tree_pin_beats_the_packager_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            root.mkdir()
            (root / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
            pin = root / "packaging" / "wrapdb"
            pin.mkdir(parents=True)
            (pin / "source-date-epoch").write_text("222\n", encoding="utf-8")
            done = _run(EPOCH_SCRIPT, [str(root)], {"HOME": tmp})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "222")

    def test_packager_pin_when_the_tag_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tag"
            root.mkdir()
            (root / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
            bindir = Path(tmp) / "bin"
            bindir.mkdir()
            git = bindir / "git"
            git.write_text(
                "#!/bin/sh\necho git-called >&2\nexit 99\n", encoding="utf-8"
            )
            git.chmod(git.stat().st_mode | stat.S_IEXEC)
            done = _run(
                EPOCH_SCRIPT,
                [str(root)],
                {"HOME": tmp, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), PIN)
        self.assertNotIn("git-called", done.stderr)

    def test_packager_pin_is_not_used_for_another_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "old"
            root.mkdir()
            (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            _git(root, "init", "-b", "main")
            _git(root, "add", "VERSION")
            commit_env = {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
                "GIT_AUTHOR_DATE": "2020-01-02T03:04:05-0600",
                "GIT_COMMITTER_DATE": "2020-01-02T03:04:05-0600",
            }
            _git(root, "commit", "-m", "pin me", env=commit_env)
            expected = subprocess.run(
                ["git", "-C", str(root), "log", "-1", "--format=%ct"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            done = _run(EPOCH_SCRIPT, [str(root)], {"HOME": tmp})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), expected)
        self.assertNotEqual(done.stdout.strip(), PIN)

    def test_fresh_ignores_the_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fresh"
            root.mkdir()
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            pin = root / "packaging" / "wrapdb"
            pin.mkdir(parents=True)
            (pin / "source-date-epoch").write_text("222\n", encoding="utf-8")
            _git(root, "init", "-b", "main")
            _git(root, "add", ".")
            commit_env = {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
                "GIT_AUTHOR_DATE": "2020-01-02T03:04:05-0600",
                "GIT_COMMITTER_DATE": "2020-01-02T03:04:05-0600",
            }
            _git(root, "commit", "-m", "fresh", env=commit_env)
            expected = subprocess.run(
                ["git", "-C", str(root), "log", "-1", "--format=%ct"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            done = _run(EPOCH_SCRIPT, ["--fresh", str(root)], {"HOME": tmp})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), expected)
        self.assertNotEqual(done.stdout.strip(), "222")

    def test_root_owned_checkout_without_a_pin(self) -> None:
        if shutil.which("sudo") is None:
            self.skipTest("sudo is required")
        probe = subprocess.run(["sudo", "-n", "true"], check=False)
        if probe.returncode != 0:
            self.skipTest("passwordless sudo is required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mounted"
            root.mkdir()
            (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            _git(root, "init", "-b", "main")
            _git(root, "add", "VERSION")
            commit_env = {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
                "GIT_AUTHOR_DATE": "2020-01-02T03:04:05-0600",
                "GIT_COMMITTER_DATE": "2020-01-02T03:04:05-0600",
            }
            _git(root, "commit", "-m", "mounted", env=commit_env)
            expected = subprocess.run(
                ["git", "-C", str(root), "log", "-1", "--format=%ct"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["sudo", "-n", "chown", "-R", "root:root", str(root)], check=True
            )
            subprocess.run(["sudo", "-n", "chmod", "-R", "a+rX", str(root)], check=True)
            home = Path(tmp) / "home"
            home.mkdir()
            try:
                done = _run(EPOCH_SCRIPT, [str(root)], {"HOME": str(home)})
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.strip(), expected)
                self.assertNotIn("dubious ownership", done.stderr)
            finally:
                subprocess.run(
                    [
                        "sudo",
                        "-n",
                        "chown",
                        "-R",
                        f"{os.getuid()}:{os.getgid()}",
                        str(root),
                    ],
                    check=False,
                )


def _fill(root: Path, order: str) -> None:
    root.mkdir(parents=True)
    (root / "sub").mkdir()
    files = {
        "b.txt": "1\n",
        "a.txt": "2\n",
        "sub/c.txt": "3\n",
    }
    names = list(files) if order == "forward" else list(reversed(files))
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[name], encoding="utf-8")


def _pack(
    tree: Path, out: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    parent = tree.parent
    merged = os.environ.copy()
    merged["SOURCE_DATE_EPOCH"] = "1794454673"
    merged.update(env)
    return subprocess.run(
        [
            "bash",
            str(TAR_SCRIPT),
            str(parent),
            str(parent),
            tree.name,
            str(out),
        ],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _members(path: Path) -> list[tarfile.TarInfo]:
    with tarfile.open(path, "r:gz") as archive:
        return archive.getmembers()


class ReproducibleTarTest(unittest.TestCase):
    def test_gnu_tar_is_stable_across_creation_order(self) -> None:
        self._assert_stable({})

    def test_bsdtar_is_stable_across_creation_order(self) -> None:
        bsdtar = shutil.which("bsdtar")
        if bsdtar is None:
            self.skipTest("bsdtar is required")
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp) / "bin"
            bindir.mkdir()
            os.symlink(bsdtar, bindir / "tar")
            parts = [str(bindir)]
            for part in os.environ["PATH"].split(os.pathsep):
                if (Path(part) / "gtar").exists():
                    continue
                parts.append(part)
            self._assert_stable(
                {"PATH": os.pathsep.join(parts), "REPRO_TAR_EXPECT": "bsd"}
            )

    def _assert_stable(self, env: dict[str, str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a" / "pkg"
            second = Path(tmp) / "b" / "pkg"
            _fill(first, "forward")
            _fill(second, "reverse")
            out_a = Path(tmp) / "a.tar.gz"
            out_b = Path(tmp) / "b.tar.gz"
            done_a = _pack(first, out_a, env)
            done_b = _pack(second, out_b, env)
            self.assertEqual(done_a.returncode, 0, done_a.stderr)
            self.assertEqual(done_b.returncode, 0, done_b.stderr)
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())
            members = _members(out_a)
            names = [item.name for item in members]
            self.assertEqual(names, sorted(names))
            expect_root = env.get("REPRO_TAR_EXPECT") == "bsd"
            for item in members:
                self.assertEqual(item.mtime, 1794454673)
                self.assertEqual(item.uid, 0)
                self.assertEqual(item.gid, 0)
                self.assertEqual(item.pax_headers, {})
                if expect_root:
                    self.assertEqual(item.uname, "root")
                    self.assertEqual(item.gname, "root")
                else:
                    self.assertEqual(item.uname, "")
                    self.assertEqual(item.gname, "")
                if item.isdir():
                    self.assertEqual(item.mode, 0o755)
                else:
                    self.assertEqual(item.mode, 0o644)
            raw = out_a.read_bytes()
            self.assertEqual(raw[3] & 0x08, 0)
            self.assertEqual(int.from_bytes(raw[4:8], "little"), 0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
