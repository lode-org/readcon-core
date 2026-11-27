"""Meson must not hand ccache to cargo as CC or as the linker."""

from __future__ import annotations

import importlib.util
import re
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


def test_linker_key_is_the_cargo_target(tmp_path: Path) -> None:
    module = _load()
    assigned = module.cargo_cc_env(
        ["clang"], TARGET, HOST, tmp_path / "readcon-cc"
    )
    assert "CC" not in assigned
    assert assigned[f"CC_{TARGET}"] == "clang"
    assert assigned[module.cargo_linker_key(TARGET)] == "clang"
    assert module.cargo_linker_key(HOST) not in assigned
