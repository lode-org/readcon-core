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

_SHARED_ALIASES = (
    "readcon_core.dll",
    "libreadcon_core.dll",
    "libreadcon_core.so",
    "libreadcon_core.dylib",
)
_STATIC_ALIASES = (
    "readcon_core.lib",
    "libreadcon_core.a",
    "libreadcon_core.lib",
    "readcon_core.dll.lib",
)


def _copy_artifact(
    built: Path, wanted: str, dest: str, aliases: tuple[str, ...]
) -> None:
    candidates = [built / wanted]
    for name in aliases:
        path = built / name
        if path not in candidates:
            candidates.append(path)
        dep = built / "deps" / name
        if dep not in candidates:
            candidates.append(dep)
    for path in candidates:
        if path.is_file():
            shutil.copy2(path, dest)
            return
    listing = sorted(p.name for p in built.iterdir()) if built.is_dir() else []
    raise FileNotFoundError(
        f"cargo artifact {wanted!r} not in {built} (tried {[str(p) for p in candidates]}); "
        f"directory listing: {listing}"
    )


def _cxx_link_args(text: str) -> list[str]:
    """Name the C++ runtime when the cargo features pull in C++ objects."""
    names = {part.strip() for part in text.split(",") if part.strip()}
    if "zstd" not in names and not any(name.startswith("chemfiles") for name in names):
        return []
    if sys.platform.startswith("linux"):
        return ["-Clink-arg=-lstdc++"]
    if sys.platform == "darwin":
        return ["-Clink-arg=-lc++"]
    return []


def _linux_libstdcxx_dir() -> str | None:
    """Directory `g++` uses for libstdc++.so. clang's link does not search it."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        out = subprocess.check_output(
            ["g++", "-print-file-name=libstdc++.so"], text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    path = out.strip()
    if not path or path == "libstdc++.so":
        return None
    parent = Path(path).parent
    if not parent.is_dir():
        return None
    return str(parent)


def main(argv: list[str]) -> int:
    if len(argv) not in (9, 10):
        print(
            "usage: meson_cargo_build.py CARGO SRC_ROOT TARGET_DIR PROFILE "
            "SHARED_NAME STATIC_NAME OUT_SHARED OUT_STATIC [FEATURES]",
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
    ) = argv[1:9]
    features = argv[9] if len(argv) == 10 else ""
    src_root_p = Path(src_root)
    cmd = [
        cargo,
        "rustc",
        "--lib",
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
    env = os.environ.copy()
    rustc_extra: list[str] = []
    cxx_link = _cxx_link_args(features)
    if cxx_link:
        libdir = _linux_libstdcxx_dir()
        if libdir:
            current = env.get("LIBRARY_PATH", "")
            parts = [part for part in current.split(":") if part]
            if libdir not in parts:
                env["LIBRARY_PATH"] = ":".join([libdir, *parts])
    if sys.platform.startswith("linux"):
        rustc_extra.append(f"-Clink-arg=-Wl,-soname,{shared_name}")
    elif sys.platform == "darwin":
        rustc_extra.append(f"-Clink-arg=-Wl,-install_name,@rpath/{shared_name}")
    rustc_extra.extend(cxx_link)
    # One crate-type per rustc invocation. MSVC cdylib+staticlib in one
    # call can omit readcon_core.lib while still writing the DLL.
    # The cdylib opts into mimalloc; that feature also gives its C objects
    # local-dynamic TLS so a later dlopen needs no static TLS surplus. The
    # staticlib uses the system allocator: a C host can link it beside
    # another Rust staticlib without crossing allocator boundaries.
    static_extra = [arg for arg in rustc_extra if arg.startswith("-Clink-arg=-l")]
    for crate_type, extra in (("cdylib", rustc_extra), ("staticlib", static_extra)):
        crate_features = features.strip()
        if crate_type == "cdylib":
            crate_features = ",".join(
                part for part in (crate_features, "capi", "mimalloc-allocator") if part
            )
        else:
            crate_features = ",".join(
                part for part in (crate_features, "capi", "static_system_alloc") if part
            )
        crate_cmd = list(cmd)
        if crate_features:
            crate_cmd.extend(["--features", crate_features])
        crate_cmd.append("--crate-type")
        crate_cmd.append(crate_type)
        if extra:
            crate_cmd += ["--", *extra]
        crate_env = env.copy()
        if crate_type == "staticlib":
            # Keep runtime object boundaries so a consumer can link several
            # Rust archives without duplicate symbols from merged LTO units.
            cargo_profile = "RELEASE" if profile == "release" else "DEV"
            crate_env[f"CARGO_PROFILE_{cargo_profile}_LTO"] = "off"
        subprocess.check_call(crate_cmd, cwd=src_root, env=crate_env)
        built = Path(target_dir) / profile
        if crate_type == "cdylib":
            _copy_artifact(built, shared_name, out_shared, _SHARED_ALIASES)
        else:
            _copy_artifact(built, static_name, out_static, _STATIC_ALIASES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
