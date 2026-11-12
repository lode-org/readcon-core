"""Negative fixtures for tag and artifact version agreement."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_release_artifacts.py"
TOOLCHAIN = Path("/usr/local/rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/bin")


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
                "v0.20.0",
                "0.20.0",
                {
                    "readcon-0.20.0-cp312-cp312-manylinux_2_17_x86_64.whl": "w",
                    "readcon_chemfiles-0.20.0.tar.gz": "s",
                    "readcon-core-cxx-0.20.0.tar.gz": "c",
                    "readcon-core-clib-0.20.0-x86_64-unknown-linux-gnu.tar.gz": "l",
                },
            ),
            0,
        )

    def test_old_wheel_name_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.20.0",
                "0.20.0",
                {"readcon-0.17.3-cp312-cp312-manylinux_2_17_x86_64.whl": "w"},
            ),
            0,
        )

    def test_version_file_must_match_the_tag(self) -> None:
        self.assertNotEqual(
            run("v0.20.0", "0.17.3", {"readcon-0.17.3.tar.gz": "s"}),
            0,
        )

    def test_dist_binary_without_manifest_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.20.0",
                "0.20.0",
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
                "v0.20.0",
                "0.20.0",
                {"readcon-core-x86_64-unknown-linux-gnu.tar.xz": "b"},
                manifest,
            ),
            0,
        )

    def test_scratch_dist_manifests_are_accepted_when_the_version_matches(self) -> None:
        name = "readcon-core-x86_64-unknown-linux-gnu.tar.xz"
        body = {
            "announcement_tag": "v0.19.0",
            "releases": [{"app_version": "0.19.0", "artifacts": [name]}],
            "artifacts": {name: {"name": name}},
        }
        encoded = json.dumps(body)
        self.assertEqual(
            run(
                "v0.19.0",
                "0.19.0",
                {
                    name: "b",
                    "x86_64-unknown-linux-gnu-dist-manifest.json": encoded,
                    "global-dist-manifest.json": encoded,
                    "plan-dist-manifest.json": encoded,
                },
            ),
            0,
        )

    def test_scratch_dist_manifest_version_must_match_the_tag(self) -> None:
        name = "readcon-core-x86_64-unknown-linux-gnu.tar.xz"
        bad = {
            "announcement_tag": "v0.17.3",
            "releases": [{"app_version": "0.17.3", "artifacts": [name]}],
            "artifacts": {},
        }
        self.assertNotEqual(
            run(
                "v0.19.0",
                "0.19.0",
                {name: "b", "global-dist-manifest.json": json.dumps(bad)},
            ),
            0,
        )

    def test_release_host_installs_python_312_before_the_check(self) -> None:
        yml = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        setup = yml.find(
            "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
        )
        check = yml.find("Require dist metadata to match the tag")
        self.assertGreater(setup, 0)
        self.assertLess(setup, check)
        self.assertIn('python-version: "3.12"', yml)
        self.assertIn(
            'allow-dirty = ["ci"]', (ROOT / "dist-workspace.toml").read_text()
        )

    def test_dist_backfill_uploads_without_publishing_or_tagging(self) -> None:
        yml = (ROOT / ".github/workflows/dist_backfill.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", yml)
        self.assertIn("gh release upload", yml)
        self.assertIn('--repo "$GITHUB_REPOSITORY"', yml)
        self.assertIn("--clobber", yml)
        self.assertIn("ref: ${{ needs.plan.outputs.tag }}", yml)
        self.assertIn("packager/scripts/check_release_artifacts.py", yml)
        self.assertNotIn("gh release create", yml)
        self.assertNotIn("cargo publish", yml)
        self.assertNotIn("twine", yml)
        self.assertNotIn("git tag", yml)
        self.assertNotIn("softprops/action-gh-release", yml)

    def test_dist_binary_passes_when_manifest_version_matches(self) -> None:
        name = "readcon-core-x86_64-unknown-linux-gnu.tar.xz"
        manifest = {
            "announcement_tag": "v0.20.0",
            "releases": [
                {"app_version": "0.20.0", "artifacts": [name, "source.tar.gz"]}
            ],
            "artifacts": {name: {"name": name}},
        }
        self.assertEqual(
            run("v0.20.0", "0.20.0", {name: "b", "source.tar.gz": "s"}, manifest),
            0,
        )

    def test_wrap_names_are_not_release_assets(self) -> None:
        self.assertNotEqual(
            run(
                "v0.20.0",
                "0.20.0",
                {
                    "readcon-core-cxx-0.20.0.tar.gz": "c",
                    "readcon-core.wrap": "slim hash overwritten by vendor",
                },
            ),
            0,
        )
        self.assertNotEqual(
            run(
                "v0.20.0",
                "0.20.0",
                {"readcon-core-cxx-0.20.0.wrap": "versioned sidecar"},
            ),
            0,
        )

    def test_cxx_workflow_uploads_only_the_two_archives(self) -> None:
        yml = (ROOT / ".github/workflows/cxx_tarball.yml").read_text(encoding="utf-8")
        self.assertIn("build-cxx/slim", yml)
        self.assertIn("build-cxx/vendor", yml)
        self.assertNotIn("package-cxx.sh dist-cxx", yml)
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slim = root / "build-cxx" / "slim"
            vendor = root / "build-cxx" / "vendor"
            dist = root / "dist-cxx"
            for path in (slim, vendor, dist):
                path.mkdir(parents=True)
            env = os.environ.copy()
            if TOOLCHAIN.is_dir():
                env["PATH"] = f"{TOOLCHAIN}{os.pathsep}{env.get('PATH', '')}"
            for args, dest in (
                (["bash", "scripts/package-cxx.sh", str(slim)], slim),
                (["bash", "scripts/package-cxx.sh", str(vendor), "--vendor"], vendor),
            ):
                done = subprocess.run(args, cwd=ROOT, env=env, check=False)
                self.assertEqual(done.returncode, 0, args)
            names = {
                f"readcon-core-cxx-{version}.tar.gz",
                f"readcon-core-cxx-{version}.tar.gz.sha256",
                f"readcon-core-cxx-{version}-vendor.tar.gz",
                f"readcon-core-cxx-{version}-vendor.tar.gz.sha256",
            }
            for name in names:
                source = slim if "vendor" not in name else vendor
                (dist / name).write_bytes((source / name).read_bytes())
            self.assertEqual(run_dir("v" + version, version, dist), 0)
            uploaded = set()
            for pattern in (
                "readcon-core-cxx-*.tar.gz",
                "readcon-core-cxx-*.tar.gz.sha256",
            ):
                uploaded.update(path.name for path in dist.glob(pattern))
            self.assertEqual(
                uploaded, {path.name for path in dist.iterdir() if path.is_file()}
            )
            self.assertEqual(uploaded, names)
            for build in (slim, vendor):
                self.assertFalse((build / "readcon-core.wrap").exists())
            slim_wrap = (slim / f"readcon-core-cxx-{version}.wrap").read_text(
                encoding="utf-8"
            )
            vendor_wrap = (
                vendor / f"readcon-core-cxx-{version}-vendor.wrap"
            ).read_text(encoding="utf-8")
            slim_sha = (
                (slim / f"readcon-core-cxx-{version}.tar.gz.sha256").read_text().strip()
            )
            vendor_sha = (
                (vendor / f"readcon-core-cxx-{version}-vendor.tar.gz.sha256")
                .read_text()
                .strip()
            )
            self.assertIn(
                f"source_filename = readcon-core-cxx-{version}.tar.gz", slim_wrap
            )
            self.assertIn(f"source_hash = sha256:{slim_sha}", slim_wrap)
            vendor_filename = vendor_wrap.split("source_filename = ", 1)[1].split(
                "\n", 1
            )[0]
            self.assertEqual(
                vendor_filename, f"readcon-core-cxx-{version}-vendor.tar.gz"
            )
            self.assertIn(f"source_hash = sha256:{vendor_sha}", vendor_wrap)
            self.assertNotEqual(slim_sha, vendor_sha)

    def test_package_scripts_hand_cygpath_output_to_python(self) -> None:
        for name in ("package-clib.sh", "package-cxx.sh"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("cygpath -w", text)
            self.assertIn("sys.argv[1]", text)
            self.assertNotIn("Path(\"'\"$ROOT_DIR\"'", text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "cygpath.log"
            argv_log = root / "python-argv.txt"
            cygpath = bin_dir / "cygpath"
            cygpath.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$CYGPATH_LOG"\n'
                "shift\n"
                'printf "%s\\n" "$1"\n',
                encoding="utf-8",
            )
            cygpath.chmod(cygpath.stat().st_mode | stat.S_IEXEC)
            wrapper = bin_dir / "python3"
            wrapper.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$3" >> "$PYTHON_ARGV"\n'
                'exec /usr/bin/python3 "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
            prefix = root / "prefix"
            (prefix / "include").mkdir(parents=True)
            (prefix / "lib" / "pkgconfig").mkdir(parents=True)
            for header in (
                "readcon-core.h",
                "readcon-core.hpp",
                "readcon-metatensor.h",
            ):
                (prefix / "include" / header).write_bytes(
                    (ROOT / "include" / header).read_bytes()
                )
            (prefix / "lib" / "libreadcon_core.so").write_text(
                "stub\n", encoding="utf-8"
            )
            out = root / "out"
            out.mkdir()
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["CYGPATH_LOG"] = str(log)
            env["PYTHON_ARGV"] = str(argv_log)
            done = subprocess.run(
                [
                    "bash",
                    "scripts/package-clib.sh",
                    str(out),
                    "--from-prefix",
                    str(prefix),
                    "--target",
                    "fixture",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            recorded = log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(recorded, "cygpath was not called")
            self.assertTrue(recorded[0].startswith("-w "))
            version_path = recorded[0].split(" ", 1)[1]
            self.assertTrue(version_path.endswith("/VERSION"), version_path)
            self.assertEqual(
                argv_log.read_text(encoding="utf-8").splitlines()[0],
                version_path,
            )

    def test_clib_nested_checkout_accepts_the_julia_manifest(self) -> None:
        yml = (ROOT / ".github/workflows/c_lib_tarball.yml").read_text(encoding="utf-8")
        self.assertIn("cygpath -w", yml)
        self.assertIn(
            'native "$GITHUB_WORKSPACE/packager/scripts/check_release_artifacts.py"',
            yml,
        )
        self.assertIn('native "$GITHUB_WORKSPACE/src/VERSION"', yml)
        self.assertIn('native "$GITHUB_WORKSPACE/dist-clib"', yml)
        self.assertNotIn(
            'python3 scripts/check_release_artifacts.py --tag "$RELEASE_TAG" --dist dist-clib',
            yml,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            code = clib_workspace(ws, "0.20.0", "0.20.0", "abc")
            self.assertEqual(code, 0)
            missing = subprocess.call(
                [
                    sys.executable,
                    "scripts/check_release_artifacts.py",
                    "--tag",
                    "v0.20.0",
                ],
                cwd=ws,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertNotEqual(missing, 0)

    def test_clib_manifest_rejects_a_wrong_version_and_a_wrong_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.20.0", "0.17.3", "old"), 0)
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.20.0", "0.20.0", "old-url"), 0)
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.20.0", "0.20.0", "bad-hash"), 0)

    def test_cachegrind_harness_builds_with_and_without_chemfiles(self) -> None:
        env = os.environ.copy()
        if TOOLCHAIN.is_dir():
            env["PATH"] = f"{TOOLCHAIN}{os.pathsep}{env.get('PATH', '')}"
        plain = subprocess.run(
            [
                "cargo",
                "rustc",
                "--locked",
                "--example",
                "cachegrind_harness",
                "--",
                "-D",
                "unused_mut",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(plain.returncode, 0)
        featured = subprocess.run(
            [
                "cargo",
                "rustc",
                "--locked",
                "--example",
                "cachegrind_harness",
                "--features",
                "chemfiles-from-sources",
                "--",
                "-D",
                "unused_mut",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        )
        self.assertEqual(featured.returncode, 0)


def run_dir(tag: str, version: str, dist: Path) -> int:
    return subprocess.call(
        [
            sys.executable,
            str(SCRIPT),
            "--tag",
            tag,
            "--version-file",
            str(ROOT / "VERSION"),
            "--dist",
            str(dist),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def clib_workspace(
    ws: Path, packed_version: str, archive_version: str, mode: str
) -> int:
    target = "x86_64-unknown-linux-gnu"
    packager = ws / "packager" / "scripts"
    packager.mkdir(parents=True)
    (packager / "check_release_artifacts.py").write_bytes(SCRIPT.read_bytes())
    (ws / "packager" / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "VERSION").write_text(packed_version + "\n", encoding="utf-8")
    dist = ws / "dist-clib"
    dist.mkdir()
    archive = f"readcon-core-clib-{archive_version}-{target}.tar.gz"
    body = b"clib-bytes"
    digest = hashlib.sha256(body).hexdigest()
    (dist / archive).write_bytes(body)
    (dist / f"{archive}.sha256").write_text(digest + "\n", encoding="utf-8")
    url_version = "0.17.3" if mode == "old-url" else archive_version
    sha = "0" * 64 if mode == "bad-hash" else digest
    toml = f"""# filled artifact manifest
[readcon_core]
git-tree-sha1 = "0000000000000000000000000000000000000000"
lazy = true

    [[readcon_core.download]]
    url = "https://github.com/lode-org/readcon-core/releases/download/v{url_version}/{archive}"
    sha256 = "{sha}"
"""
    (dist / f"Artifacts-{target}.toml").write_text(toml, encoding="utf-8")
    env = os.environ.copy()
    env["GITHUB_WORKSPACE"] = str(ws)
    env["RELEASE_TAG"] = "v0.20.0"
    return subprocess.call(
        [
            "bash",
            "-lc",
            'native() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; '
            'else printf "%s\\n" "$1"; fi; }; '
            'python3 "$(native "$GITHUB_WORKSPACE/packager/scripts/check_release_artifacts.py")" '
            '--tag "$RELEASE_TAG" '
            '--version-file "$(native "$GITHUB_WORKSPACE/src/VERSION")" '
            '--dist "$(native "$GITHUB_WORKSPACE/dist-clib")"',
        ],
        cwd=ws,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    unittest.main()
