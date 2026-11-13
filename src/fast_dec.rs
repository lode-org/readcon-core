//! Decimal scan for coordinate and vector rows.
//!
//! The common CON number is an optional sign, digits, one dot, and more
//! digits, with no exponent. That form is turned into an `f64` here. An
//! exponent or a non-finite spelling returns `None` and the caller uses the
//! general parser, which also builds the error text.
//!
//! A fixed-point dump such as `{:.17}` is often 20 digits once the integer
//! part has three places (`125.9324…`). Those digits do not fit in one `u64`,
//! so the scan keeps the leading 19 and accepts the value only when moving
//! the last digit by one does not change the rounded `f64`. A leading zero
//! that would push a significant digit out of that window still returns
//! `None`.

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
    // Every caller proves `i + 8 <= bytes.len()` before this load, so the
    // eight bytes are inside the slice. That includes the last word of a
    // mapped file with no trailing newline: the slice length is the map
    // length, and a word that ends on that length is still in range.
    // `parse_fixed_decimal` checks `dot + 16 < len` and then steps onto
    // the first fraction digit, so both words end at or before `len`.
    // `parse_f64_hot` and `parse_f64_long` check `p + 8 <= len`.
    debug_assert!(i + 8 <= bytes.len());
    let ptr = bytes.as_ptr().wrapping_add(i);
    u64::from_le(unsafe { (ptr as *const u64).read_unaligned() })
}

#[inline(always)]
pub(crate) fn decimal_f64(neg: bool, mant: u64, exp: i32) -> Option<f64> {
    finish(neg, mant, exp)
}

/// Plain decimal with a dot and 16 fraction digits, plus an optional 17th.
///
/// Returns `None` as soon as the shape does not match, before a second scan.
/// A third integer digit and a 17th fraction digit is 20 digits: the extra
/// digit stays out of the mantissa and only confirms the rounding.
#[inline(always)]
pub(crate) fn parse_fixed_decimal(bytes: &[u8], mut i: usize) -> Option<(f64, usize)> {
    if i >= bytes.len() {
        return None;
    }
    let mut neg = false;
    match bytes[i] {
        b'+' => i += 1,
        b'-' => {
            neg = true;
            i += 1;
        }
        _ => {}
    }
    if i >= bytes.len() || !bytes[i].is_ascii_digit() {
        return None;
    }
    let mut mant = u64::from(bytes[i] - b'0');
    let mut nd = 1u32;
    i += 1;
    while i < bytes.len() && bytes[i].is_ascii_digit() {
        if nd == 3 {
            return None;
        }
        mant = mant * 10 + u64::from(bytes[i] - b'0');
        nd += 1;
        i += 1;
    }
    // `i` is the dot. Sixteen fraction bytes must sit in the slice, so
    // after stepping onto the first of them the two 8-byte words end at
    // or before `len`, even when the file ends on that digit.
    if i >= bytes.len() || bytes[i] != b'.' || i + 16 >= bytes.len() {
        return None;
    }
    i += 1;
    let w0 = read_u64(bytes, i);
    if !is_8digits(w0) {
        return None;
    }
    let w1 = read_u64(bytes, i + 8);
    if !is_8digits(w1) {
        return None;
    }
    mant = mant
        .wrapping_mul(100_000_000)
        .wrapping_add(parse_8digits(w0))
        .wrapping_mul(100_000_000)
        .wrapping_add(parse_8digits(w1));
    i += 16;
    let mut exp = -16i32;
    let mut sticky = false;
    if i < bytes.len() && bytes[i].is_ascii_digit() {
        if i + 1 < bytes.len() && bytes[i + 1].is_ascii_digit() {
            return None;
        }
        if nd + 17 > 19 {
            sticky = bytes[i] != b'0';
        } else {
            mant = mant * 10 + u64::from(bytes[i] - b'0');
            exp = -17;
        }
        i += 1;
    }
    if i < bytes.len() && bytes[i] != b' ' {
        return None;
    }
    let val = if sticky {
        // The 20th digit sits strictly between `mant` and `mant + 1`.
        finish_unit_interval(neg, mant, exp)?
    } else {
        decimal_f64(neg, mant, exp)?
    };
    Some((val, i))
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

/// More than 19 digits. Kept out of [`parse_f64_hot`] so the common
/// coordinate loop does not carry this state.
#[cold]
#[inline(never)]
pub(crate) fn parse_f64_long(bytes: &[u8], i: usize) -> Option<(f64, usize)> {
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
    // A leading zero would fill the 19-digit window and drop a later
    // significant digit. Leave that token to the general parser.
    let fragile = lead == b'0' || (lead == b'.' && (p + 1 >= bytes.len() || bytes[p + 1] == b'0'));

    let mut mant: u64 = 0;
    let mut exp: i32 = 0;
    let mut ndigits: u32 = 0;
    let mut many = false;
    let mut sticky = false;
    let mut extra = 0u32;

    while p < bytes.len() && bytes[p].is_ascii_digit() {
        if ndigits == 19 {
            if fragile || extra == 40 {
                return None;
            }
            many = true;
            extra += 1;
            if bytes[p] != b'0' {
                sticky = true;
            }
            exp += 1;
            p += 1;
            continue;
        }
        mant = mant * 10 + u64::from(bytes[p] - b'0');
        ndigits += 1;
        p += 1;
    }
    if p < bytes.len() && bytes[p] == b'.' {
        p += 1;
        if !many {
            while p + 8 <= bytes.len() && ndigits + 8 <= 19 {
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
        }
        while p < bytes.len() && bytes[p].is_ascii_digit() {
            if ndigits == 19 {
                if fragile || extra == 40 {
                    return None;
                }
                many = true;
                extra += 1;
                if bytes[p] != b'0' {
                    sticky = true;
                }
                p += 1;
                continue;
            }
            mant = mant * 10 + u64::from(bytes[p] - b'0');
            ndigits += 1;
            exp -= 1;
            p += 1;
        }
    }
    if ndigits == 0 || !many {
        return None;
    }
    if p < bytes.len() && (bytes[p] == b'e' || bytes[p] == b'E') {
        return None;
    }
    if sticky {
        // The unread tail sits strictly between `mant` and `mant + 1` at this
        // scale. When both round to the same `f64`, that is the only result
        // the general parser can return.
        let low = finish_unit_interval(neg, mant, exp)?;
        return Some((low, p));
    }
    finish(neg, mant, exp).map(|val| (val, p))
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
    // The short division above needs a mantissa that fits in an `f64`.
    // A wider one is `round(w) + (w - round(w))` over the exact power of
    // ten. The residual of that division is an `fma`, so the common
    // 16/17-digit fixed spelling does not take the general product.
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

#[inline(always)]
fn compute_float(q: i64, mut w: u64) -> Adjusted {
    let lz = w.leading_zeros();
    w <<= lz;
    let (lo, hi) = product(q, w);
    adjusted_from_product(q, lo, hi, lz)
}

/// `mant * 10^exp` when `(mant + 1) * 10^exp` rounds to the same `f64`.
///
/// One product covers a gap that stays on one side of a midpoint, including
/// a single step off a round bit that is already set. A pair of products
/// covers a midpoint, and `None` there means the two sides disagree.
#[inline(always)]
fn finish_unit_interval(neg: bool, mant: u64, exp: i32) -> Option<f64> {
    if let Some(value) = proved_same_neighbor(neg, mant, exp) {
        return Some(value);
    }
    let low = finish(neg, mant, exp)?;
    let high = finish(neg, mant.checked_add(1)?, exp)?;
    (low.to_bits() == high.to_bits()).then_some(low)
}

/// Rounded value of `mant` when adding one cannot change it.
///
/// `None` means the proof did not apply. The caller then rounds both sides.
#[inline(always)]
fn proved_same_neighbor(neg: bool, mant: u64, exp: i32) -> Option<f64> {
    if mant == 0 || mant == u64::MAX || mant <= MAX_FAST_MANTISSA {
        return None;
    }
    let q = i64::from(exp);
    let index = q - i64::from(POW5_LO);
    if index < 0 || index as usize >= POW5.len() {
        return None;
    }
    let lz = mant.leading_zeros();
    if (mant + 1).leading_zeros() != lz {
        return None;
    }
    // Low 9 bits, the same mask `product` uses for its second limb.
    const MASK: u64 = 0xFFFF_FFFF_FFFF_FFFF >> 55;
    let (lo5, _) = POW5[index as usize];
    let wn = mant << lz;
    let first = (wn as u128).wrapping_mul(lo5 as u128);
    let lo = first as u64;
    let hi = (first >> 64) as u64;
    if hi & MASK == MASK {
        return None;
    }
    // `(mant + 1) << lz` stays in `u64` when the leading-zero count matches,
    // so this sum is the full 128-bit product and does not wrap.
    let delta = (lo5 as u128) << lz;
    let sum = first.checked_add(delta)?;
    let hi2 = (sum >> 64) as u64;
    if hi2 & MASK == MASK {
        return None;
    }
    let upperbit = (hi >> 63) as i32;
    let shift = upperbit + 64 - 52 - 3;
    let mantissa = hi >> shift;
    let neighbor = hi2 >> shift;
    // No carry into the rounding bits, or a one-step carry off an already
    // set round bit. Both of those round to the same word. A pure tie does
    // not: the extra unit leaves the midpoint.
    let same = mantissa == neighbor || (neighbor == mantissa + 1 && mantissa & 1 == 1);
    if !same {
        return None;
    }
    if lo <= 1 && (-4..=23).contains(&q) && mantissa & 3 == 1 && (mantissa << shift) == hi {
        return None;
    }
    let adjusted = adjusted_from_product(q, lo, hi, lz);
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

#[inline(always)]
fn adjusted_from_product(q: i64, lo: u64, hi: u64, lz: u32) -> Adjusted {
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
    use super::{finish, parse_f64_hot, parse_f64_long};

    /// One extra unit on the mantissa must not change the bits the single
    /// product returns, including at ties and at powers of two.
    #[test]
    fn unit_interval_matches_both_sides() {
        fn spec(neg: bool, mant: u64, exp: i32) -> Option<u64> {
            let low = super::finish(neg, mant, exp)?;
            let high = super::finish(neg, mant.checked_add(1)?, exp)?;
            (low.to_bits() == high.to_bits()).then_some(low.to_bits())
        }
        let mut state = 0xC0FFEE_u64;
        let mut next = || {
            state = state
                .wrapping_mul(0x5851_f42d_4c95_7f2d)
                .wrapping_add(0x1405_7b7e_f767_814f);
            state
        };
        let mut differed = 0u32;
        // Every power the product table indexes, including the ends.
        let exp_lo = super::POW5_LO;
        let exp_hi = super::POW5_LO + super::POW5.len() as i32 - 1;
        for exp in exp_lo..=exp_hi {
            for _ in 0..4_000 {
                let mant = next();
                for neg in [false, true] {
                    let got = super::finish_unit_interval(neg, mant, exp).map(f64::to_bits);
                    let want = spec(neg, mant, exp);
                    assert_eq!(got, want, "mant {mant} exp {exp} neg {neg}");
                    if want.is_none() {
                        differed += 1;
                    }
                }
            }
            // 19-digit window used by a 20-digit coordinate, the powers of two,
            // and the first mantissas past the short division.
            let mut edges = vec![
                10u64.pow(18),
                10u64.pow(18) + 1,
                10u64.pow(19) - 2,
                (1u64 << 62) - 1,
                1u64 << 62,
                (1u64 << 63) - 1,
                1u64 << 63,
                u64::MAX - 1,
                u64::MAX,
                0,
                1,
            ];
            for step in 1..=32u64 {
                edges.push(super::MAX_FAST_MANTISSA + step);
            }
            for mant in edges {
                for neg in [false, true] {
                    assert_eq!(
                        super::finish_unit_interval(neg, mant, exp).map(f64::to_bits),
                        spec(neg, mant, exp),
                        "edge mant {mant} exp {exp}"
                    );
                }
            }
        }
        // 19 digits at 10^-16, the fixed coordinate shape.
        for _ in 0..20_000 {
            let mant = 10u64.pow(18) + (next() % (10u64.pow(19) - 10u64.pow(18) - 1));
            assert_eq!(
                super::finish_unit_interval(false, mant, -16).map(f64::to_bits),
                spec(false, mant, -16)
            );
        }
        assert!(
            differed > 0,
            "expected some mantissas to straddle a boundary"
        );
    }

    /// `hi` has bit 63 clear and the next mantissa sets it. Every such step
    /// the table can produce is checked against rounding both sides.
    #[test]
    fn upperbit_crossing_matches_both_sides() {
        fn spec(neg: bool, mant: u64, exp: i32) -> Option<u64> {
            let low = super::finish(neg, mant, exp)?;
            let high = super::finish(neg, mant.checked_add(1)?, exp)?;
            (low.to_bits() == high.to_bits()).then_some(low.to_bits())
        }
        fn div_ceil(n: u128, d: u128) -> u128 {
            (n + d - 1) / d
        }
        let mut saw = 0u32;
        let exp_lo = i64::from(super::POW5_LO);
        for (index, &(lo5, _)) in super::POW5.iter().enumerate() {
            let exp = (exp_lo + index as i64) as i32;
            let lo5 = lo5 as u128;
            let target = 1u128 << 127;
            for lz in 0..64u32 {
                let delta = lo5 << lz;
                if delta == 0 || delta > target {
                    continue;
                }
                // `wn * lo5` lands in `[2^127 - delta, 2^127)`. Adding `delta`
                // is the step to `mant + 1`, so bit 63 of the high half flips.
                let wn_lo = div_ceil(target - delta, lo5);
                let wn_hi = div_ceil(target, lo5);
                let start = wn_lo.max(1u128 << 63);
                let end = wn_hi.min(1u128 << 64);
                if start >= end {
                    continue;
                }
                let step = 1u128 << lz;
                let mut wn = (start + step - 1) & !(step - 1);
                while wn < end {
                    let mant = (wn >> lz) as u64;
                    wn += step;
                    if mant == 0
                        || mant == u64::MAX
                        || mant.leading_zeros() != lz
                        || (mant + 1).leading_zeros() != lz
                    {
                        continue;
                    }
                    let first = ((mant as u128) << lz).wrapping_mul(lo5);
                    let sum = first + delta;
                    let hi = (first >> 64) as u64;
                    let hi2 = (sum >> 64) as u64;
                    if hi >> 63 != 0 || hi2 >> 63 != 1 {
                        continue;
                    }
                    saw += 1;
                    for neg in [false, true] {
                        assert_eq!(
                            super::finish_unit_interval(neg, mant, exp).map(f64::to_bits),
                            spec(neg, mant, exp),
                            "upperbit mant {mant} exp {exp} neg {neg}"
                        );
                    }
                }
            }
        }
        assert!(saw > 0, "no mantissa crossed bit 63 of the high product");
    }

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
                    // Exponents, non-finite spellings, and a long mantissa whose
                    // rounding is ambiguous stay on the general parser.
                    let _ = reference(text);
                }
            }
        }
        assert!(saw_long, "17-digit coordinates must stay on the hot path");
    }

    #[test]
    fn fixed_width_coordinates_match_fast_float() {
        // `{:.17}` with a 3-digit integer part is 20 digits. The row used to
        // leave the hot scan there and reparse every field.
        let mut accepted = 0usize;
        let mut total = 0usize;
        for i in 0..200 {
            let x = (i % 50) as f64 * 2.557 + 0.6394;
            let y = ((i / 50) % 50) as f64 * 3.617 + 0.9045 + 100.0;
            let z = -((i / 2500) as f64) * 2.087 - 0.0001;
            for value in [x, y, z] {
                let plain = format!("{value:.17}");
                let scientific = format!("{value:.17}e0");
                assert!(
                    parse_f64_hot(scientific.as_bytes(), 0).is_none(),
                    "{scientific}"
                );
                total += 1;
                let fell = agree(plain.as_bytes(), 0);
                if !fell {
                    accepted += 1;
                }
            }
        }
        assert!(
            accepted * 10 > total * 8,
            "accepted {accepted} of {total} fixed-point coordinates"
        );
        // Trailing zeros past the 19th digit are exact, not a rounding tie.
        assert!(!agree(b"125.93240000000000000", 0));
        assert!(!agree(b"12345678901234567890", 0));
        // A leading zero that would hide a significant digit must decline.
        assert!(parse_f64_hot(b"0000000000000000000123", 0).is_none());
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
            0..=2 => {
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
                out.extend(std::iter::repeat_n(b'0', zeros));
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
                out.extend(std::iter::repeat_n(b'0', zeros));
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
        let hot = parse_f64_hot(bytes, at).or_else(|| parse_f64_long(bytes, at));
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
            fallback > 100_000,
            "fallback {fallback}, expected exponents, ambiguous long mantissas, and non-finite spellings"
        );
    }

    #[test]
    fn edge_tokens_match_fast_float_or_decline() {
        for token in [
            "-0.0",
            "-0.00000000",
            "0.0",
            "-0",
            "1e-10",
            "1E+20",
            "1.0e-320",
            "2.2250738585072014e-308",
            "1234567890123456789",
            "12345678901234567890",
            "inf",
            "-Infinity",
            "nan",
            "1.0000000000000002",
            "63.546000",
            "  -2.5",
        ] {
            let _ = agree(token.as_bytes(), 0);
        }
    }

    #[test]
    fn corpus_coordinate_tokens_match_fast_float_or_decline() {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        for dir in [
            "resources/conformance/valid",
            "resources/test",
            "resources/examples",
        ] {
            let dir = root.join(dir);
            if !dir.is_dir() {
                continue;
            }
            for entry in std::fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                let name = path.file_name().unwrap().to_string_lossy();
                if !(name.ends_with(".con") || name.ends_with(".convel")) {
                    continue;
                }
                let bytes = std::fs::read(&path).unwrap();
                let mut i = 0usize;
                while i < bytes.len() {
                    if bytes[i].is_ascii_digit()
                        || bytes[i] == b'-'
                        || bytes[i] == b'+'
                        || bytes[i] == b'.'
                    {
                        let _ = agree(&bytes, i);
                        while i < bytes.len() && !bytes[i].is_ascii_whitespace() {
                            i += 1;
                        }
                    } else {
                        i += 1;
                    }
                }
            }
        }
    }

    fn expect_fixed(text: &str) {
        let bytes = text.as_bytes();
        let Some((val, n)) = super::parse_fixed_decimal(bytes, 0) else {
            return;
        };
        let spelled = &text[..n];
        let (expect, used) = fast_float2::parse_partial::<f64, _>(spelled).unwrap();
        assert_eq!(used, spelled.len(), "{spelled}");
        assert_eq!(val.to_bits(), expect.to_bits(), "{spelled}");
    }

    /// Corpus spellings, random 17-digit values in `[-1e4, 1e4]`, and edges.
    #[test]
    fn fixed_17_digits_match_the_general_parser() {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        for dir in [
            "resources/conformance/valid",
            "resources/test",
            "resources/examples",
        ] {
            let dir = root.join(dir);
            if !dir.is_dir() {
                continue;
            }
            for entry in std::fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                let name = path.file_name().unwrap().to_string_lossy();
                if !(name.ends_with(".con") || name.ends_with(".convel")) {
                    continue;
                }
                let text = std::fs::read_to_string(&path).unwrap();
                for raw in text.split_whitespace() {
                    if raw.contains('.') && raw.len() >= 18 {
                        expect_fixed(raw);
                    }
                }
            }
        }
        let mut state = 0xc0ff_ee00_1234_5678u64;
        for _ in 0..2_000_000 {
            state = state.wrapping_mul(0x5851_f42d_4c95_7f2d).wrapping_add(1);
            // 17 significant digits, magnitude inside [-1e4, 1e4].
            let digits = state % 100_000_000_000_000_000;
            let scale = ((state >> 17) % 8) as i32;
            let mag = (digits as f64) / 10f64.powi(13 + scale);
            let value = if state & 1 == 0 { mag } else { -mag };
            if !(-1e4..=1e4).contains(&value) {
                continue;
            }
            expect_fixed(&format!("{value:.17}"));
            expect_fixed(&format!("{value:.16}"));
        }
        // Halfway values, signed zero, a subnormal, and the exponent window.
        for text in [
            "-0.0",
            "-0.00000000000000000",
            "0.00000000000000000",
            "0.5",
            "1.00000000000000000",
            "2.2250738585072014e-308",
            "1.7976931348623157e308",
            "999.9999999999999999",
            "-999.9999999999999999",
            "5.00000000000000000",
            "1.0000000000000002",
            "9007199254740992.0",
            "9007199254740993.0",
        ] {
            let _ = expect_fixed(text);
            let bytes = text.as_bytes();
            if let Some((val, n)) = parse_f64_hot(bytes, 0) {
                if n == bytes.len() {
                    let (expect, _) = fast_float2::parse_partial::<f64, _>(text).unwrap();
                    assert_eq!(val.to_bits(), expect.to_bits(), "{text}");
                }
            }
        }
        assert_eq!(finish(true, 0, 0).unwrap().to_bits(), (-0.0f64).to_bits());
        assert_eq!(finish(false, 0, -17).unwrap().to_bits(), 0.0f64.to_bits());
    }

    /// The last 8-byte word may end on the slice length. The next page is
    /// inaccessible, so a load past that word faults.
    #[test]
    fn fixed_word_stops_at_the_end_of_a_mapping() {
        unsafe extern "C" {
            fn mmap(
                addr: *mut u8,
                len: usize,
                prot: i32,
                flags: i32,
                fd: i32,
                offset: i64,
            ) -> *mut u8;
            fn mprotect(addr: *mut u8, len: usize, prot: i32) -> i32;
            fn munmap(addr: *mut u8, len: usize) -> i32;
        }
        const PROT_NONE: i32 = 0;
        const PROT_READ: i32 = 1;
        const PROT_WRITE: i32 = 2;
        const MAP_PRIVATE: i32 = 2;
        const MAP_ANONYMOUS: i32 = 0x20;
        let page = 4096usize;
        let ptr = unsafe {
            mmap(
                std::ptr::null_mut(),
                page * 2,
                PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        assert!(!ptr.is_null() && ptr != (-1isize as usize as *mut u8));
        assert_eq!(unsafe { mprotect(ptr.add(page), page, PROT_NONE) }, 0);
        // Sixteen fraction digits, file ends on the last one. No newline.
        let text = b"1.1234567890123456";
        assert_eq!(text.len(), 18);
        let start = page - text.len();
        unsafe {
            std::ptr::copy_nonoverlapping(text.as_ptr(), ptr.add(start), text.len());
        }
        let slice = unsafe { std::slice::from_raw_parts(ptr, page) };
        let (val, n) = super::parse_fixed_decimal(slice, start).expect("in-bounds word");
        assert_eq!(n, page);
        let (expect, used) = fast_float2::parse_partial::<f64, _>(text).unwrap();
        assert_eq!(used, text.len());
        assert_eq!(val.to_bits(), expect.to_bits());
        // Eight fraction digits filling the final word of the hot scanner.
        let hot = b"2.12345678";
        let hot_at = page - hot.len();
        unsafe {
            std::ptr::copy_nonoverlapping(hot.as_ptr(), ptr.add(hot_at), hot.len());
        }
        let (hot_val, hot_n) = parse_f64_hot(slice, hot_at).expect("hot final word");
        assert_eq!(hot_n, page);
        let (hot_expect, _) = fast_float2::parse_partial::<f64, _>(hot).unwrap();
        assert_eq!(hot_val.to_bits(), hot_expect.to_bits());
        unsafe {
            mprotect(ptr.add(page), page, PROT_READ | PROT_WRITE);
            munmap(ptr, page * 2);
        }
    }
}
