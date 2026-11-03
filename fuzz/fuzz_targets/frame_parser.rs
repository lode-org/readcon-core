#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::ConFrameIterator;

fuzz_target!(|data: &[u8]| {
    // A frame that parses consumes input and the loop stops at the first
    // error, so more results than bytes mean the iterator stopped consuming.
    let mut results = 0usize;
    for result in ConFrameIterator::from_bytes(data) {
        results += 1;
        assert!(results <= data.len() + 1);
        if result.is_err() {
            break;
        }
    }
});
