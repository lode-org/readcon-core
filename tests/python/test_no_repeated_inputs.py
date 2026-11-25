"""Timing drivers must not build a file by copying one frame."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("bench", "benches", "benchmarks", "examples", "paper")
_COPIED = r"(?:text|one|blob|fixture|FRAME|content|data)"
_LISTED = r"(?:text|one|blob|fixture|FRAME|raw|arr|frame|content|data)"
_NAMED = r"(?:arr|pos0|positions|frame|text|one|raw|content|data)"
PATTERNS = (
    re.compile(r"\.read_bytes\(\)\s*\*"),
    re.compile(r"\.read_text\(\)\s*\*"),
    re.compile(r"\bread_text\s*\([^)]*\)\s*\*\s*\w+"),
    re.compile(rf"\b{_COPIED}\s*\*\s*\w+"),
    re.compile(rf"\[{_LISTED}\]\s*\*\s*\w+"),
    re.compile(r"\bnp\.tile\s*\("),
    re.compile(rf"\bnp\.repeat\s*\(\s*{_NAMED}\s*,"),
    re.compile(rf"""\.join\(\s*\[{_LISTED}\]\s*\*\s*\w+"""),
    re.compile(r"""(?:''|"")\.join\(\s*\w+\s+for\s+_\s+in\s+range\s*\("""),
    re.compile(rf"\[\s*(?:{_LISTED}|t)\s+for\s+_\s+in\s+range\s*\("),
    re.compile(r"\bitertools\.cycle\s*\("),
    re.compile(r"\.writelines\s*\(\s*\[[^\]]*\]\s*\*"),
    re.compile(r"vec!\s*\[[^\]]*\b(?:x|frame)\.clone\(\)"),
    re.compile(r"vec!\s*\[\s*&frame\s*;"),
    re.compile(r"::repeat\s*\("),
    re.compile(r"\[\s*\w+\s*;\s*\w+\s*\]\s*\.(?:concat|join)\s*\("),
    re.compile(
        rf"vec!\s*\[\s*&?(?:{_LISTED}|x|t)(?:\.(?:clone|to_vec|to_owned|to_string)\(\))?\s*;"
    ),
    re.compile(r"(?<![\w.])repeat(?:_n|_with)?\s*\("),
    re.compile(r"(?<![\w.])cycle\s*\("),
    re.compile(rf"\b\w+\s*\*\s*{_COPIED}\b(?!\s*[\[(.])"),
    re.compile(
        rf"[\[(]\s*(?:{_LISTED}|t)(?:\.(?:copy|clone)\(\))?\s+for\s+(?!(?:{_LISTED}|t)\b)\w+\s+in\s+range\s*\("
    ),
    re.compile(
        r"\b(?:copy\.deepcopy\(\s*\w+\s*\)|\w+\.copy\(\))\s+for\s+_\w*\s+in\s+range\s*\("
    ),
    re.compile(rf"\bnp\.repeat\s*\(\s*{_NAMED}\s*\[[^\]]*\]\s*,"),
    re.compile(r"\bnp\.broadcast_to\s*\("),
    re.compile(r"\brepeat_text\b"),
    re.compile(r"(?<!p)\.repeat\("),
)
# Error probes and the writer metadata-cache clone. Exact path and line.
ALLOW = {
    ("benches/iterator_bench.rs", 214),
    # The formatter is timed on one frame. It does not parse a tiled file.
    ("examples/format_profile.rs", 40),
    ("examples/format_profile.rs", 48),
    # Each copy takes the positions of its own frame on the next line.
    ("benches/h5md_vs_con.py", 164),
    # A checksum of the cell over the frames. It writes no input.
    ("paper/cpc/bench/make_payloads.py", 447),
    # A 5x5x5 supercell, then Velocity Verlet. It does not tile one frame.
    ("paper/cpc/bench-like-for-like/make_al_md.py", 50),
}
REFEREE_REPEAT_MARKERS = (
    'TINY.read_text(encoding="utf-8") * 2',
    "TINY.read_bytes() * 2",
    "text * 300",
    "text * copies",
)


def repeated_hits(text: str) -> list[str]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in PATTERNS):
            found.append(f"{number}: {line.strip()}")
    return found


def test_np_tile_is_a_repeated_input() -> None:
    assert repeated_hits("positions = np.tile(arr, (8, 1))")


def test_a_list_repeat_is_a_repeated_input() -> None:
    assert repeated_hits("frames = [one]*8")


def test_read_text_times_n_is_a_repeated_input() -> None:
    assert repeated_hits("body = read_text(path)*8")


def test_bytes_join_of_copies_is_a_repeated_input() -> None:
    assert repeated_hits('blob = b"".join([raw]*8)')


def test_content_times_eight_is_a_repeated_input() -> None:
    assert repeated_hits("body = content*8")


def test_data_times_n_frames_is_a_repeated_input() -> None:
    assert repeated_hits("body = data*n_frames")


def test_np_repeat_along_frames_is_a_repeated_input() -> None:
    assert repeated_hits("positions = np.repeat(arr,8,axis=0)")
    assert not repeated_hits(
        "mass = np.repeat(np.array(universe.atoms.masses), len(frames), axis=0)"
    )


def test_a_comprehension_over_range_is_a_repeated_input() -> None:
    assert repeated_hits("frames = [text for _ in range(n)]")


def test_join_of_a_comprehension_is_a_repeated_input() -> None:
    assert repeated_hits("blob = ''.join(text for _ in range(n))")


def test_itertools_cycle_is_a_repeated_input() -> None:
    assert repeated_hits("stream = itertools.cycle(frames)")


def test_writelines_of_copies_is_a_repeated_input() -> None:
    assert repeated_hits("handle.writelines([t]*8)")


def test_vec_macro_of_clones_is_a_repeated_input() -> None:
    assert repeated_hits("let frames = vec![x.clone();8];")


def test_iter_repeat_take_is_a_repeated_input() -> None:
    assert repeated_hits("let frames = iter::repeat(frame).take(8);")


def test_array_concat_is_a_repeated_input() -> None:
    assert repeated_hits("let frames = [t;8].concat();")


def test_vec_macro_of_one_value_is_a_repeated_input() -> None:
    assert repeated_hits("let v = vec![x;8];")
    assert repeated_hits("let v = vec![text.clone(); n];")
    assert repeated_hits("let v = vec![one; n_frames];")
    assert not repeated_hits("let v = vec![0u8; n];")


def test_repeat_n_and_bare_repeat_are_repeated_inputs() -> None:
    assert repeated_hits("let v = std::iter::repeat_n(frame, 8).collect();")
    assert repeated_hits("let v = repeat(frame).take(8);")
    assert not repeated_hits("let v = frames.iter().take(8);")


def test_bare_cycle_is_a_repeated_input() -> None:
    assert repeated_hits("stream = cycle(frames)")


def test_count_times_copy_is_a_repeated_input() -> None:
    assert repeated_hits("body = 8*text")
    assert repeated_hits("body = n_frames * content")


def test_comprehension_with_any_unused_name_is_a_repeated_input() -> None:
    assert repeated_hits("frames = [frame for i in range(n)]")
    assert repeated_hits("frames = [text for _i in range(n)]")
    assert repeated_hits("fh.writelines(text for _ in range(8))")
    assert repeated_hits("frames = [copy.deepcopy(atoms) for _ in range(8)]")
    assert not repeated_hits("frames = [perturb(text, i) for i in range(n)]")


def test_np_repeat_of_an_indexed_frame_is_a_repeated_input() -> None:
    assert repeated_hits("pos = np.repeat(pos0[None], 8, axis=0)")
    assert repeated_hits("pos = np.broadcast_to(arr, (8,) + arr.shape)")


def test_array_join_is_a_repeated_input() -> None:
    assert repeated_hits('let s = [t;8].join("");')


def test_drivers_do_not_tile_one_frame() -> None:
    found = []
    for root_name in ROOTS:
        base = ROOT / root_name
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".rs"} or not path.is_file():
                continue
            # paper/cpc/.pixi is the gitignored pixi environment.
            if any(part.startswith(".") for part in path.relative_to(base).parts):
                continue
            rel = path.relative_to(ROOT).as_posix()
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if (rel, number) in ALLOW:
                    continue
                if rel == "paper/cpc/scripts/referee_probes.py" and any(
                    marker in line for marker in REFEREE_REPEAT_MARKERS
                ):
                    continue
                if repeated_hits(line):
                    found.append(f"{rel}:{number}: {line.strip()}")
    assert not found, "repeated timing input:\n" + "\n".join(found)
