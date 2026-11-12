"""Negative fixtures for tag and artifact version agreement."""

from __future__ import annotations

import hashlib
import json
import os
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
                "v0.19.0",
                "0.19.0",
                {
                    "readcon-0.19.0-cp312-cp312-manylinux_2_17_x86_64.whl": "w",
                    "readcon_chemfiles-0.19.0.tar.gz": "s",
                    "readcon-core-cxx-0.19.0.tar.gz": "c",
                    "readcon-core-clib-0.19.0-x86_64-unknown-linux-gnu.tar.gz": "l",
                },
            ),
            0,
        )

    def test_old_wheel_name_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.19.0",
                "0.19.0",
                {"readcon-0.17.3-cp312-cp312-manylinux_2_17_x86_64.whl": "w"},
            ),
            0,
        )

    def test_version_file_must_match_the_tag(self) -> None:
        self.assertNotEqual(
            run("v0.19.0", "0.17.3", {"readcon-0.17.3.tar.gz": "s"}),
            0,
        )

    def test_dist_binary_without_manifest_is_refused(self) -> None:
        self.assertNotEqual(
            run(
                "v0.19.0",
                "0.19.0",
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
                "v0.19.0",
                "0.19.0",
                {"readcon-core-x86_64-unknown-linux-gnu.tar.xz": "b"},
                manifest,
            ),
            0,
        )

    def test_dist_binary_passes_when_manifest_version_matches(self) -> None:
        name = "readcon-core-x86_64-unknown-linux-gnu.tar.xz"
        manifest = {
            "announcement_tag": "v0.19.0",
            "releases": [
                {"app_version": "0.19.0", "artifacts": [name, "source.tar.gz"]}
            ],
            "artifacts": {name: {"name": name}},
        }
        self.assertEqual(
            run("v0.19.0", "0.19.0", {name: "b", "source.tar.gz": "s"}, manifest),
            0,
        )

    def test_wrap_names_are_not_release_assets(self) -> None:
        self.assertNotEqual(
            run(
                "v0.19.0",
                "0.19.0",
                {
                    "readcon-core-cxx-0.19.0.tar.gz": "c",
                    "readcon-core.wrap": "slim hash overwritten by vendor",
                },
            ),
            0,
        )
        self.assertNotEqual(
            run(
                "v0.19.0",
                "0.19.0",
                {"readcon-core-cxx-0.19.0.wrap": "versioned sidecar"},
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

    def test_clib_nested_checkout_accepts_the_julia_manifest(self) -> None:
        yml = (ROOT / ".github/workflows/c_lib_tarball.yml").read_text(encoding="utf-8")
        self.assertIn(
            'python3 "$GITHUB_WORKSPACE/packager/scripts/check_release_artifacts.py"',
            yml,
        )
        self.assertIn('--version-file "$GITHUB_WORKSPACE/src/VERSION"', yml)
        self.assertIn('--dist "$GITHUB_WORKSPACE/dist-clib"', yml)
        self.assertNotIn(
            'python3 scripts/check_release_artifacts.py --tag "$RELEASE_TAG" --dist dist-clib',
            yml,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            code = clib_workspace(ws, "0.19.0", "0.19.0", "abc")
            self.assertEqual(code, 0)
            missing = subprocess.call(
                [
                    sys.executable,
                    "scripts/check_release_artifacts.py",
                    "--tag",
                    "v0.19.0",
                ],
                cwd=ws,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertNotEqual(missing, 0)

    def test_clib_manifest_rejects_a_wrong_version_and_a_wrong_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.19.0", "0.17.3", "old"), 0)
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.19.0", "0.19.0", "old-url"), 0)
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertNotEqual(clib_workspace(ws, "0.19.0", "0.19.0", "bad-hash"), 0)

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
    env["RELEASE_TAG"] = "v0.19.0"
    return subprocess.call(
        [
            "bash",
            "-lc",
            'python3 "$GITHUB_WORKSPACE/packager/scripts/check_release_artifacts.py" '
            '--tag "$RELEASE_TAG" '
            '--version-file "$GITHUB_WORKSPACE/src/VERSION" '
            '--dist "$GITHUB_WORKSPACE/dist-clib"',
        ],
        cwd=ws,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    unittest.main()
