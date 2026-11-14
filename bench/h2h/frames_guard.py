"""Distinct CON frames for benchmark inputs.

A file of identical copies hits the repeated-frame shortcut
(``repeated_span``, ``tiled_frame_count``, ``parse_repeated_copies``), so a
timed read measures that shortcut. ``distinct_frames`` keeps the atom count
and the species lines and nudges each frame's coordinates with a fixed seed.
``require_distinct_frames`` refuses a run of byte-identical frames.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

_MASK64 = (1 << 64) - 1
_FLOAT = re.compile(r"[-+]?\d+\.\d+")


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


def _splitmix64(value: int) -> int:
    z = value & _MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return (z ^ (z >> 31)) & _MASK64


def _pcg32(state: int) -> tuple[int, int]:
    """PCG-XSH-RR. One stream per frame, not a 997-step linear residue."""
    state = (state * 6364136223846793005 + 1442695040888963407) & _MASK64
    xorshifted = (((state >> 18) ^ state) >> 27) & 0xFFFFFFFF
    rot = state >> 59
    bits = ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & 0xFFFFFFFF
    return state, bits


def _frame_state(frame: int, seed: int) -> int:
    mixed = (seed & _MASK64) ^ (((frame + 1) * 0x9E3779B97F4A7C15) & _MASK64) ^ 0xC0FFEE
    return _splitmix64(mixed)


def _bump_token(token: str, draw: int) -> str:
    """Change the last digit. The field width and the other digits stay."""
    chars = list(token)
    delta = (draw % 9) + 1
    for index in range(len(chars) - 1, -1, -1):
        if chars[index].isdigit():
            chars[index] = str((int(chars[index]) + delta) % 10)
            return "".join(chars)
    return token


def perturb_frame(text: str, frame: int, seed: int = 1) -> str:
    """One copy of ``text`` whose coordinates depend on ``frame`` and ``seed``.

    The printed field widths stay those of ``text``, so a 16771-byte cuh2
    frame is still 16771 bytes. The nudge is a per-frame PCG32 stream.
    """
    state = _frame_state(frame, seed)
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        body = line[: -len(newline)] if newline else line
        if _coord_parts(body) is None:
            out.append(line)
            continue
        pieces: list[str] = []
        last = 0
        bumped = 0
        for match in _FLOAT.finditer(body):
            if bumped >= 3:
                break
            pieces.append(body[last : match.start()])
            state, draw = _pcg32(state)
            pieces.append(_bump_token(match.group(0), draw))
            last = match.end()
            bumped += 1
        pieces.append(body[last:])
        out.append("".join(pieces) + newline)
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
    frames = distinct_frame_list(text, n, seed)
    if n > 1:
        require_distinct_frames(frames)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(frame)
