"""Distinct CON frames for benchmark inputs.

A file of identical copies hits the repeated-frame shortcut
(``repeated_span``, ``tiled_frame_count``, ``parse_repeated_copies``), so a
timed read measures that shortcut. ``distinct_frames`` keeps the atom count
and the species lines and nudges each frame's coordinates with a fixed seed.
``require_distinct_frames`` refuses a run of byte-identical frames.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def _coord_parts(line: str) -> list[str] | None:
    parts = line.split()
    if len(parts) < 5:
        return None
    try:
        float(parts[0])
        float(parts[1])
        float(parts[2])
        int(parts[3])
        int(parts[4])
    except ValueError:
        return None
    return parts


def perturb_frame(text: str, frame: int, seed: int = 1) -> str:
    """One copy of ``text`` whose coordinates depend on ``frame`` and ``seed``."""
    atom = 0
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        parts = _coord_parts(body)
        if parts is None:
            out.append(line)
            continue
        nudge = ((seed + (frame + 1) * 1_000_003 + atom * 17) % 997) * 1e-6
        parts[0] = f"{float(parts[0]) + nudge:.8f}"
        out.append(" ".join(parts) + newline)
        atom += 1
    return "".join(out)


def distinct_frame_list(text: str, n: int, seed: int = 1) -> list[str]:
    """``n`` frames. Each differs in its coordinate bytes. Species lines do not."""
    if n < 1:
        raise ValueError("n")
    one = text if text.endswith("\n") else text + "\n"
    return [perturb_frame(one, frame, seed) for frame in range(n)]


def distinct_frames(text: str, n: int, seed: int = 1) -> str:
    return "".join(distinct_frame_list(text, n, seed))


def _species_lines(frame: str) -> list[str]:
    found = []
    for line in frame.splitlines():
        parts = line.split()
        if len(parts) == 1 and not parts[0].replace(".", "", 1).isdigit():
            found.append(parts[0])
    return found


def _coord_count(frame: str) -> int:
    return sum(_coord_parts(line) is not None for line in frame.splitlines())


def _refuse_copies(hashes: list[str]) -> list[str]:
    if len(hashes) != len(set(hashes)):
        raise SystemExit(
            "byte-identical frames; a repeated frame measures a copy, not a parse"
        )
    return hashes


def _require_coord_frames(positions: np.ndarray) -> list[str]:
    """SHA-256 of each frame's coordinates.

    Two frames with the same hash are the same bytes. The repeated-frame
    reader would time a copy of the first.
    """
    coords = np.ascontiguousarray(positions, dtype="<f8")
    if coords.ndim != 3 or coords.shape[2] != 3:
        raise SystemExit("positions are not frames x atoms x 3")
    hashes = [
        hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest()
        for frame in coords
    ]
    return _refuse_copies(hashes)


def _require_text_frames(frames: list[str]) -> list[str]:
    if len(frames) < 1:
        raise SystemExit("positions are not frames x atoms x 3")
    counts = {_coord_count(frame) for frame in frames}
    species = {tuple(_species_lines(frame)) for frame in frames}
    if len(counts) != 1 or len(species) != 1:
        raise SystemExit("frames do not share an atom count and species")
    if counts == {0}:
        raise SystemExit("frames have no coordinate rows")
    hashes = [hashlib.sha256(frame.encode("utf-8")).hexdigest() for frame in frames]
    return _refuse_copies(hashes)


def require_distinct_frames(frames: np.ndarray | list[str]) -> list[str]:
    """SHA-256 of each frame. Identical frames are refused.

    ``frames`` is a coordinate array of shape ``(n_frames, n_atoms, 3)`` or a
    list of CON texts. One frame is allowed. Two copies of one frame are not.
    """
    if isinstance(frames, (list, tuple)):
        return _require_text_frames([str(frame) for frame in frames])
    return _require_coord_frames(frames)


def write_distinct_copies(path: Path, one: str | bytes, n: int, seed: int = 1) -> None:
    """Write ``n`` distinct copies of one CON frame. An older tiled file is replaced."""
    text = one.decode("utf-8") if isinstance(one, bytes) else one
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for frame in distinct_frame_list(text, n, seed):
            handle.write(frame)
