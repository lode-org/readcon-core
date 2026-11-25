"""Whether a spec-measurement record carries measured_at.commit.

The field arrived in 7e8c078e with spec-measurement-0.24.0.json. No
measurement file in this history was written before that commit, so the
legacy list is empty. A record that omits the field fails.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Paths whose bytes predate measured_at. Empty: the stored record was
# added with the field, and 9984e6da later removed it.
LEGACY_WITHOUT_MEASURED_AT: frozenset[str] = frozenset()

# Stored records that name a supersedes target but are not on its chain.
# feat/capi-gate measured spec-measurement-0.24.0-r2.json at b2fc6255
# under its own -rN naming before the develop merge. Develop's chain from
# the stored file runs through -measured and -measured-2. The -r2 record
# stays as stored, and the walk does not take it as a successor.
OFF_CHAIN: frozenset[str] = frozenset(
    {"paper/cpc/data/spec/spec-measurement-0.24.0-r2.json"}
)


class MeasurementSchemaError(Exception):
    """A record that is not legacy is missing measured_at.commit."""


def resolve_measurement(records: dict[str, dict], relpath: str) -> tuple[str, dict]:
    """Follow supersedes links from ``relpath`` to the record that replaces it.

    A record replaces a path when its ``supersedes`` field is that path.
    The walk is that chain; a record in OFF_CHAIN replaces nothing. Two
    records replacing the same path, or a cycle, is an error. The record
    the walk ends on is returned as stored; ``measured_commit`` still has
    to accept it, so a successor that omits ``measured_at.commit`` fails
    by name.
    """
    seen: set[str] = set()
    current = relpath
    while current not in seen:
        seen.add(current)
        record = records.get(current)
        if not isinstance(record, dict):
            raise MeasurementSchemaError(f"{current} is not a measurement record")
        nxt = sorted(
            path
            for path, body in records.items()
            if path not in OFF_CHAIN
            and isinstance(body, dict)
            and body.get("supersedes") == current
        )
        if not nxt:
            return current, record
        if len(nxt) > 1:
            raise MeasurementSchemaError(f"{current} is superseded by {', '.join(nxt)}")
        current = nxt[0]
    raise MeasurementSchemaError(f"{relpath} supersede links cycle")


def measured_commit(record: dict, relpath: str) -> str | None:
    """Return the measured commit, or None for a legacy path.

    A path outside LEGACY_WITHOUT_MEASURED_AT must name measured_at.commit.
    """
    measured_at = record.get("measured_at")
    if not isinstance(measured_at, dict) or "commit" not in measured_at:
        if relpath in LEGACY_WITHOUT_MEASURED_AT:
            return None
        raise MeasurementSchemaError(f"{relpath} has no measured_at.commit")
    commit = measured_at["commit"]
    if not isinstance(commit, str) or not commit:
        raise MeasurementSchemaError(f"{relpath} has no measured_at.commit")
    return commit


def require_ancestor(checkout: Path, commit: str, relpath: str) -> None:
    """Fail unless ``commit`` is an ancestor of HEAD in ``checkout``.

    An object that only a local clone holds, such as the parent of a
    rewritten commit, resolves there and nowhere else.
    """
    done = subprocess.run(
        ["git", "-C", str(checkout), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise MeasurementSchemaError(
            f"{relpath} names measured_at.commit {commit}, "
            "which is not an ancestor of this commit"
        )
