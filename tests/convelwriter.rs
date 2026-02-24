mod common;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;
use std::fs;
use std::path::Path;

#[test]
fn test_convel_writer_roundtrip() {
    let fdat = fs::read_to_string(test_case!("tiny_cuh2.convel"))
        .expect("Can't find convel test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert!(!frames_original.is_empty());
    assert!(frames_original[0].has_velocities());

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write convel to buffer.");
    }

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
        "Frame data should be identical after a convel read-write-read roundtrip."
    );
}

#[test]
fn test_convel_multi_writer_roundtrip() {
    let fdat = fs::read_to_string(test_case!("tiny_multi_cuh2.convel"))
        .expect("Can't find multi convel test file.");
    let parser = ConFrameIterator::new(&fdat);
    let frames_original: Vec<_> = parser.map(|r| r.unwrap()).collect();

    assert_eq!(frames_original.len(), 2);
    assert!(frames_original[0].has_velocities());
    assert!(frames_original[1].has_velocities());

    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer
            .extend(frames_original.iter())
            .expect("Failed to write multi convel to buffer.");
    }

    let fdat_roundtrip = String::from_utf8(buffer).expect("Buffer is not valid UTF-8.");
    let parser_roundtrip = ConFrameIterator::new(&fdat_roundtrip);
    let frames_roundtrip: Vec<_> = parser_roundtrip.map(|r| r.unwrap()).collect();

    assert_eq!(frames_original.len(), frames_roundtrip.len());

    for (orig, round) in frames_original.iter().zip(frames_roundtrip.iter()) {
        assert_eq!(orig, round);
    }
}
