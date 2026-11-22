"""Whether a spec-measurement record carries measured_at.commit.

The field arrived in f899b5eb937a with spec-measurement-0.24.0.json. No
measurement file in this history was written before that commit, so the
legacy list is empty. A record that omits the field fails.
"""

from __future__ import annotations

# Paths whose bytes predate measured_at. Empty: the 0.24.0 record was
# added with the field, and 8319e6043a35 later removed it.
LEGACY_WITHOUT_MEASURED_AT: frozenset[str] = frozenset()


class MeasurementSchemaError(Exception):
    """A record that is not legacy is missing measured_at.commit."""


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
