//! Codec-only ceiling for the compressed CON campaign.
//!
//! ```text
//! codec_ceiling inflate COMPRESSED THREADS REPEATS
//! codec_ceiling deflate PLAIN THREADS REPEATS gzip|zstd MEMBERS
//! ```
//!
//! One untimed call, then `REPEATS` samples. Prints the raw sample list.
//! Inflate and deflate use the codec on independent members. Neither
//! call parses a CON frame.

use std::env;
use std::fs;
use std::time::Instant;

fn samples(repeats: usize, mut once: impl FnMut()) -> Vec<f64> {
    once();
    let mut out = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        once();
        out.push(started.elapsed().as_secs_f64());
    }
    out
}

fn main() {
    let mut args = env::args().skip(1);
    let op = args.next().expect("op");
    let path = args.next().expect("path");
    let threads: usize = args.next().expect("threads").parse().expect("threads");
    let repeats: usize = args.next().expect("repeats").parse().expect("repeats");
    let bytes = fs::read(&path).expect("read");
    let values = match op.as_str() {
        "inflate" => samples(repeats, || {
            readcon_core::compression::codec_inflate(&bytes, threads).expect("inflate");
        }),
        "deflate" => {
            let kind = args.next().expect("gzip|zstd");
            let members: usize = args.next().expect("members").parse().expect("members");
            let gzip = match kind.as_str() {
                "gzip" => true,
                "zstd" => false,
                other => panic!("unknown codec {other}"),
            };
            samples(repeats, || {
                readcon_core::compression::codec_deflate(&bytes, members, threads, gzip)
                    .expect("deflate");
            })
        }
        other => panic!("unknown op {other}"),
    };
    let body: Vec<String> = values.iter().map(|sample| format!("{sample:.9}")).collect();
    println!("[{}]", body.join(","));
}
