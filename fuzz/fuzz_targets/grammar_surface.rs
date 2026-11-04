#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::grammar::parse_surface;

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let _ = parse_surface(&text);
});
