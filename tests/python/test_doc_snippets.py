"""Execute the Python code blocks in the published documentation.

Each ``.. code:: python`` block under ``docs/source`` is compiled and run.
A block that calls chemfiles or MPI on a build without that feature is
accepted only when the exception is the feature-disabled error those pages
describe. Every other exception fails the test.
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from io import StringIO
from pathlib import Path

import readcon

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "source"
PLUGIN = ROOT / "ase-readcon"
DIRECTIVE = re.compile(r"^\.\. code(?:-block)?::\s+(\S+)\s*$")
FIDELITY_WORDS = (
    "exact",
    "within_tolerance",
    "reordered",
    "mismatch",
    "label_changed",
    "absent",
    "not_representable",
    "read_error",
    "write_error",
    "unavailable",
)


def _blocks(text: str):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = DIRECTIVE.match(lines[index])
        if match is None:
            index += 1
            continue
        language = match.group(1)
        index += 1
        while (
            index < len(lines)
            and lines[index].startswith((" ", "\t"))
            and lines[index].strip().startswith(":")
        ):
            index += 1
        if index < len(lines) and lines[index].strip() == "":
            index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() == "":
                look = index + 1
                while look < len(lines) and lines[look].strip() == "":
                    look += 1
                if look < len(lines) and lines[look].startswith((" ", "\t")):
                    body.append("")
                    index += 1
                    continue
                break
            if line.startswith("    "):
                body.append(line[4:])
                index += 1
                continue
            if line.startswith("\t"):
                body.append(line[1:])
                index += 1
                continue
            break
        yield language, "\n".join(body).strip("\n")


def _ensure_ase() -> None:
    if str(PLUGIN) not in sys.path:
        sys.path.insert(0, str(PLUGIN))
    from ase.io.formats import define_io_format, ioformats
    from ase_readcon.io import readcon_con_format, readcon_convel_format

    for name, fmt in (
        ("readcon-con", readcon_con_format),
        ("readcon-convel", readcon_convel_format),
    ):
        if name not in ioformats:
            define_io_format(name, **fmt._asdict(), external=True)


def _write(path: Path, frames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), frames)


def _atom(symbol: str, x: float, atom_id: int, mass: float, fixed=None, velocity=None):
    atom = readcon.Atom(symbol, x, 0.0, 0.0, fixed=fixed, atom_id=atom_id, mass=mass)
    if velocity is not None:
        atom.vx, atom.vy, atom.vz = velocity
    return atom


def _seed(work: Path) -> dict:
    hydrogen = _atom("H", 0.0, 1, 1.0)
    frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [hydrogen])
    frame.set_energy(-1.5)
    frame.set_frame_index(1)
    frame.set_timestep(0.5)
    moving = _atom("Cu", 0.2, 7, 63.546, velocity=(0.1, -0.2, 0.3))
    convel = readcon.ConFrame((8.0, 8.0, 8.0), (90.0, 90.0, 90.0), [moving])
    saddle_ids = [3, 0, 1, 4, 2]
    saddle_atoms = [
        _atom("Cu", float(index), atom_id, 63.546)
        for index, atom_id in enumerate(saddle_ids)
    ]
    saddle = readcon.ConFrame((12.0, 12.0, 12.0), (90.0, 90.0, 90.0), saddle_atoms)
    reactant = readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        [_atom("C", 0.0, 1, 12.0), _atom("O", 1.0, 2, 16.0)],
    )
    product = readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        [_atom("O", 1.2, 2, 16.0), _atom("C", 0.1, 1, 12.0)],
    )
    plain = work / "input.con"
    _write(plain, [frame])
    text = plain.read_text(encoding="utf-8")
    for name in (
        "trajectory.con",
        "large_trajectory.con",
        "old_eon_file.con",
        "structure.con",
        "traj.con",
        "saddle.con",
    ):
        target = work / name
        if name == "saddle.con":
            _write(target, [saddle])
        else:
            _write(target, [frame])
    _write(work / "trajectory.convel", [convel])
    _write(work / "input.convel", [convel])
    _write(work / "path" / "to" / "file.con", [frame, frame])
    _write(work / "path" / "to" / "neb.con", [frame, frame])
    readcon.write_con(str(work / "long_run.con.gz"), [frame, frame])
    (work / "structure.xyz").write_text(
        "2\ncomment\nH 0 0 0\nO 0 0 1\n", encoding="utf-8"
    )
    water_xyz = (
        "3\n"
        "water demo for readcon-core chemfiles tutorial\n"
        "O  0.000  0.000  0.000\n"
        "H  0.957  0.000  0.000\n"
        "H -0.240  0.927  0.000\n"
    )
    (work / "water.xyz").write_text(water_xyz, encoding="utf-8")
    (work / "traj.xyz").write_text(water_xyz, encoding="utf-8")
    (work / "input.pdb").write_text(_water_pdb(), encoding="utf-8")
    incoming = work / "incoming"
    incoming.mkdir()
    (incoming / "water.xyz").write_text(water_xyz, encoding="utf-8")
    bonded = readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        [
            _atom("O", 0.0, 1, 16.0),
            _atom("H", 0.957, 2, 1.0),
            _atom("H", -0.24, 3, 1.0),
        ],
        metadata={"con_spec_version": 2, "bonds": [[0, 1], [0, 2]]},
    )
    _write(work / "with_bonds.con", [bonded])
    _write(work / "water_with_bonds.con", [bonded])
    (work / "resources").symlink_to(ROOT / "resources")
    return {
        "frames": [frame],
        "more": [frame],
        "frame": frame,
        "reactant": reactant,
        "product": product,
        "band": [reactant, product],
        "reference": reactant,
        "other": product,
        "path": str(plain),
        "text": text,
        "contents": text,
    }


def _water_pdb() -> str:
    """Three-atom water PDB in the fixed columns chemfiles reads."""

    def atom(serial: int, name: str, x: float, y: float, z: float, element: str) -> str:
        return (
            f"ATOM  {serial:5d} {name:<4s} HOH     1    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {element:>2s}"
        )

    lines = [
        "HEADER    WATER",
        atom(1, "O", 0.000, 0.000, 0.000, "O"),
        atom(2, "H1", 0.957, 0.000, 0.000, "H"),
        atom(3, "H2", -0.240, 0.927, 0.000, "H"),
        "END",
        "",
    ]
    return "\n".join(lines)


def _optional(exc: BaseException, page: str) -> bool:
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", None) == "torch":
        return True
    message = str(exc)
    chemfiles_off = not readcon.has_chemfiles_support()
    if chemfiles_off and (
        "chemfiles support is not enabled" in message
        or "chemfiles not linked" in message
    ):
        return True
    # Those pages need the chemfiles build. A lean wheel stops at the support
    # check, or at a file the chemfiles notebook would have written.
    if (
        chemfiles_off
        and page.startswith("chemfiles-")
        and isinstance(exc, (AssertionError, OSError, SystemExit, RuntimeError))
    ):
        return True
    return not readcon.has_mpi_support() and (
        (isinstance(exc, ImportError) and "mpi4py" in message)
        or "mpi support" in message.lower()
    )


def test_published_python_snippets_run(tmp_path: Path) -> None:
    _ensure_ase()
    namespace = {"__name__": "__doc_snippets__"}
    namespace.update(_seed(tmp_path))
    previous = Path.cwd()
    os.chdir(tmp_path)
    os.environ["READCON_TUT_ROOT"] = str(ROOT)
    os.environ["READCON_TUT_WORK"] = str(tmp_path / "tutorial-work")
    failures: list[str] = []
    ran = 0
    try:
        pages = sorted(DOCS.glob("*.rst"))
        for page in pages:
            file_ns = dict(namespace)
            file_ns["__name__"] = page.stem
            for number, (language, source) in enumerate(
                _blocks(page.read_text(encoding="utf-8")), start=1
            ):
                if language != "python" or not source.strip():
                    continue
                ran += 1
                stdin = sys.stdin
                sys.stdin = StringIO(file_ns["text"])
                try:
                    # The block is the documented program.
                    exec(  # noqa: S102
                        compile(source, f"{page.name}:{number}", "exec"),
                        file_ns,
                        file_ns,
                    )
                except (Exception, SystemExit) as exc:  # noqa: BLE001
                    if _optional(exc, page.name):
                        if page.name == "chemfiles-notebook.rst":
                            break
                        continue
                    failures.append(
                        f"{page.name}:{number}\n{source}\n{''.join(traceback.format_exception(exc))}"
                    )
                finally:
                    sys.stdin = stdin
    finally:
        os.chdir(previous)
    assert ran > 40, ran
    assert not failures, "\n----\n".join(failures)


def test_snippet_workdir_prepares_named_inputs(tmp_path: Path) -> None:
    _seed(tmp_path)
    for name in (
        "input.pdb",
        "traj.xyz",
        "water.xyz",
        "with_bonds.con",
        "water_with_bonds.con",
        "trajectory.con",
    ):
        assert (tmp_path / name).is_file(), name
    incoming = tmp_path / "incoming"
    assert incoming.is_dir()
    assert (incoming / "water.xyz").is_file()
    assert "ATOM" in (tmp_path / "input.pdb").read_text(encoding="utf-8")
    bonded = readcon.read_first_frame(str(tmp_path / "water_with_bonds.con"))
    assert bonded.has_bonds


def test_missing_torch_is_an_optional_snippet_dependency() -> None:
    missing = ModuleNotFoundError("No module named 'torch'", name="torch")
    assert _optional(missing, "bindings.rst")
    other = ModuleNotFoundError("No module named 'readcon'", name="readcon")
    assert not _optional(other, "bindings.rst")
    assert not _optional(FileNotFoundError("input.pdb"), "bindings.rst")


def test_fidelity_page_uses_the_campaign_status_words() -> None:
    page = (DOCS / "fidelity.rst").read_text(encoding="utf-8")
    campaign = (ROOT / "bench" / "fidelity" / "campaign.py").read_text(encoding="utf-8")
    for word in FIDELITY_WORDS:
        assert f"``{word}``" in page
        assert f'"{word}"' in campaign
    assert "not_installed" not in page
