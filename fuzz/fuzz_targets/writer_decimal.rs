//! Round trip and byte identity of the short decimal formatter.
//!
//! Values that are an exact decimal of at most six places take the fixed
//! path. Everything else is spelled by ryu. Both must match `ryu`'s own
//! spelling, parse back to the same bits, and stay byte-identical when the
//! frame is formatted on one thread and on four.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::frames_from_bytes;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::write_frames_to_vec_with_threads;

fn interesting(byte: u8) -> f64 {
    match byte % 16 {
        0 => 0.0,
        1 => -0.0,
        2 => 1.0,
        3 => -1.0,
        4 => 0.1,
        5 => 0.5,
        6 => 0.123456,
        7 => 10.000001,
        8 => 1e-6,
        9 => 1e6,
        10 => 1e15,
        11 => 1e16,
        12 => f64::MIN_POSITIVE,
        13 => f64::from_bits(1),
        14 => f64::MAX,
        _ => -f64::MAX,
    }
}

fn finite_from(data: &[u8], at: usize) -> f64 {
    let mut buf = [0u8; 8];
    for (index, slot) in buf.iter_mut().enumerate() {
        *slot = data.get(at + index).copied().unwrap_or(0);
    }
    let value = f64::from_le_bytes(buf);
    if value.is_finite() { value } else { 0.0 }
}

fn frame_of(values: &[f64]) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for (index, value) in values.iter().copied().enumerate() {
        builder.add_atom(
            "Cu",
            value,
            if index % 2 == 0 { -0.0 } else { 0.25 },
            1.0,
            [false, false, false],
            index as u64,
            63.546,
        );
    }
    builder.build().expect("frame")
}

fn ryu_spell(value: f64) -> String {
    let mut buffer = ryu::Buffer::new();
    buffer.format_finite(value).to_string()
}

fn coord_tokens(text: &str) -> Vec<&str> {
    let marker = "Coordinates of Component 1\n";
    let rest = text.split(marker).nth(1).expect("coordinates");
    let mut tokens = Vec::new();
    for line in rest.lines() {
        if line.is_empty() {
            break;
        }
        tokens.extend(line.split_whitespace().take(3));
    }
    tokens
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 512 {
        return;
    }
    let mut values = Vec::new();
    values.push(interesting(data.first().copied().unwrap_or(0)));
    values.push(interesting(data.get(1).copied().unwrap_or(1)));
    let count = 1 + usize::from(data.get(2).copied().unwrap_or(0) % 8);
    for index in 0..count {
        values.push(finite_from(data, 3 + index * 3));
    }
    let frame = frame_of(&values);
    let frames = [frame];
    let serial = write_frames_to_vec_with_threads(&frames, 1, None, false).expect("serial");
    let threaded = write_frames_to_vec_with_threads(&frames, 4, None, false).expect("threaded");
    assert_eq!(serial, threaded, "formatter bytes diverged across threads");
    let text = std::str::from_utf8(&serial).expect("utf8");
    let parsed = frames_from_bytes(&serial, Some(1)).expect("parse");
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].atom_data.len(), values.len());
    let tokens = coord_tokens(text);
    assert_eq!(tokens.len(), values.len() * 3);
    for (index, value) in values.iter().copied().enumerate() {
        let atom = &parsed[0].atom_data[index];
        assert_eq!(atom.x().to_bits(), value.to_bits(), "x bits {value}");
        assert_eq!(tokens[index * 3], ryu_spell(value), "x spelling {value}");
        let y = if index % 2 == 0 { -0.0f64 } else { 0.25 };
        assert_eq!(atom.y().to_bits(), y.to_bits());
        assert_eq!(tokens[index * 3 + 1], ryu_spell(y));
        assert_eq!(atom.z().to_bits(), 1.0f64.to_bits());
        assert_eq!(tokens[index * 3 + 2], ryu_spell(1.0));
    }
});
