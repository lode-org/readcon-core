#!/usr/bin/env python3
"""Run the install commands documented in the README and the docs.

Unversioned ``pip install readcon`` and ``cargo add readcon-core`` must
resolve on PyPI and crates.io. A pin equal to this tree's ``VERSION`` may
still be unpublished; that is reported and does not fail a branch push.
``--require-published`` (tag pushes) requires the pin. ``ase-readcon`` is
installed from this checkout, which is the documented command.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "readcon-install-docs"
PIP_PACKAGES = ("readcon", "readcon-chemfiles", "readcon-db")
CRATES = ("readcon-core", "readcon-db")
COMMAND = re.compile(
    r"(?:pip3? install(?: -e|-U)?|cargo add)\s+((?:'[^']+'|\"[^\"]+\"|\S+)(?:\s+(?:'[^']+'|\"[^\"]+\"|\S+))*)"
)


class InstallError(Exception):
    """A documented install command does not match a published package."""


def tree_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def documented_commands(root: Path) -> list[str]:
    files = [root / "README.md"]
    files.extend(sorted((root / "docs" / "source").rglob("*.rst")))
    files.extend(sorted((root / "docs" / "orgmode").rglob("*.org")))
    commands = []
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            for match in COMMAND.finditer(line):
                command = " ".join(match.group(0).split())
                if command not in commands:
                    commands.append(command)
    return commands


def split_token(token: str) -> str:
    return token.strip("'\"")


def specs_in(command: str, version: str) -> list[tuple[str, str, str | None]]:
    """Tool, package name, and optional pin for readcon packages."""
    tool = "cargo" if command.startswith("cargo") else "pip"
    body = command.split(None, 2)[-1]
    found = []
    for raw in body.split():
        if raw.startswith("-"):
            continue
        token = split_token(raw).replace("@READCON_VERSION@", version)
        if token.startswith("ase-readcon"):
            found.append((tool, "ase-readcon", None))
            continue
        name, pin = parse_requirement(token)
        if name in PIP_PACKAGES or name in CRATES:
            found.append((tool, name, pin))
    return found


def parse_requirement(token: str) -> tuple[str, str | None]:
    token = token.split("[", 1)[0]
    for sep in ("==", "@"):
        if sep in token:
            name, pin = token.split(sep, 1)
            if not re.fullmatch(r"\d+\.\d+\.\d+", pin):
                return name, None
            return name, pin
    return token, None


def fetch_json(url: str) -> tuple[int, dict | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def pypi_has(name: str, pin: str | None) -> bool:
    url = f"https://pypi.org/pypi/{name}/json"
    if pin is not None:
        url = f"https://pypi.org/pypi/{name}/{pin}/json"
    status, _payload = fetch_json(url)
    if status not in (200, 404):
        raise InstallError(f"PyPI {name} returned HTTP {status}")
    return status == 200


def crates_has(name: str, pin: str | None) -> bool:
    status, payload = fetch_json(f"https://crates.io/api/v1/crates/{name}")
    if status == 404:
        return False
    if status != 200 or payload is None:
        raise InstallError(f"crates.io {name} returned HTTP {status}")
    if pin is None:
        return True
    versions = [item["num"] for item in payload.get("versions", [])]
    return pin in versions


def check_commands(root: Path, require_published: bool) -> list[str]:
    version = tree_version(root)
    pending = []
    commands = documented_commands(root)
    if not any("readcon" in command for command in commands):
        raise InstallError("no readcon install commands found")
    seen: set[tuple[str, str, str | None]] = set()
    for command in commands:
        for tool, name, pin in specs_in(command, version):
            key = (tool, name, pin)
            if key in seen:
                continue
            seen.add(key)
            if name == "ase-readcon":
                if "-e ase-readcon" not in command:
                    raise InstallError(
                        f"{command} installs ase-readcon from PyPI; it is repo-local"
                    )
                continue
            if tool == "cargo":
                published = crates_has(name, pin)
                index = "crates.io"
            else:
                published = pypi_has(name, pin)
                index = "PyPI"
            if published:
                print(f"{index} {name}{'==' + pin if pin else ''} is published")
                continue
            if pin == version and not require_published:
                pending.append(f"{name}=={pin}")
                print(f"{index} {name}=={pin} is not published yet")
                continue
            raise InstallError(f"{command} does not resolve ({index} {name} {pin})")
    return pending


def install_published(root: Path, work: Path) -> None:
    """Install the unversioned README commands and the repo-local ASE plugin."""
    venv = work / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    python = venv / "bin" / "python"
    subprocess.run(
        [str(pip), "install", "--disable-pip-version-check", "ase", "numpy"],
        check=True,
    )
    subprocess.run(
        [
            str(pip),
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "readcon",
        ],
        check=True,
    )
    subprocess.run(
        [
            str(pip),
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "readcon-chemfiles",
        ],
        check=True,
    )
    subprocess.run(
        [
            str(pip),
            "install",
            "--disable-pip-version-check",
            "-e",
            str(root / "ase-readcon"),
        ],
        check=True,
    )
    probe = r"""
import importlib.metadata as meta
names = {ep.name for ep in meta.entry_points(group="ase.ioformats")}
missing = {"readcon-con", "readcon-convel"} - names
if missing:
    raise SystemExit(f"ase entry points missing: {sorted(missing)}")
import readcon
print(readcon.__version__ if hasattr(readcon, "__version__") else "readcon")
"""
    subprocess.run([str(python), "-c", probe], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--require-published", action="store_true")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="query the indexes without installing",
    )
    parser.add_argument("--work", type=Path)
    args = parser.parse_args(argv)
    pending = check_commands(args.root, args.require_published)
    if pending:
        print("pending this release: " + ", ".join(pending))
    if not args.check_only:
        work = args.work
        if work is None:
            from work_dir import work_dir

            with work_dir("install") as tmp:
                install_published(args.root, tmp)
        else:
            install_published(args.root, work)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallError, subprocess.CalledProcessError) as exc:
        print(f"install docs: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
