//! STREAM-style bandwidth probe.
//!
//! Three arrays, each larger than the last-level cache. The triad is
//! `a = b + scalar * c`. Bytes moved are three arrays per step.
//! Build with `rustc -C opt-level=3 -C target-cpu=native examples/stream_triad.rs`.

use std::env;
use std::time::Instant;

fn kib(bytes: usize) -> usize {
    bytes / 1024
}

fn run(n: usize, scalar: f64, repeats: usize) -> (f64, f64, f64, f64) {
    let mut a = vec![1.0_f64; n];
    let mut b = vec![2.0_f64; n];
    let mut c = vec![3.0_f64; n];
    // Touch the pages before the timed window.
    for i in 0..n {
        a[i] = 1.0;
        b[i] = 2.0;
        c[i] = 3.0;
    }
    let bytes = 3.0 * (n as f64) * 8.0;
    let mut best_copy = 0.0_f64;
    let mut best_scale = 0.0_f64;
    let mut best_add = 0.0_f64;
    let mut best_triad = 0.0_f64;
    for _ in 0..repeats {
        let t = Instant::now();
        for i in 0..n {
            c[i] = a[i];
        }
        let dt = t.elapsed().as_secs_f64();
        // Copy moves two arrays.
        best_copy = best_copy.max((2.0 * (n as f64) * 8.0) / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            b[i] = scalar * c[i];
        }
        let dt = t.elapsed().as_secs_f64();
        best_scale = best_scale.max((2.0 * (n as f64) * 8.0) / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            c[i] = a[i] + b[i];
        }
        let dt = t.elapsed().as_secs_f64();
        best_add = best_add.max(bytes / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            a[i] = b[i] + scalar * c[i];
        }
        let dt = t.elapsed().as_secs_f64();
        best_triad = best_triad.max(bytes / dt / 1.0e9);
    }
    // Keep the arrays live.
    let sink = a[0] + b[n / 2] + c[n - 1];
    if !sink.is_finite() {
        eprintln!("non-finite stream sink");
    }
    (best_copy, best_scale, best_add, best_triad)
}

fn triad_parallel(n: usize, threads: usize, scalar: f64, repeats: usize) -> f64 {
    let mut a = vec![1.0_f64; n];
    let b = vec![2.0_f64; n];
    let c = vec![3.0_f64; n];
    let chunk = n.div_ceil(threads);
    let bytes = 3.0 * (n as f64) * 8.0;
    let mut best = 0.0_f64;
    for _ in 0..repeats {
        let t = Instant::now();
        std::thread::scope(|scope| {
            for ((aa, bb), cc) in a
                .chunks_mut(chunk)
                .zip(b.chunks(chunk))
                .zip(c.chunks(chunk))
            {
                scope.spawn(move || {
                    for i in 0..aa.len() {
                        aa[i] = bb[i] + scalar * cc[i];
                    }
                });
            }
        });
        let dt = t.elapsed().as_secs_f64();
        best = best.max(bytes / dt / 1.0e9);
    }
    let sink = a[0] + a[n - 1];
    if !sink.is_finite() {
        eprintln!("non-finite parallel sink");
    }
    best
}

fn main() {
    let cache_mib: usize = env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(320);
    let factor: usize = env::args().nth(2).and_then(|s| s.parse().ok()).unwrap_or(4);
    let repeats: usize = env::args().nth(3).and_then(|s| s.parse().ok()).unwrap_or(8);
    // Three arrays, each `factor` times the cache.
    let bytes_each = cache_mib * factor * 1024 * 1024;
    let n = bytes_each / 8;
    let (copy, scale, add, triad) = run(n, 3.0, repeats);
    let parallel = triad_parallel(n, 8, 3.0, repeats);
    println!("n {n}");
    println!("parallel_threads 8");
    println!("parallel_triad_gbs {parallel:.6}");
    println!("array_kib {}", kib(bytes_each));
    println!("copy_gbs {copy:.6}");
    println!("scale_gbs {scale:.6}");
    println!("add_gbs {add:.6}");
    println!("triad_gbs {triad:.6}");
}
