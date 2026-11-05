#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::frames_from_bytes;

fuzz_target!(|data: &[u8]| {
    let one = frames_from_bytes(data, Some(1));
    let two = frames_from_bytes(data, Some(2));
    assert_eq!(one.ok(), two.ok());
});
