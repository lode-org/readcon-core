//! Measurements that used to be assertions in the unit tests.
//!
//! `cargo test --release` on a shared runner is not a speed gate. These
//! benches record the times and do not fail on a ratio or a millisecond cap.

use criterion::{Criterion, criterion_group, criterion_main};
use readcon_core::index_proj::frame_composition_formula;
use readcon_core::iterators::read_positions_with_threads;
use readcon_core::types::ConFrameBuilder;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Duration;

fn scratch(name: &str) -> PathBuf {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("build")
        .join("speed-checks");
    fs::create_dir_all(&root).expect("bench directory");
    root.join(name)
}

fn wide_text(n: usize) -> String {
    let mut one = String::from(
        "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
    );
    one.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
    for i in 0..n {
        one.push_str(&format!("{i}.125000 0.250000 0.500000 0 {i}\n"));
    }
    one
}

fn wide_read(c: &mut Criterion) {
    let n = 50_000usize;
    let one = wide_text(n);
    let two = format!("{one}{one}");
    let one_path = scratch("one.con");
    let two_path = scratch("two.con");
    fs::write(&one_path, &one).expect("write");
    fs::write(&two_path, &two).expect("write");
    let mut group = c.benchmark_group("WideRead");
    group.sample_size(10);
    group.measurement_time(Duration::from_secs(4));
    group.bench_function("one_frame_one_thread", |b| {
        b.iter(|| {
            let got = read_positions_with_threads(&one_path, Some(1)).expect("read");
            black_box(got.values.len());
        });
    });
    group.bench_function("two_frames_two_threads", |b| {
        b.iter(|| {
            let got = read_positions_with_threads(&two_path, Some(2)).expect("read");
            black_box(got.values.len());
        });
    });
    group.finish();
    let _ = fs::remove_file(&one_path);
    let _ = fs::remove_file(&two_path);
}

fn formula(c: &mut Criterion) {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    let n = 20_000u32;
    for i in 0..n {
        builder.add_atom("Cu", i as f64, 0.0, 0.0, [false; 3], i as u64, 63.546);
    }
    for i in 0..10 {
        builder.add_atom("H", i as f64, 1.0, 0.0, [false; 3], n as u64 + i, 1.008);
    }
    let frame = builder.build().expect("frame");
    let mut group = c.benchmark_group("CompositionFormula");
    group.sample_size(10);
    group.measurement_time(Duration::from_secs(2));
    group.bench_function("twenty_thousand_atoms", |b| {
        b.iter(|| {
            black_box(frame_composition_formula(black_box(&frame)));
        });
    });
    group.finish();
}

criterion_group!(benches, wide_read, formula);
criterion_main!(benches);
