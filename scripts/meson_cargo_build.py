#!/usr/bin/env python3
"""Build the readcon-core C ABI via cargo rustc and copy artifacts.

Used by meson.build. Headers are shipped; this script never invokes cbindgen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 9:
        print(
            "usage: meson_cargo_build.py CARGO SRC_ROOT TARGET_DIR PROFILE "
            "SHARED_NAME STATIC_NAME OUT_SHARED OUT_STATIC",
            file=sys.stderr,
        )
        return 2
    (
        cargo,
        src_root,
        target_dir,
        profile,
        shared_name,
        static_name,
        out_shared,
        out_static,
    ) = argv[1:]
    src_root_p = Path(src_root)
    cmd = [
        cargo,
        "rustc",
        "--manifest-path",
        str(src_root_p / "Cargo.toml"),
        "--target-dir",
        target_dir,
    ]
    if (src_root_p / "Cargo.lock").is_file():
        cmd.append("--locked")
    if (src_root_p / "vendor").is_dir():
        cmd.append("--offline")
    if profile == "release":
        cmd.append("--release")
    rustc_args = ["--crate-type=cdylib", "--crate-type=staticlib"]
    if sys.platform.startswith("linux"):
        rustc_args.append(f"-Clink-arg=-Wl,-soname,{shared_name}")
    elif sys.platform == "darwin":
        rustc_args.append(f"-Clink-arg=-Wl,-install_name,@rpath/{shared_name}")
    cmd.extend(["--", *rustc_args])
    env = os.environ.copy()
    subprocess.check_call(cmd, cwd=src_root, env=env)
    built = Path(target_dir) / profile
    shutil.copy2(built / shared_name, out_shared)
    shutil.copy2(built / static_name, out_static)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
