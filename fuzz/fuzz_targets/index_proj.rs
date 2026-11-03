#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::index_proj::{
    frame_byte_spans, frame_byte_spans_skip, parse_frame_at, spans_cover_buffer, symbol_histogram,
};

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let _ = frame_byte_spans_skip(&text);
    let _ = frame_byte_spans(&text);
    let _ = symbol_histogram(&text);
    let _ = spans_cover_buffer(&text);
    let _ = parse_frame_at(&text, 0);
    let _ = parse_frame_at(&text, 1);
});
