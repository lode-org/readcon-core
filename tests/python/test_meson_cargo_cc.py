"""Meson must not hand ccache to cargo as CC or as the linker."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "meson_cargo_build.py"
HOST = "x86_64-unknown-linux-gnu"
TARGET = "aarch64-unknown-linux-gnu"


def _load():
    spec = importlib.util.spec_from_file_location("meson_cargo_build_cc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_host_toolchain_file_is_not_global() -> None:
    text = (ROOT / ".cargo" / "config.toml").read_text(encoding="utf-8")
    assert "HOST_CMAKE_TOOLCHAIN_FILE" in text
    assert re.search(r"(?m)^CMAKE_TOOLCHAIN_FILE\s*=", text) is None


def test_ccache_plus_cc_sets_nothing(tmp_path: Path) -> None:
    module = _load()
    assigned = module.cargo_cc_env(
        ["/usr/bin/ccache", "cc"], HOST, HOST, tmp_path / "readcon-cc"
    )
    assert assigned == {}
    assert not (tmp_path / "readcon-cc").exists()


def test_ccache_plus_gcc_is_gcc_not_ccache(tmp_path: Path) -> None:
    module = _load()
    assigned = module.cargo_cc_env(
        ["ccache", "/usr/bin/gcc"], HOST, HOST, tmp_path / "readcon-cc"
    )
    assert assigned["CC"] == "/usr/bin/gcc"
    assert assigned[module.cargo_linker_key(HOST)] == "/usr/bin/gcc"
    assert "/usr/bin/ccache" not in assigned.values()


def test_extra_args_become_a_wrapper(tmp_path: Path) -> None:
    module = _load()
    wrapper = tmp_path / "readcon-cc"
    assigned = module.cargo_cc_env(
        ["/usr/bin/ccache", "/usr/bin/gcc", "-m32"], HOST, HOST, wrapper
    )
    assert assigned["CC"] == str(wrapper)
    assert assigned[module.cargo_linker_key(HOST)] == str(wrapper)
    text = wrapper.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "/usr/bin/gcc" in text
    assert "-m32" in text
    assert "ccache" not in text
    assert wrapper.stat().st_mode & 0o111


def test_android_links_the_ndk_runtime() -> None:
    module = _load()
    assert module._cxx_link_args("zstd", "aarch64-linux-android") == [
        "-Clink-arg=-lc++"
    ]


def test_androideabi_links_the_ndk_runtime() -> None:
    module = _load()
    assert module._cxx_link_args("zstd", "armv7-linux-androideabi") == [
        "-Clink-arg=-lc++"
    ]


def test_android_does_not_take_the_host_libstdcxx_dir() -> None:
    module = _load()
    host = "/usr/lib/gcc/x86_64-linux-gnu/13"
    assert (
        module._host_libstdcxx_library_path(
            "armv7-linux-androideabi", host, "/opt/ndk/lib"
        )
        is None
    )
    assert (
        module._host_libstdcxx_library_path("aarch64-linux-android", host, "") is None
    )
    assert (
        module._host_libstdcxx_library_path(
            "x86_64-unknown-linux-gnu", host, "/opt/lib"
        )
        == f"{host}:/opt/lib"
    )


def test_static_keeps_link_args_that_are_not_l() -> None:
    module = _load()
    args = [
        "-Clink-arg=-Wl,-soname,libreadcon_core.so",
        "-Clink-arg=-lstdc++",
        "-Clink-arg=-L/opt/lib",
        "-Clink-arg=-pthread",
    ]
    kept = module.link_args_for_static(args)
    assert kept == [
        "-Clink-arg=-lstdc++",
        "-Clink-arg=-L/opt/lib",
        "-Clink-arg=-pthread",
    ]


def test_meson_link_arg_file_becomes_rustc_flags(tmp_path: Path) -> None:
    module = _load()
    path = tmp_path / "link.txt"
    path.write_text("-L/opt/lib\n-pthread\n", encoding="utf-8")
    assert module.read_meson_link_args(str(path)) == [
        "-Clink-arg=-L/opt/lib",
        "-Clink-arg=-pthread",
    ]
    assert module.read_meson_link_args("") == []


def test_msvc_cl_is_not_the_linker(tmp_path: Path) -> None:
    module = _load()
    triple = "x86_64-pc-windows-msvc"
    assigned = module.cargo_cc_env(
        [r"C:\BuildTools\VC\Tools\MSVC\bin\cl.exe"],
        triple,
        triple,
        tmp_path / "readcon-cc",
    )
    assert assigned["CC"].endswith("cl.exe")
    assert module.cargo_linker_key(triple) not in assigned
    assert not (tmp_path / "readcon-cc").exists()


def test_cross_check_heredoc_does_not_interpolate_the_scratch_path(
    tmp_path: Path,
) -> None:
    text = (ROOT / "scripts" / "check_cross_cmake.sh").read_text(encoding="utf-8")
    blocks = re.findall(
        r"cat >\"\$work/(cc|cxx)\" <<'EOF'\n(.*?)\nEOF",
        text,
        re.S,
    )
    assert [name for name, _body in blocks] == ["cc", "cxx"]
    work = tmp_path / "scratch dir"
    work.mkdir()
    invoked = work / "invoked"
    for name, body in blocks:
        assert "$work" not in body
        wrapper = work / name
        wrapper.write_text(body, encoding="utf-8")
        wrapper.chmod(0o755)
        subprocess.run(
            [str(wrapper), "-dumpversion"],
            check=True,
            env={**os.environ, "READCON_CROSS_INVOKED": str(invoked)},
            stdout=subprocess.DEVNULL,
        )
    log = invoked.read_text(encoding="utf-8")
    assert f"cc:{work / 'cc'}" in log
    assert f"cxx:{work / 'cxx'}" in log


def test_linker_key_is_the_cargo_target(tmp_path: Path) -> None:
    module = _load()
    assigned = module.cargo_cc_env(["clang"], TARGET, HOST, tmp_path / "readcon-cc")
    assert "CC" not in assigned
    assert assigned[f"CC_{TARGET}"] == "clang"
    assert assigned[module.cargo_linker_key(TARGET)] == "clang"
    assert module.cargo_linker_key(HOST) not in assigned
