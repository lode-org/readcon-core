//! Opt-in low-rank trajectory fit with a caller-supplied absolute bound.
//!
//! The first step of a tensor-train SVD is a low-rank factorization of an
//! unfolding (Oseledets, SIAM J. Sci. Comput. 33, 2011,
//! <https://doi.org/10.1137/090752286>). For a trajectory tensor
//! `(frames, atoms, xyz)` that unfolding is the coordinate matrix. This fit
//! is that step: center, Jacobi eigensystem of the Gram matrix, then the
//! smallest rank whose reconstruction stays inside `max_abs`.
//!
//! The reader never calls this. A non-positive or non-finite bound is refused.

const MAGIC: &[u8; 8] = b"RCLOWR01";
const VERSION: u32 = 1;
const MAX_COORDS: usize = 512;

/// One fitted model and the rank/error curve used to choose it.
#[derive(Debug, Clone)]
pub struct Fit {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub rank: usize,
    pub bound: f64,
    pub achieved_max_abs: f64,
    pub met_bound: bool,
    /// `(rank, max abs)` for powers of two and the full column count.
    pub err_at_rank: Vec<(usize, f64)>,
    /// Eigenvalues of the centered Gram matrix, descending.
    pub eigenvalues: Vec<f64>,
    /// Second tensor-train rank of the kept basis, and the byte count of a
    /// three-core train with those ranks. `None` when the rank is zero.
    pub tt_r2: Option<usize>,
    pub tt_bytes: Option<usize>,
    pub bytes: Vec<u8>,
}

/// Fit `values` in frame-major `(frame, atom, xyz)` order.
pub fn fit_positions(
    values: &[f64],
    n_frames: usize,
    n_atoms: usize,
    max_abs: f64,
) -> Result<Fit, String> {
    if !max_abs.is_finite() || max_abs <= 0.0 {
        return Err("low-rank bound must be finite and positive; lossy fit is opt-in".into());
    }
    let n_coords = n_atoms.checked_mul(3).ok_or("shape")?;
    if n_frames < 2 {
        return Err("low-rank fit needs at least two frames".into());
    }
    if n_coords == 0 || n_coords > MAX_COORDS {
        return Err(format!(
            "low-rank prototype supports 1..={MAX_COORDS} coordinates, got {n_coords}"
        ));
    }
    if values.len() != n_frames * n_coords {
        return Err("position length does not match the frame shape".into());
    }
    let mut mean = vec![0.0; n_coords];
    for row in values.chunks_exact(n_coords) {
        for (slot, value) in mean.iter_mut().zip(row) {
            *slot += *value;
        }
    }
    let scale = n_frames as f64;
    for slot in &mut mean {
        *slot /= scale;
    }
    let mut gram = vec![0.0; n_coords * n_coords];
    for row in values.chunks_exact(n_coords) {
        for i in 0..n_coords {
            let di = row[i] - mean[i];
            for j in i..n_coords {
                gram[i * n_coords + j] += di * (row[j] - mean[j]);
            }
        }
    }
    for i in 0..n_coords {
        for j in 0..i {
            gram[i * n_coords + j] = gram[j * n_coords + i];
        }
    }
    let mut vectors = vec![0.0; n_coords * n_coords];
    jacobi(&mut gram, n_coords, &mut vectors);
    let mut order: Vec<usize> = (0..n_coords).collect();
    order.sort_by(|&a, &b| {
        gram[b * n_coords + b]
            .partial_cmp(&gram[a * n_coords + a])
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let eigenvalues: Vec<f64> = order.iter().map(|&k| gram[k * n_coords + k]).collect();
    let mut basis = vec![0.0; n_coords * n_coords];
    for (rank, &src) in order.iter().enumerate() {
        for coord in 0..n_coords {
            basis[coord + rank * n_coords] = vectors[coord * n_coords + src];
        }
    }
    let mut err_at = vec![0.0; n_coords];
    let mut delta = vec![0.0; n_coords];
    let mut pred = vec![0.0; n_coords];
    for row in values.chunks_exact(n_coords) {
        for c in 0..n_coords {
            delta[c] = row[c] - mean[c];
            pred[c] = mean[c];
        }
        for rank in 0..n_coords {
            let column = &basis[rank * n_coords..(rank + 1) * n_coords];
            let mut score = 0.0;
            for c in 0..n_coords {
                score += delta[c] * column[c];
            }
            for c in 0..n_coords {
                pred[c] += column[c] * score;
            }
            let mut worst = 0.0f64;
            for c in 0..n_coords {
                worst = worst.max((row[c] - pred[c]).abs());
            }
            if worst > err_at[rank] {
                err_at[rank] = worst;
            }
        }
    }
    let err_at_rank: Vec<(usize, f64)> = err_at
        .iter()
        .enumerate()
        .map(|(index, err)| (index + 1, *err))
        .collect();
    let mut chosen = n_coords;
    let mut achieved = err_at.last().copied().unwrap_or(0.0);
    for (rank, err) in &err_at_rank {
        if *err <= max_abs {
            chosen = *rank;
            achieved = *err;
            break;
        }
    }
    let met_bound = achieved <= max_abs;
    let (tt_r2, tt_bytes) = if chosen == 0 {
        (None, None)
    } else {
        let r2 = second_rank(&basis, n_atoms, chosen);
        let bytes = (n_frames * chosen + chosen * n_atoms * r2 + r2 * 3) * 8;
        (Some(r2), Some(bytes))
    };
    let bytes = encode_model(
        values, &mean, &basis, n_frames, n_atoms, chosen, max_abs, achieved, met_bound,
    );
    Ok(Fit {
        n_frames,
        n_atoms,
        rank: chosen,
        bound: max_abs,
        achieved_max_abs: achieved,
        met_bound,
        err_at_rank,
        eigenvalues,
        tt_r2,
        tt_bytes,
        bytes,
    })
}

/// Reconstruct positions from a blob written by [`fit_positions`].
pub fn decode_lowrank(bytes: &[u8]) -> Result<Vec<f64>, String> {
    let header = 8 + 4 + 8 + 8 + 4 + 4 + 8 + 8;
    if bytes.len() < header || &bytes[..8] != MAGIC {
        return Err("low-rank header".into());
    }
    if u32::from_le_bytes(bytes[8..12].try_into().unwrap()) != VERSION {
        return Err("low-rank version".into());
    }
    let n_frames = u64::from_le_bytes(bytes[12..20].try_into().unwrap()) as usize;
    let n_atoms = u64::from_le_bytes(bytes[20..28].try_into().unwrap()) as usize;
    let rank = u32::from_le_bytes(bytes[28..32].try_into().unwrap()) as usize;
    let n_coords = n_atoms * 3;
    let mut at = header;
    let mean = read_f64s(bytes, &mut at, n_coords)?;
    let basis = read_f64s(bytes, &mut at, n_coords * rank)?;
    let scores = read_f64s(bytes, &mut at, n_frames * rank)?;
    let mut out = vec![0.0; n_frames * n_coords];
    for frame in 0..n_frames {
        let dest = &mut out[frame * n_coords..(frame + 1) * n_coords];
        dest.copy_from_slice(&mean);
        let score = &scores[frame * rank..(frame + 1) * rank];
        for k in 0..rank {
            let column = &basis[k * n_coords..(k + 1) * n_coords];
            for c in 0..n_coords {
                dest[c] += column[c] * score[k];
            }
        }
    }
    Ok(out)
}

fn dot_k(delta: &[f64], basis: &[f64], n_coords: usize, k: usize) -> f64 {
    let mut score = 0.0;
    for c in 0..n_coords {
        score += delta[c] * basis[c + k * n_coords];
    }
    score
}

fn encode_model(
    values: &[f64],
    mean: &[f64],
    basis: &[f64],
    n_frames: usize,
    n_atoms: usize,
    rank: usize,
    bound: f64,
    achieved: f64,
    met_bound: bool,
) -> Vec<u8> {
    let n_coords = n_atoms * 3;
    let mut scores = vec![0.0; n_frames * rank];
    let mut delta = vec![0.0; n_coords];
    for (frame, row) in values.chunks_exact(n_coords).enumerate() {
        for c in 0..n_coords {
            delta[c] = row[c] - mean[c];
        }
        for k in 0..rank {
            scores[frame * rank + k] = dot_k(&delta, basis, n_coords, k);
        }
    }
    let mut out = Vec::new();
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&(n_frames as u64).to_le_bytes());
    out.extend_from_slice(&(n_atoms as u64).to_le_bytes());
    out.extend_from_slice(&(rank as u32).to_le_bytes());
    out.extend_from_slice(&(u32::from(met_bound)).to_le_bytes());
    out.extend_from_slice(&bound.to_le_bytes());
    out.extend_from_slice(&achieved.to_le_bytes());
    write_f64s(&mut out, mean);
    write_f64s(&mut out, &basis[..n_coords * rank]);
    write_f64s(&mut out, &scores);
    out
}

fn second_rank(basis: &[f64], n_atoms: usize, rank: usize) -> usize {
    // Rows are (component, atom), columns are xyz.
    let mut gram = [0.0; 9];
    for k in 0..rank {
        for atom in 0..n_atoms {
            let base = k * n_atoms * 3 + atom * 3;
            for x in 0..3 {
                for y in 0..3 {
                    gram[x * 3 + y] += basis[base + x] * basis[base + y];
                }
            }
        }
    }
    let mut vectors = [0.0; 9];
    jacobi(&mut gram, 3, &mut vectors);
    let mut evals = [gram[0], gram[4], gram[8]];
    evals.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
    let floor = evals[0].abs() * 1e-8;
    evals
        .iter()
        .filter(|value| value.abs() > floor.max(1e-18))
        .count()
        .max(1)
}

fn jacobi(a: &mut [f64], n: usize, v: &mut [f64]) {
    v.fill(0.0);
    for i in 0..n {
        v[i * n + i] = 1.0;
    }
    for _ in 0..64 {
        let mut off = 0.0;
        for p in 0..n {
            for q in (p + 1)..n {
                off += a[p * n + q].abs();
            }
        }
        if off <= 1e-14 * (n as f64) {
            break;
        }
        for p in 0..n {
            for q in (p + 1)..n {
                let apq = a[p * n + q];
                if apq.abs() <= 1e-18 {
                    continue;
                }
                let app = a[p * n + p];
                let aqq = a[q * n + q];
                let tau = (aqq - app) / (2.0 * apq);
                let t = if tau == 0.0 {
                    1.0
                } else {
                    tau.signum() / (tau.abs() + (1.0 + tau * tau).sqrt())
                };
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = t * c;
                a[p * n + p] = app - t * apq;
                a[q * n + q] = aqq + t * apq;
                a[p * n + q] = 0.0;
                a[q * n + p] = 0.0;
                for r in 0..n {
                    if r == p || r == q {
                        continue;
                    }
                    let arp = a[r * n + p];
                    let arq = a[r * n + q];
                    let new_rp = c * arp - s * arq;
                    let new_rq = s * arp + c * arq;
                    a[r * n + p] = new_rp;
                    a[p * n + r] = new_rp;
                    a[r * n + q] = new_rq;
                    a[q * n + r] = new_rq;
                }
                for r in 0..n {
                    let vrp = v[r * n + p];
                    let vrq = v[r * n + q];
                    v[r * n + p] = c * vrp - s * vrq;
                    v[r * n + q] = s * vrp + c * vrq;
                }
            }
        }
    }
}

fn read_f64s(bytes: &[u8], at: &mut usize, n: usize) -> Result<Vec<f64>, String> {
    let end = at
        .checked_add(n * 8)
        .filter(|end| *end <= bytes.len())
        .ok_or("truncated low-rank payload")?;
    let mut out = Vec::with_capacity(n);
    for chunk in bytes[*at..end].chunks_exact(8) {
        out.push(f64::from_le_bytes(chunk.try_into().unwrap()));
    }
    *at = end;
    Ok(out)
}

fn write_f64s(out: &mut Vec<u8>, values: &[f64]) {
    for value in values {
        out.extend_from_slice(&value.to_le_bytes());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jacobi_splits_a_symmetric_pair() {
        let mut a = vec![2.0, 1.0, 1.0, 2.0];
        let mut v = vec![0.0; 4];
        jacobi(&mut a, 2, &mut v);
        let mut evals = [a[0], a[3]];
        evals.sort_by(|left, right| right.partial_cmp(left).unwrap());
        assert!((evals[0] - 3.0).abs() < 1e-10);
        assert!((evals[1] - 1.0).abs() < 1e-10);
    }

    #[test]
    fn a_line_meets_a_tight_bound_at_low_rank() {
        let n_frames = 12usize;
        let n_atoms = 2usize;
        let mut values = vec![0.0; n_frames * n_atoms * 3];
        for frame in 0..n_frames {
            for atom in 0..n_atoms {
                let base = (frame * n_atoms + atom) * 3;
                values[base] = frame as f64 * 0.01 + atom as f64;
                values[base + 1] = frame as f64 * -0.02;
                values[base + 2] = 1.5;
            }
        }
        let fit = fit_positions(&values, n_frames, n_atoms, 1e-8).unwrap();
        assert!(fit.met_bound, "achieved {}", fit.achieved_max_abs);
        assert!(fit.rank <= 2, "rank {}", fit.rank);
        let back = decode_lowrank(&fit.bytes).unwrap();
        let mut worst = 0.0f64;
        for (got, expect) in back.iter().zip(&values) {
            worst = worst.max((got - expect).abs());
        }
        assert!(worst <= 1e-8, "{worst}");
    }

    #[test]
    fn a_non_positive_bound_is_refused() {
        let err = fit_positions(&[0.0, 1.0, 2.0, 3.0, 4.0, 5.0], 2, 1, 0.0).unwrap_err();
        assert!(err.contains("opt-in"), "{err}");
    }

    #[test]
    fn a_modular_series_does_not_collapse() {
        let n_frames = 24usize;
        let n_coords = 6usize;
        let mut values = vec![0.0; n_frames * n_coords];
        for frame in 0..n_frames {
            for coord in 0..n_coords {
                values[frame * n_coords + coord] = ((frame * 17 + coord * 3) % 50) as f64;
            }
        }
        let fit = fit_positions(&values, n_frames, n_coords / 3, 1e-6).unwrap();
        assert!(fit.met_bound);
        assert!(
            fit.rank >= n_coords / 2,
            "modular series rank {} of {n_coords}",
            fit.rank
        );
        let rank1 = fit
            .err_at_rank
            .iter()
            .find(|(rank, _)| *rank == 1)
            .unwrap()
            .1;
        assert!(rank1 > 1.0, "rank-1 error {rank1}");
    }
}
