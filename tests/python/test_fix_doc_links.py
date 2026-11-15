"""The org-export link rewrite must not swallow the PDB code block."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs" / "scripts" / "fix_doc_links.py"
HOWTO = ROOT / "docs" / "source" / "howto.rst"
OLD = re.compile(r"`([^`<>]+)\s+<((?![a-z][a-z0-9+.-]*:)[^>]+?\.(?:rst|org))>`_")


def _module():
    spec = importlib.util.spec_from_file_location("fix_doc_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _broken(text: str) -> str:
    return OLD.sub(lambda match: f":doc:`{Path(match.group(2)).stem}`", text)


def test_howto_pdb_block_survives_the_rewrite() -> None:
    text = HOWTO.read_text(encoding="utf-8")
    fixed = _module().fix_text(text)
    assert 'read_pdb("one.pdb")' in fixed
    assert "    assert list(cell[0][:3]) == [10.0, 12.0, 14.0]" in fixed
    assert ":doc:`chemfiles-howto`" in fixed
    # The published page no longer keeps a raw ``.rst`` link after ``ENDMDL``.
    # This specimen is the old shape: a code span, a ``<`` inside the block,
    # then a link the naive substitution can swallow.
    specimen = (
        "filled for H and Cu. Any other element is NaN. ``ENDMDL`` closes a frame.\n"
        "A file with no model records is one frame.\n"
        "\n"
        ".. code:: python\n"
        "\n"
        "    assert abs(masses[0, 0] - 63.546) < 1e-9\n"
        "    assert list(cell[0][:3]) == [10.0, 12.0, 14.0]\n"
        "\n"
        "See `chemfiles-howto.org <chemfiles-howto.rst>`_.\n"
    )
    broken = _broken(specimen)
    assert "``ENDMDL`:doc:`" in broken
    assert any(line.startswith("    assert list") for line in broken.splitlines())
    assert "``ENDMDL``" in _module().fix_text(specimen)


# The published how-to used to carry this section, with raw ``.rst`` links
# after the PDB example. The naive substitution starts at the closing
# backtick of ``ENDMDL`` and stops at a later ``<``. That leaves the
# indented assertion in the section body.
OLD_SECTION = """\
PDB columns
-----------

``read_pdb`` scans a PDB file. Masses are
filled for H and Cu. Any other element is NaN. ``ENDMDL`` closes a frame.
A file with no model records is one frame.

.. code:: python

    assert abs(masses[0, 0] - 63.546) < 1e-9
    assert list(cell[0][:3]) == [10.0, 12.0, 14.0]

See the track:

- Tutorial: `chemfiles-tutorial.org <chemfiles-tutorial.rst>`_

- How-to: `chemfiles-howto.org <chemfiles-howto.rst>`_
"""


def _warnings(text: str) -> str:
    from io import StringIO

    from docutils.core import publish_doctree

    warn = StringIO()
    publish_doctree(
        text,
        settings_overrides={
            "warning_stream": warn,
            "halt_level": 5,
            "report_level": 2,
        },
    )
    return warn.getvalue()


def test_the_old_pattern_is_a_docutils_error() -> None:
    pytest.importorskip("docutils")
    published = HOWTO.read_text(encoding="utf-8")
    assert OLD.search(published) is None
    assert "    assert list(cell[0][:3]) == [10.0, 12.0, 14.0]" in published
    published_notes = _warnings(published)
    assert "Unexpected indentation." not in published_notes
    assert "Inline literal start-string without end-string." not in published_notes

    broken = _broken(OLD_SECTION)
    lines = broken.splitlines()
    escaped = next(
        number
        for number, line in enumerate(lines, start=1)
        if line.startswith("    assert list")
    )
    # Docutils reports the unclosed literal on the first line of its paragraph.
    unclosed_body = next(
        index
        for index, line in enumerate(lines)
        if "ENDMDL" in line and "``ENDMDL``" not in line
    )
    unclosed = unclosed_body
    while unclosed > 0 and lines[unclosed - 1].strip():
        unclosed -= 1
    unclosed += 1
    notes = _warnings(broken)
    assert f":{escaped}: (ERROR/3) Unexpected indentation." in notes
    assert (
        f":{unclosed}: (WARNING/2) Inline literal start-string without end-string."
        in notes
    )

    fixed = _module().fix_text(OLD_SECTION)
    assert "``ENDMDL``" in fixed
    assert "    assert list(cell[0][:3]) == [10.0, 12.0, 14.0]" in fixed
    assert ":doc:`chemfiles-howto`" in fixed
    fixed_notes = _warnings(fixed)
    assert "Unexpected indentation." not in fixed_notes
    assert "Inline literal start-string without end-string." not in fixed_notes
