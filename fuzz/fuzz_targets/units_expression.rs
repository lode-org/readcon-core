#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::units::{parse_unit_expression, unit_conversion_factor};

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let trimmed = text.trim();
    let _ = parse_unit_expression(trimmed);

    let mut tokens = trimmed.split_ascii_whitespace();
    if let (Some(from), Some(to)) = (tokens.next(), tokens.next()) {
        let _ = unit_conversion_factor(from, to);
    }
});
