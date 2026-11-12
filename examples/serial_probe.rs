//! Serial read of one file.
//!
//! ```text
//! serial_probe FILE OUT.json [REPEATS] [default|one]
//! ```
//!
//! `default` calls [`readcon_core::iterators::read_all_frames`].
//! `one` calls that read with a single worker.
//! `positions` calls [`readcon_core::iterators::read_positions_with_threads`]
//! on one thread, which is the column walker. Repeats default to 6.
//! One untimed call runs first and is not a sample. The samples are
//! the timed calls, in order.

use std::env;
use std::fs;
use std::path::Path;
use std::time::Instant;

fn read_frames(path: &Path, mode: &str) -> usize {
    match mode {
        "one" => readcon_core::iterators::read_all_frames_with_threads(path, Some(1))
            .expect("read")
            .len(),
        "positions" => {
            readcon_core::iterators::read_positions_with_threads(path, Some(1))
                .expect("read")
                .n_frames
        }
        _ => readcon_core::iterators::read_all_frames(path)
            .expect("read")
            .len(),
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: serial_probe FILE OUT.json [REPEATS] [default|one]");
        std::process::exit(2);
    }
    let path = Path::new(&args[1]);
    let out_path = Path::new(&args[2]);
    let repeats = args
        .get(3)
        .map(|text| text.parse::<usize>().expect("repeats"))
        .unwrap_or(6);
    let mode = args.get(4).map(String::as_str).unwrap_or("default");
    if repeats < 1 {
        eprintln!("repeats are below 1");
        std::process::exit(2);
    }
    let warm = read_frames(path, mode);
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        let n = read_frames(path, mode);
        samples.push(started.elapsed().as_secs_f64());
        assert_eq!(n, warm);
    }
    let mut listed = String::new();
    for (index, sample) in samples.iter().enumerate() {
        if index > 0 {
            listed.push_str(", ");
        }
        listed.push_str(&format!("{sample:.9}"));
    }
    let body = format!(
        "{{\n  \"mode\": \"{mode}\",\n  \"frames\": {warm},\n  \"repeats\": {repeats},\n  \"samples_s\": [{listed}]\n}}\n"
    );
    if let Some(parent) = out_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(out_path, &body).expect("write");
}
