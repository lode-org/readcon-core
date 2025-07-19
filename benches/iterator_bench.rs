use criterion::{criterion_group, criterion_main, Criterion};
use readcon_core::iterators::ConFrameIterator;
use std::fs;
use std::hint::black_box;

fn iterator_bench(c: &mut Criterion) {
    // Load the test file into memory once to avoid I/O overhead in the benchmark loop.
    // For a more realistic benchmark, you might want to create a larger file with
    // many more frames than the tiny test case.
    let file_contents = fs::read_to_string(
        "/home/rgoswami/Git/Github/LODE/readcon-core/resources/test/tiny_multi_cuh2.con",
    )
    .expect("Failed to read test file.");

    // Create a benchmark group to compare the two iteration methods.
    let mut group = c.benchmark_group("FrameIteration");

    // Benchmark 1: Full Parsing with `next()`
    // This measures the performance of iterating through the file and fully parsing
    // every frame. This is the "baseline" performance.
    group.bench_function("full_parse_next", |b| {
        b.iter(|| {
            // Create a new iterator for each iteration of the benchmark.
            let mut iterator = ConFrameIterator::new(&file_contents);
            // Consume the iterator, ensuring the work isn't optimized away.
            for frame_result in &mut iterator {
                let _ = black_box(frame_result);
            }
        })
    });

    // Benchmark 2: Skipping with `forward()`
    // This measures the performance of iterating through the file by only parsing
    // the headers and skipping the atom data. This should be significantly faster.
    group.bench_function("skip_with_forward", |b| {
        b.iter(|| {
            let mut iterator = ConFrameIterator::new(&file_contents);
            // Consume the iterator by calling `forward()` until it's empty.
            while let Some(result) = iterator.forward() {
                let _ = black_box(result);
            }
        })
    });

    group.finish();
}

criterion_group!(benches, iterator_bench);
criterion_main!(benches);
