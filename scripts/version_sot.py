"""Read the canonical package version and emit cogapp output.

cogapp: https://cog.readthedocs.io/en/latest/
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "VERSION"
# Shared by read_version and the bump scripts.
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?"
VERSION_RE = re.compile(VERSION_PATTERN)


def generated_targets() -> list[tuple[str, str]]:
    """Outputs written with ``python -m cogapp -d -o``, in stamp order.

    https://cog.readthedocs.io/en/latest/
    """
    return [
        (".zenodo.json", "scripts/cog/zenodo.cog"),
        ("codemeta.json", "scripts/cog/codemeta.cog"),
        ("packaging/wrapdb/readcon-core.wrap", "scripts/cog/wrap.cog"),
    ]


def marker_files() -> list[str]:
    """Tracked and untracked sources with in-place cogapp markers.

    Generator inputs under ``scripts/cog/`` are applied with ``-o`` and are
    not part of this list.
    """
    skip_parts = {".git", "target", ".pixi", "bbdir", "builddir", "docs"}
    found: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("scripts", "cog"):
            continue
        if any(part in skip_parts for part in rel.parts):
            continue
        # docs/orgmode is authored text; markers live in package files.
        # The skip above drops all of docs/, which is intentional.
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Split so this source does not contain a cogapp start marker.
        token = "[" * 3 + "cog"
        if token in text:
            found.append(rel.as_posix())
    return sorted(found)


RENDERED_PINS = (
    "README.md",
    "docs/source/index.rst",
    "docs/source/migrate.rst",
    "docs/source/getting-started.rst",
    "docs/source/bindings.rst",
    "docs/source/chemfiles-howto.rst",
    "docs/source/chemfiles-tutorial.rst",
    "docs/source/architecture.rst",
)


def refresh_rendered_pins(old: str, new: str) -> None:
    """Rewrite exported pages that embed the previous package version."""
    if old == new:
        return
    accept_version(old)
    accept_version(new)
    for rel in RENDERED_PINS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        if old not in text:
            raise SystemExit(f"{rel} does not contain the previous version {old}")
        path.write_text(text.replace(old, new), encoding="utf-8")


def accept_version(text: str) -> str:
    """Return text when it matches VERSION_PATTERN."""
    if VERSION_RE.fullmatch(text) is None:
        raise SystemExit(f"version is not a dotted release: {text}")
    return text


def read_version() -> str:
    """Return the package version from VERSION."""
    text = VERSION_PATH.read_text(encoding="utf-8")
    if text.count("\n") != 1 or not text.endswith("\n"):
        raise SystemExit("VERSION must be one line ending in a single newline")
    version = text[:-1]
    if not version or version.strip() != version:
        raise SystemExit("VERSION line must not have surrounding whitespace")
    return accept_version(version)


def emit(cog, template: str) -> None:
    """Write one line. ``template`` uses ``{v}`` for the package version."""
    cog.outl(template.format(v=read_version()))


def emit_c_version(cog) -> None:
    """Write the C preprocessor macros for the package version."""
    version = read_version()
    major, minor, patch = version.split(".", 2)
    patch_num = re.match(r"\d+", patch)
    if patch_num is None:
        raise SystemExit(f"VERSION patch is not numeric: {version}")
    cog.outl(f'#define READCON_CORE_VERSION "{version}"')
    cog.outl(f"#define READCON_CORE_VERSION_MAJOR {major}")
    cog.outl(f"#define READCON_CORE_VERSION_MINOR {minor}")
    cog.outl(f"#define READCON_CORE_VERSION_PATCH {patch_num.group(0)}")


def heading_re() -> re.Pattern[str]:
    """Match ``## v`` headings, including a pre-release suffix from VERSION_PATTERN."""
    return re.compile(rf"(?m)^## (v{VERSION_PATTERN})\b")


def changelog_headings(text: str) -> list[str]:
    """Return ``vX.Y.Z`` headings, keeping suffixes such as ``-rc1``."""
    return heading_re().findall(text)


def emit_changelog_links(cog) -> None:
    """Write compare links for each ``## vX.Y.Z`` heading in CHANGELOG.md."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = changelog_headings(text)
    if not versions:
        raise SystemExit("CHANGELOG.md has no version headings")
    cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    found = re.search(r'(?m)^repository = "([^"]+)"', cargo)
    if found is None:
        raise SystemExit("Cargo.toml has no repository URL")
    repo = found.group(1).rstrip("/")
    lines: list[str] = []
    for index, ver in enumerate(versions):
        if index + 1 < len(versions):
            prev = versions[index + 1]
            lines.append(f"[{ver}]: {repo}/compare/{prev}...{ver}")
        else:
            lines.append(f"[{ver}]: {repo}/releases/tag/{ver}")
    cog.out("\n".join(lines) + "\n")


def _fill_version(template_name: str, expected: int) -> str:
    """Substitute @VERSION@ in a template that is not the generated output."""
    version = read_version()
    text = (ROOT / template_name).read_text(encoding="utf-8")
    count = text.count("@VERSION@")
    if count != expected:
        raise SystemExit(
            f"{template_name} has {count} @VERSION@ slots, expected {expected}"
        )
    return text.replace("@VERSION@", version)


def render_codemeta() -> str:
    """Return codemeta.json from its template and VERSION.

    The template has one @VERSION@ slot: the package version key.
    """
    return _fill_version("scripts/cog/codemeta.json.in", 1)


def render_zenodo() -> str:
    """Return .zenodo.json from its template and VERSION.

    The template has three @VERSION@ slots: the version key, the tree URL
    and the deposit note.
    """
    text = _fill_version("scripts/cog/zenodo.json.in", 3)
    if 'affiliation": "TurtleTech ehf"' not in text:
        raise SystemExit('.zenodo.json template must list affiliation "TurtleTech ehf"')
    if "0000-0002-2393-8056" not in text:
        raise SystemExit(".zenodo.json template is missing ORCID 0000-0002-2393-8056")
    return text


def render_wrap() -> str:
    """Return the wrap file from wrap.in, VERSION, and the sha256 sidecar."""
    version = read_version()
    sha_path = ROOT / "packaging/wrapdb/readcon-core.sha256"
    sha = sha_path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit(
            "packaging/wrapdb/readcon-core.sha256 is not a sha256 hex digest"
        )
    template = (ROOT / "packaging/wrapdb/readcon-core.wrap.in").read_text(
        encoding="utf-8"
    )
    return template.replace("@VERSION@", version).replace("@SHA256@", sha)
