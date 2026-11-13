//! Release timings for the publication ladder.
//!
//! `scale_probe pos|fmt PATH threads` prints one median line and the samples.

use std::time::Instant;

fn median(samples: &[f64]) -> f64 {
    let mut ordered = samples.to_vec();
    ordered.sort_by(|left, right| left.partial_cmp(right).unwrap());
    let mid = ordered.len() / 2;
    if ordered.len().is_multiple_of(2) {
        (ordered[mid - 1] + ordered[mid]) / 2.0
    } else {
        ordered[mid]
    }
}

fn time_it(repeats: usize, mut body: impl FnMut()) -> Vec<f64> {
    body();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        body();
        samples.push(started.elapsed().as_secs_f64());
    }
    samples
}

fn main() {
    let mut args = std::env::args().skip(1);
    let which = args.next().unwrap_or_else(|| "pos".into());
    let path = args.next().expect("path");
    let workers: usize = args.next().unwrap_or_else(|| "1".into()).parse().unwrap();
    let samples = match which.as_str() {
        "pos" => time_it(6, || {
            let block = readcon_core::iterators::read_positions_with_threads(
                std::path::Path::new(&path),
                Some(workers),
            )
            .unwrap();
            std::hint::black_box(block.values.len());
        }),
        "fmt" => {
            let text = std::fs::read_to_string(&path).unwrap();
            let frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
            time_it(6, || {
                let bytes = readcon_core::writer::write_frames_to_vec_with_threads(
                    &frames, workers, None, false,
                )
                .unwrap();
                std::hint::black_box(bytes.len());
            })
        }
        "write" => {
            let text = std::fs::read_to_string(&path).unwrap();
            let frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
            let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
            let out = std::path::Path::new("/tmp/readcon-r6-rust-write.con");
            time_it(6, || {
                readcon_core::writer::write_frame_refs_to_path(
                    out, &refs, workers, None, false, true,
                )
                .unwrap();
            })
        }
        "xyz" => {
            let bytes = std::fs::read(&path).unwrap();
            time_it(6, || {
                let tables = readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads(
                    &bytes, workers,
                )
                .unwrap();
                std::hint::black_box(tables.positions.len());
            })
        }
        other => {
            eprintln!("unknown {other}");
            std::process::exit(2);
        }
    };
    let text = samples
        .iter()
        .map(|sample| format!("{sample:.6}"))
        .collect::<Vec<_>>()
        .join(",");
    println!(
        "kind={which} workers={workers} median={:.6} samples={text}",
        median(&samples)
    );
}
