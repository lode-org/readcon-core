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
PIN_SCRIPT = ROOT / "scripts" / "accept-cxx-wrap-pin.sh"
TAR_SCRIPT = ROOT / "scripts" / "reproducible-tar.sh"
CXX_PIN = ROOT / "packaging" / "wrapdb" / "readcon-core.sha256"
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


def _head_is_release() -> bool:
    """Whether HEAD is the release whose archive pin it carries."""
    tagged = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "describe",
            "--exact-match",
            "--match",
            f"v{VERSION}",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return tagged.returncode == 0


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


class AcceptCxxWrapPinTest(unittest.TestCase):
    def test_tag_pin_match_does_not_consult_the_workflow_ref(self) -> None:
        built = "3" * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tag"
            _write_pin(root, "9.9.9", built)
            done = _run(PIN_SCRIPT, [built, str(root)], {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "")

    def test_same_tree_mismatch_is_a_refusal(self) -> None:
        built = "0" * 64
        done = _run(PIN_SCRIPT, [built, str(ROOT)], {})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"refusing upload: built {built} != wrap pin", done.stderr)
        self.assertNotIn("workflow-ref", done.stderr)
        self.assertNotIn("workflow-ref pin matches", done.stdout)

    def test_workflow_ref_pin_when_the_versions_match(self) -> None:
        pin = (
            (ROOT / "packaging" / "wrapdb" / "readcon-core.sha256")
            .read_text(encoding="utf-8")
            .strip()
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tag"
            _write_pin(root, VERSION, "1" * 64)
            done = _run(PIN_SCRIPT, [pin, str(root)], {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("workflow-ref pin matches this build", done.stdout)

    def test_workflow_ref_pin_is_not_used_for_another_version(self) -> None:
        pin = (
            (ROOT / "packaging" / "wrapdb" / "readcon-core.sha256")
            .read_text(encoding="utf-8")
            .strip()
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "old"
            _write_pin(root, "9.9.9", "1" * 64)
            done = _run(PIN_SCRIPT, [pin, str(root)], {})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("refusing upload", done.stderr)
        self.assertNotIn("workflow-ref pin matches", done.stdout)

    def test_workflow_ref_pin_must_be_this_build(self) -> None:
        built = "2" * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tag"
            _write_pin(root, VERSION, "1" * 64)
            done = _run(PIN_SCRIPT, [built, str(root)], {})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(
            f"refusing upload: built {built} != wrap pin {'1' * 64}",
            done.stderr,
        )
        self.assertIn("workflow-ref pin", done.stderr)
        self.assertIn("does not match this build either", done.stderr)


def _write_pin(root: Path, version: str, digest: str) -> None:
    root.mkdir(parents=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    pin = root / "packaging" / "wrapdb"
    pin.mkdir(parents=True)
    (pin / "readcon-core.sha256").write_text(digest + "\n", encoding="utf-8")


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


class CxxArchiveStabilityTest(unittest.TestCase):
    def test_slim_archive_ignores_directory_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "no-tag"
            tagged = Path(tmp) / "tagged"
            _shared_clone(bare)
            _shared_clone(tagged)
            for repo in (bare, tagged):
                subprocess.run(
                    ["git", "-C", str(repo), "tag", "-d", f"v{VERSION}"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            _git(tagged, "tag", f"v{VERSION}", "HEAD")
            bare_out = Path(tmp) / "no-tag-out"
            tagged_out = Path(tmp) / "tagged-out"
            other_dir = Path(tmp) / "other-out"
            self.assertEqual(_slim_sha(bare, bare_out), _slim_sha(tagged, tagged_out))
            self.assertEqual(
                _slim_sha(bare, other_dir),
                _slim_sha(bare, bare_out),
            )
            if _head_is_release():
                pin = CXX_PIN.read_text(encoding="utf-8").strip()
                self.assertEqual(_slim_sha(bare, bare_out), pin)


class CallerEpochTest(unittest.TestCase):
    def test_a_caller_epoch_does_not_move_the_recorded_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            _shared_clone(repo)
            first = _repo_script(repo, "record-cxx-wrap.sh", None)
            self.assertEqual(first.returncode, 0, first.stderr)
            _git(
                repo,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "--allow-empty",
                "-am",
                "record the pin",
            )
            pin = (repo / "packaging" / "wrapdb" / "readcon-core.sha256").read_text(
                encoding="utf-8"
            )
            epoch = (repo / "packaging" / "wrapdb" / "source-date-epoch").read_text(
                encoding="utf-8"
            )
            second = _repo_script(repo, "record-cxx-wrap.sh", "123")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                (repo / "packaging" / "wrapdb" / "readcon-core.sha256").read_text(
                    encoding="utf-8"
                ),
                pin,
            )
            self.assertEqual(
                (repo / "packaging" / "wrapdb" / "source-date-epoch").read_text(
                    encoding="utf-8"
                ),
                epoch,
            )
            self.assertIn(
                f"ignoring SOURCE_DATE_EPOCH=123; using the committed epoch {epoch.strip()}",
                second.stderr,
            )
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(status.stdout, "")
            check = _repo_script(repo, "check_cxx_wrap_pin.sh", "123")
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn("matches the packaged tree", check.stdout)


def _repo_script(
    repo: Path, script: str, epoch: str | None
) -> subprocess.CompletedProcess[str]:
    """Run a script of the clone from its root, with SOURCE_DATE_EPOCH set to epoch or unset."""
    env = os.environ.copy()
    env["RUSTUP_TOOLCHAIN"] = "1.88.0"
    env.pop("CARGO_TARGET_DIR", None)
    env.pop("SOURCE_DATE_EPOCH", None)
    if epoch is not None:
        env["SOURCE_DATE_EPOCH"] = epoch
    return subprocess.run(
        ["bash", str(repo / "scripts" / script)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


# The commit that recorded the previous pin, and that pin. Its archive still carried paper/ and the other
# trees that the include list of Cargo.toml now leaves out.
BASE_PIN_COMMIT = "eb37eeed07f7e99eed2f78cc057dca3ee81e3472"
BASE_PIN_SHA = "2b1f4a9a15f1f67e7fcffeaaa6e764807d530bd087fa0370ecdd44c858569f1a"
# The file edited on purpose since that pin, the manifest, and the copy of it cargo keeps.
EDITED = ("Cargo.toml", "Cargo.toml.orig")
# Library sources, the inputs build.rs reads, and the cxx wrap surface that package-cxx.sh lays over the crate.
LIBRARY_FILES = {
    "Cargo.lock",
    "build.rs",
    "VERSION",
    "LICENSE",
    "grammar/readcon.pest",
    "support/metatensor_install.rs",
    "schema/ReadCon.capnp",
    "CMakeLists.txt",
    "meson.build",
    "meson_options.txt",
    "README.md",
    "README.cxx.md",
    "scripts/meson_cargo_build.py",
    "examples/c_api_sample.c",
    "examples/cpp_api_sample.cpp",
    "examples/cpp_v31_units_roundtrip.cpp",
    "examples/frame_builder_consume.c",
    "examples/meson.build",
    "resources/test/tiny_multi_cuh2.con",
}
LIBRARY_TREES = ("src/", "include/", "cmake/", "third_party/metatensor-sys/")


class CxxArchiveAgainstBasePinTest(unittest.TestCase):
    def test_every_change_from_the_base_pin_archive_is_the_manifest_an_exclusion_or_library_source(
        self,
    ) -> None:
        from test_cargo_package_list import allowed

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            head = Path(tmp) / "head"
            _shared_clone(base)
            _git(base, "checkout", "--quiet", "--detach", BASE_PIN_COMMIT)
            _shared_clone(head)
            for repo in (base, head):
                subprocess.run(
                    ["git", "-C", str(repo), "tag", "-d", f"v{VERSION}"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(_slim_sha(base, Path(tmp) / "base-out"), BASE_PIN_SHA)
            _slim_sha(head, Path(tmp) / "head-out")
            old = _archive_files(
                Path(tmp) / "base-out" / f"readcon-core-cxx-{VERSION}.tar.gz"
            )
            new = _archive_files(
                Path(tmp) / "head-out" / f"readcon-core-cxx-{VERSION}.tar.gz"
            )
        changed = sorted(name for name in new if old.get(name) != new[name])
        removed = sorted(set(old) - set(new))
        library = [
            name
            for name in changed
            if name in LIBRARY_FILES or name.startswith(LIBRARY_TREES)
        ]
        # Every change is an edited manifest or a library source; anything else is a leak.
        self.assertEqual(set(changed), {*EDITED, *library})
        self.assertEqual(
            [
                name
                for name in removed
                if allowed(name) and not name.startswith(LIBRARY_TREES)
            ],
            [],
        )


def _archive_files(path: Path) -> dict[str, bytes]:
    """Each regular file of the archive by its path below the top directory, with its bytes."""
    files = {}
    with tarfile.open(path) as archive:
        for item in archive.getmembers():
            if item.isfile():
                handle = archive.extractfile(item)
                assert handle is not None
                files[item.name.split("/", 1)[1]] = handle.read()
    return files


def _shared_clone(dest: Path) -> None:
    subprocess.run(
        ["git", "clone", "--shared", str(ROOT), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )


def _slim_sha(repo: Path, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["RUSTUP_TOOLCHAIN"] = "1.88.0"
    env.pop("SOURCE_DATE_EPOCH", None)
    done = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "package-cxx.sh"),
            str(out),
            "--source-root",
            str(repo),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(done.stderr or done.stdout)
    name = f"readcon-core-cxx-{VERSION}.tar.gz.sha256"
    return (out / name).read_text(encoding="utf-8").strip()


if __name__ == "__main__":
    raise SystemExit(unittest.main())
