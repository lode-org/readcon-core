//! Distinct CON frames. The nudge matches ``bench/h2h/frames_guard.py``.
//!
//! Each frame has its own PCG32 stream. Coordinate fields keep their width,
//! so a copied cuh2 frame stays 16771 bytes. Identical frames panic.

use std::collections::HashSet;

pub fn distinct_frames(text: &str, n: usize) -> String {
    let one = if text.ends_with('\n') {
        text.to_string()
    } else {
        format!("{text}\n")
    };
    let mut out = String::with_capacity(one.len().saturating_mul(n));
    let mut seen = HashSet::with_capacity(n);
    for frame in 0..n {
        let rewritten = perturb_frame(&one, frame);
        if n > 1 && !seen.insert(rewritten.clone()) {
            panic!("byte-identical frames; a repeated frame measures a copy, not a parse");
        }
        out.push_str(&rewritten);
    }
    out
}

fn perturb_frame(text: &str, frame: usize) -> String {
    let mut state = frame_state(frame);
    let mut out = String::with_capacity(text.len());
    for line in text.split_inclusive('\n') {
        let (body, newline) = line
            .strip_suffix('\n')
            .map(|body| (body, true))
            .unwrap_or((line, false));
        if !is_coord(body) {
            out.push_str(line);
            continue;
        }
        out.push_str(&bump_coords(body, &mut state));
        if newline {
            out.push('\n');
        }
    }
    out
}

fn is_coord(body: &str) -> bool {
    let parts: Vec<&str> = body.split_whitespace().collect();
    if parts.len() < 5 {
        return false;
    }
    parts[0].parse::<f64>().is_ok()
        && parts[1].parse::<f64>().is_ok()
        && parts[2].parse::<f64>().is_ok()
        && parts[3].parse::<i64>().is_ok()
        && parts[4].parse::<i64>().is_ok()
}

fn bump_coords(body: &str, state: &mut u64) -> String {
    let bytes = body.as_bytes();
    let mut out = String::with_capacity(body.len());
    let mut index = 0usize;
    let mut bumped = 0usize;
    while index < bytes.len() && bumped < 3 {
        if let Some(end) = float_at(bytes, index) {
            let token = &body[index..end];
            let draw = pcg32(state);
            out.push_str(&bump_token(token, draw));
            index = end;
            bumped += 1;
        } else {
            out.push(body[index..].chars().next().unwrap());
            index += body[index..].chars().next().unwrap().len_utf8();
        }
    }
    out.push_str(&body[index..]);
    out
}

fn float_at(bytes: &[u8], start: usize) -> Option<usize> {
    let mut index = start;
    if index < bytes.len() && (bytes[index] == b'+' || bytes[index] == b'-') {
        index += 1;
    }
    let digits = index;
    while index < bytes.len() && bytes[index].is_ascii_digit() {
        index += 1;
    }
    if index == digits || index >= bytes.len() || bytes[index] != b'.' {
        return None;
    }
    index += 1;
    let frac = index;
    while index < bytes.len() && bytes[index].is_ascii_digit() {
        index += 1;
    }
    if index == frac {
        return None;
    }
    Some(index)
}

fn bump_token(token: &str, draw: u32) -> String {
    let mut chars: Vec<char> = token.chars().collect();
    let delta = (draw % 9) + 1;
    for index in (0..chars.len()).rev() {
        if chars[index].is_ascii_digit() {
            let digit = chars[index].to_digit(10).unwrap();
            chars[index] = char::from_digit((digit + delta) % 10, 10).unwrap();
            return chars.into_iter().collect();
        }
    }
    token.to_string()
}

fn frame_state(frame: usize) -> u64 {
    let mixed = 1u64
        ^ ((frame as u64)
            .wrapping_add(1)
            .wrapping_mul(0x9E3779B97F4A7C15))
        ^ 0xC0FFEE;
    splitmix64(mixed)
}

fn splitmix64(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

fn pcg32(state: &mut u64) -> u32 {
    *state = state
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    let xorshifted = (((*state >> 18) ^ *state) >> 27) as u32;
    let rot = (*state >> 59) as u32;
    xorshifted.rotate_right(rot)
}
