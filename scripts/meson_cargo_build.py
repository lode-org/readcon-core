#!/usr/bin/env python3
"""Build the readcon-core C ABI via cargo rustc and copy artifacts.

Used by meson.build. Headers are shipped; this script never invokes cbindgen.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_CACHE_WRAPPERS = {"ccache", "sccache", "distcc"}
# rustc's MSVC linker is link.exe. cl.exe is only the compiler.
_MSVC_CL = {"cl", "clang-cl"}

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


def _tool_name(part: str) -> str:
    name = Path(part.replace("\\", "/")).name
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name.lower()


def compiler_without_cache(command: list[str]) -> list[str]:
    """Drop leading ccache/sccache/distcc. They are not linkers."""
    index = 0
    while index < len(command) and _tool_name(command[index]) in _CACHE_WRAPPERS:
        index += 1
    return command[index:]


def cargo_linker_key(triple: str) -> str:
    return "CARGO_TARGET_" + triple.upper().replace("-", "_") + "_LINKER"


def cargo_cc_env(
    command: list[str], triple: str, host: str, wrapper: Path
) -> dict[str, str]:
    """CC and linker for cargo, or nothing when plain ``cc`` already matches.

    A single ``cc`` is cargo's default, including ``ccache cc``. Extra
    arguments (``gcc -m32``) become a wrapper both CC and the linker exec.
    The linker variable is the cargo target, not always the rustc host.
    ``cl.exe`` stays the compiler only; MSVC links with ``link.exe``.
    """
    real = compiler_without_cache(command)
    if not real or (len(real) == 1 and _tool_name(real[0]) == "cc"):
        return {}
    msvc = _tool_name(real[0]) in _MSVC_CL
    if msvc or len(real) == 1:
        program = real[0]
    else:
        quoted = " ".join(shlex.quote(part) for part in real)
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("#!/bin/sh\nexec " + quoted + ' "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        program = str(wrapper)
    assigned: dict[str, str] = {}
    if not msvc:
        assigned[cargo_linker_key(triple)] = program
    if triple == host:
        assigned["CC"] = program
    else:
        assigned[f"CC_{triple}"] = program
    return assigned


def _rustc_host(env: dict[str, str]) -> str:
    out = subprocess.check_output(["rustc", "-vV"], text=True, env=env)
    for line in out.splitlines():
        if line.startswith("host: "):
            return line[len("host: ") :]
    raise RuntimeError("rustc did not report its host target")


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
    cc_file = env.pop("READCON_MESON_CC_FILE", "")
    meson_cc: list[str] = []
    if cc_file:
        meson_cc = [
            part
            for part in Path(cc_file).read_text(encoding="utf-8").split("\n")
            if part
        ]
    if meson_cc:
        host = _rustc_host(env)
        triple = env.get("CARGO_BUILD_TARGET", "").strip() or host
        assigned = cargo_cc_env(
            meson_cc, triple, host, Path(target_dir) / "readcon-cc"
        )
        env.update(assigned)
        program = assigned.get("CC", "")
        if not program:
            program = next(
                (value for key, value in assigned.items() if key.startswith("CC_")),
                "default",
            )
        print(f"cargo cc: {program}", file=sys.stderr)
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
