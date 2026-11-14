//! Frame scans stop where `ConFrameIterator` stops, and the parallel readers
//! return what the sequential reader returns (CON-frame.1).

use readcon_core::frame_index::FrameIndex;
use readcon_core::index_proj::frame_byte_spans;
use readcon_core::iterators::{frame_start_offsets, frames_from_bytes, frames_from_text};

const SINGLE: &str = include_str!("../resources/test/tiny_cuh2.con");
const MULTI_CONVEL: &str = include_str!("../resources/test/tiny_multi_cuh2.convel");

/// Whitespace that `str::trim` removes but a space or tab test misses:
/// vertical tab, form feed and no-break space.
const OTHER_BLANKS: [&str; 3] = ["\u{b}", "\u{c}", "\u{a0}"];

fn inputs() -> Vec<String> {
    let mut out: Vec<String> = ["", "\n", " ", "\n\n", "\r\n", " \u{b}"]
        .map(String::from)
        .to_vec();
    let separator = "\n\nCu\nVelocities";
    assert!(MULTI_CONVEL.contains(separator));
    for blank in OTHER_BLANKS {
        out.push(blank.to_string());
        out.push(format!("{SINGLE}{blank}"));
        out.push(format!("{SINGLE}{blank}\n"));
        out.push(MULTI_CONVEL.replacen(separator, &format!("\n{blank}\nCu\nVelocities"), 1));
    }
    out
}

#[test]
fn parallel_readers_match_the_sequential_reader() {
    for text in inputs() {
        let one = frames_from_text(&text, Some(1)).ok();
        assert!(one.is_some(), "{text:?}");
        assert_eq!(frames_from_text(&text, Some(2)).ok(), one, "{text:?}");
        assert_eq!(
            frames_from_bytes(text.as_bytes(), Some(2)).ok(),
            one,
            "{text:?}"
        );
    }
}

#[test]
fn frame_scans_find_the_frames_the_iterator_reads() {
    for text in inputs() {
        let starts: Vec<usize> = frame_byte_spans(&text)
            .unwrap()
            .iter()
            .map(|span| span.start)
            .collect();
        assert_eq!(frame_start_offsets(&text), starts, "{text:?}");
        let offsets: Vec<u64> = starts.iter().map(|&s| s as u64).collect();
        assert_eq!(
            FrameIndex::scan(&text).unwrap().offsets,
            offsets,
            "{text:?}"
        );
    }
}

#[test]
fn a_form_feed_line_still_separates_the_velocity_block() {
    let text = MULTI_CONVEL.replacen("\n\nCu\nVelocities", "\n\u{c}\nCu\nVelocities", 1);
    let frames = frames_from_text(&text, Some(1)).unwrap();
    assert_eq!(frames, frames_from_text(MULTI_CONVEL, Some(1)).unwrap());
    assert_eq!(frames_from_text(&text, Some(2)).unwrap(), frames);
}
