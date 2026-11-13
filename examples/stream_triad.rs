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

/// Type-7 percentile, the same rule as the ladder.
fn percentile_type7(samples: &[f64], pct: f64) -> f64 {
    let mut ordered = samples.to_vec();
    ordered.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if ordered.len() == 1 {
        return ordered[0];
    }
    let rank = (pct / 100.0) * ((ordered.len() - 1) as f64);
    let lo = rank.floor() as usize;
    let hi = rank.ceil() as usize;
    if lo == hi {
        return ordered[lo];
    }
    let weight = rank - (lo as f64);
    ordered[lo] * (1.0 - weight) + ordered[hi] * weight
}

fn median(samples: &[f64]) -> f64 {
    percentile_type7(samples, 50.0)
}

fn iqr(samples: &[f64]) -> f64 {
    percentile_type7(samples, 75.0) - percentile_type7(samples, 25.0)
}

fn run(n: usize, scalar: f64, repeats: usize) -> (Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>) {
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
    let mut copy = Vec::with_capacity(repeats);
    let mut scale = Vec::with_capacity(repeats);
    let mut add = Vec::with_capacity(repeats);
    let mut triad = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let t = Instant::now();
        // This is the timed STREAM copy. A memcpy would change the measurement.
        #[allow(clippy::manual_memcpy)]
        for i in 0..n {
            c[i] = a[i];
        }
        let dt = t.elapsed().as_secs_f64();
        // Copy moves two arrays.
        copy.push((2.0 * (n as f64) * 8.0) / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            b[i] = scalar * c[i];
        }
        let dt = t.elapsed().as_secs_f64();
        scale.push((2.0 * (n as f64) * 8.0) / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            c[i] = a[i] + b[i];
        }
        let dt = t.elapsed().as_secs_f64();
        add.push(bytes / dt / 1.0e9);

        let t = Instant::now();
        for i in 0..n {
            a[i] = b[i] + scalar * c[i];
        }
        let dt = t.elapsed().as_secs_f64();
        triad.push(bytes / dt / 1.0e9);
    }
    // Keep the arrays live.
    let sink = a[0] + b[n / 2] + c[n - 1];
    if !sink.is_finite() {
        eprintln!("non-finite stream sink");
    }
    (copy, scale, add, triad)
}

fn triad_parallel(n: usize, threads: usize, scalar: f64, repeats: usize) -> Vec<f64> {
    let mut a = vec![1.0_f64; n];
    let b = vec![2.0_f64; n];
    let c = vec![3.0_f64; n];
    let chunk = n.div_ceil(threads);
    let bytes = 3.0 * (n as f64) * 8.0;
    let mut samples = Vec::with_capacity(repeats);
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
        samples.push(bytes / dt / 1.0e9);
    }
    let sink = a[0] + a[n - 1];
    if !sink.is_finite() {
        eprintln!("non-finite parallel sink");
    }
    samples
}

fn main() {
    let cache_mib: usize = env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(320);
    let factor: usize = env::args().nth(2).and_then(|s| s.parse().ok()).unwrap_or(4);
    let repeats: usize = env::args().nth(3).and_then(|s| s.parse().ok()).unwrap_or(8);
    if repeats < 6 {
        eprintln!("repeats are below 6");
        std::process::exit(2);
    }
    // Three arrays, each `factor` times the cache.
    let bytes_each = cache_mib * factor * 1024 * 1024;
    let n = bytes_each / 8;
    let (copy, scale, add, triad) = run(n, 3.0, repeats);
    let parallel = triad_parallel(n, 8, 3.0, repeats);
    println!("n {n}");
    println!("repeats {repeats}");
    println!("parallel_threads 8");
    println!("parallel_triad_gbs {:.6}", median(&parallel));
    println!("parallel_triad_iqr {:.6}", iqr(&parallel));
    println!("array_kib {}", kib(bytes_each));
    println!("copy_gbs {:.6}", median(&copy));
    println!("copy_iqr {:.6}", iqr(&copy));
    println!("scale_gbs {:.6}", median(&scale));
    println!("scale_iqr {:.6}", iqr(&scale));
    println!("add_gbs {:.6}", median(&add));
    println!("add_iqr {:.6}", iqr(&add));
    println!("triad_gbs {:.6}", median(&triad));
    println!("triad_iqr {:.6}", iqr(&triad));
}
