mod common;
use readcon::iterators::ConFrameIterator;
use readcon::types::ConFrame;
use std::fs;
use std::path::Path;

#[test]
fn test_valid_parsing() {
    let fdat = fs::read_to_string(test_case!("cuh2.con")).expect("Can't find test.");
    let parser = ConFrameIterator::new(&fdat);
    let good_frames: Vec<ConFrame> = parser()
        .map(|res| match res {
            Ok(frame) => Some(frame),
            Err(_) => {
                todo!()
            }
        })
        .collect();
    assert_eq!(good_frames.len(), 1);
}
