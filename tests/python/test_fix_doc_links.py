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


def test_the_old_pattern_is_a_docutils_error() -> None:
    docutils = pytest.importorskip("docutils")
    from io import StringIO

    from docutils.core import publish_doctree

    del docutils
    broken = _broken(HOWTO.read_text(encoding="utf-8"))
    warn = StringIO()
    publish_doctree(
        broken,
        settings_overrides={
            "warning_stream": warn,
            "halt_level": 5,
            "report_level": 2,
        },
    )
    text = warn.getvalue()
    assert ":1215: (ERROR/3) Unexpected indentation." in text
    assert ":1209: (WARNING/2) Inline literal start-string without end-string." in text
