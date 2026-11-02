"""Bench and example output must not record a machine name."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benches"))

from cpu_model import cpu_model, platform_label, strip_host_token  # noqa: E402

OUTPUT_DIRS = (ROOT / "benches" / "results", ROOT / "examples")
SOURCE_GLOBS = (
    (ROOT / "benches", "*.py"),
    (ROOT / "examples", "*.rs"),
    (ROOT / "scripts", "bench_*.py"),
)
FORBIDDEN_CALLS = (
    "gethostname",
    'Command::new("hostname")',
    "Command::new('hostname')",
)


def _read_hostname_file() -> str:
    try:
        return Path("/etc/hostname").read_text(encoding="utf-8")
    except OSError:
        return ""


def _machine_names() -> set[str]:
    names = set()
    for raw in (platform.node(), _read_hostname_file()):
        node = raw.strip()
        if node and node.lower() != "localhost":
            names.add(node)
    return names


def _text_files(path: Path):
    if not path.exists():
        return
    if path.is_file():
        yield path
        return
    for child in path.rglob("*"):
        if child.is_file() and ".git" not in child.parts:
            yield child


def test_strip_host_token_removes_only_a_whole_component():
    label = "Linux-7.0.13-arch1-1-rg-x86_64-with-glibc2.43"
    assert strip_host_token(label, "rg") == "Linux-7.0.13-arch1-1-x86_64-with-glibc2.43"
    assert strip_host_token(label, "r") == label
    assert strip_host_token(label, "") == label


def test_platform_label_omits_the_kernel_release_and_the_hostname():
    label = platform_label()
    assert platform.release() not in label
    for name in _machine_names():
        assert name not in label.split("-")


def test_python_and_rust_cpu_model_agree():
    proc = subprocess.run(
        [
            "cargo",
            "test",
            "--offline",
            "--lib",
            "hostlabel::tests::cpu_model_value",
            "--",
            "--exact",
            "--nocapture",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rust = None
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        marker = "CPU_MODEL="
        if marker in line:
            rust = line.split(marker, 1)[1].strip()
    assert rust is not None
    assert cpu_model() == rust


def test_bench_and_example_output_has_no_hostname():
    names = _machine_names()
    for directory in OUTPUT_DIRS:
        for path in _text_files(directory):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for name in names:
                assert name not in text, f"{path} contains {name}"


def test_writers_do_not_call_hostname():
    for directory, pattern in SOURCE_GLOBS:
        for path in directory.glob(pattern):
            text = path.read_text(encoding="utf-8")
            for call in FORBIDDEN_CALLS:
                assert call not in text, f"{path} calls {call}"
            if path.name != "cpu_model.py":
                assert "platform.node" not in text, f"{path} reads platform.node"
