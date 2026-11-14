//! Measure one wide frame on one thread against two copies on two threads.
//!
//! The unit test checks that the two writes produce the same bytes. This
//! bench records how long each write takes. It does not assert a ratio:
//! a debug build on a shared runner is not a speed gate.

use criterion::{Criterion, criterion_group, criterion_main};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::write_frame_refs_to_path;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Duration;

fn wide_frame(n: usize) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for i in 0..n {
        builder.add_atom(
            "Cu",
            i as f64 * 0.125,
            0.25,
            0.5,
            [false, false, false],
            i as u64,
            63.546,
        );
    }
    builder.build().expect("frame")
}

fn scratch(name: &str) -> PathBuf {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("build")
        .join("wide-write");
    fs::create_dir_all(&root).expect("bench directory");
    root.join(name)
}

fn wide_write(c: &mut Criterion) {
    let n = 50_000usize;
    let one = wide_frame(n);
    let frames = [one.clone(), one.clone()];
    let mut group = c.benchmark_group("WideWrite");
    group.sample_size(10);
    group.measurement_time(Duration::from_secs(4));

    group.bench_function("one_frame_one_thread", |b| {
        let path = scratch("one.con");
        let refs: [&ConFrame; 1] = [&one];
        b.iter(|| {
            write_frame_refs_to_path(black_box(&path), black_box(&refs), 1, None, false, false)
                .expect("write");
        });
        let _ = fs::remove_file(&path);
    });

    group.bench_function("two_frames_two_threads", |b| {
        let path = scratch("two.con");
        let refs: [&ConFrame; 2] = [&frames[0], &frames[1]];
        b.iter(|| {
            write_frame_refs_to_path(black_box(&path), black_box(&refs), 2, None, false, false)
                .expect("write");
        });
        let _ = fs::remove_file(&path);
    });

    group.finish();
}

criterion_group!(benches, wide_write);
criterion_main!(benches);
