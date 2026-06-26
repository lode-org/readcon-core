//! Deterministic workload for Cachegrind / Callgrind CI.
//! Runs each scenario a fixed number of times (no timing loops).
//! Usage: cargo run --release --example cachegrind_harness -- [scenario|all]

use readcon_core::iterators::ConFrameIterator;
use readcon_core::parser::{parse_line_of_n, parse_line_of_n_f64};
use readcon_core::writer::ConFrameWriter;
use std::env;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;

fn test_case(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources/test")
        .join(name)
}

fn gen_frames(n: usize) -> String {
    let single = fs::read_to_string(test_case("tiny_cuh2.con")).expect("tiny_cuh2.con");
    let mut buf = String::with_capacity(single.len() * n);
    for _ in 0..n {
        buf.push_str(&single);
    }
    buf
}

fn scenario_parse_multi() {
    let fdat = fs::read_to_string(test_case("tiny_multi_cuh2.con")).unwrap();
    for _ in 0..50 {
        let iter = ConFrameIterator::new(&fdat);
        for frame in iter {
            let _ = black_box(frame);
        }
    }
}

fn scenario_forward_multi() {
    let fdat = fs::read_to_string(test_case("tiny_multi_cuh2.con")).unwrap();
    for _ in 0..50 {
        let mut iter = ConFrameIterator::new(&fdat);
        while let Some(r) = iter.forward() {
            let _ = black_box(r);
        }
    }
}

fn scenario_convel() {
    let fdat = fs::read_to_string(test_case("tiny_multi_cuh2.convel")).unwrap();
    for _ in 0..50 {
        for frame in ConFrameIterator::new(&fdat) {
            let _ = black_box(frame);
        }
    }
}

fn scenario_100_frames() {
    let large = gen_frames(100);
    for _ in 0..10 {
        let frames: Vec<_> = ConFrameIterator::new(&large).collect();
        let _ = black_box(frames);
    }
}

fn scenario_100_forward() {
    let large = gen_frames(100);
    for _ in 0..10 {
        let mut iter = ConFrameIterator::new(&large);
        while let Some(r) = iter.forward() {
            let _ = black_box(r);
        }
    }
}

fn scenario_cuh2() {
    let fdat = fs::read_to_string(test_case("cuh2.con")).unwrap();
    for _ in 0..20 {
        let frames: Vec<_> = ConFrameIterator::new(&fdat).collect();
        let _ = black_box(frames);
    }
}

fn scenario_float_fast() {
    let line = "  1.23456789012345  -9.87654321098765  0.00000000000001  1.0  42";
    for _ in 0..10_000 {
        let vals = parse_line_of_n_f64(black_box(line), 5).unwrap();
        let _ = black_box(vals);
    }
}

fn scenario_float_std() {
    let line = "  1.23456789012345  -9.87654321098765  0.00000000000001  1.0  42";
    for _ in 0..10_000 {
        let vals = parse_line_of_n::<f64>(black_box(line), 5).unwrap();
        let _ = black_box(vals);
    }
}

fn scenario_write_100() {
    let large = gen_frames(100);
    let frames: Vec<_> = ConFrameIterator::new(&large)
        .map(|r| r.unwrap())
        .collect();
    for _ in 0..10 {
        let mut buffer: Vec<u8> = Vec::with_capacity(large.len());
        {
            let mut writer = ConFrameWriter::new(&mut buffer);
            writer.extend(frames.iter()).unwrap();
        }
        let _ = black_box(buffer);
    }
}

type Scenario = (&'static str, fn());

const SCENARIOS: &[Scenario] = &[
    ("parse_multi_2x4", scenario_parse_multi),
    ("forward_multi_2x4", scenario_forward_multi),
    ("convel_multi", scenario_convel),
    ("parse_100_frames", scenario_100_frames),
    ("forward_100_frames", scenario_100_forward),
    ("parse_cuh2_218", scenario_cuh2),
    ("float_fast_float2", scenario_float_fast),
    ("float_std_parse", scenario_float_std),
    ("write_100_frames", scenario_write_100),
];

fn main() {
    let arg = env::args().nth(1).unwrap_or_else(|| "all".into());
    if arg == "list" {
        for (name, _) in SCENARIOS {
            println!("{name}");
        }
        return;
    }
    let run_one = |name: &str, f: fn()| {
        eprintln!("cachegrind_harness: start {name}");
        f();
        eprintln!("cachegrind_harness: done {name}");
    };
    if arg == "all" {
        for (name, f) in SCENARIOS {
            run_one(name, *f);
        }
        return;
    }
    for (name, f) in SCENARIOS {
        if *name == arg {
            run_one(name, *f);
            return;
        }
    }
    eprintln!("unknown scenario: {arg}");
    std::process::exit(2);
}
