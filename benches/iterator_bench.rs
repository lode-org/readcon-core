#[path = "../tests/common/mod.rs"]
mod common;

use std::path::Path;
use criterion::{criterion_group, criterion_main, Criterion};
use readcon_core::iterators::ConFrameIterator;
use std::fs;
use std::hint::black_box;

fn generate_large_file(num_frames: usize) -> String {
    let single_frame = fs::read_to_string(test_case!("tiny_cuh2.con")).expect("Can't find test.");
    let mut buf = String::with_capacity(single_frame.len() * num_frames);
    for _ in 0..num_frames {
        buf.push_str(&single_frame);
    }
    buf
}

fn iterator_bench(c: &mut Criterion) {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("Can't find test.");
    let mut group = c.benchmark_group("FrameIteration");

    group.bench_function("full_parse_next", |b| {
        b.iter(|| {
            let mut iterator = ConFrameIterator::new(&fdat);
            for frame_result in &mut iterator {
                let _ = black_box(frame_result);
            }
        })
    });

    group.bench_function("skip_with_forward", |b| {
        b.iter(|| {
            let mut iterator = ConFrameIterator::new(&fdat);
            while let Some(result) = iterator.forward() {
                let _ = black_box(result);
            }
        })
    });

    group.finish();
}

fn convel_bench(c: &mut Criterion) {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.convel")).expect("Can't find test.");
    let mut group = c.benchmark_group("ConvelParsing");

    group.bench_function("convel_full_parse", |b| {
        b.iter(|| {
            let iter = ConFrameIterator::new(&fdat);
            for frame_result in iter {
                let _ = black_box(frame_result);
            }
        })
    });

    group.bench_function("convel_skip_forward", |b| {
        b.iter(|| {
            let mut iter = ConFrameIterator::new(&fdat);
            while let Some(result) = iter.forward() {
                let _ = black_box(result);
            }
        })
    });

    group.finish();
}

fn c_api_roundtrip_bench(c: &mut Criterion) {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2.con")).expect("Can't find test.");
    let mut group = c.benchmark_group("CApiRoundtrip");

    group.bench_function("rust_parse_only", |b| {
        b.iter(|| {
            let iter = ConFrameIterator::new(&fdat);
            let frames: Vec<_> = iter.collect();
            let _ = black_box(frames);
        })
    });

    group.finish();
}

fn large_file_bench(c: &mut Criterion) {
    let large = generate_large_file(100);
    let mut group = c.benchmark_group("LargeFile");

    group.bench_function("100_frames_sequential", |b| {
        b.iter(|| {
            let iter = ConFrameIterator::new(&large);
            let frames: Vec<_> = iter.collect();
            let _ = black_box(frames);
        })
    });

    group.bench_function("100_frames_forward_skip", |b| {
        b.iter(|| {
            let mut iter = ConFrameIterator::new(&large);
            while let Some(result) = iter.forward() {
                let _ = black_box(result);
            }
        })
    });

    group.finish();
}

fn mmap_vs_read_bench(c: &mut Criterion) {
    let path = test_case!("cuh2.con");
    let mut group = c.benchmark_group("MmapVsRead");

    group.bench_function("read_to_string", |b| {
        b.iter(|| {
            let fdat = fs::read_to_string(&path).unwrap();
            let iter = ConFrameIterator::new(&fdat);
            let frames: Vec<_> = iter.collect();
            let _ = black_box(frames);
        })
    });

    group.bench_function("mmap_read", |b| {
        b.iter(|| {
            let frames = readcon_core::iterators::read_all_frames(&path).unwrap();
            let _ = black_box(frames);
        })
    });

    group.finish();
}

fn fast_float_microbench(c: &mut Criterion) {
    let line = "  1.23456789012345  -9.87654321098765  0.00000000000001  1.0  42";
    let mut group = c.benchmark_group("FloatParsing");

    group.bench_function("fast_float2_parse_5", |b| {
        b.iter(|| {
            let vals = readcon_core::parser::parse_line_of_n_f64(black_box(line), 5).unwrap();
            let _ = black_box(vals);
        })
    });

    group.bench_function("std_parse_5", |b| {
        b.iter(|| {
            let vals = readcon_core::parser::parse_line_of_n::<f64>(black_box(line), 5).unwrap();
            let _ = black_box(vals);
        })
    });

    group.finish();
}

criterion_group!(
    benches,
    iterator_bench,
    convel_bench,
    c_api_roundtrip_bench,
    large_file_bench,
    mmap_vs_read_bench,
    fast_float_microbench,
);
criterion_main!(benches);
