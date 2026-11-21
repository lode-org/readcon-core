"""Top-level JSON metadata lookup in paper/cpc/bench/native/readcon_read.cpp."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "paper" / "cpc" / "bench" / "native"

DRIVER = r"""
#define READCON_READ_NO_MAIN
#include "readcon_read.cpp"

#include <cassert>

int main() {
    {
        const std::string meta =
            R"({"aaa":{"pbc":[false,false,false]},"pbc":[true,false,true]})";
        const auto got = pbc_of(meta);
        assert((got == std::array<bool, 3>{true, false, true}));
    }
    {
        const std::string meta =
            R"({"aaa":{"pbc":[false,false,false]}})";
        const auto got = pbc_of(meta);
        assert((got == std::array<bool, 3>{true, true, true}));
    }
    {
        const std::string meta =
            R"({"note":"\"pbc\":[false,false,false] { }","items":[{"pbc":[false,false,false]}],"pbc" : [ false , true , false ]})";
        const auto got = pbc_of(meta);
        assert((got == std::array<bool, 3>{false, true, false}));
    }
    {
        const std::string meta =
            R"({"nested":{"lattice_vectors":[[9,0,0],[0,9,0],[0,0,9]]},"lattice_vectors":[[1,0,0],[0,2,0],[0,0,3]]})";
        std::array<double, 9> m{};
        assert(parse_lattice_vectors(meta, m));
        assert(m[0] == 1.0 && m[4] == 2.0 && m[8] == 3.0);
    }
    {
        const std::string meta =
            R"({"nested":{"lattice_vectors":[[9,0,0],[0,9,0],[0,0,9]]}})";
        std::array<double, 9> m{};
        assert(!parse_lattice_vectors(meta, m));
    }
    {
        bool threw = false;
        try {
            (void)pbc_of(R"({"pbc":[true,false]})");
        } catch (const std::runtime_error &) {
            threw = true;
        }
        assert(threw);
    }
    return 0;
}
"""


def test_readcon_read_top_level_metadata_lookup(tmp_path: Path) -> None:
    cxx = shutil.which("g++") or shutil.which("c++")
    if cxx is None:
        pytest.skip("no C++ compiler on PATH")
    src = tmp_path / "test_readcon_read_metadata.cpp"
    exe = tmp_path / "test_readcon_read_metadata"
    src.write_text(DRIVER, encoding="utf-8")
    subprocess.run(
        [
            cxx,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{NATIVE}",
            f"-I{ROOT / 'include'}",
            str(src),
            "-o",
            str(exe),
        ],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
