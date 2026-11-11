//! Decimal scan for coordinate and vector rows.
//!
//! The common CON number is an optional sign, digits, one dot, and more
//! digits, with no exponent. That form is turned into an `f64` here. Anything
//! else (an exponent, a non-finite spelling, more than 19 digits) returns
//! `None` and the caller uses the general parser, which also builds the
//! error text.

/// `5^q` approximations for `q` in `-22..=22`, same words the general
/// decimal conversion uses for that exponent window.
const POW5_LO: i32 = -22;
const POW5: [(u64, u64); 45] = [
    (0xf1c90080baf72cb1, 0x5324c68b12dd6339),
    (0x971da05074da7bee, 0xd3f6fc16ebca5e04),
    (0xbce5086492111aea, 0x88f4bb1ca6bcf585),
    (0xec1e4a7db69561a5, 0x2b31e9e3d06c32e6),
    (0x9392ee8e921d5d07, 0x3aff322e62439fd0),
    (0xb877aa3236a4b449, 0x09befeb9fad487c3),
    (0xe69594bec44de15b, 0x4c2ebe687989a9b4),
    (0x901d7cf73ab0acd9, 0x0f9d37014bf60a11),
    (0xb424dc35095cd80f, 0x538484c19ef38c95),
    (0xe12e13424bb40e13, 0x2865a5f206b06fba),
    (0x8cbccc096f5088cb, 0xf93f87b7442e45d4),
    (0xafebff0bcb24aafe, 0xf78f69a51539d749),
    (0xdbe6fecebdedd5be, 0xb573440e5a884d1c),
    (0x89705f4136b4a597, 0x31680a88f8953031),
    (0xabcc77118461cefc, 0xfdc20d2b36ba7c3e),
    (0xd6bf94d5e57a42bc, 0x3d32907604691b4d),
    (0x8637bd05af6c69b5, 0xa63f9a49c2c1b110),
    (0xa7c5ac471b478423, 0x0fcf80dc33721d54),
    (0xd1b71758e219652b, 0xd3c36113404ea4a9),
    (0x83126e978d4fdf3b, 0x645a1cac083126ea),
    (0xa3d70a3d70a3d70a, 0x3d70a3d70a3d70a4),
    (0xcccccccccccccccc, 0xcccccccccccccccd),
    (0x8000000000000000, 0x0),
    (0xa000000000000000, 0x0),
    (0xc800000000000000, 0x0),
    (0xfa00000000000000, 0x0),
    (0x9c40000000000000, 0x0),
    (0xc350000000000000, 0x0),
    (0xf424000000000000, 0x0),
    (0x9896800000000000, 0x0),
    (0xbebc200000000000, 0x0),
    (0xee6b280000000000, 0x0),
    (0x9502f90000000000, 0x0),
    (0xba43b74000000000, 0x0),
    (0xe8d4a51000000000, 0x0),
    (0x9184e72a00000000, 0x0),
    (0xb5e620f480000000, 0x0),
    (0xe35fa931a0000000, 0x0),
    (0x8e1bc9bf04000000, 0x0),
    (0xb1a2bc2ec5000000, 0x0),
    (0xde0b6b3a76400000, 0x0),
    (0x8ac7230489e80000, 0x0),
    (0xad78ebc5ac620000, 0x0),
    (0xd8d726b7177a8000, 0x0),
    (0x878678326eac9000, 0x0),
];

const POW10: [f64; 23] = [
    1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15, 1e16,
    1e17, 1e18, 1e19, 1e20, 1e21, 1e22,
];

/// Largest mantissa the short division path rounds correctly.
const MAX_FAST_MANTISSA: u64 = 2_u64 << 52;

struct Adjusted {
    mantissa: u64,
    power2: i32,
}

#[inline(always)]
fn is_8digits(v: u64) -> bool {
    let a = v.wrapping_add(0x4646_4646_4646_4646);
    let b = v.wrapping_sub(0x3030_3030_3030_3030);
    (a | b) & 0x8080_8080_8080_8080 == 0
}

#[inline(always)]
fn parse_8digits(mut v: u64) -> u64 {
    const MASK: u64 = 0x0000_00FF_0000_00FF;
    const MUL1: u64 = 0x000F_4240_0000_0064;
    const MUL2: u64 = 0x0000_2710_0000_0001;
    v -= 0x3030_3030_3030_3030;
    v = (v * 10) + (v >> 8);
    let v1 = (v & MASK).wrapping_mul(MUL1);
    let v2 = ((v >> 16) & MASK).wrapping_mul(MUL2);
    ((v1.wrapping_add(v2) >> 32) as u32) as u64
}

#[inline(always)]
fn read_u64(bytes: &[u8], i: usize) -> u64 {
    let mut buf = [0u8; 8];
    buf.copy_from_slice(&bytes[i..i + 8]);
    u64::from_le_bytes(buf)
}

/// Parse one decimal at `i`. The returned index is the first byte after the
/// number. `None` means the general parser must handle this token.
#[inline(always)]
pub(crate) fn parse_f64_hot(bytes: &[u8], i: usize) -> Option<(f64, usize)> {
    if i >= bytes.len() {
        return None;
    }
    let mut p = i;
    let mut neg = false;
    match bytes[p] {
        b'+' => p += 1,
        b'-' => {
            neg = true;
            p += 1;
        }
        _ => {}
    }
    if p >= bytes.len() {
        return None;
    }
    let lead = bytes[p];
    if !lead.is_ascii_digit() && lead != b'.' {
        return None;
    }

    let mut mant: u64 = 0;
    let mut exp: i32 = 0;
    let mut ndigits: u32 = 0;

    while p < bytes.len() && bytes[p].is_ascii_digit() {
        if ndigits == 19 {
            return None;
        }
        mant = mant * 10 + u64::from(bytes[p] - b'0');
        ndigits += 1;
        p += 1;
    }
    if p < bytes.len() && bytes[p] == b'.' {
        p += 1;
        while p + 8 <= bytes.len() && ndigits <= 11 {
            let word = read_u64(bytes, p);
            if !is_8digits(word) {
                break;
            }
            mant = mant
                .wrapping_mul(100_000_000)
                .wrapping_add(parse_8digits(word));
            ndigits += 8;
            exp -= 8;
            p += 8;
        }
        while p < bytes.len() && bytes[p].is_ascii_digit() {
            if ndigits == 19 {
                return None;
            }
            mant = mant * 10 + u64::from(bytes[p] - b'0');
            ndigits += 1;
            exp -= 1;
            p += 1;
        }
    }
    if ndigits == 0 {
        return None;
    }
    if p < bytes.len() && (bytes[p] == b'e' || bytes[p] == b'E') {
        return None;
    }
    let val = finish(neg, mant, exp)?;
    Some((val, p))
}

#[inline(always)]
fn finish(neg: bool, mant: u64, exp: i32) -> Option<f64> {
    if mant == 0 {
        return Some(if neg { -0.0 } else { 0.0 });
    }
    if mant <= MAX_FAST_MANTISSA && (-22..=22).contains(&exp) {
        let mut value = mant as f64;
        if exp < 0 {
            value /= POW10[(-exp) as usize];
        } else if exp > 0 {
            value *= POW10[exp as usize];
        }
        if neg {
            value = -value;
        }
        return Some(value);
    }
    if !(-22..=22).contains(&exp) {
        return None;
    }
    let adjusted = compute_float(i64::from(exp), mant);
    if adjusted.power2 < 0 {
        return None;
    }
    let mut word = adjusted.mantissa;
    word |= (adjusted.power2 as u64) << 52;
    if neg {
        word |= 1_u64 << 63;
    }
    let value = f64::from_bits(word);
    value.is_finite().then_some(value)
}

#[inline]
fn compute_float(q: i64, mut w: u64) -> Adjusted {
    let lz = w.leading_zeros();
    w <<= lz;
    let (lo, hi) = product(q, w);
    let upperbit = (hi >> 63) as i32;
    let mut mantissa = hi >> (upperbit + 64 - 52 - 3);
    let mut power2 = power(q as i32) + upperbit - lz as i32 - (-1023);
    if power2 <= 0 {
        if -power2 + 1 >= 64 {
            return Adjusted {
                mantissa: 0,
                power2: 0,
            };
        }
        mantissa >>= -power2 + 1;
        mantissa += mantissa & 1;
        mantissa >>= 1;
        power2 = i32::from(mantissa >= (1_u64 << 52));
        return Adjusted { mantissa, power2 };
    }
    if lo <= 1
        && (-4..=23).contains(&q)
        && mantissa & 3 == 1
        && (mantissa << (upperbit + 64 - 52 - 3)) == hi
    {
        mantissa &= !1_u64;
    }
    mantissa += mantissa & 1;
    mantissa >>= 1;
    if mantissa >= (2_u64 << 52) {
        mantissa = 1_u64 << 52;
        power2 += 1;
    }
    mantissa &= !(1_u64 << 52);
    if power2 >= 0x7FF {
        return Adjusted {
            mantissa: 0,
            power2: -1,
        };
    }
    Adjusted { mantissa, power2 }
}

#[inline(always)]
fn power(q: i32) -> i32 {
    (q.wrapping_mul(152_170 + 65536) >> 16) + 63
}

#[inline(always)]
fn product(q: i64, w: u64) -> (u64, u64) {
    // 52 explicit bits plus 3 guard bits. The mask is the low 9 bits.
    const MASK: u64 = 0xFFFF_FFFF_FFFF_FFFF >> 55;
    let index = (q - i64::from(POW5_LO)) as usize;
    let (lo5, hi5) = POW5[index];
    let first = (w as u128).wrapping_mul(lo5 as u128);
    let mut first_lo = first as u64;
    let mut first_hi = (first >> 64) as u64;
    if first_hi & MASK == MASK {
        let second_hi = (((w as u128).wrapping_mul(hi5 as u128)) >> 64) as u64;
        first_lo = first_lo.wrapping_add(second_hi);
        if second_hi > first_lo {
            first_hi += 1;
        }
    }
    (first_lo, first_hi)
}

#[cfg(test)]
mod tests {
    use super::parse_f64_hot;

    fn bits_of(text: &str) -> Option<u64> {
        let (val, n) = parse_f64_hot(text.as_bytes(), 0)?;
        if n != text.len() {
            return None;
        }
        Some(val.to_bits())
    }

    fn reference(text: &str) -> u64 {
        let (val, n) = fast_float2::parse_partial::<f64, _>(text).unwrap();
        assert_eq!(n, text.len(), "{text}");
        val.to_bits()
    }

    #[test]
    fn hot_decimals_match_the_general_parser() {
        let mut samples = vec![
            "0".into(),
            "0.0".into(),
            "-0".into(),
            "-0.0".into(),
            "1".into(),
            "-1".into(),
            "+2".into(),
            "0.5".into(),
            ".5".into(),
            "1.".into(),
            "-.25".into(),
            "10.5".into(),
            "218".into(),
            "63.546".into(),
            "1.00793".into(),
            "15.3456".into(),
            "90.0".into(),
            "0.6394".into(),
            "0.63939999999999997".into(),
            "3.19639999999999969".into(),
            "13.42440000000000033".into(),
            "-0.003456".into(),
            "0.00000000000000000".into(),
            "10000000000000000".into(),
            "9007199254740992".into(),
            "9007199254740993".into(),
        ];
        for digits in 1..=19 {
            let mut token = String::new();
            for i in 0..digits {
                token.push(char::from(b'0' + ((i * 3 + 1) % 10) as u8));
            }
            samples.push(token.clone());
            if digits > 1 {
                let (head, tail) = token.split_at(1);
                samples.push(format!("{head}.{tail}"));
                samples.push(format!("-{head}.{tail}"));
                samples.push(format!("0.{token}"));
                samples.push(format!("-0.{token}"));
            }
        }
        for shift in 0..12 {
            let x = (shift as f64) * 2.557 + 0.6394 + (shift as f64) * 1.0e-4;
            samples.push(format!("{x:.17}"));
            samples.push(format!("{x:.6}"));
            samples.push(format!("{:-.17}", -x));
        }
        let mut saw_long = false;
        for text in &samples {
            match bits_of(text) {
                Some(got) => {
                    assert_eq!(got, reference(text), "{text}");
                    if text.contains("63939999999999997") {
                        saw_long = true;
                    }
                }
                None => {
                    // Exponents, non-finite spellings, and more than 19 digits
                    // stay on the general parser. It must still accept the token.
                    let _ = reference(text);
                }
            }
        }
        assert!(saw_long, "17-digit coordinates must stay on the hot path");
    }

    #[test]
    fn hot_path_rejects_exponents_and_nonfinite() {
        for text in ["1e-2", "1E10", "nan", "inf", "-inf", ""] {
            assert!(parse_f64_hot(text.as_bytes(), 0).is_none(), "{text}");
        }
        // A second dot ends the number. The row parser then rejects the
        // leftover, so this token is not accepted as a coordinate field.
        let (val, n) = parse_f64_hot(b"1.2.3", 0).unwrap();
        assert_eq!(n, 3);
        assert_eq!(val.to_bits(), 1.2f64.to_bits());
        assert_eq!(b"1.2.3"[n], b'.');
    }

    /// xorshift64. The seed is fixed so a failure reprints the same string.
    struct Rng(u64);

    impl Rng {
        fn next_u64(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            self.0 = x;
            x
        }

        fn below(&mut self, n: usize) -> usize {
            (self.next_u64() as usize) % n
        }
    }

    fn push_digits(rng: &mut Rng, out: &mut Vec<u8>, n: usize, lead_zero: bool) {
        for i in 0..n {
            let digit = if i == 0 && !lead_zero {
                1 + rng.below(9)
            } else if lead_zero && rng.below(3) == 0 {
                0
            } else {
                rng.below(10)
            };
            out.push(b'0' + digit as u8);
        }
    }

    /// One decimal token, possibly followed by junk the scan must not swallow.
    fn push_token(rng: &mut Rng, out: &mut Vec<u8>, kind: usize) {
        out.clear();
        let sign = rng.below(3);
        if sign == 1 {
            out.push(b'+');
        } else if sign == 2 {
            out.push(b'-');
        }
        match kind % 8 {
            0 | 1 | 2 => {
                // In-range form: 1..=19 digits, optional dot, optional trailing dot.
                let digits = 1 + rng.below(19);
                let lead_zero = rng.below(2) == 0;
                let dot_at = rng.below(digits + 1);
                push_digits(rng, out, digits, lead_zero);
                if dot_at < digits {
                    out.insert(out.len() - (digits - dot_at), b'.');
                } else if rng.below(4) == 0 {
                    out.push(b'.');
                }
            }
            3 => {
                // 20-digit mantissa. The scan must fall back.
                let lead_zero = rng.below(2) == 0;
                push_digits(rng, out, 20, lead_zero);
                if rng.below(2) == 0 {
                    let at = 1 + rng.below(19);
                    out.insert(out.len() - at, b'.');
                }
            }
            4 => {
                // Magnitude near the subnormal and overflow edges, written
                // with an exponent so the simple scan has to refuse it.
                let exp: i32 = match rng.below(8) {
                    0 => -324,
                    1 => -323,
                    2 => -308,
                    3 => -307,
                    4 => 308,
                    5 => 309,
                    6 => -400 + rng.below(50) as i32,
                    _ => 280 + rng.below(40) as i32,
                };
                let body = 1 + rng.below(6);
                push_digits(rng, out, body, false);
                if rng.below(2) == 0 {
                    out.push(b'.');
                    let frac = rng.below(8);
                    push_digits(rng, out, frac, true);
                }
                out.push(if rng.below(2) == 0 { b'e' } else { b'E' });
                if exp < 0 {
                    out.push(b'-');
                }
                out.extend(exp.unsigned_abs().to_string().bytes());
            }
            5 => {
                // Long run of zeros after the point: subnormal or underflow
                // if it were accepted, and past the 19-digit cutoff.
                out.push(b'0');
                out.push(b'.');
                let zeros = 20 + rng.below(340);
                out.extend(std::iter::repeat(b'0').take(zeros));
                out.push(b'1');
            }
            6 => {
                // Explicit fallback spellings and empty prefixes.
                const SPELL: [&[u8]; 8] =
                    [b"", b"+", b"-", b".", b"nan", b"inf", b"+Infinity", b"-inf"];
                out.extend_from_slice(SPELL[rng.below(SPELL.len())]);
            }
            _ => {
                // Leading zeros, a short body, and a trailing dot.
                let zeros = rng.below(8);
                out.extend(std::iter::repeat(b'0').take(zeros));
                let body = 1 + rng.below(12);
                push_digits(rng, out, body, false);
                out.push(b'.');
                if rng.below(2) == 0 {
                    let frac = rng.below(6);
                    push_digits(rng, out, frac, true);
                }
            }
        }
        // Junk after the token. An exponent marker forces a fallback.
        match rng.below(6) {
            0 => out.push(b' '),
            1 => out.push(b'x'),
            2 => out.extend_from_slice(b"e10"),
            3 => out.push(b'\n'),
            _ => {}
        }
    }

    fn agree(bytes: &[u8], at: usize) -> bool {
        let hot = parse_f64_hot(bytes, at);
        let reference = fast_float2::parse_partial::<f64, _>(&bytes[at..]);
        match (hot, reference) {
            (Some((got, end)), Ok((want, n))) => {
                assert_eq!(
                    end,
                    at + n,
                    "length mismatch on {:?} at {at}",
                    String::from_utf8_lossy(bytes)
                );
                assert_eq!(
                    got.to_bits(),
                    want.to_bits(),
                    "bit mismatch on {:?} at {at}: scanner {:e} reference {:e}",
                    String::from_utf8_lossy(bytes),
                    got,
                    want
                );
                false
            }
            (Some((got, end)), Err(_)) => {
                panic!(
                    "scanner accepted {:?} at {at} as {got:e} ending at {end}, reference rejected it",
                    String::from_utf8_lossy(bytes)
                );
            }
            (None, _) => true,
        }
    }

    #[test]
    fn random_decimals_match_fast_float_bits() {
        let mut rng = Rng(0x5eed_f64d_ec17_a10d);
        let mut token = Vec::with_capacity(400);
        let mut buf = Vec::with_capacity(420);
        let mut accepted = 0usize;
        let mut fallback = 0usize;
        let mut saw_sign = false;
        let mut saw_lead_zero = false;
        let mut saw_trail_dot = false;
        let mut saw_twenty = false;
        let mut saw_extreme = false;
        const N: usize = 1_000_000;
        for i in 0..N {
            push_token(&mut rng, &mut token, i);
            let text = String::from_utf8(token.clone()).unwrap();
            if text.starts_with('+') || text.starts_with('-') {
                saw_sign = true;
            }
            if text.contains("00") {
                saw_lead_zero = true;
            }
            if text.contains('.')
                && !text
                    .as_bytes()
                    .windows(2)
                    .any(|w| w[0] == b'.' && w[1].is_ascii_digit())
            {
                saw_trail_dot = true;
            }
            let digits = text.bytes().filter(|b| b.is_ascii_digit()).count();
            if digits >= 20 && !text.bytes().any(|b| b == b'e' || b == b'E') {
                saw_twenty = true;
                assert!(
                    parse_f64_hot(text.as_bytes(), 0).is_none(),
                    "20-digit mantissa must fall back: {text}"
                );
            }
            if text.bytes().any(|b| b == b'e' || b == b'E')
                || text.bytes().filter(|b| *b == b'0').count() > 24
            {
                saw_extreme = true;
            }
            if agree(text.as_bytes(), 0) {
                fallback += 1;
            } else {
                accepted += 1;
            }
            // The same token starting later in a buffer.
            if i % 32 == 0 {
                buf.clear();
                buf.extend_from_slice(b"[]");
                buf.extend_from_slice(text.as_bytes());
                let fell = agree(&buf, 2);
                if fell {
                    fallback += 1;
                } else {
                    accepted += 1;
                }
            }
        }
        assert!(saw_sign && saw_lead_zero && saw_trail_dot && saw_twenty && saw_extreme);
        assert!(
            accepted > 400_000,
            "accepted {accepted}, expected the hot path to take a large share"
        );
        assert!(
            fallback > 200_000,
            "fallback {fallback}, expected exponents, long mantissas, and non-finite spellings"
        );
    }
}
