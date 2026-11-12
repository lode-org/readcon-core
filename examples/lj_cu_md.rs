//! Short Lennard-Jones molecular dynamics of FCC copper near 300 K.
//!
//! The pair parameters are the 12-6 values Heinz, Vaia, Farmer, and Naik
//! fitted to room-temperature density and surface energy
//! (J. Phys. Chem. C 112, 2008, doi:10.1021/jp801931d): σ = 2.616 Å and
//! ε = 4.72 kcal/mol. The cell is the experimental cubic lattice constant
//! 3.615 Å, eight cells on a side (2048 atoms). A velocity-Verlet run in
//! metal units (Å, eV, u, ps) rescales toward 300 K and then records 1200
//! frames. The trajectory is written as CON text and is not meant to be
//! committed.

use std::env;
use std::fs::File;
use std::io::{BufWriter, Write};

const SIGMA: f64 = 2.616;
const EPSILON_KCAL: f64 = 4.72;
/// kcal/mol to eV, using 1 cal = 4.184 J and the electron charge in kJ/mol.
const KCAL_TO_EV: f64 = 4184.0 / 96485.3321;
const EPSILON: f64 = EPSILON_KCAL * KCAL_TO_EV;
const MASS: f64 = 63.546;
const CUTOFF: f64 = 2.5 * SIGMA;
const LATTICE: f64 = 3.615;
const SIDE: usize = 8;
const KB_EV: f64 = 8.617333262145e-5;
const TEMP: f64 = 300.0;
/// (eV/Å)/u converted to Å/ps².
const ACCEL: f64 = 9648.5332123316;
const DT: f64 = 0.002;
const EQUIL: usize = 400;
const FRAMES: usize = 1200;

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| {
        eprintln!("usage: lj_cu_md OUT.con");
        std::process::exit(2);
    });
    let n = SIDE * SIDE * SIDE * 4;
    let box_l = SIDE as f64 * LATTICE;
    let mut x = fcc(box_l);
    let mut v = thermal_velocities(n, box_l);
    let mut f = vec![[0.0; 3]; n];
    forces(&x, box_l, &mut f);
    for step in 0..EQUIL {
        verlet(&mut x, &mut v, &mut f, box_l);
        if step % 20 == 19 {
            rescale(&mut v, TEMP);
        }
    }
    let mut out = BufWriter::new(File::create(&path).unwrap());
    let mut sum_t = 0.0;
    for _ in 0..FRAMES {
        verlet(&mut x, &mut v, &mut f, box_l);
        sum_t += temperature(&v);
        write_frame(&mut out, &x, box_l);
    }
    out.flush().unwrap();
    let mean_t = sum_t / FRAMES as f64;
    eprintln!(
        "atoms {n} frames {FRAMES} box_A {box_l:.6} mean_temperature_K {mean_t:.2} epsilon_eV {EPSILON:.6}"
    );
}

fn fcc(box_l: f64) -> Vec<[f64; 3]> {
    let _ = box_l;
    let basis = [
        [0.0, 0.0, 0.0],
        [0.5, 0.5, 0.0],
        [0.5, 0.0, 0.5],
        [0.0, 0.5, 0.5],
    ];
    let mut x = Vec::with_capacity(SIDE * SIDE * SIDE * 4);
    for iz in 0..SIDE {
        for iy in 0..SIDE {
            for ix in 0..SIDE {
                for b in basis {
                    x.push([
                        (ix as f64 + b[0]) * LATTICE,
                        (iy as f64 + b[1]) * LATTICE,
                        (iz as f64 + b[2]) * LATTICE,
                    ]);
                }
            }
        }
    }
    x
}

fn thermal_velocities(n: usize, _box: f64) -> Vec<[f64; 3]> {
    let mut rng = Rng(0x5eed_c0ffee);
    let sigma = (KB_EV * TEMP / MASS * ACCEL).sqrt();
    let mut v = Vec::with_capacity(n);
    let mut com = [0.0; 3];
    for _ in 0..n {
        let sample = [
            gauss(&mut rng) * sigma,
            gauss(&mut rng) * sigma,
            gauss(&mut rng) * sigma,
        ];
        com[0] += sample[0];
        com[1] += sample[1];
        com[2] += sample[2];
        v.push(sample);
    }
    for sample in &mut v {
        sample[0] -= com[0] / n as f64;
        sample[1] -= com[1] / n as f64;
        sample[2] -= com[2] / n as f64;
    }
    v
}

fn verlet(x: &mut [[f64; 3]], v: &mut [[f64; 3]], f: &mut [[f64; 3]], box_l: f64) {
    let half = 0.5 * DT;
    for i in 0..x.len() {
        let inv_m = ACCEL / MASS;
        for k in 0..3 {
            v[i][k] += half * f[i][k] * inv_m;
            x[i][k] += DT * v[i][k];
            x[i][k] -= box_l * (x[i][k] / box_l).floor();
        }
    }
    forces(x, box_l, f);
    for i in 0..x.len() {
        let inv_m = ACCEL / MASS;
        for k in 0..3 {
            v[i][k] += half * f[i][k] * inv_m;
        }
    }
}

fn rescale(v: &mut [[f64; 3]], target: f64) {
    let temp = temperature(v);
    if temp > 1.0e-8 {
        let scale = (target / temp).sqrt();
        for sample in v.iter_mut() {
            sample[0] *= scale;
            sample[1] *= scale;
            sample[2] *= scale;
        }
    }
}

fn temperature(v: &[[f64; 3]]) -> f64 {
    let mut ke = 0.0;
    for sample in v {
        ke += sample[0] * sample[0] + sample[1] * sample[1] + sample[2] * sample[2];
    }
    ke *= 0.5 * MASS / ACCEL;
    2.0 * ke / (3.0 * v.len() as f64 * KB_EV)
}

fn forces(x: &[[f64; 3]], box_l: f64, f: &mut [[f64; 3]]) {
    for slot in f.iter_mut() {
        *slot = [0.0, 0.0, 0.0];
    }
    let ncell = (box_l / CUTOFF).floor().max(3.0) as usize;
    let inv = ncell as f64 / box_l;
    let mut head = vec![usize::MAX; ncell * ncell * ncell];
    let mut next = vec![usize::MAX; x.len()];
    for (i, pos) in x.iter().enumerate() {
        let ix = (pos[0] * inv).floor() as usize % ncell;
        let iy = (pos[1] * inv).floor() as usize % ncell;
        let iz = (pos[2] * inv).floor() as usize % ncell;
        let cell = (iz * ncell + iy) * ncell + ix;
        next[i] = head[cell];
        head[cell] = i;
    }
    let cut2 = CUTOFF * CUTOFF;
    let sig2 = SIGMA * SIGMA;
    let sig6 = sig2 * sig2 * sig2;
    let sig12 = sig6 * sig6;
    for iz in 0..ncell {
        for iy in 0..ncell {
            for ix in 0..ncell {
                let cell = (iz * ncell + iy) * ncell + ix;
                let mut i = head[cell];
                while i != usize::MAX {
                    for dz in -1..=1 {
                        for dy in -1..=1 {
                            for dx in -1..=1 {
                                let jx = (ix as isize + dx).rem_euclid(ncell as isize) as usize;
                                let jy = (iy as isize + dy).rem_euclid(ncell as isize) as usize;
                                let jz = (iz as isize + dz).rem_euclid(ncell as isize) as usize;
                                let neighbor = (jz * ncell + jy) * ncell + jx;
                                let mut j = head[neighbor];
                                while j != usize::MAX {
                                    if i < j {
                                        let mut rij = [0.0; 3];
                                        let mut r2 = 0.0;
                                        for k in 0..3 {
                                            let delta = min_image(x[i][k] - x[j][k], box_l);
                                            rij[k] = delta;
                                            r2 += delta * delta;
                                        }
                                        if r2 < cut2 && r2 > 1.0e-12 {
                                            let inv_r2 = 1.0 / r2;
                                            let inv_r6 = inv_r2 * inv_r2 * inv_r2;
                                            let mag = 24.0
                                                * EPSILON
                                                * inv_r2
                                                * (2.0 * sig12 * inv_r6 * inv_r6 - sig6 * inv_r6);
                                            for k in 0..3 {
                                                let component = mag * rij[k];
                                                f[i][k] += component;
                                                f[j][k] -= component;
                                            }
                                        }
                                    }
                                    j = next[j];
                                }
                            }
                        }
                    }
                    i = next[i];
                }
            }
        }
    }
}

fn min_image(dx: f64, box_l: f64) -> f64 {
    dx - box_l * (dx / box_l).round()
}

fn write_frame(out: &mut impl Write, x: &[[f64; 3]], box_l: f64) {
    writeln!(
        out,
        "grid\n{{\"con_spec_version\":2}}\n{box_l:.6} {box_l:.6} {box_l:.6}\n90.000000 90.000000 90.000000\n0 0\n0 0\n1\n{}\n63.546000\nCu\nCoordinates of Component 1",
        x.len()
    )
    .unwrap();
    for (id, pos) in x.iter().enumerate() {
        writeln!(out, " {:.8} {:.8} {:.8} 0 {id}", pos[0], pos[1], pos[2]).unwrap();
    }
}

fn gauss(rng: &mut Rng) -> f64 {
    let u1 = rng.unit().max(1.0e-12);
    let u2 = rng.unit();
    (-2.0 * u1.ln()).sqrt() * (std::f64::consts::TAU * u2).cos()
}

struct Rng(u64);

impl Rng {
    fn unit(&mut self) -> f64 {
        self.next() as f64 / (u64::MAX as f64)
    }
    fn next(&mut self) -> u64 {
        let mut z = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        self.0 = z;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }
}
