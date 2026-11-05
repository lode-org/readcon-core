#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::parser::parse_frame_header;

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let mut lines = text.lines();
    let _ = parse_frame_header(&mut lines);
});
