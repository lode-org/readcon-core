"""Write minor_token_probes.json and minor_token_probes.toml.

Each case is a one-atom v3 line 2 with velocities, once with
units.time "fs" (w) and once without it (n). The cases are the 52
line-2 shapes from the dupkey r2 review probes, kept verbatim in
dupkey_r2_probe_inputs.tsv, plus 000, a tab variant of the whitespace
case, and standalone false, null, string, array, and object minors.
Rust, C, RPC, and Python read the JSON file and Julia reads the TOML
file, which holds the same data.

Only the line-2 bodies are written by hand. Each expected result is
computed from the line itself:

- classify() parses the line as strict JSON and returns whether it is
  valid, a duplicate, or invalid, and the top-level con_spec_minor
  (None when absent; nested keys do not count).
- reader_minor() repeats the reader's minor detection, which is what
  its velocity check sees on the n line.

Error tags are "dup" (duplicate con_spec_minor key), "invalid"
(invalid metadata JSON), and "units" (velocities need units.time).
An accepted write is the exact line 2 the writer emits.

    python tests/fixtures/generate_minor_token_probes.py
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FMAX = (2**53 - 1) * 2**971
P1 = str(FMAX + 1)
P2 = str(FMAX + 2**970 - 1)
P3 = str(FMAX + 2**970)
U64_MAX = 2**64 - 1
NATURAL = "(amu*angstrom^2/eV)^0.5"
NATURAL_SYMBOL = "(u*Å^2/eV)^0.5"
U_T = '"units":{"length":"angstrom","energy":"eV","time":"fs"}'
U_N = '"units":{"length":"angstrom","energy":"eV"}'
KEY = "con_spec_minor"
JSON_UINT = re.compile(r"0|[1-9][0-9]*")

VALID, DUP, INVALID = "valid", "dup", "invalid"

# (name, line-2 body between con_spec_version and units)
CASES: list[tuple[str, str]] = [
    ("zero", '"con_spec_minor":0'),
    ("one", '"con_spec_minor":1'),
    ("two64", '"con_spec_minor":18446744073709551616'),
    ("fmax", '"con_spec_minor":%d' % FMAX),
    ("fmax+1", '"con_spec_minor":' + P1),
    ("fmax+2^970-1", '"con_spec_minor":' + P2),
    ("fmax+2^970", '"con_spec_minor":' + P3),
    ("fmax+2^971", '"con_spec_minor":%d' % (FMAX + 2**971)),
    ("neg1", '"con_spec_minor":-1'),
    ("negzero", '"con_spec_minor":-0'),
    ("neg_fmax+1", '"con_spec_minor":-' + P1),
    ("exp1e309", '"con_spec_minor":1e309'),
    ("exp1E400", '"con_spec_minor":1E400'),
    ("exp1e0", '"con_spec_minor":1e0'),
    ("exp1e20", '"con_spec_minor":1e20'),
    ("frac1.5", '"con_spec_minor":1.5'),
    ("frac1.0", '"con_spec_minor":1.0'),
    ("frac0.0", '"con_spec_minor":0.0'),
    ("fracP1.0", '"con_spec_minor":' + P1 + ".0"),
    ("lead00", '"con_spec_minor":00'),
    ("lead000", '"con_spec_minor":000'),
    ("lead01", '"con_spec_minor":01'),
    ("lead0P1", '"con_spec_minor":0' + P1),
    ("dup_0_0", '"con_spec_minor":0,"con_spec_minor":0'),
    ("dup_0_1", '"con_spec_minor":0,"con_spec_minor":1'),
    ("dup_1_0", '"con_spec_minor":1,"con_spec_minor":0'),
    ("dup_esc", r'"con_spec_minor":1,"\u0063on_spec_minor":2'),
    ("dup_P1_0", '"con_spec_minor":%s,"con_spec_minor":0' % P1),
    ("dup_0_P1", '"con_spec_minor":0,"con_spec_minor":%s' % P1),
    ("dup_P3_0", '"con_spec_minor":%s,"con_spec_minor":0' % P3),
    ("dup_0_P3", '"con_spec_minor":0,"con_spec_minor":%s' % P3),
    ("dup_neg0_0", '"con_spec_minor":-0,"con_spec_minor":0'),
    ("dup_ws", '"con_spec_minor" : 0 , "con_spec_minor" : 1'),
    ("nested_only1", '"x":{"con_spec_minor":1}'),
    ("nested2_top0", '"x":{"con_spec_minor":2},"con_spec_minor":0'),
    ("esc5f_dup", r'"con_spec\u005fminor":1,"con_spec_minor":2'),
    ("escslash_nodup", r'"con\/spec_minor":1,"con_spec_minor":2'),
    ("str_brace_dup", r'"s":"}\"{","con_spec_minor":0,"con_spec_minor":1'),
    ("str_bs_dup", r'"s":"x\\","con_spec_minor":0,"con_spec_minor":1'),
    ("str_bs_single", r'"s":"x\\","con_spec_minor":1'),
    ("objval_dup", r'"con_spec_minor":{"a":1},"con_spec_minor":1'),
    ("arrval_dup", r'"con_spec_minor":[1],"con_spec_minor":1'),
    ("strval_dup", r'"con_spec_minor":"1","con_spec_minor":1'),
    (
        "nested_deep_dup",
        r'"x":{"y":{"con_spec_minor":1}},"con_spec_minor":0,"z":[{"con_spec_minor":3}]',
    ),
    ("esc_single_P1", r'"\u0063on_spec_minor":' + P1),
    ("esc_single_1", r'"\u0063on_spec_minor":1'),
    ("esc_single_0", r'"\u0063on_spec_minor":0'),
    ("bad_esc_key_dup", r'"con_spec_minor\q":1,"con_spec_minor":2'),
    ("surrogate_key", r'"\ud83d\ude00":1,"con_spec_minor":1'),
    ("ws_space_P1", '"con_spec_minor"   :   ' + P1),
    ("ws_tab_P1", '"con_spec_minor"\t:\t' + P1),
    ("P1_then_other", '"con_spec_minor":%s,"x":1' % P1),
    ("null_dup", '"con_spec_minor":null,"con_spec_minor":1'),
    ("true_minor", '"con_spec_minor":true'),
    ("false_minor", '"con_spec_minor":false'),
    ("null_minor", '"con_spec_minor":null'),
    ("strval_minor", '"con_spec_minor":"1"'),
    ("arrval_minor", '"con_spec_minor":[1]'),
    ("objval_minor", '"con_spec_minor":{"a":1}'),
]


class _Pairs(list):
    """A JSON object as its decoded (key, value) pairs, repeats kept."""


class _Num(str):
    """A JSON number as its source text."""


def _reject_constant(name: str) -> None:
    raise ValueError(f"not JSON: {name}")


def _parse(line: str) -> _Pairs:
    return json.loads(
        line,
        object_pairs_hook=_Pairs,
        parse_int=_Num,
        parse_float=_Num,
        parse_constant=_reject_constant,
    )


def _serde_rejects(value) -> bool:
    """True for a number serde_json reports as out of range, or a lone surrogate."""
    if isinstance(value, _Num):
        return math.isinf(float(value))
    if isinstance(value, str):
        return any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
    if isinstance(value, _Pairs):
        return any(_serde_rejects(k) or _serde_rejects(v) for k, v in value)
    if isinstance(value, list):
        return any(_serde_rejects(v) for v in value)
    return False


def classify(line: str) -> tuple[str, int | None]:
    """Kind of a line 2 and its top-level minor, as every builder sees it.

    A repeated decoded top-level key is a duplicate even when a value is
    out of range (CON-line2.14). Otherwise the line must be JSON that
    serde_json accepts, and a top-level minor must be a JSON integer
    >= 0 (CON-line2.13).
    """
    try:
        obj = _parse(line)
    except ValueError:
        return INVALID, None
    minors = [v for k, v in obj if k == KEY]
    if len(minors) > 1:
        return DUP, None
    if _serde_rejects(obj):
        return INVALID, None
    if not minors:
        return VALID, None
    token = minors[0]
    if not isinstance(token, _Num) or not JSON_UINT.fullmatch(token):
        return INVALID, None
    return VALID, int(token)


def reader_minor(line: str) -> int:
    """The minor the reader's velocity check uses (types.rs minor_from_line).

    The last decoded top-level token saturates when it is an integer
    above u64::MAX that serde_json accepts. Otherwise the reader takes
    the digits of the first decoded top-level "con_spec_minor" value,
    and reads 0 when the key is absent, the value has no leading digits,
    or they do not fit in u64. A nested key does not count, and an
    escaped top-level key does.
    """
    minors = [v for k, v in _parse(line) if k == KEY]
    if not minors:
        return 0
    token = minors[-1]
    if (
        isinstance(token, _Num)
        and JSON_UINT.fullmatch(token)
        and int(token) > U64_MAX
        and not math.isinf(float(token))
    ):
        return U64_MAX
    first = minors[0]
    digits = re.match(r"[0-9]*", first).group(0) if isinstance(first, _Num) else ""
    if not digits or int(digits) > U64_MAX:
        return 0
    return int(digits)


def dump(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def written(line2: str, *, stamp_minor: bool, natural_time: bool) -> str:
    obj = json.loads(line2)
    obj["con_spec_version"] = 4
    obj["con_spec_patch"] = 5
    obj["sections"] = ["velocities"]
    if stamp_minor:
        obj["con_spec_minor"] = 0
    if natural_time:
        obj["units"]["time"] = NATURAL_SYMBOL
    return dump(obj)


def rpc_written(line2: str) -> str:
    obj = json.loads(line2)
    obj["con_spec_version"] = 3
    obj["sections"] = ["velocities"]
    return dump(obj)


def expect(name: str, body: str) -> dict:
    w = '{"con_spec_version":3,%s,%s}' % (body, U_T)
    n = '{"con_spec_version":3,%s,%s}' % (body, U_N)
    kind, top = classify(w)
    assert classify(n) == (kind, top), name
    case = {"name": name, "kind": kind, "line2_w": w, "line2_n": n}
    if kind != VALID:
        for op in (
            "read_w",
            "read_n",
            "raw_w",
            "raw_n",
            "rpc_w",
            "rpc_n",
            "binding_w",
            "binding_n",
        ):
            case[op] = kind
        return case
    # CON-units.9 applies to every minor of major 3. A missing units.time
    # therefore never rejects one of these valid probe frames.
    case["read_w"] = "ok"
    case["read_n"] = "ok"
    # Builders and binding rewrites emit current major 4. An absent minor
    # becomes the current minor, and a major-3 velocity without units.time
    # is carried forward in the natural time unit (CON-units.19).
    case["raw_w"] = written(w, stamp_minor=top is None, natural_time=False)
    case["raw_n"] = written(n, stamp_minor=top is None, natural_time=True)
    case["rpc_w"] = rpc_written(w)
    case["rpc_n"] = rpc_written(n)
    case["binding_w"] = written(w, stamp_minor=top is None, natural_time=False)
    case["binding_n"] = written(n, stamp_minor=top is None, natural_time=True)
    return case


def toml_string(value: str) -> str:
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def main() -> None:
    cases = [expect(*row) for row in CASES]
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names))
    header = {
        "fmax_plus_1": P1,
        "fmax_plus_2_970_minus_1": P2,
        "fmax_plus_2_970": P3,
        "natural_time": NATURAL,
    }
    (HERE / "minor_token_probes.json").write_text(
        json.dumps({**header, "cases": cases}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Generated by generate_minor_token_probes.py. Same data as minor_token_probes.json."
    ]
    for key, value in header.items():
        lines.append(f"{key} = {toml_string(value)}")
    for case in cases:
        lines.append("")
        lines.append("[[cases]]")
        for key, value in case.items():
            lines.append(f"{key} = {toml_string(value)}")
    (HERE / "minor_token_probes.toml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
