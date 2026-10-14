//! Serial vs indexed read timings.
//!
//! `cargo run --release --features parallel --example rcidx_bench -- FILE [THREADS]`
//!
//! Reports: offset scan, sidecar load, strict UTF-8, sliced UTF-8,
//! serial `read_all_frames`, and `read_all_frames_indexed` cold (no
//! sidecar) and warm (valid sidecar). Times are the median of 5 runs.
use readcon_core::{compression, frame_index, iterators};
use std::path::Path;
use std::time::Instant;

fn median<F: FnMut() -> usize>(mut f: F) -> (f64, usize) {
    let mut t = Vec::new();
    let mut n = 0;
    for _ in 0..5 {
        let s = Instant::now();
        n = f();
        t.push(s.elapsed().as_secs_f64() * 1e3);
    }
    t.sort_by(|a, b| a.partial_cmp(b).unwrap());
    (t[2], n)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = Path::new(&args[1]);
    let threads = args.get(2).map(|s| s.parse().unwrap());
    let side = frame_index::sidecar_path(path);
    let fc = compression::read_file_contents(path).unwrap();
    let bytes: &[u8] = match &fc {
        compression::FileContents::Owned(s) => s.as_bytes(),
        compression::FileContents::Mapped(m) => m,
    };
    let text = fc.as_str().unwrap();
    let rows: Vec<(&str, (f64, usize))> = vec![
        (
            "utf8 strict",
            median(|| std::str::from_utf8(bytes).unwrap().len()),
        ),
        (
            "utf8 sliced",
            median(|| frame_index::validate_utf8_sliced(bytes).unwrap().len()),
        ),
        (
            "offset scan",
            median(|| frame_index::FrameIndex::scan(text).unwrap().len()),
        ),
        (
            "serial read_all_frames",
            median(|| iterators::read_all_frames(path).unwrap().len()),
        ),
        (
            "parallel, legacy scan",
            median(|| {
                iterators::read_all_frames_with_threads(path, threads)
                    .unwrap()
                    .len()
            }),
        ),
        (
            "indexed cold",
            median(|| {
                let _ = std::fs::remove_file(&side);
                iterators::read_all_frames_indexed(path, threads)
                    .unwrap()
                    .len()
            }),
        ),
        (
            "sidecar load",
            median(|| frame_index::read_sidecar(path).unwrap().unwrap().len()),
        ),
        (
            "indexed warm",
            median(|| {
                iterators::read_all_frames_indexed(path, threads)
                    .unwrap()
                    .len()
            }),
        ),
    ];
    for (name, (ms, n)) in rows {
        println!("{name:24} {ms:10.1} ms  (n={n})");
    }
}
