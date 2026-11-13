#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::parser::{
    NUMERIC_STACK_WIDTH, parse_line_of_n, parse_line_of_n_f64, parse_line_of_range_f64,
    parse_line_of_range_f64_stack,
};

// Byte 0 is the most values asked for and byte 1 the fewest; the rest is the
// line. The exact-count parsers also get `usize::MAX - max`, far more values
// than any line holds.
fuzz_target!(|data: &[u8]| {
    let [max, min, rest @ ..] = data else {
        return;
    };
    let Ok(line) = std::str::from_utf8(rest) else {
        return;
    };
    let max = usize::from(*max);
    let min = usize::from(*min).min(max);
    for n in [max, usize::MAX - max] {
        let _ = parse_line_of_n_f64(line, n);
        let _ = parse_line_of_n::<u64>(line, n);
    }
    let defaults: Vec<f64> = (0..max).map(|i| i as f64).collect();
    let _ = parse_line_of_range_f64(line, min, max, &defaults);
    let stack_max = max.min(NUMERIC_STACK_WIDTH);
    let mut stack = [0.0_f64; NUMERIC_STACK_WIDTH];
    let _ = parse_line_of_range_f64_stack(line, min.min(stack_max), stack_max, &defaults, &mut stack);
});
