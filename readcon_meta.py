"""Package version for towncrier.

Towncrier imports this module and reads ``__version__``.
https://towncrier.readthedocs.io/en/stable/configuration.html
"""

from pathlib import Path

_text = Path(__file__).resolve().parent.joinpath("VERSION").read_text(encoding="utf-8")
if _text.count("\n") != 1 or not _text.endswith("\n"):
    raise RuntimeError("VERSION must be one line ending in a single newline")
__version__ = _text[:-1]
