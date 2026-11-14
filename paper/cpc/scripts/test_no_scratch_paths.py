"""Scripts under paper/ must not use a scratch directory for I/O.

A /tmp string that only sits in a tuple or list on the right of ``in`` is a
redaction token: the log drops lines that contain it. The same string is I/O
when it is a path. That includes open, Path, an environment default, and
Vibrations' name.
"""

from __future__ import annotations

import ast
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]
PATH_CALLS = {
    "open",
    "Path",
    "Vibrations",
    "mkdir",
    "makedirs",
    "chdir",
    "mkdtemp",
    "mkstemp",
    "TemporaryDirectory",
    "NamedTemporaryFile",
}
PATH_KEYWORDS = {
    "name",
    "path",
    "dir",
    "file",
    "filename",
    "dest",
    "out",
    "output",
    "root",
    "cwd",
    "prefix",
}
ENV_CALLS = {"get", "getenv", "setdefault"}


def script_paths() -> list[Path]:
    found = []
    for path in PAPER.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".py" or path.name == "Snakefile":
            found.append(path)
    return found


def _folded_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _folded_string(node.left)
        right = _folded_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _used_as_path(node: ast.AST, parent: dict[ast.AST, ast.AST]) -> bool:
    """True when node, or a concatenation that contains it, is a path argument."""
    current: ast.AST | None = node
    while current is not None and current in parent:
        owner = parent[current]
        if isinstance(owner, ast.BinOp):
            current = owner
            continue
        if isinstance(owner, ast.Call):
            name = _call_name(owner.func)
            if name in PATH_CALLS:
                return True
            if name in ENV_CALLS and (
                (current in owner.args and owner.args.index(current) >= 1)
                or any(kw.arg == "default" and kw.value is current for kw in owner.keywords)
            ):
                return True
            if any(kw.value is current and kw.arg in PATH_KEYWORDS for kw in owner.keywords):
                return True
            return False
        return False
    return False


def scratch_uses(source: str, filename: str = "<snippet>") -> list[str]:
    """Locations where source uses a scratch path for I/O."""
    if filename.endswith("Snakefile") or filename == "Snakefile":
        hits = []
        for lineno, line in enumerate(source.splitlines(), 1):
            if "/tmp" in line or "gettempdir" in line:
                hits.append(f"{filename}:{lineno}: {line.strip()}")
        return hits
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno}: cannot parse"]
    parent = _parents(tree)
    hits = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == "gettempdir":
            hits.append(f"{filename}:{node.lineno}: tempfile gettempdir call")
            continue
        text = _folded_string(node)
        if text is None or "/tmp" not in text:
            continue
        if not _used_as_path(node, parent):
            continue
        key = (getattr(node, "lineno", 0), text)
        if key in seen:
            continue
        seen.add(key)
        hits.append(f"{filename}:{key[0]}: {text}")
    return hits


def test_scripts_do_not_use_a_scratch_directory() -> None:
    hits = []
    for path in script_paths():
        text = path.read_text(encoding="utf-8", errors="replace")
        hits.extend(scratch_uses(text, str(path.relative_to(PAPER))))
    if hits:
        raise SystemExit("scripts use a scratch directory:\n" + "\n".join(hits))


def test_a_scratch_default_is_rejected() -> None:
    """The old READCON_DB fallback must still be a failure."""
    sample = 'READCON_DB = Path(os.environ.get("READCON_DB", "/tmp/readcon-db"))\n'
    hits = scratch_uses(sample, "pinned_emit.py")
    if not hits:
        raise SystemExit("a /tmp default was accepted")


if __name__ == "__main__":
    bad = scratch_uses(
        'READCON_DB = Path(os.environ.get("READCON_DB", "/tmp/readcon-db"))\n',
        "pinned_emit.py",
    )
    print("rejected default:")
    for hit in bad:
        print(hit)
    if not bad:
        raise SystemExit("a /tmp default was accepted")
    test_scripts_do_not_use_a_scratch_directory()
    print("tree ok")
