=================================
The CON File Format Specification
=================================

    :Date: 2026-11-18


Requirement words
-----------------

The words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY on this page follow `RFC 2119 <https://www.rfc-editor.org/rfc/rfc2119>`_.

Specification
-------------

Version
    4.0.2 (major 4, minor 0, patch 2)

Date
    2026-11-18

Status
    Stable

Reference implementation
    `readcon-core <https://github.com/lode-org/readcon-core>`_

Lexical grammar
    the normative ABNF appendix

Surface grammar
    ``grammar/readcon.pest`` (included in the appendix; not the hot path)

Clause index
    ``docs/orgmode/clauses.tsv``, emitted by ``scripts/emit_clauses.py``

In-memory API
    :doc:`implementation-notes` (informative for this format)

This document is the normative CON format. CON checkpoints come from
rare-event work on eOn
:cite:t:`goswamiNEBOrchestration2026` :cite:t:`goswamiRMSDProjections2026` :cite:t:`goswamiGaussianProcessSaddle2025` :cite:t:`chillEONSoftwareLong2014`.
Each normative requirement has an id ``CON-<section>.<n>``.
Where this prose and the included PEG disagree, these clauses win.
Requirement words in uppercase follow RFC 2119 and RFC 8174
:cite:t:`bradnerKeyWordsUse1997` :cite:t:`rfc8174`.
Lowercase spellings of those words are not requirement words.

CON-status.1 \:\: MUST
    A reader MUST accept every minor and every patch of major 4, and every minor of major 3, including minor 0 and a minor or patch it does not implement.

CON-status.2 \:\: MUST
    A new implementation MUST accept version 2 and implicit version 1.

CON-status.3 \:\: MUST
    The identity of this specification MUST be the triple major.minor.patch.

CON-status.4 \:\: MUST
    Any change to normative text MUST increase at least the patch component of that identity.

CON-status.5 \:\: MUST NOT
    A minor revision MUST NOT change the meaning of an existing key or of an existing section.

CON-status.6 \:\: MAY
    A minor revision MAY add keys and sections. A reader of an earlier minor of that major MUST preserve an unknown key and MUST apply ``CON-section.8`` and ``CON-section.9`` to an unknown section.

.. _file:

File
----

A file is a concatenation of frames. Extensions: ``.con``, ``.convel``,
and the compression envelopes ``.con.gz``, ``.convel.gz``, ``.con.zst``,
``.convel.zst``.

CON-file.1 \:\: MUST
    A CON file MUST be UTF-8. A line that is not UTF-8 MUST be ``ValidationError``, except where ``CON-num.10`` names ``InvalidNumberFormat``.

CON-file.2 \:\: MUST NOT
    A CON file MUST NOT begin with a byte-order mark, and no frame may begin with U+FEFF. A reader MUST reject either case as ``ValidationError``.

CON-file.3 \:\: MUST
    Parsers MUST accept LF (``\n``) and CRLF (``\r\n``) line endings. A writer MUST end each line with LF and MUST NOT use a bare CR as its line ending.

CON-file.4 \:\: MUST
    Parsers MUST ignore trailing spaces and tabs on every line.

CON-file.5 \:\: MUST
    A label comparison MUST split both lines on ASCII spaces and tabs, drop empty words, and compare the words with ASCII case folding.

CON-file.6 \:\: MUST NOT
    Writers MUST NOT insert an extra blank line between frames.

CON-file.7 \:\: MUST
    A blank line MUST contain only characters of Unicode White\_Space, and no other character.

CON-file.8 \:\: MUST
    A line that is not UTF-8 and is not consumed as a numeric field MUST be ``ValidationError``.

CON-file.9 \:\: MUST
    A CR that is the last byte of the input MUST be read as a line ending. The bytes before that CR are that line, and a line with no other bytes MUST be a blank line.

CON-file.10 \:\: MUST
    This specification does not register a media type :cite:t:`rfc6838`. A reader MUST accept a file these clauses accept whether or not a media type is supplied beside it.

CON-file.11 \:\: MUST
    A reader MUST NOT apply Unicode normalization :cite:t:`rfc3629`. A reader MUST NOT apply case folding except the ASCII case folding of label words in ``CON-file.5`` and the exact spellings of ``CON-units.16``. A float spelling is not canonical: any spelling that ``CON-num.6`` accepts is enough.

.. _frame:

Frame and end of file
---------------------

Each frame is a 9-line header, one coordinate block per atom type, then
the declared sections. There is no inter-frame marker.
After a complete frame the next line is line 1 of the next frame, even when that line is empty.
A stray blank therefore shifts that header and fails at its line 3.

CON-frame.1 \:\: MUST
    After the last complete frame, the ignored tail MUST be at most one blank line as in ``CON-file.7``, followed only by lines whose bytes are spaces, tabs, form feeds, or carriage returns. Any other following line MUST be read as the next frame.

CON-frame.2 \:\: MUST NOT
    Readers MUST NOT silently drop a partial last frame.

CON-frame.3 \:\: MUST
    One to eight header lines of a further frame MUST be reported as ``IncompleteHeader``, except a type count of 0 at end of file whose lines 8 and 9 are absent.

CON-frame.4 \:\: MUST
    Fewer coordinate rows than the header declares MUST be reported as ``IncompleteFrame``.

CON-frame.5 \:\: MUST NOT
    A blank line followed only by whitespace to end of file MUST NOT be read as a legacy velocity block.

CON-frame.6 \:\: MUST
    A partial declared section MUST be reported as ``IncompleteSection(name)``.

CON-frame.7 \:\: MUST
    After a complete frame, including its declared sections or the legacy velocity block where that applies, the next line MUST be line 1 of the next frame, even when it is empty.

CON-frame.8 \:\: MUST
    A file that contains no bytes MUST be read as zero frames.

CON-frame.9 \:\: MUST
    At the start of a file, a reader MUST read the lines as the header of a frame. ``CON-frame.1`` applies only after a complete frame.

Header
------

.. table::

    +------+--------------------------------------------------+
    | Line | Content                                          |
    +======+==================================================+
    |    1 | Free-form generator text, preserved              |
    +------+--------------------------------------------------+
    |    2 | One JSON object, or free text for version 1      |
    +------+--------------------------------------------------+
    |    3 | Three lengths a, b, and c, in ``units.length``   |
    +------+--------------------------------------------------+
    |    4 | ``alpha beta gamma`` in degrees                  |
    +------+--------------------------------------------------+
    |    5 | Free-form text, preserved                        |
    +------+--------------------------------------------------+
    |    6 | Free-form text, preserved                        |
    +------+--------------------------------------------------+
    |    7 | Type count, integer >= 0                         |
    +------+--------------------------------------------------+
    |    8 | Per-type counts, empty when line 7 is 0          |
    +------+--------------------------------------------------+
    |    9 | Masses in ``units.mass``, empty when line 7 is 0 |
    +------+--------------------------------------------------+

Line 1 and lines 5-6 have no semantics.
Line 1 MAY be empty, and parsers MUST keep that empty line.
Line 2 MAY be empty. An empty line 2 does not start with ``{``, so the frame is implicit version 1.
Angstrom and amu apply when ``units`` or that key is absent.

CON-header.1 \:\: MAY
    Writers MAY leave lines 5 and 6 empty.

CON-header.2 \:\: MUST
    Parsers MUST preserve line 1 and lines 5 and 6.

CON-header.3 \:\: MUST
    Line 3 and the coordinate columns MUST be read in ``units.length``, and line 9 in ``units.mass``. Absent ``units`` or an absent key means angstrom and amu.

CON-header.4 \:\: MUST
    Parsers MUST accept an empty line 1 and an empty line 2. An empty line 1 is preserved. An empty line 2 is implicit version 1.

.. _metadata:

Line 2: Metadata
~~~~~~~~~~~~~~~~

Line 2 is one JSON object when the file is version 2 or newer.
A line that does not start with ``{`` after trimming is implicit version 1.
Metadata is line 2. Line numbers count from 1.

CON-line2.1 \:\: MUST
    A line 2 that starts with ``{`` MUST be one UTF-8 JSON object and nothing else.

CON-line2.2 \:\: MUST
    Malformed JSON on that line MUST be rejected.

CON-line2.3 \:\: MUST
    A JSON object that omits ``con_spec_version`` MUST be rejected.

CON-line2.4 \:\: MUST
    ``con_spec_version`` MUST be a JSON integer, the major version, and not a string. A JSON number that is not an integer MUST be ``InvalidMetadataJson``.

CON-line2.5 \:\: MUST
    JSON ``con_spec_version`` 0 or 1 MUST be rejected as ``UnsupportedVersion``.

CON-line2.6 \:\: MUST
    An unknown major MUST be rejected as ``UnsupportedVersion``.

CON-line2.7 \:\: MUST
    A reader of a known major MUST accept every minor and every patch of that major, including a minor or patch it does not implement.

CON-line2.8 \:\: MUST
    Unknown keys MUST be preserved on rewrite as their JSON values :cite:t:`brayJavascriptObjectNotation2017`. The rewrite MUST NOT be required to preserve key order, insignificant whitespace, or the original spelling of a number, and it is not required to follow the JSON Canonicalization Scheme :cite:t:`rfc8785`. A JSON string MUST be preserved as that string. An escape that is not a JSON escape MUST be ``InvalidMetadataJson`` under ``CON-line2.2``.

CON-line2.9 \:\: MUST
    ``con_spec_minor``, when present, MUST be a JSON integer >= 0.

CON-line2.10 \:\: MUST
    A missing ``con_spec_minor``, or an explicit 0, MUST mean minor 0.

CON-line2.11 \:\: MUST
    ``sections``, when present, MUST be an array of strings.

CON-line2.12 \:\: MUST
    ``validate``, when present, MUST be a boolean.

CON-line2.13 \:\: MUST
    Reserved keys MUST use the types in this document.

CON-line2.14 \:\: MUST NOT
    A line 2 object MUST NOT repeat the ``con_spec_minor`` key.

CON-line2.15 \:\: MUST
    ``con_spec_patch``, when present, MUST be a JSON integer >= 0. Any other type MUST be ``InvalidMetadataJson``.

CON-line2.16 \:\: MUST
    A missing ``con_spec_patch``, or an explicit 0, MUST mean patch 0.

CON-line2.17 \:\: MUST
    A reader of a known major MUST accept every patch of that major.

CON-line2.18 \:\: MUST
    A reader MUST accept line 2 when the nesting depth of its JSON value, counting the outer value, is at most 127, and MUST reject a greater depth as ``InvalidMetadataJson``. That rejection MUST NOT require stack space proportional to the depth.

CON-line2.19 \:\: MUST
    A reserved key that must hold a finite number, and whose JSON number is not a finite binary64, MUST be ``InvalidMetadataJson``.

CON-line2.20 \:\: MUST
    A reader MUST apply the every-mode type check of a reserved key before the checks of ``CON-validate.4``. A wrong type MUST be ``InvalidMetadataJson``.

CON-line2.21 \:\: MUST NOT
    A JSON number that is not a finite binary64, stored under a key this document does not reserve, MUST NOT reject the frame.

CON-line2.22 \:\: MUST
    ``con_spec_minor``, ``con_spec_patch``, and any other integer version field MUST fit in an unsigned 64-bit integer. A reader MUST reject a larger value as ``InvalidMetadataJson``.

CON-line2.23 \:\: MUST
    A JSON object MUST NOT repeat a name. A repeated name, in the metadata object or in any object it contains, MUST be ``InvalidMetadataJson``. The reader MUST NOT keep one of the values.

CON-line2.24 \:\: MUST
    This schema MUST be informative. These clauses decide acceptance. The schema carries this specification identity.

CON-line2.25 \:\: MUST
    ``CON-line2.18`` is the resource limit on line 2. A reader MUST accept a frame the conformance corpus accepts. A reader MUST NOT reject a frame these clauses accept because of the byte length of the file.

.. _cell:

Cell
~~~~

Line 3 is ``|a| |b| |c|``. Line 4 is ``alpha`` ``angle(b,c)``, ``beta`` ``angle(a,c)``,
``gamma`` ``angle(a,b)``, in degrees. ``a`` lies along x and ``b`` lies in the xy plane.
eOn 3.6.0 reads that placement at ``client/ConFileIO.cpp:659-681`` and writes it at ``:531-549``.
ASE ``cellpar_to_cell`` uses the same orientation by default (``ase/geometry/cell.py:50``, ``ab_normal=(0,0,1)``).
``lattice_vectors`` is three row vectors in ``units.length``, ``[a, b, c]``.

CON-cell.1 \:\: MUST
    When ``lattice_vectors`` is present, readers MUST prefer it over lines 3-4.

CON-cell.2 \:\: MUST
    A writer that emits ``lattice_vectors`` MUST write lines 3-4 consistent with that matrix at the precision the writer is using.

CON-cell.3 \:\: MUST
    A missing ``pbc`` key MUST be read as periodic in all three directions.

CON-cell.4 \:\: MUST
    ``pbc``, when present, MUST be a length-3 array of booleans.

CON-cell.5 \:\: MUST
    ``lattice_vectors``, when present, MUST be three length-3 arrays of finite numbers.

CON-cell.6 \:\: MUST
    When ``lattice_vectors`` is absent, a reader MUST build the cell from lines 3 and 4. The angles are converted from degrees to radians, ``a=(|a|, 0, 0)``, ``b=(|b| cos gamma, |b| sin gamma, 0)``, and ``c=(|c| cos beta, |c| (cos alpha - cos beta cos gamma) / sin gamma, |c| sqrt(1 - cos^2 beta - ((cos alpha - cos beta cos gamma) / sin gamma)^2))``. The square root is the z component of ``c``. A construction that is not a real cell MUST be rejected on the angles line, as ``CON-cell.7`` requires.

CON-cell.7 \:\: MUST
    When ``lattice_vectors`` is absent and each angle is in (0, 180) degrees, a reader MUST evaluate the radicand of ``c_z`` in binary64 and MUST NOT contract a multiply and an add into a fused multiply-add. With alpha, beta, and gamma the angles in radians, the operations in order are cos alpha, cos beta, cos gamma, sin gamma, cy = (cos alpha - cos beta \* cos gamma) / sin gamma, and radicand = 1 - cos beta \* cos beta - cy \* cy. A radicand greater than -1e-12 MUST be accepted, and a negative radicand in that window MUST set ``c_z`` to 0. Any other radicand, including a NaN radicand, MUST be ``ValidationError`` on the angles line.

Counts
~~~~~~

A type count of 0 is a frame with no atoms.
Lines 8 and 9 are whitespace only, no coordinate block and no section follow, ``sections`` is absent or empty, and the legacy velocity fallback does not apply.
That frame is legal with ``validate`` true.
A per-type count of 0 is InvalidCount when the type count is 1 or more.
ASE 3.29.0 ``write_eon(Atoms())`` writes type count 0, an empty line 8, and an unterminated empty line 9 (``ase/io/eon.py:277-307``).
``ase.io.eon.read_eon`` then raises ``IndexError`` at ``images[0]`` (``ase/io/eon.py:188``). The ``StopIteration`` from the ninth ``next()`` is caught inside that function (``:177-179``).
``ase.io.read(path, format``"eon")= raises ``StopIteration`` from ``ase/io/formats.py:821`` (``next(_iread(...))`` on a read that yields no image).

CON-count.1 \:\: MUST
    A type count of 0 MUST be a frame with zero atoms: lines 8 and 9 contain only spaces and tabs, no coordinate block and no section block follow, ``sections`` is absent or empty, and the legacy velocity fallback does not apply. Any other character on line 8 or 9, including other Unicode White\_Space, MUST be ``InvalidCount``.

CON-count.2 \:\: MUST
    A zero-atom frame of that form MUST be accepted in every mode, including ``validate`` true. ``CON-validate.3`` still requires the ``sections`` key when ``validate`` is true.

CON-count.3 \:\: MUST
    When the type count is 1 or more, each per-type count MUST be an integer >= 1, and any other count token MUST be ``InvalidCount``.

CON-count.4 \:\: MUST
    At end of file, when line 7 is 0, missing lines 8 and 9 MUST be read as empty, and ``CON-frame.3`` MUST NOT report that frame as ``IncompleteHeader``.

CON-count.5 \:\: SHOULD NOT
    Writers SHOULD NOT write a zero-atom frame for a consumer that predates v3.1.

CON-count.6 \:\: MUST
    The coordinate blocks MUST follow header order.

CON-count.7 \:\: MUST
    The total atom count MUST equal the sum of line 8.

CON-count.8 \:\: MUST
    Component numbers in labels MUST start at 1.

CON-count.9 \:\: MUST
    A count token MUST be an integer in 0 through 2^64-1. An integer outside that range MUST be ``InvalidCount``.

CON-count.10 \:\: MUST
    On a count line, a token that is not an unsigned integer MUST be reported as ``InvalidCount`` before the field-count check of ``CON-num.9`` is applied to that line.

Coordinates
-----------

One block per type: a symbol line, a ``Coordinates of Component N`` label,
then one atom line per atom of that type. Columns are whitespace-separated.

.. table::

    +--------+---------+------------------------+
    | Column | Token   | Meaning                |
    +========+=========+========================+
    |      1 | float   | x, in ``units.length`` |
    +--------+---------+------------------------+
    |      2 | float   | y, in ``units.length`` |
    +--------+---------+------------------------+
    |      3 | float   | z, in ``units.length`` |
    +--------+---------+------------------------+
    |      4 | integer | Constraint flag        |
    +--------+---------+------------------------+
    |      5 | integer | Atom id, optional      |
    +--------+---------+------------------------+

CON-coord.1 \:\: MUST
    In every mode, the label of a coordinate block MUST equal ``Coordinates of Component N`` under ``CON-file.5``, with N starting at 1, and any other label MUST be ``ValidationError``.

.. _constraints:

Per-direction constraints (column 4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Column 4 is an integer token. Bit 0 is x, bit 1 is y, bit 2 is z.
Spec 1 (no JSON on line 2): 0 is free, 1 is fixed in all three directions.
Spec 2 and later: 0 through 7 are the bitmask, and 1 is x only.
Writers of spec 2 and later emit 7 for all-fixed.

CON-mask.1 \:\: MUST
    Column 4 MUST be an integer token with no sign and no decimal point.

CON-mask.2 \:\: MUST
    In spec 1, readers MUST treat 0 as free and 1 as fixed on x, y, and z.

CON-mask.3 \:\: MUST
    In spec 1, any other column-4 token MUST be ``InvalidFixedFlag``.

CON-mask.4 \:\: MUST
    In spec 2 and later, values 0 through 7 MUST be read as the bitmask above.

CON-mask.5 \:\: MUST
    A float spelling, a sign, or a value outside the legal set MUST be ``InvalidFixedFlag`` in every mode, including when ``validate`` is absent or false.

CON-mask.6 \:\: MUST NOT
    A spec 2 or later writer MUST NOT emit 1 to mean all-fixed.

CON-mask.7 \:\: MUST
    A spec 2 or later writer MUST emit 7 for an atom fixed on x, y, and z.

.. _atom-index:

Atom index (column 5)
~~~~~~~~~~~~~~~~~~~~~

Column 5 is the atom id. No base is implied.
Grouping by type reorders atoms relative to a pre-group sequence.
eOn 3.6.0 stable-sorts by ascending id when the ids are unique, and keeps file order when any id repeats (``client/ConFileIO.cpp:147-176`` ``matter_order``, called at ``:691``).
v3.4.0 has the same function.

CON-id.1 \:\: MUST
    Column 5, when present, MUST be parsed as an integer in 0 through 2^64-1, and MUST NOT be parsed through binary64.

CON-id.2 \:\: MUST NOT
    Readers MUST NOT assume that ids start at 0 or at 1.

CON-id.3 \:\: MUST
    Writers MUST emit ids that are unique within the frame.

CON-id.4 \:\: MUST
    Readers MUST accept repeated ids.

CON-id.5 \:\: MUST
    The pre-grouping order of a frame MUST be ascending column-5 id when the ids are unique, and file order otherwise.

CON-id.6 \:\: MUST
    A reader MUST expose column-5 ids unchanged.

CON-id.7 \:\: MUST
    A reader or consumer that returns atoms in pre-grouping order MUST use ``CON-id.5``.

CON-id.8 \:\: MAY
    A reader MAY return atoms in file order together with their column-5 ids.

CON-id.9 \:\: MUST
    A 4-column atom line MUST use the 0-based position of that atom in the frame as its id.

CON-id.10 \:\: MUST
    ``ids_persistent``, when present, MUST be a JSON boolean. Any other type MUST be ``InvalidMetadataJson``.

CON-id.11 \:\: MUST
    When ``ids_persistent`` is true on any frame, it MUST be true on every frame, every frame MUST hold the same set of column-5 ids, and each of those ids MUST occur once in a frame. A reader MUST reject a file that breaks this rule as ``ValidationError`` on the last line of the frame that breaks it. A writer MUST NOT emit such a file.

CON-id.12 \:\: MUST NOT
    When ``ids_persistent`` is absent or false on every frame, a reader MUST NOT treat an id in one frame as the same atom in another frame. ``CON-id.4`` still applies inside a frame.

CON-id.13 \:\: MUST
    A read of a frame followed by a write of that frame MUST preserve each column-5 id.

.. _sections:

Sections
--------

A section is present exactly when its name is in ``sections``.
An empty ``sections`` array means no section follows, and it disables the
legacy velocity fallback. With no ``sections`` key, one blank line that
begins a complete velocity block is a velocity section. A blank line
that does not begin that block is line 1 of the next frame. That fallback
is the only undeclared section, and ``CON-frame.5`` limits it.
Minor 1 reserves the names in the table below.
A vector row has arity 3 and a scalar row has arity 1.
Those integers count value fields only.

Section declaration
~~~~~~~~~~~~~~~~~~~

CON-section.1 \:\: MUST
    On disk, a section MUST be treated as present exactly when its name is listed in ``sections``, aside from the legacy velocity fallback.

CON-section.2 \:\: MUST
    Exactly one blank line MUST precede each section block.

CON-section.3 \:\: MUST NOT
    Writers MUST NOT put a blank line between the component blocks inside a section.

CON-section.4 \:\: MUST
    Each component block MUST be a symbol line, a label, and one data row per atom of that type.

CON-section.5 \:\: MUST
    The per-atom energy section name MUST be ``energies``.

CON-section.6 \:\: MUST NOT
    ``atom_energies`` MUST NOT be used as a section name.

CON-section.7 \:\: MUST
    An unknown section name MUST be reported as ``UnknownSection`` when the frame minor is not newer than the minor this reader implements.

CON-section.8 \:\: MUST
    When the frame minor is newer than the minor this reader implements for that major, the reader MUST skip an unknown section whose value-field count is given by ``section_arity``. For major 4 that minor is 0. For major 3 that minor is 1.

CON-section.9 \:\: MUST
    If that minor is newer and ``section_arity`` does not give the value-field count, the reader MUST report ``UnknownSection``.

CON-section.10 \:\: MUST
    Adding a reserved section name MUST increase ``con_spec_minor``.

CON-section.11 \:\: MUST NOT
    Adding a reserved section name MUST NOT require a new major.

CON-section.12 \:\: MUST
    ``section_arity``, when present, MUST be an object mapping section names to integers >= 1, each the number of value fields on a data row, excluding the flag and the optional id.

CON-section.13 \:\: MUST
    An entry for a reserved section MUST equal 3 for a vector row and 1 for a scalar row. A reader MUST reject any other value because the row does not have the number of fields that section requires.

CON-section.14 \:\: MUST
    A data row of an unknown section MUST hold that arity of value fields, then the flag, and an optional id, so the row has arity+1 or arity+2 tokens.

CON-section.15 \:\: MUST
    The label of any section MUST be its name compared under ``CON-file.5``, followed by ``of Component N``. When ``validate`` is not true, a label that does not match MUST be ``IncompleteSection``. When ``validate`` is true, that label MUST be ``ValidationError``.

CON-section.16 \:\: MUST
    A writer whose minor is greater than the minor that reserves the section table MUST list in ``section_arity`` every section it emits that the table does not name. That reserving minor is 0 for major 4 and 1 for major 3.

.. table::

    +-------------------+----------------------------------+---------------------------------------------------+
    | Name              | Label                            | Row                                               |
    +===================+==================================+===================================================+
    | ``velocities``    | ``Velocities of Component N``    | ``vx vy vz`` flag id                              |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``forces``        | ``Forces of Component N``        | ``fx fy fz`` flag id                              |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``energies``      | ``Energies of Component N``      | energy flag id                                    |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``charges``       | ``Charges of Component N``       | charge flag id                                    |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``spins``         | ``Spins of Component N``         | spin flag id                                      |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``magmoms``       | ``Magmoms of Component N``       | ``mx my mz`` flag id                              |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``displacements`` | ``Displacements of Component N`` | ``dx dy dz`` flag id, ``units.length``            |
    +-------------------+----------------------------------+---------------------------------------------------+
    | ``spreads``       | ``Spreads of Component N``       | ``sx sy sz`` flag id, ``units.length``, each >= 0 |
    +-------------------+----------------------------------+---------------------------------------------------+

Identity columns repeat the coordinate flag and id.
0 in a ``spreads`` row is a classical point.

CON-section.17 \:\: MUST
    When ``validate`` is not true, a reader MUST ignore an identity-column mismatch after the row has the right number of fields.

CON-section.18 \:\: SHOULD
    The ``energy`` metadata value SHOULD equal the sum of the ``energies`` rows.

CON-section.19 \:\: MUST NOT
    A mismatch between that sum and ``energy`` MUST NOT reject the frame.

CON-section.20 \:\: MUST
    Each ``spreads`` value MUST be finite and >= 0. A value that is not MUST be ``ValidationError``.

CON-section.21 \:\: MUST NOT
    When ``validate`` is not true, a reader MUST NOT reject a section because of its symbol line, including a blank symbol line.

CON-section.22 \:\: MUST
    Section blocks MUST follow the coordinate blocks in the order listed in ``sections``. A label that does not match the next listed section MUST be ``IncompleteSection``.

CON-section.23 \:\: MUST
    Two or more blank lines before a section block make the second blank line the symbol line of that section. The following line is then its label, and a label that fails ``CON-section.15`` MUST be ``IncompleteSection``.

CON-section.24 \:\: MUST
    A name MUST NOT appear twice in ``sections``. A repeated name MUST be ``InvalidMetadataJson``.

.. _validation-mode:

Validation mode
~~~~~~~~~~~~~~~

CON-validate.1 \:\: MUST
    ``validate`` true MUST add the checks in ``CON-validate.4``.

CON-validate.2 \:\: MUST NOT
    ``validate`` true MUST NOT relax a check that already applies in every mode.

CON-validate.3 \:\: MUST
    When ``validate`` is true, ``sections`` MUST be present, and an empty array is legal.

CON-validate.4 \:\: MUST
    In that mode, readers MUST reject a non-positive cell length, an angle outside (0, 180) degrees, a non-positive mass, an unrecognized symbol other than ``X``, a section symbol mismatch, or an identity column that does not match the coordinate row, as ``ValidationError``. A bad reserved-key type is ``InvalidMetadataJson`` under ``CON-line2.13`` and ``CON-line2.19``. A coordinate label is ``CON-coord.1`` in every mode. A section label is ``CON-section.15`` in every mode.

.. _bonds:

Frame topology (bonds)
~~~~~~~~~~~~~~~~~~~~~~

``bonds`` is optional frame topology, not a section.
Each entry is ``[i, j]`` or ``{"i": i, "j": j}`` with an optional integer ``order``.
Indices are 0-based into coordinate-block order, not column-5 ids.
This key is legal on major 3. It does not change the major.

CON-bonds.1 \:\: MUST NOT
    ``bonds`` MUST NOT appear in ``sections``.

CON-bonds.2 \:\: MUST
    With ``validate`` true, a malformed ``bonds`` entry MUST be rejected.

CON-bonds.3 \:\: MUST
    With ``validate`` false, unknown ``bonds`` shapes MUST be preserved.

.. _units:

Units (required)
----------------

``units`` maps a dimension to a unit expression: names combined with ``\*``, ``/``, ``^``, and parentheses.
Version 3 requires ``length`` and ``energy``.
Velocity is length/time taken from ``units``.

The natural time unit used by eOn and by ASE, verified by an eOn 3.6.0 round trip, is written exactly ``(amu*angstrom^2/eV)^0.5``.
That expression is a time. ``units.rs`` parses it as about 10.180505710759414 fs.
eOn hard-codes 10.1805055 fs (``include/eon/ParametersOptions.h:26``).
The relative difference is about 2e-8.
A writer that canonicalises the expression by inserting spaces is not using the pinned spelling.
The conversion constants are the CODATA 2018 values :cite:t:`tiesingaCodataRecommendedValues2021` :cite:t:`bipmSI2019`. ``kcal`` is the thermochemical kilocalorie, exactly 4184 joule :cite:t:`nistSP811Conversions`, and is not a CODATA value. ``mol`` is the mole, the Avogadro constant of that edition.

CON-units.1 \:\: MUST
    Major 3 and later MUST include ``units.length`` and ``units.energy`` as non-empty strings of the matching dimension.

CON-units.2 \:\: MUST
    Optional ``mass``, ``time``, ``velocity``, and ``force`` strings, when present, MUST have the matching dimension.

CON-units.3 \:\: MUST
    A writer of major 4 or later MUST write ``units.time`` whenever the frame has a velocities section.

CON-units.4 \:\: MUST NOT
    A writer MUST NOT insert ``time: fs`` silently when the frame does not carry a time unit.

CON-units.5 \:\: MUST
    The natural unit MUST be written with the exact spelling ``(amu*angstrom^2/eV)^0.5``.

CON-units.6 \:\: MUST NOT
    Version 1 MUST NOT carry a ``units`` object.

CON-units.7 \:\: MAY
    Version 2 MAY carry ``units``.

CON-units.8 \:\: MUST
    In versions 1 and 2, and in every minor of major 3, velocities MUST be read as ``units.length`` per the natural time unit, and length is angstrom when ``units.length`` is absent.

CON-units.9 \:\: MUST NOT
    Any ``units.time`` on versions 1 and 2, and on every minor of major 3, MUST NOT be trusted, and a missing ``units.time`` MUST NOT reject the frame.

CON-units.10 \:\: MUST
    In major 4 and later, ``units.time`` MUST be authoritative for velocities.

CON-units.11 \:\: MUST
    A frame of major 4 or later with a velocities section and no ``units.time`` MUST be rejected with ``InvalidUnits``.

CON-units.12 \:\: MUST
    A writer of major 4 or later asked to write velocities with no time unit MUST fail with ``InvalidUnits``.

CON-units.13 \:\: MUST
    An invalid unit expression on write MUST be reported as ``InvalidUnits``.

CON-units.14 \:\: MUST NOT
    Writers MUST NOT replace an invalid unit with a default.

CON-units.15 \:\: MAY
    A consumer MAY apply an explicit velocity time-unit override when a file breaks ``CON-units.8`` through ``CON-units.10``.

CON-units.16 \:\: MUST
    A reader MUST accept at least these spellings and MUST match them exactly. ``MeV`` is megaelectronvolt, one million times ``eV``. ``meV`` and ``mev`` are millielectronvolt. ``eV`` and ``ev`` are electronvolt. Length: ``m``, ``meter``, ``metre``, ``angstrom``, ``Angstrom``, ``A``, ``a``, ``å``, ``Å``, ``nm``, ``nanometer``, ``bohr``, ``a0``. Energy: ``J``, ``j``, ``joule``, ``eV``, ``ev``, ``meV``, ``mev``, ``MeV``, ``hartree``, ``ha``, ``kcal``, ``kJ``, ``kj``. Mass: ``kg``, ``kilogram``, ``u``, ``amu``, ``AMU``, ``dalton``, ``da``. Time: ``s``, ``second``, ``fs``, ``femtosecond``, ``ps``, ``picosecond``, ``ns``, ``nanosecond``. Count: ``mol``. A different capitalization that this list does not write out MUST be an unknown unit.

CON-units.17 \:\: MUST
    A reader MUST remove ASCII spaces and tabs from a unit expression before reading that expression.

CON-units.18 \:\: MUST
    A reader MUST use the constants in the table of this section. ``bohr`` and ``a0`` are 5.29177210903e-11 metre. ``amu``, ``AMU``, ``u``, ``dalton``, and ``da`` are 1.66053906660e-27 kilogram. ``hartree`` and ``ha`` are 4.3597447222071e-18 joule. ``eV`` and ``ev`` are 1.602176634e-19 joule. ``meV`` and ``mev`` are 1.602176634e-22 joule. ``MeV`` is 1.602176634e-13 joule. ``mol`` is 6.02214076e23. ``kcal`` is 4184 joule. ``angstrom``, ``Angstrom``, ``A``, ``a``, ``å``, and ``Å`` are 1e-10 metre. ``fs`` is 1e-15 second. ``kJ`` and ``kj`` are 1000 joule.

CON-units.19 \:\: MUST
    A rewrite that emits major 4 for velocities read under ``CON-units.8`` MUST set ``units.time`` to the spelling of ``CON-units.5`` and MUST NOT keep a ``units.time`` label that ``CON-units.9`` forbids trusting. The absent ``units.length`` of that frame MUST be written as ``angstrom``, and the absent ``units.energy`` MUST be written as ``eV``.

Every minor of major 3 keeps the version 3.0 rule, because a minor must not change the meaning of ``units.time``. The producers of those velocity sections wrote natural-unit numbers under an ``fs`` label. Major 4 carries the meaning version 3.1 gave that key.

.. _numbers:

Numbers
-------

CON-num.1 \:\: MUST
    Readers MUST reject NaN, Inf, Infinity, and the signed and mixed-case spellings of those words, in every numeric field and in every mode, as ``NonFiniteValue``.

CON-num.2 \:\: MUST NOT
    ``validate`` true MUST NOT be required before a reader applies ``CON-num.1``.

CON-num.3 \:\: MUST NOT
    ``validate`` true MUST NOT accept a non-finite value.

CON-num.4 \:\: MUST NOT
    A writer MUST NOT encode an absent numeric value as a NaN. The informative annex names one implementation's in-memory sentinel.

CON-num.5 \:\: MUST
    Readers MUST convert a finite decimal token to binary64 with correct rounding: round to nearest, ties to even, including subnormal values :cite:t:`ieeecomputersocietyIeeeStandardFloatingpoint2019` :cite:t:`clingerHowReadFloating1990`. A token whose value is negative zero MUST be read as negative zero. A finite spelling whose magnitude is too large for a finite binary64 MUST be ``NonFiniteValue``. The reader MUST consume the whole token.

CON-num.6 \:\: MUST
    A conforming writer in its default mode MUST write each finite float so that parsing it returns the same binary64 value. Any such spelling is enough. A writer MUST NOT be required to use the shortest spelling. The shortest round-tripping spelling is permitted :cite:t:`steeleHowPrintFloatingpoint1990` :cite:t:`adamsRyFastFloattostring2018`.

CON-num.7 \:\: MUST
    Fixed-decimal output MUST be used only when the writer is asked for it, and it need not round-trip.

CON-num.8 \:\: MUST
    A token that is not a decimal number and not a non-finite spelling MUST be ``InvalidNumberFormat``, except where ``CON-error.3`` names another class.

CON-num.9 \:\: MUST
    A reader MUST reject a row that does not have the number of fields that row requires.

CON-num.10 \:\: MUST
    A numeric field whose bytes are not a finite decimal token MUST be ``InvalidNumberFormat``, including when a byte of that field is not UTF-8.

eOn ``.convel`` output at 6 digits after the decimal (``kConvelPrecision`` in ``client/ConFileIO.cpp:43``) is fixed-decimal and lossy.
The kinetic-energy loss for that rounding was measured on one 336-atom Pt slab at 300 K (one Maxwell-Boltzmann draw) as 5.8e-7 relative.

Cell numbers are the ``boxl`` and ``angles`` lines, the extended XYZ ``Lattice`` string, the PDB ``CRYST1`` record, the CON-bin cell column, and the cell or lattice an API caller passes to a builder or a column writer. A NaN or an infinity in one, or a decimal binary64 cannot hold such as ``1e999``, is ``NonFiniteValue``. The message names the field and, when the entry point knows it, the 0-based frame: ``non-finite value: cell field boxl[1] of frame 1 is NaN``. The field is ``boxl[i]``, ``angles[i]``, ``Lattice[i]``, ``cell[i]``, or ``lattice_vectors[r][c]``. A writer refuses a frame whose cell is non-finite with the same class and writes none of that frame. A refused batch or path write creates no file. A cell that is finite in binary64 and infinite in binary32 is refused when a file is written as binary32.

A float token is an optional ``+`` or ``-``, a significand with at least one digit, an optional fraction (a leading dot is allowed), and an optional exponent. An integer token is one or more ASCII digits and nothing else.

.. _compression:

Compression
-----------

CON-compress.1 \:\: MUST
    A gzip envelope MUST expose every member of a multi-member file, in order, as CON text.

CON-compress.2 \:\: MUST
    A zstd envelope MUST expose every frame in the stream as CON text.

CON-compress.3 \:\: MUST
    Readers MUST detect gzip and zstd by magic bytes, not only by the extension.

CON-compress.4 \:\: MAY
    A writer MAY split one frame across gzip members at the same deflate level. The first member then sets the FEXTRA flag. Its extra field contains subfield id ``RC`` whose data is the ASCII magic ``RCZ1``, a little-endian ``u16`` member count, and that many little-endian ``u64`` file offsets of the members. A reader MAY inflate those slices concurrently. A gzip file without that subfield, including one member and a multi-member file from another writer, MUST still be read in order. ``gzip -d`` reads both.

CON-compress.5 \:\: MAY
    A writer MAY split one frame across zstd frames at the same level. A skippable frame (magic ``50 2a 4d 18``) then precedes them and carries the same ``RCZ1`` index. A decoder MUST ignore an unknown skippable frame. A one-frame zstd file has no index. ``zstd -d`` reads both.

Errors
------

Line numbers count from 1. Metadata failures are line 2.
``IncompleteSection`` carries the section name.
A reader that stops at the first error MUST use the lowest line number, so threads cannot change which error is reported.

.. table::

    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Class                       | When                                                                                                                                                                                   |
    +=============================+========================================================================================================================================================================================+
    | ``MissingSpecVersion``      | Line 2 starts with ``{`` but omits ``con_spec_version``.                                                                                                                               |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidMetadataJson``     | Line 2 is malformed JSON, a reserved key has the wrong type, an object repeats a name, or ``validate`` true omits ``sections``.                                                        |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``NonFiniteValue``          | NaN, Inf, or a spelling of either, any mode. A cell field is named, with its frame when known.                                                                                         |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidFixedFlag``        | Column 4 is not a legal integer flag, any mode.                                                                                                                                        |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidCount``            | A count field is not an unsigned integer, or a per-type count is 0 when the type count is 1 or more. A type count of 0 is a legal zero-atom frame.                                     |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidUnits``            | A unit expression is missing, mistyped, or the wrong dimension. A frame of major 4 or later with velocities and no ``units.time`` is this class on read and on write.                  |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``IncompleteHeader``        | A started frame has too few header lines, other than ``CON-count.4``.                                                                                                                  |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``IncompleteFrame``         | A coordinate block is shorter than declared.                                                                                                                                           |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``IncompleteSection(name)`` | A declared section is missing or short.                                                                                                                                                |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidNumberFormat``     | Column 5 or another field is not a decimal number.                                                                                                                                     |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``InvalidVectorLength``     | A row has the wrong number of fields, or a reserved arity is not 3 for a vector or 1 for a scalar. An unknown-section row has that many value fields, then a flag, and an optional id. |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``UnknownSection``          | A section name is not known and cannot be skipped.                                                                                                                                     |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``UnsupportedVersion``      | Unknown major, or JSON major 0 or 1.                                                                                                                                                   |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ``ValidationError``         | A check that names this class failed, including ``CON-cell.7`` and ``CON-id.11``. It MUST NOT relax ``NonFiniteValue`` or ``InvalidFixedFlag``. A legal zero-atom frame is accepted.   |
    +-----------------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

CON-error.1 \:\: MUST
    Each class in the table MUST be distinguishable by a caller.

CON-error.2 \:\: MUST
    Reported line numbers MUST count from 1, with metadata on line 2.

CON-error.3 \:\: MUST
    A count field that is not an unsigned integer, including a sign, a decimal point, or ``-1``, MUST be ``InvalidCount``. Column 4 MUST be ``InvalidFixedFlag``. Column 5 and every other such field MUST be ``InvalidNumberFormat``.

CON-error.4 \:\: MUST
    A reader that stops at an error MUST report the one with the lowest line number.

CON-error.5 \:\: MUST
    When one line can fail more than one check, the reader MUST report the class the clause for that line names. ``CON-error.4`` still selects the lowest line. On a count line the count class of ``CON-count.10`` precedes the field-count class of ``CON-num.9``. On the angles line, the cell check of ``CON-cell.7`` is ``ValidationError``.

.. _conformance:

Conformance
-----------

A product is a reader, a validating reader, a writer, a consumer, or a round trip :cite:t:`w3cTestGuidelines`.
Optional compression is ``CON-compress.4`` and ``CON-compress.5``.
Passing is the conformance corpus: the verdict, the class, and the line the manifest names.

CON-profile.1 \:\: MUST
    A reader MUST apply every requirement this document addresses to a reader, in every mode.

CON-profile.2 \:\: MUST
    A validating reader MUST be a reader. ``validate`` true MUST add the checks of ``CON-validate.4`` and MUST NOT relax a check that applies in every mode.

CON-profile.3 \:\: MUST
    A writer MUST apply every requirement this document addresses to a writer.

CON-profile.4 \:\: MUST NOT
    A consumer MUST NOT be required to apply a reader check. An explicit velocity time-unit override is ``CON-units.15``.

CON-profile.5 \:\: MUST
    A round trip is a read of a frame, a write of that frame, and a read of the result. The second read MUST return the same binary64 coordinates, velocities, and cell entries, the same masks, identifiers, and periodic flags, and units of the same dimension. It MUST NOT be required to return the same spelling of a float or of an unknown key.

Version history
---------------

.. table::

    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    | Version |       Date | Change                                                                                                                    |
    +=========+============+===========================================================================================================================+
    |       1 |   original | eOn text. Column 5 present. Column 4 is 0 or 1. No JSON.                                                                  |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |       2 | 2026-03-25 | JSON line 2, ids, bit masks, declared sections.                                                                           |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |     3.0 | 2026-06-27 | ``units.length`` and ``units.energy`` MUST be present. Minor absent.                                                      |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |     3.1 | 2026-10-11 | Minor 1. ``units.time`` when velocities are present. Natural-unit rule.                                                   |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |   4.0.0 | 2026-11-18 | Major 4. ``units.time`` is authoritative. Major 3 keeps the 3.0 meaning. Patch identity.                                  |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |   4.0.1 | 2026-11-18 | An integer version field MUST fit in an unsigned 64-bit integer. A byte-order mark at the start of any frame is rejected. |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+
    |   4.0.2 | 2026-11-18 | Lexical grammar, object names, unit spellings, the numeric contract, and conformance classes.                             |
    +---------+------------+---------------------------------------------------------------------------------------------------------------------------+

The major version moved from 3 to 4 because the meaning of ``units.time`` changed.

Version 3.0 defined the old meaning in ``CON-units.8`` and ``CON-units.9`` of that text: in versions 1, 2, and 3.0, velocities MUST be read as ``units.length`` per the natural time unit, and length is angstrom when ``units.length`` is absent. Any ``units.time`` on versions 1, 2, and 3.0 MUST NOT be trusted.

Version 3.1 defined the new meaning in ``CON-units.10`` of that text: from minor 1 onward, ``units.time`` MUST be authoritative for velocities.

That change altered the meaning of an existing key inside one major, so it is not a minor revision (``CON-status.5``). Major 4 carries the version 3.1 meaning: ``units.time`` is authoritative for velocities. Every minor of major 3 carries the version 3.0 meaning: velocities are ``units.length`` per the natural time unit, and ``units.time`` MUST NOT be trusted. A reader of major 3 MUST NOT apply ``units.time`` and MUST NOT reject a velocities section for a missing ``units.time``.

The specification identity is major.minor.patch (``CON-status.3``). Any change to normative text increases at least the patch (``CON-status.4``). This text is 4.0.2.

Normative changes on 2026-10-11, by decision:

- Non-finite numbers are rejected in every mode (``D1``).

- A partial last frame is an error. Trailing whitespace is not a frame. A blank line and then only whitespace is not a velocity block (``D2``).

- A section is present exactly when its name is in ``sections``. Builder clearing is not a format rule (``D3``).

- A type count of 0 with empty lines 8 and 9 is a legal zero-atom frame. A zero per-type count when the type count is >= 1 is ``InvalidCount``. D4 revised after checking eOn 3.6.0 (``D4``).

- One blank line before a section, and none between its component blocks (``D5``).

- The scalar energy section is ``energies`` (``D6``).

- ``bonds`` is specified for major 3 (``D7``).

- Column 4 is an integer flag, with spec-1 and spec-2 meanings (``D8``).

- Column 5 is an integer id. Unique ids define ascending pre-grouping order. A repeated id keeps file order (``D9``).

- Velocity units follow the version rules, and the natural spelling is pinned (``D10``).

- Invalid units fail the writer (``D11``).

- Lines 3-4 and ``lattice_vectors`` follow the cell convention. Missing ``pbc`` is fully periodic (``D12``).

- Default float text round-trips binary64. Fixed decimals are opt-in (``D13``).

- Unknown keys are kept. Unknown sections of a newer minor MAY be skipped by ``section_arity`` (``D14``).

- The major is 4. ``con_spec_minor`` is 0. ``con_spec_patch`` is 1. A same-major reader accepts every minor and every patch (``D15``).

- Gzip members and zstd frames are normative envelopes (``D16``).

- Line 2 is one JSON line. Trailing space is ignored. Labels collapse spaces (``D17``).

``con_spec_minor`` is the minor of that major. ``con_spec_patch`` is the patch of that minor. The builder stamps minor 0 and patch 2 on every major 4 frame it builds when the caller has not set the key. ``set_con_spec_minor`` overrides the minor before ``build``. The writer MUST NOT invent or replace ``con_spec_minor`` or ``con_spec_patch`` (D15).

The media type ``chemical/x-con`` is informative, as is ``text/plain; charset=utf-8``.
CON has no magic bytes. Identify a file by extension and by this header.

Reader compatibility
--------------------

Version 1 is the text of the pre-readcon eOn writer (``svn-Dec16_2020`` ``client/Matter.cpp:748``).
The eOn 2.17-3.4 column calls readcon.
Cells cite ``file:line`` at eOn v3.6.0, v3.4.0, and v2.17.10, ASE 3.29.0, and readcon f09b1af.

.. table::

    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | Feature        | eOn >= 3.5                                                                                                                                         | eOn 2.17-3.4                                                                                                                                          | ASE 3.29.0 ``ase/io/eon.py``                                                 | chemfiles                        | OVITO 3.16.1                                    | readcon f09b1af                                                                                                                   |
    +================+====================================================================================================================================================+=======================================================================================================================================================+==============================================================================+==================================+=================================================+===================================================================================================================================+
    | JSON line 2    | v3.6.0 ``client/ConFileIO.cpp:586`` ``read_all_frames``, ``:463`` ``frame_from_matter``.                                                           | v3.4.0 ``client/ConFileIO.cpp:573``. v2.17.10 ``client/ConFileIO.cpp:294``.                                                                           | ``:72`` stores line 2 as text. ``:255`` writes ``preBox_header_2``.          | No CON reader (``src/formats``). | No CON reader. The input list has no CON entry. | ``src/parser.rs:458``.                                                                                                            |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | Masks 1-6      | v3.6.0 ``client/ConFileIO.cpp:386`` ``getFixedMask``, ``:714`` ``setFixedMask``.                                                                   | v3.4.0 ``client/ConFileIO.cpp:386`` and ``:701``. v2.17.10 ``:144-146`` writes one boolean on all axes and ``:384-385`` collapses any fixed bit to 1. | ``:139`` ``bool(int(tokens[3]))``. Writer emits 0 or 1.                      | No CON reader.                   | No CON reader.                                  | ``src/types.rs:644``. Outside 0-7 is not ``InvalidFixedFlag`` unless ``validate`` is true.                                        |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | Sections       | v3.6.0 ``client/ConFileIO.cpp:422-424`` leaves forces off.                                                                                         | v3.4.0 ``client/ConFileIO.cpp:422``. v2.17.10 has velocities only (``:174``).                                                                         | ``:177`` reads the next line as a header, so a section blank does not parse. | No CON reader.                   | No CON reader.                                  | ``src/parser.rs:1100``.                                                                                                           |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | 4-column lines | v3.6.0 ``client/ConFileIO.cpp:586`` via readcon.                                                                                                   | v3.4.0 ``client/ConFileIO.cpp:573``. v2.17.10 ``client/ConFileIO.cpp:294``.                                                                           | ``:138-139`` reads xyz and column 4, not column 5.                           | No CON reader.                   | No CON reader.                                  | ``src/parser.rs:665`` defaults column 5 to the 0-based index.                                                                     |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | Gzip           | v3.6.0 ``client/ConFileIO.cpp:577-578`` one gzip member.                                                                                           | v3.4.0 ``client/ConFileIO.cpp:564-565``. v2.17.10 ``:118`` ``compression_from_extension``.                                                            | ``:177`` reads text lines. No gzip decoder in this module.                   | No CON reader.                   | No CON reader.                                  | ``src/compression.rs:85`` ``GzDecoder`` reads the first member.                                                                   |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+
    | Velocities     | v3.6.0 ``client/ConFileIO.cpp:43`` precision 6, ``:444`` ``set_atom_velocity``, ``include/eon/ParametersOptions.h:26`` ``timeUnit`` 10.1805055 fs. | v3.4.0 ``client/ConFileIO.cpp:43`` and ``:431``, same ``ParametersOptions.h:26``. v2.17.10 ``client/ConFileIO.cpp:174``.                              | ``:303`` writes xyz, flag, and id. No velocity block.                        | No CON reader.                   | No CON reader.                                  | ``src/parser.rs:1117`` parses the numbers and does not apply ``units.time``. ``src/writer.rs:269`` can still insert ``time: fs``. |
    +----------------+----------------------------------------------------------------------------------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------------------------------------------------------------+----------------------------------+-------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------------------+

Examples
--------

Version 3.1
~~~~~~~~~~~

Two types, ``lattice_vectors``, ``pbc``, masks 0, 3, and 7, ids out of order, velocities with ``units.time``, and forces.
Ids 2, 0, 1 appear in that file order. Mask 3 is x and y. Mask 7 is all three.

::
    :name: v31-frame

    Generated by readcon v3.1 example
    {"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"(amu*angstrom^2/eV)^0.5"},"pbc":[true,true,false],"lattice_vectors":[[10.0,0.0,0.0],[0.0,10.0,0.0],[0.0,0.0,20.0]],"sections":["velocities","forces"]}
    10.0 10.0 20.0
    90.0 90.0 90.0
    0 0
    0 0 0
    2
    2 1
    195.084 1.00794
    Pt
    Coordinates of Component 1
    0.0 0.0 0.0 0 2
    5.0 5.0 0.0 3 0
    H
    Coordinates of Component 2
    5.0 5.0 10.0 7 1

    Pt
    Velocities of Component 1
    0.01 0.0 0.0 0 2
    0.0 0.02 0.0 3 0
    H
    Velocities of Component 2
    0.0 0.0 0.03 7 1

    Pt
    Forces of Component 1
    0.1 0.0 0.0 0 2
    0.0 -0.2 0.0 3 0
    H
    Forces of Component 2
    0.0 0.0 0.3 7 1

The same frame as a version 1 reader sees it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Spec 1 cannot store masks 3 or 7, JSON, or sections.
The projection below uses column 4 values 0 and 1 only.
Mask 3 and mask 7 both become 1, meaning all-fixed.
Velocities and forces are omitted because a version 1 reader that treats a blank line as the next header cannot return them.
ASE ``read_eon`` is that reader.

::
    :name: v31-as-v1

    Generated by readcon v3.1 example
    0.0000 TIME
    10.0 10.0 20.0
    90.0 90.0 90.0
    0 0
    0 0 0
    2
    2 1
    195.084 1.00794
    Pt
    Coordinates of Component 1
    0.0 0.0 0.0 0 2
    5.0 5.0 0.0 1 0
    H
    Coordinates of Component 2
    5.0 5.0 10.0 1 1

Zero atoms
~~~~~~~~~~

Nine header lines. Line 7 is 0. Lines 8 and 9 are empty.
No coordinate block and no section follow.

::
    :name: zero-atom-frame

    zero-atom frame
    {"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}
    10.0 10.0 10.0
    90.0 90.0 90.0


    0

.. _tokens:

Token grammar
-------------

CON-token.1 \:\: MUST
    Integer tokens MUST match one or more ASCII digits, with no sign and no decimal point.

CON-token.2 \:\: MUST
    Float tokens MUST be finite decimals. A leading sign, a leading dot, and an exponent are allowed. Non-finite spellings are ``CON-num.1``, not floats.

CON-token.3 \:\: MUST
    The separators inside a line MUST be spaces or tabs.

CON-token.4 \:\: MUST
    The included PEG is informative surface syntax. A reader MUST follow this document when the PEG allows a token these clauses reject. The normative lexical grammar is the ABNF appendix.

.. _lexical-grammar:

Appendix: lexical grammar
-------------------------

This appendix is the normative lexical grammar of the text after decompression, in ABNF :cite:t:`rfc5234` with case-sensitive strings :cite:t:`rfc7405`.
A numbered clause decides acceptance where this grammar and a clause both speak.
The included PEG is informative. Its semantic actions are the numbered clauses.
Acceptance does not depend on the byte length of a file these clauses accept.

CON-lex.1 \:\: MUST
    This appendix MUST be the normative lexical grammar of the text after decompression. A numbered clause decides acceptance where this grammar and a clause both speak. The included PEG is informative, and the semantic actions are the numbered clauses.

::

    HTAB           = %x09
    SP             = %x20
    CR             = %x0D
    LF             = %x0A
    eol            = LF / (CR LF)
    WSP            = SP / HTAB
    blank-char     = <a character of Unicode White_Space>
    blank-line     = *blank-char eol
    line-char      = <a Unicode scalar value other than CR or LF>
    text-line      = *line-char eol
    digit          = %x30-39
    sign           = "+" / "-"
    integer        = 1*digit
    float          = [sign] ( 1*digit ["." *digit] / "." 1*digit ) [ ( "e" / "E" ) [sign] 1*digit ]
    float-line     = float 2*( 1*WSP float ) *WSP eol
    count-line     = [integer *(1*WSP integer)] *WSP eol
    json-line      = <one JSON object and nothing else> eol
    v1-line        = text-line
    header         = text-line (json-line / v1-line) float-line float-line text-line text-line count-line count-line count-line
    coord-row      = float 1*WSP float 1*WSP float 1*WSP integer [1*WSP integer] *WSP eol
    label-line     = text-line
    symbol-line    = text-line
    coord-block    = symbol-line label-line *coord-row
    section-block  = blank-line symbol-line label-line *coord-row
    frame          = header *coord-block *section-block
    tail           = [blank-line] *(*WSP eol)
    file           = *frame [tail]

    unit-power     = "^" ["-"] ( 1*digit ["." *digit] / "." 1*digit )
    unit-atom      = %s"m" / %s"meter" / %s"metre" / %s"angstrom" / %s"Angstrom" / %s"A" / %s"a" / %s"å" / %s"Å" / %s"nm" / %s"nanometer" / %s"bohr" / %s"a0" / %s"J" / %s"j" / %s"joule" / %s"eV" / %s"ev" / %s"meV" / %s"mev" / %s"MeV" / %s"hartree" / %s"ha" / %s"kcal" / %s"kJ" / %s"kj" / %s"kg" / %s"kilogram" / %s"u" / %s"amu" / %s"AMU" / %s"dalton" / %s"da" / %s"s" / %s"second" / %s"fs" / %s"femtosecond" / %s"ps" / %s"picosecond" / %s"ns" / %s"nanosecond" / %s"mol"
    unit-term      = unit-atom [unit-power] / "(" unit-expr ")" [unit-power]
    unit-expr      = unit-term *( ( "*" / "/" ) unit-term )

Section blocks follow the coordinate blocks in the order of the ``sections`` array.
A JSON object does not repeat a name.
``MeV`` and ``meV`` are different unit names.

Appendix: PEG
-------------

The surface grammar is ``grammar/readcon.pest``.
A bare ``src`` include leaves the language empty and does not export, so this include names ``text``.

.. code:: text

    // CON / convel surface syntax (PEG / Pest).
    //
    // Aligns with docs/orgmode/spec.org (CON v3.1). This grammar defines the
    // *syntactic* shape of one or more concatenated frames. Semantic rules
    // (atom counts matching header N_i, fixed-mask legal sets, validate=true
    // geometry, section_arity skips) are enforced by src/parser.rs.
    // Where this PEG and the specification disagree, the specification wins
    // (CON-token.4).
    //
    // Hot-path I/O does not depend on Pest. gzip and zstd envelopes are not
    // grammar (CON-compress): readers detect them by magic bytes.
    //
    // Section row arities (spec sections):
    //   vector: velocities, forces, magmoms, displacements, spreads
    //           -> v0 v1 v2 fixed atom_id
    //   scalar: energies, charges, spins -> value fixed atom_id
    //   unknown: a newer minor may skip a block whose data rows have the
    //           token count declared by section_arity (semantic; the PEG
    //           accepts the generic block shape).

    /// One or more frames. No leading BOM. Trailing whitespace-only lines
    /// after the last frame are ignored (CON-file.6, CON-frame.1).
    file = { SOI ~ !bom ~ frame+ ~ (ws* ~ NL)* ~ EOI }

    bom = { "\u{FEFF}" }

    /// Header lines 1-6. The type count chooses a zero-atom tail or typed body.
    header_open = {
        free_line ~ NL
        ~ metadata_line ~ NL
        ~ float3_line
        ~ float3_line
        ~ free_line ~ NL
        ~ free_line ~ NL
    }

    /// One or more frames. A type count of 0 has no coordinate block (CON-count.1).
    frame = { header_open ~ (zero_atom | typed_body) }

    /// Free-form line. Does not consume the trailing newline.
    free_line = { (!NL ~ ANY)* }

    /// Line 2 is one JSON object when it starts with `{`, otherwise legacy text.
    metadata_line = { ws* ~ json_object | legacy_metadata }
    legacy_metadata = { ws* ~ !"{" ~ free_line }

    json_object = {
        "{" ~ ws*
        ~ (json_pair ~ (ws* ~ "," ~ ws* ~ json_pair)*)?
        ~ ws* ~ "}" ~ ws*
    }
    json_pair = { json_string ~ ws* ~ ":" ~ ws* ~ json_value }
    json_value = {
        json_string | json_number | json_object | json_array | "true" | "false" | "null"
    }
    json_array = {
        "[" ~ ws*
        ~ (json_value ~ (ws* ~ "," ~ ws* ~ json_value)*)?
        ~ ws* ~ "]"
    }
    json_string = @{ "\"" ~ json_char* ~ "\"" }
    json_char = _{
        "\\\"" | "\\\\" | "\\/" | "\\b" | "\\f" | "\\n" | "\\r" | "\\t"
        | "\\u" ~ ASCII_HEX_DIGIT{4}
        | (!("\"" | "\\") ~ ANY)
    }
    json_number = @{
        "-"? ~ ASCII_DIGIT+
        ~ ("." ~ ASCII_DIGIT+)?
        ~ (("e" | "E") ~ ("+" | "-")? ~ ASCII_DIGIT+)?
    }

    float3_line = { ws* ~ float ~ ws+ ~ float ~ ws+ ~ float ~ ws* ~ NL }

    /// Type count >= 1 (CON-count.3). A type count of 0 uses zero_atom.
    count_line = { ws* ~ positive_integer ~ ws* ~ NL }

    count_list_line = { ws* ~ positive_integer ~ (ws+ ~ positive_integer)* ~ ws* ~ NL }

    float_list_line = { ws* ~ float ~ (ws+ ~ float)* ~ ws* ~ NL }

    /// "0", "00", ... with no other token. The newline may be absent at EOI.
    zero_integer = @{ "0"+ }
    zero_count_line = { ws* ~ zero_integer ~ ws* ~ (NL | EOI) }
    blank_line = { ws* ~ NL }

    /// Whitespace lines 8 and 9, shortened only at end of file (CON-count.4).
    zero_atom = {
        zero_count_line ~
        (
            blank_line ~ (blank_line | EOI)
            | EOI
        )
    }

    typed_body = {
        count_line
        ~ count_list_line
        ~ float_list_line
        ~ type_block+
        ~ section*
    }

    /// One chemical-type block: symbol, "Coordinates of Component k", atom lines.
    type_block = {
        symbol_line ~ NL
        ~ coord_label ~ NL
        ~ vector_atom_line ~ (NL ~ vector_atom_line)*
        ~ NL?
    }

    symbol_line = { ws* ~ symbol ~ ws* }

    /// Element / type symbol (letters, optional trailing digits/underscore).
    symbol = @{ ASCII_ALPHA ~ (ASCII_ALPHANUMERIC | "_")* }

    /// Labels are case-insensitive. Runs of spaces are `ws+` (CON-file.4).
    coord_label = {
        ws* ~ ^"Coordinates of Component" ~ ws+ ~ positive_integer ~ ws*
    }

    /// Coordinate row: v0 v1 v2 fixed_mask [atom_id]. Column 4 and 5 are
    /// unsigned integer tokens (no sign, no decimal point).
    vector_atom_line = {
        ws* ~ float ~ ws+ ~ float ~ ws+ ~ float
        ~ ws+ ~ integer
        ~ (ws+ ~ integer)?
        ~ ws*
    }

    /// Scalar section row: value fixed_mask atom_id. Identity columns required.
    scalar_atom_line = {
        ws* ~ float
        ~ ws+ ~ integer
        ~ ws+ ~ integer
        ~ ws*
    }

    /// Backward-compatible alias used by tests and older notes.
    atom_line = { vector_atom_line }

    /// Optional section: one blank line, then homogeneous type blocks.
    section = {
        ws* ~ NL
        ~ (section_type_block_vector+ | section_type_block_scalar+ | generic_type_block+)
    }

    section_type_block_vector = {
        symbol_line ~ NL
        ~ section_label_vector ~ NL
        ~ vector_section_line ~ (NL ~ vector_section_line)*
        ~ NL?
    }

    section_type_block_scalar = {
        symbol_line ~ NL
        ~ section_label_scalar ~ NL
        ~ scalar_atom_line ~ (NL ~ scalar_atom_line)*
        ~ NL?
    }

    /// Unknown section shape. The hand parser skips it only for a newer minor
    /// whose `section_arity` names the exact token count (CON-section.8).
    generic_type_block = {
        symbol_line ~ NL
        ~ generic_label ~ NL
        ~ token_line ~ (NL ~ token_line)*
        ~ NL?
    }

    generic_label = { ws* ~ symbol ~ (ws+ ~ (symbol | positive_integer))* ~ ws* }

    token_line = { ws* ~ (float | integer) ~ (ws+ ~ (float | integer))* ~ ws* }

    /// Vector section rows require the flag and the id (exact five tokens).
    vector_section_line = {
        ws* ~ float ~ ws+ ~ float ~ ws+ ~ float
        ~ ws+ ~ integer
        ~ ws+ ~ integer
        ~ ws*
    }

    section_kind_vector = { ^"Velocities" | ^"Forces" | ^"Magmoms" | ^"Displacements" | ^"Spreads" }
    section_kind_scalar = { ^"Energies" | ^"Charges" | ^"Spins" }

    /// Union of all section kinds (docs / tests).
    section_kind = { section_kind_vector | section_kind_scalar }

    section_label_vector = {
        ws* ~ section_kind_vector ~ ws+ ~ ^"of Component" ~ ws+ ~ positive_integer ~ ws*
    }

    section_label_scalar = {
        ws* ~ section_kind_scalar ~ ws+ ~ ^"of Component" ~ ws+ ~ positive_integer ~ ws*
    }

    /// Finite decimal, or a non-finite spelling the semantic layer rejects
    /// as NonFiniteValue (CON-num.1, CON-token.2). A leading sign, a leading
    /// dot, and an exponent are allowed.
    float = _{ finite_float | non_finite }

    finite_float = @{
        ("+" | "-")?
        ~ (ASCII_DIGIT+ ~ ("." ~ ASCII_DIGIT*)? | "." ~ ASCII_DIGIT+)
        ~ (("e" | "E") ~ ("+" | "-")? ~ ASCII_DIGIT+)?
    }

    non_finite = @{
        ("+" | "-")? ~ (^"infinity" | ^"nan" | ^"inf")
    }

    /// Unsigned digit token. No sign and no decimal point (CON-token.1).
    integer = @{ ASCII_DIGIT+ }

    positive_integer = @{ ("1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9") ~ ASCII_DIGIT* }

    ws = _{ " " | "\t" }
    NL = _{ "\r\n" | "\n" }

.. _informative-annex:

Informative annex
-----------------

This annex is not normative. It records names used by one implementation and keys one importer writes. A conforming reader follows the numbered clauses, not this annex.

One C ABI returns an IEEE NaN from a getter when a number is absent. ``rkr_frame_energy`` does this when the frame has no ``energy`` key. That NaN is an in-memory sentinel. It is not a CON number, and ``CON-num.4`` forbids writing it to a file.

The default numeric text of a conforming writer is the mode that ``CON-num.6`` requires: parsing the written token returns the same binary64 value. A fixed-decimal mode is ``CON-num.7``. The C binding's writer for the default mode is ``create_writer_from_path_round_trip_c``.

The error table names the class a reader reports when a row does not have the number of fields that row requires, which is the failure ``CON-section.13`` and ``CON-num.9`` require.

The keys ``chemfiles_atom_names``, ``chemfiles_atom_types``, and ``chemfiles_atom_properties`` are not reserved. One importer stores display names, atomic types, and per-atom properties under those keys, in that importer's atom order. A reader preserves them as unknown keys under ``CON-line2.8``. A later revision that reserves an extension namespace does so by a minor that adds keys (``CON-status.6``), and does not treat these three spellings as part of the core language.

.. _references:

References
----------

The metadata schema is ``schema/con-metadata.schema.json``.
Unknown keys validate. ``con_spec_minor`` and ``section_arity`` are reserved.

.. bibliography::
   :style: alpha
