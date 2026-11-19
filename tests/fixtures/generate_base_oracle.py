#!/usr/bin/env python3
"""Deterministically generate tests/fixtures/base_oracle_9aff911e.json from BASE 9aff911e."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_BASE_COMMIT = "9aff911e809390163d2d7b08671145ad99f24496"
EXPECTED_BASE_TREE = "d775f9f7fda1ddff5becaea3e1b1545b1d1ba053"

FORTY_DIGITS = "1000000000000000000000000000000000000007"
THREE_HUNDRED_DIGITS = "1" + ("0" * 298) + "7"
FOUR_HUNDRED_DIGITS = "1" + ("0" * 398) + "7"

ADVERSARIAL_LINES: list[str] = [
    '{"con_spec_version":2,"f":1.50,"e":1E5,"p":1e+2}',
    '{"con_spec_version":2,"energy":-1.20}',
    '{"con_spec_version":2,"energy":-0,"x":-0}',
    '{"con_spec_version":2,"extra":18446744073709551616}',
    '{"con_spec_version":2,"prec":0.1000000000000000055511151231257827}',
    '{"con_spec_version":2,"nested":{"con_spec_minor":18446744073709551616}}',
    f'{{"con_spec_version":2,"nested":{{"con_spec_minor":{FOUR_HUNDRED_DIGITS}}}}}',
    f'{{"con_spec_version":2,"other":{FOUR_HUNDRED_DIGITS}}}',
    '{"con_spec_version":2,"note":"\\"con_spec_minor\\":18446744073709551616"}',
    '{"con_spec_version":2,"note":"}{","energy":1.50}',
    # Standalone plain-valid huge minors (expected to flip from BASE err to HEAD ok)
    '{"con_spec_version":2,"con_spec_minor":18446744073709551617}',
    f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS}}}',
    # section_arity & con_spec_version overflow / -0 cases
    '{"con_spec_version":2,"section_arity":{"widgets":18446744073709551616}}',
    f'{{"con_spec_version":2,"section_arity":{{"widgets":{FORTY_DIGITS}}}}}',
    '{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"},"section_arity":{"velocities":18446744073709551616}}',
    '{"con_spec_version":2,"section_arity":{"widgets":-0}}',
    '{"con_spec_version":2,"section_arity":{"widgets":0}}',
    '{"con_spec_version":2,"section_arity":{"widgets":-0,"widgets":2}}',
    '{"con_spec_version":2,"section_arity":{"widgets":2,"widgets":-0}}',
    '{"con_spec_version":18446744073709551616}',
    f'{{"con_spec_version":{FOUR_HUNDRED_DIGITS}}}',
    '{"con_spec_version":-0}',
    '{"con_spec_version":-0,"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":3,"con_spec_minor":-0,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"con_spec_minor":-0,"units":{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":2,"sections":[],"validate":true,"frame_index":-0}',
    '{"con_spec_version":2,"energy":1e400}',
    '{"con_spec_version":2,"lattice_vectors":[[10,0,0],[0,10,0],[0,0,1e999]]}',
    '{"con_spec_version":2,"con_spec_minor":"1"}',
    '{"con_spec_version":2,"con_spec_minor":1.0}',
    '{"con_spec_version":2,"con_spec_minor":1e0}',
    '{"con_spec_version":2,"con_spec_minor":-1}',
    '{"con_spec_version":2,"con_spec_minor":+1}',
    '{"con_spec_version":2,"con_spec_minor":01}',
    '{"con_spec_version":2} trailing',
    '{"con_spec_minor":18446744073709551616,"energy":1e999,"con_spec_version":2}',
    '{"con_spec_minor":184467440737095516161,"energy":1e999,"con_spec_version":2}',
    f'{{"con_spec_minor":{FORTY_DIGITS},"energy":1e999,"con_spec_version":2}}',
    f'{{"con_spec_minor":{FORTY_DIGITS},"energy":, "con_spec_version":2}}',
    f'{{"con_spec_minor":{THREE_HUNDRED_DIGITS},"energy":1e999,"con_spec_version":2}}',
    f'{{"con_spec_minor":{FOUR_HUNDRED_DIGITS},"energy":1e999,"con_spec_version":2}}',
    f'{{"con_spec_version":3,"con_spec_minor":{FOUR_HUNDRED_DIGITS},"units":{{"length":"angstrom","energy":"eV"}}}}',
    # Form feed (\x0c) and vertical tab (\x0b) around huge minors and before v3 units
    '{"con_spec_version":2,"con_spec_minor":\x0c18446744073709551616}',
    '{"con_spec_version":2,"con_spec_minor":18446744073709551616\x0c}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":\x0c{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":3,"units":\x0c{"length":"angstrom","energy":"eV"},"con_spec_minor":18446744073709551616}',
    '{"con_spec_version":2,"con_spec_minor":\x0b18446744073709551616}',
    '{"con_spec_version":2,"con_spec_minor":18446744073709551616\x0b}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":\x0b{"length":"angstrom","energy":"eV"}}',
    '{"con_spec_version":3,"units":\x0b{"length":"angstrom","energy":"eV"},"con_spec_minor":18446744073709551616}',
    # Raw control bytes (< 0x20) inside quoted units values with huge minors
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"ang\tstrom","energy":"eV"}}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom","energy":"\x0beV"}}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom","energy":"eV","time":"fs\r"}}',
    '{"con_spec_version":3,"con_spec_minor":18446744073709551616,"units":{"length":"angstrom\x0c","energy":"eV"}}',
    f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS},"units":{{"length":"x\x0cy","energy":"z"}}}}',
    f'{{"con_spec_version":2,"con_spec_minor":{FORTY_DIGITS},"units":{{"length":"x\x00y","energy":"z"}}}}',
]

# Sweep minor variants across plain/spaced/tabbed and clean/1e999 forms.
for ws in ("", " ", "  \t"):
    for tok in ("0", "7", "18446744073709551615", "-0", "-1", "1.5", "1e2", '"7"'):
        val = f"{ws}{tok}{ws}"
        ADVERSARIAL_LINES.append(
            f'{{"con_spec_version":2,"con_spec_minor":{val},"e":-1.20}}'
        )
        ADVERSARIAL_LINES.append(
            f'{{"e":1e999,"con_spec_minor":{val},"con_spec_version":2}}'
        )

RUST_MAIN_RS = r"""
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Path, PathBuf};

fn record_file(path: &Path) -> Value {
    match readcon_core::iterators::read_all_frames(path) {
        Ok(frames) => {
            let mut f_arr = Vec::with_capacity(frames.len());
            for frame in &frames {
                let mut m = Map::new();
                m.insert(
                    "con_spec_version".into(),
                    Value::from(frame.header.spec_version),
                );
                for (k, v) in &frame.header.metadata {
                    m.insert(k.clone(), v.clone());
                }
                if !frame.header.sections.is_empty() && !m.contains_key("sections") {
                    m.insert(
                        "sections".into(),
                        Value::from(frame.header.sections.clone()),
                    );
                }
                let metadata_json = serde_json::to_string(&Value::Object(m)).unwrap();
                f_arr.push(json!({
                    "spec_version": frame.header.spec_version,
                    "metadata_json": metadata_json,
                }));
            }
            let canonical_line2 = if let Some(first) = frames.first() {
                let mut buf = Vec::new();
                let res = readcon_core::writer::ConFrameWriter::new(&mut buf)
                    .canonical(true)
                    .write_frame(first);
                match res {
                    Ok(()) => String::from_utf8(buf)
                        .ok()
                        .and_then(|s| s.lines().nth(1).map(str::to_owned)),
                    Err(_) => None,
                }
            } else {
                None
            };
            json!({
                "status": "ok",
                "frames": f_arr,
                "canonical_line2": canonical_line2,
            })
        }
        Err(e) => json!({
            "status": "err",
            "error_class": "Error",
            "error_message": e.to_string(),
        }),
    }
}

fn main() {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let req: Value = serde_json::from_str(&input).unwrap();
    let base_repo = PathBuf::from(req["base_repo"].as_str().unwrap());
    let c31_dir = PathBuf::from(req["corpus31_dir"].as_str().unwrap());

    let mut tracked_out = BTreeMap::new();
    for rel in req["tracked_files"].as_array().unwrap() {
        let rel_s = rel.as_str().unwrap();
        tracked_out.insert(rel_s.to_owned(), record_file(&base_repo.join(rel_s)));
    }

    let mut c31_out = BTreeMap::new();
    for name in req["corpus31_files"].as_array().unwrap() {
        let name_s = name.as_str().unwrap();
        c31_out.insert(name_s.to_owned(), record_file(&c31_dir.join(name_s)));
    }

    let mut adv_out = Vec::new();
    for line in req["adversarial_lines"].as_array().unwrap() {
        let line2 = line.as_str().unwrap();
        let lines = ["PRE", line2, "10 10 10", "90 90 90", "", "", "0", "", ""];
        match readcon_core::parser::parse_frame_header(&mut lines.iter().copied()) {
            Ok(h) => {
                let mut m = Map::new();
                m.insert("con_spec_version".into(), Value::from(h.spec_version));
                for (k, v) in &h.metadata {
                    m.insert(k.clone(), v.clone());
                }
                let metadata_json = serde_json::to_string(&Value::Object(m)).unwrap();
                adv_out.push(json!({
                    "line2": line2,
                    "status": "ok",
                    "spec_version": h.spec_version,
                    "metadata_json": metadata_json,
                }));
            }
            Err(e) => {
                adv_out.push(json!({
                    "line2": line2,
                    "status": "err",
                    "error_class": e.class_name(),
                    "error_message": e.to_string(),
                }));
            }
        }
    }

    let out = json!({
        "tracked_corpus": tracked_out,
        "corpus31": c31_out,
        "adversarial_lines": adv_out,
    });
    println!("{}", serde_json::to_string(&out).unwrap());
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-repo",
        type=Path,
        required=True,
        help="Path to clean checkout of BASE commit 9aff911e",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "base_oracle_9aff911e.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Optional CARGO_TARGET_DIR for building the BASE probe binary",
    )
    args = parser.parse_args()

    base_repo = args.base_repo.resolve()
    head_commit = subprocess.check_output(
        ["git", "-C", str(base_repo), "rev-parse", "HEAD"], text=True
    ).strip()
    head_tree = subprocess.check_output(
        ["git", "-C", str(base_repo), "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    if head_commit != EXPECTED_BASE_COMMIT or head_tree != EXPECTED_BASE_TREE:
        raise SystemExit(
            f"Expected BASE {EXPECTED_BASE_COMMIT} (tree {EXPECTED_BASE_TREE}), "
            f"got {head_commit} (tree {head_tree})"
        )

    status_out = subprocess.check_output(
        ["git", "-C", str(base_repo), "status", "--porcelain"], text=True
    ).strip()
    if status_out:
        raise SystemExit(f"BASE repo is dirty:\n{status_out}")

    base_commit_date_utc = subprocess.check_output(
        ["git", "-C", str(base_repo), "show", "-s", "--format=%cI", "HEAD"], text=True
    ).strip()

    tracked_files = sorted(
        subprocess.check_output(
            ["git", "-C", str(base_repo), "ls-files", "*.con", "*.convel"], text=True
        ).splitlines()
    )
    assert len(tracked_files) == 70, len(tracked_files)

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        c31_dir = td / "corpus31"
        subprocess.run(
            [
                sys.executable,
                str(base_repo / "paper" / "cpc" / "scripts" / "make_corpus31.py"),
                "--out",
                str(c31_dir),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        c31_files = sorted(
            p.name for p in c31_dir.iterdir() if p.is_file() and p.name != "manifest.toml"
        )
        assert len(c31_files) == 143, len(c31_files)

        crate_dir = td / "oracle_probe"
        (crate_dir / "src").mkdir(parents=True)
        shutil.copy2(base_repo / "Cargo.lock", crate_dir / "Cargo.lock")
        (crate_dir / "Cargo.toml").write_text(
            "\n".join(
                [
                    "[package]",
                    'name = "oracle_probe"',
                    'version = "0.1.0"',
                    'edition = "2024"',
                    "",
                    "[dependencies]",
                    f'readcon-core = {{ path = {json.dumps(str(base_repo))} }}',
                    'serde_json = { version = "1.0", features = ["float_roundtrip"] }',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (crate_dir / "src" / "main.rs").write_text(RUST_MAIN_RS, encoding="utf-8")

        env = os.environ.copy()
        if args.target_dir is not None:
            env["CARGO_TARGET_DIR"] = str(args.target_dir.resolve())
        else:
            env["CARGO_TARGET_DIR"] = str(td / "target")

        req = {
            "base_repo": str(base_repo),
            "tracked_files": tracked_files,
            "corpus31_dir": str(c31_dir),
            "corpus31_files": c31_files,
            "adversarial_lines": ADVERSARIAL_LINES,
        }
        proc = subprocess.run(
            [
                "cargo",
                "run",
                "--release",
                "--quiet",
                "--offline",
                "--manifest-path",
                str(crate_dir / "Cargo.toml"),
            ],
            input=json.dumps(req),
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"oracle_probe failed ({proc.returncode}):\n{proc.stderr}"
            )
        raw_out = json.loads(proc.stdout)

    final = {
        "provenance": {
            "base_commit": EXPECTED_BASE_COMMIT,
            "base_tree": EXPECTED_BASE_TREE,
            "base_commit_date_utc": base_commit_date_utc,
            "generator_script": "tests/fixtures/generate_base_oracle.py",
            "rust_generator": (
                "readcon_core::iterators::read_all_frames + "
                "readcon_core::parser::parse_frame_header + "
                "readcon_core::writer::ConFrameWriter"
            ),
        },
        "tracked_corpus": raw_out["tracked_corpus"],
        "corpus31": raw_out["corpus31"],
        "adversarial_lines": raw_out["adversarial_lines"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
