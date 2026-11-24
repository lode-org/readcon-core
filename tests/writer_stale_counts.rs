//! A header whose per-type counts no longer match the atom list.
//!
//! The component loops of the writer slice the atom list by
//! `natms_per_type`. A frame that lost or gained an atom without its header
//! following must be an error, not a slice past the end of the list and not
//! a write of only the declared prefix.

use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use readcon_core::writer::{ConFrameWriter, WriteError, write_frames_to_vec_with_threads};

fn frame(path: &str) -> ConFrame {
    let text = std::fs::read_to_string(path).unwrap();
    ConFrameIterator::new(&text).next().unwrap().unwrap()
}

fn write(frame: &ConFrame) -> Result<Vec<u8>, WriteError> {
    let mut out = Vec::new();
    ConFrameWriter::new(&mut out).write_frame(frame)?;
    Ok(out)
}

fn invalid_count(result: Result<Vec<u8>, WriteError>) -> String {
    match result {
        Err(WriteError::Format(ParseError::InvalidCount(message))) => message,
        Err(other) => panic!("expected InvalidCount, got {other}"),
        Ok(bytes) => {
            let text = String::from_utf8_lossy(&bytes);
            panic!("wrote the declared prefix and dropped the extra atoms:\n{text}");
        }
    }
}

#[test]
fn a_frame_that_lost_an_atom_is_an_error() {
    for path in [
        "resources/test/tiny_cuh2.con",
        "resources/test/tiny_cuh2_vel_forces.con",
    ] {
        let mut frame = frame(path);
        let held = frame.atom_data.len();
        frame.atom_data.pop();
        let message = invalid_count(write(&frame));
        assert!(
            message.contains(&held.to_string()) && message.contains(&(held - 1).to_string()),
            "{path}: {message}"
        );
    }
}

#[test]
fn a_frame_that_gained_an_atom_is_an_error() {
    let mut frame = frame("resources/test/tiny_cuh2.con");
    let declared = frame.atom_data.len();
    let mut extra = frame.atom_data[0].clone();
    extra.atom_id = frame
        .atom_data
        .iter()
        .map(|atom| atom.atom_id)
        .max()
        .unwrap_or(0)
        .saturating_add(1);
    frame.atom_data.push(extra);
    let message = invalid_count(write(&frame));
    assert!(
        message.contains(&declared.to_string()) && message.contains(&(declared + 1).to_string()),
        "{message}"
    );
}

#[test]
fn a_stale_count_does_not_poison_the_writer() {
    let good = frame("resources/test/tiny_cuh2_vel_forces.con");
    let mut stale = good.clone();
    stale.atom_data.pop();
    let mut out = Vec::new();
    let mut writer = ConFrameWriter::new(&mut out);
    assert!(writer.write_frame(&stale).is_err());
    writer.write_frame(&good).unwrap();
    drop(writer);
    assert_eq!(out, write(&good).unwrap());
}

#[test]
fn a_matching_header_still_writes() {
    let frame = frame("resources/test/tiny_cuh2_vel_forces.con");
    let text = String::from_utf8(write(&frame).unwrap()).unwrap();
    let again = ConFrameIterator::new(&text).next().unwrap().unwrap();
    assert_eq!(again.atom_data.len(), frame.atom_data.len());
}

#[test]
fn every_writer_entry_rejects_a_stale_header() {
    let mut frame = frame("resources/test/tiny_cuh2.con");
    frame.atom_data.pop();
    let mut out = Vec::new();
    let mut writer = ConFrameWriter::new(&mut out);
    match writer.extend(std::iter::once(&frame)) {
        Err(WriteError::Format(ParseError::InvalidCount(_))) => {}
        Err(other) => panic!("extend: expected InvalidCount, got {other}"),
        Ok(()) => panic!("extend wrote the declared prefix"),
    }
    for workers in [1usize, 4] {
        match write_frames_to_vec_with_threads(std::slice::from_ref(&frame), workers, None, false) {
            Err(WriteError::Format(ParseError::InvalidCount(_))) => {}
            Err(other) => panic!("{workers} workers: expected InvalidCount, got {other}"),
            Ok(_) => panic!("{workers} workers wrote the declared prefix"),
        }
    }
}
