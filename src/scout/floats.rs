//! `fast_dec` against `fast_float2` on coordinate tokens.
//!
//! Lemire's parser (Software: Practice and Experience 51, 2021,
//! <https://doi.org/10.1002/spe.2984>, <https://arxiv.org/abs/2101.11408>)
//! is already the fallback in this crate. The hot kernel is a shorter
//! decimal. This times both on tokens taken from a CON buffer. Tokens the
//! hot kernel refuses are counted and left out of both clocks.

use std::time::Instant;

/// One in-process warmup and six samples. The samples are seconds.
#[derive(Debug, Clone)]
pub struct FloatReport {
    pub n_numbers: usize,
    pub fallbacks: usize,
    pub mismatches: usize,
    pub fast_dec_s: Vec<f64>,
    pub fast_float_s: Vec<f64>,
}

/// Parse up to `limit` coordinate-like tokens from `bytes`.
pub fn bench_float_kernels(bytes: &[u8], limit: usize) -> FloatReport {
    let tokens = collect_tokens(bytes, limit);
    let mut mismatches = 0usize;
    let mut keep_ends = Vec::with_capacity(tokens.ends.len());
    let mut start = 0usize;
    for &end in &tokens.ends {
        let token = &tokens.buf[start..end];
        let hot = crate::fast_dec::parse_f64_hot(token, 0).filter(|(_, n)| *n == token.len());
        let general = fast_float2::parse_partial::<f64, _>(token).ok();
        match (hot, general) {
            (Some((left, _)), Some((right, n))) if n == token.len() => {
                if left.to_bits() != right.to_bits() {
                    mismatches += 1;
                } else {
                    keep_ends.push(end);
                }
            }
            _ => {}
        }
        start = end;
    }
    let fallbacks = tokens.ends.len() - keep_ends.len() - mismatches;
    let kept = compact(&tokens.buf, &tokens.ends, &keep_ends);
    FloatReport {
        n_numbers: kept.ends.len(),
        fallbacks,
        mismatches,
        fast_dec_s: time_kernel(&kept, true),
        fast_float_s: time_kernel(&kept, false),
    }
}

struct Tokens {
    buf: Vec<u8>,
    ends: Vec<usize>,
}

fn collect_tokens(bytes: &[u8], limit: usize) -> Tokens {
    let mut out = Tokens {
        buf: Vec::new(),
        ends: Vec::new(),
    };
    let mut pos = 0usize;
    while pos < bytes.len() && out.ends.len() < limit {
        let rest = &bytes[pos..];
        let (line, advance) = match memchr::memchr(b'\n', rest) {
            Some(i) => (&rest[..i], i + 1),
            None => (rest, rest.len()),
        };
        pos += advance;
        let mut index = 0usize;
        let mut taken = 0usize;
        while taken < 3 && out.ends.len() < limit {
            let Some((start, end)) = next_token(line, index) else {
                break;
            };
            index = end;
            let token = &line[start..end];
            if looks_numeric(token) {
                out.buf.extend_from_slice(token);
                out.ends.push(out.buf.len());
                taken += 1;
            }
        }
    }
    out
}

fn compact(buf: &[u8], ends: &[usize], keep: &[usize]) -> Tokens {
    let mut out = Tokens {
        buf: Vec::new(),
        ends: Vec::with_capacity(keep.len()),
    };
    let mut prev = 0usize;
    let mut keep_at = 0usize;
    for &end in ends {
        if keep_at < keep.len() && keep[keep_at] == end {
            out.buf.extend_from_slice(&buf[prev..end]);
            out.ends.push(out.buf.len());
            keep_at += 1;
        }
        prev = end;
    }
    out
}

fn time_kernel(tokens: &Tokens, hot: bool) -> Vec<f64> {
    let once = || -> u64 {
        let mut acc = 0u64;
        let mut start = 0usize;
        for &end in &tokens.ends {
            let token = &tokens.buf[start..end];
            let bits = if hot {
                crate::fast_dec::parse_f64_hot(token, 0).map(|(value, _)| value.to_bits())
            } else {
                fast_float2::parse_partial::<f64, _>(token)
                    .ok()
                    .map(|(value, _)| value.to_bits())
            };
            acc ^= bits.unwrap_or(0);
            start = end;
        }
        acc
    };
    let warm = once();
    std::hint::black_box(warm);
    let mut samples = Vec::with_capacity(6);
    for _ in 0..6 {
        let started = Instant::now();
        let acc = once();
        let elapsed = started.elapsed().as_secs_f64();
        std::hint::black_box(acc);
        samples.push(elapsed);
    }
    samples
}

fn looks_numeric(token: &[u8]) -> bool {
    matches!(token.first(), Some(b'+' | b'-' | b'.' | b'0'..=b'9'))
}

fn next_token(line: &[u8], mut index: usize) -> Option<(usize, usize)> {
    while index < line.len() && line[index].is_ascii_whitespace() {
        index += 1;
    }
    if index >= line.len() {
        return None;
    }
    let start = index;
    while index < line.len() && !line[index].is_ascii_whitespace() {
        index += 1;
    }
    Some((start, index))
}
