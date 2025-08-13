mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn test_writer_roundtrip() {
    let fdat_original =
        fs::read_to_string(test_case!("tiny_multi_cuh2.con")).expect("Can't find test file.");
    let parser_original = ConFrameIterator::new(&fdat_original);
    let frames_original: Vec<_> = parser_original.map(|r| r.unwrap()).collect();

    // Ensure we have something to test.
    assert!(!frames_original.is_empty());

    let mut buffer: Vec<u8> = Vec::new();

    // Introduce a scope so the writer releases its borrow on the buffer.
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write to buffer.");
    } // `writer` is dropped here, borrow ends.

    // Convert the buffer back to a string and re-parse.
    // This move is now valid because the borrow has ended.
    let fdat_roundtrip = String::from_utf8(buffer).expect("Buffer is not valid UTF-8.");
    let parser_roundtrip = ConFrameIterator::new(&fdat_roundtrip);
    let frames_roundtrip: Vec<_> = parser_roundtrip.map(|r| r.unwrap()).collect();

    assert_eq!(
        frames_original.len(),
        frames_roundtrip.len(),
        "Number of frames should be the same after roundtrip."
    );
    assert_eq!(
        frames_original, frames_roundtrip,
        "Frame data should be identical after a read-write-read roundtrip."
    );
}
