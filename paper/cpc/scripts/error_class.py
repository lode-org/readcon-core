"""The ParseError class of a failed readcon read.

readcon-core 0.17.4 raises OSError with the Display text of the Rust
ParseError (``src/error.rs``), and ``classify`` maps that text to the name of
the variant.
"""

from __future__ import annotations

import re

MESSAGES = (
    (re.compile(r"file ended unexpectedly while parsing frame header"), "IncompleteHeader"),
    (re.compile(r"file ended unexpectedly while reading atom data"), "IncompleteFrame"),
    (re.compile(r"file ended unexpectedly while reading .* section"), "IncompleteSection"),
    (re.compile(r"expected \d+ values on line, found \d+"), "InvalidVectorLength"),
    (re.compile(r"invalid number format: "), "InvalidNumberFormat"),
    (re.compile(r'line 2 must be a JSON object containing "con_spec_version"'), "MissingSpecVersion"),
    (re.compile(r"unsupported con_spec_version: "), "UnsupportedVersion"),
    (re.compile(r"invalid JSON metadata on line 2: "), "InvalidMetadataJson"),
    (re.compile(r"unknown section type in metadata: "), "UnknownSection"),
    (re.compile(r"CON validation failed: "), "ValidationError"),
    (re.compile(r"non-finite value: "), "NonFiniteValue"),
    (re.compile(r"invalid fixed flag: "), "InvalidFixedFlag"),
    (re.compile(r"invalid count: "), "InvalidCount"),
    (re.compile(r"invalid units: "), "InvalidUnits"),
    (re.compile(r"stream did not contain valid UTF-8"), "ValidationError"),
    (re.compile(r"zstd-compressed input detected"), "Compression"),
)
SECTION_CLASSES = {"IncompleteVelocitySection", "IncompleteForceSection", "IncompleteEnergySection"}


def normal(cls: str | None) -> str | None:
    return "IncompleteSection" if cls in SECTION_CLASSES else cls


def classify(exc: BaseException) -> tuple[str, int | None, bool]:
    """Error class and line, and whether the exception carried them as attributes rather than in its message."""
    kind = getattr(exc, "kind", None)
    if isinstance(kind, str):
        return normal(kind), getattr(exc, "line", None) or None, True
    message = str(exc).removeprefix("parse error: ")
    line = None
    located = re.match(r"line (\d+): ", message)
    if located:
        line, message = int(located[1]), message[located.end():]
    for pattern, cls in MESSAGES:
        if pattern.match(message):
            return cls, line, False
    return "Other", line, False
