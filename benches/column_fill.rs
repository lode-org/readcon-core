//! Distinct-frame column fill against the frame parser.
//!
//! The release unit test used to assert a time ratio and failed when the
//! machine was busy. This benchmark is where that comparison lives.

use criterion::{Criterion, criterion_group, criterion_main};
use readcon_core::{Slabs, fill_bytes, fill_bytes_threaded, layout_bytes};
use readcon_core::iterators::frames_from_bytes_phased;
use std::hint::black_box;

fn distinct_copies(src: &[u8], n: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(src.len().saturating_mul(n));
    for index in 0..n {
        if index == 0 {
            out.extend_from_slice(src);
            continue;
        }
        let text = std::str::from_utf8(src).expect("fixture").to_string();
        let marker = "Coordinates of Component";
        let at = text.find(marker).expect("coordinates");
        let line_start = text[at..].find('\n').expect("line") + at + 1;
        let line_end = text[line_start..]
            .find('\n')
            .unwrap_or(text.len() - line_start)
            + line_start;
        let mut parts: Vec<String> = text[line_start..line_end]
            .split_whitespace()
            .map(str::to_string)
            .collect();
        let value: f64 = parts[0].parse().expect("x");
        parts[0] = format!("{}", value + index as f64 * 1e-6);
        let mut frame = String::new();
        frame.push_str(&text[..line_start]);
        frame.push_str(&parts.join(" "));
        frame.push_str(&text[line_end..]);
        out.extend(frame.into_bytes());
    }
    out
}

fn empty_slabs(positions: &mut [f64]) -> Slabs<'_> {
    Slabs {
        positions,
        velocities: None,
        forces: None,
        energies: None,
        charges: None,
        spins: None,
        magmoms: None,
        displacements: None,
        spreads: None,
    }
}

fn column_fill(c: &mut Criterion) {
    let src = std::fs::read("resources/test/cuh2.con").expect("fixture");
    let bytes = distinct_copies(&src, 100);
    let layout = layout_bytes(&bytes).expect("layout");
    let mut group = c.benchmark_group("distinct_cuh2_100");
    for threads in [1usize, 2, 4, 8] {
        group.bench_function(format!("column_fill_{threads}"), |b| {
            b.iter(|| {
                let n3 = layout.n_frames * layout.n_atoms * 3;
                let mut positions = vec![0.0; n3];
                let found = if threads < 2 {
                    fill_bytes(
                        &bytes,
                        layout.n_frames,
                        layout.n_atoms,
                        layout.sections,
                        empty_slabs(&mut positions),
                    )
                } else {
                    fill_bytes_threaded(
                        &bytes,
                        layout.n_frames,
                        layout.n_atoms,
                        layout.sections,
                        threads,
                        &layout.frame_offsets,
                        layout.frames_end,
                        empty_slabs(&mut positions),
                    )
                }
                .expect("fill");
                black_box(found.n_frames);
                black_box(positions[0]);
            });
        });
        group.bench_function(format!("frame_parser_{threads}"), |b| {
            b.iter(|| {
                let frames = frames_from_bytes_phased(&bytes, (threads >= 2).then_some(threads))
                    .expect("parser");
                black_box(frames.frames.len());
            });
        });
    }
    group.finish();
}

criterion_group!(fills, column_fill);
criterion_main!(fills);
