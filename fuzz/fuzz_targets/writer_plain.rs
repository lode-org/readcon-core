#![no_main]

use libfuzzer_sys::fuzz_target;

#[path = "writer_gen.rs"]
mod writer_gen;

fuzz_target!(|data: &[u8]| {
    if data.len() > 4096 {
        return;
    }
    let Some(frames) = writer_gen::frames_from(data, false) else {
        return;
    };
    writer_gen::assert_threads_match(&frames);
});
