//! Timed parse of one CON buffer. Prints nanoseconds, byte count, and frame count.
fn main() {
    let mut args = std::env::args().skip(1);
    let path = args.next().expect("path");
    let repeats: usize = args.next().expect("repeats").parse().expect("repeats");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {path}: {err}"));
    let bytes = text.len();
    let _ = readcon_core::iterators::frames_from_text(&text, Some(1))
        .unwrap_or_else(|err| panic!("warmup: {err}"));
    for _ in 0..repeats {
        let start = std::time::Instant::now();
        let frames = readcon_core::iterators::frames_from_text(&text, Some(1))
            .unwrap_or_else(|err| panic!("parse: {err}"));
        let ns = start.elapsed().as_nanos();
        println!("{ns} {bytes} {}", frames.len());
    }
}
