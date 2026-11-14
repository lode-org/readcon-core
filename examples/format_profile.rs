//! One-worker formatter timing.
//!
//! `format_profile FRAMES [con|convel]` parses one fixture frame, repeats
//! it `FRAMES` times, and formats with one worker. The output is dropped
//! in chunks so a million frames do not have to stay resident.

use readcon_core::iterators::frames_from_text;
use readcon_core::types::ConFrame;
use readcon_core::writer::format_frame_refs_unstored;
use std::env;
use std::fs;
use std::hint::black_box;
use std::time::Instant;

fn load(kind: &str) -> ConFrame {
    let text = fs::read_to_string("resources/test/cuh2.con").expect("cuh2");
    let mut frames = frames_from_text(&text, Some(1)).expect("parse");
    let frame = frames.pop().expect("frame");
    if kind == "convel" {
        let mut frame = frame;
        for (index, atom) in frame.atom_data.iter_mut().enumerate() {
            atom.set_velocity(Some([0.01, -0.02, (index as f64) * 0.001]));
        }
        frame
    } else {
        frame
    }
}

fn main() {
    let mut args = env::args().skip(1);
    let frames_n: usize = args
        .next()
        .unwrap_or_else(|| "1000".into())
        .parse()
        .unwrap();
    let kind = args.next().unwrap_or_else(|| "con".into());
    let frame = load(&kind);
    let chunk = 256.min(frames_n.max(1));
    let refs: Vec<&ConFrame> = vec![&frame; chunk];
    // One untimed pass.
    let _ = format_frame_refs_unstored(&refs, 1, None, false, true).unwrap();
    let mut bytes = 0u64;
    let started = Instant::now();
    let mut left = frames_n;
    while left > 0 {
        let n = chunk.min(left);
        let refs: Vec<&ConFrame> = vec![&frame; n];
        let parts = format_frame_refs_unstored(&refs, 1, None, false, true).unwrap();
        bytes += parts.iter().map(|part| part.len() as u64).sum::<u64>();
        black_box(parts);
        left -= n;
    }
    let elapsed = started.elapsed().as_secs_f64();
    println!(
        "kind={kind} frames={frames_n} bytes={bytes} seconds={elapsed:.6} GBps={:.3}",
        bytes as f64 / elapsed / 1e9
    );
}
