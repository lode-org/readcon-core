//! CPC benchmark helper. Times parses, hashes every public frame field, and
//! prints the natural velocity unit parsed by `units.rs`.

use readcon_core::iterators::read_all_frames_with_threads;
use readcon_core::types::ConFrame;
use readcon_core::units::{canonicalize_unit_expression, parse_unit_expression};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::hint::black_box;
use std::io::{self, BufRead, Write};
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_else(|| "serve".to_string());
    let result = match cmd.as_str() {
        "serve" => serve(),
        "time" => one_shot(&mut args, "time"),
        "hash" => one_shot(&mut args, "hash"),
        "dump" => {
            let path = expect_arg(&mut args, "path");
            dump(&path)
        }
        "units" => units(),
        other => Err(format!("unknown command {other}")),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("err\t{err}");
            ExitCode::from(1)
        }
    }
}

fn expect_arg(args: &mut impl Iterator<Item = String>, name: &str) -> String {
    args.next().unwrap_or_else(|| {
        eprintln!("err\tmissing {name}");
        std::process::exit(1);
    })
}

fn one_shot(args: &mut impl Iterator<Item = String>, kind: &str) -> Result<(), String> {
    let path = expect_arg(args, "path");
    let threads: usize = expect_arg(args, "threads")
        .parse()
        .map_err(|e| format!("threads: {e}"))?;
    let line = dispatch(kind, &path, threads)?;
    println!("{line}");
    Ok(())
}

fn serve() -> Result<(), String> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        let mut parts = line.split('\t');
        let kind = parts.next().unwrap_or("");
        if kind.is_empty() || kind == "quit" {
            break;
        }
        let path = parts.next().unwrap_or("");
        let threads: usize = parts.next().unwrap_or("0").parse().unwrap_or(0);
        let reply = match dispatch(kind, path, threads) {
            Ok(body) => body,
            Err(err) => format!("err\t{err}"),
        };
        writeln!(stdout, "{reply}").map_err(|e| e.to_string())?;
        stdout.flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn dispatch(kind: &str, path: &str, threads: usize) -> Result<String, String> {
    match kind {
        "time" => {
            let (secs, tag) = time_one(path, threads)?;
            Ok(format!("ok\t{secs:.9}\t{tag}"))
        }
        "hash" => {
            let frames = load(path, threads)?;
            Ok(format!("ok\t{}", hash_frames(&frames)))
        }
        other => Err(format!("unknown serve command {other}")),
    }
}

fn load(path: &str, threads: usize) -> Result<Vec<ConFrame>, String> {
    let n = if threads == 0 { None } else { Some(threads) };
    read_all_frames_with_threads(Path::new(path), n).map_err(|e| e.to_string())
}

fn time_one(path: &str, threads: usize) -> Result<(f64, u64), String> {
    let start = Instant::now();
    let frames = load(path, threads)?;
    let mut tag: u64 = frames.len() as u64;
    if let Some(frame) = frames.first() {
        if let Some(atom) = frame.atom_data.first() {
            tag ^= atom.x.to_bits();
        }
    }
    black_box(&frames);
    let secs = start.elapsed().as_secs_f64();
    Ok((secs, black_box(tag)))
}

fn hash_frames(frames: &[ConFrame]) -> String {
    let mut hasher = Sha256::new();
    for frame in frames {
        hash_frame(&mut hasher, frame);
    }
    format!("{:x}", hasher.finalize())
}

fn hash_frame(hasher: &mut Sha256, frame: &ConFrame) {
    let hdr = &frame.header;
    feed_u64(hasher, u64::from(hdr.spec_version));
    feed_u64(hasher, hdr.natm_types as u64);
    for value in hdr.boxl {
        feed_f64(hasher, value);
    }
    for value in hdr.angles {
        feed_f64(hasher, value);
    }
    feed_str(hasher, &hdr.prebox_header.user);
    feed_str(hasher, &hdr.postbox_header[0]);
    feed_str(hasher, &hdr.postbox_header[1]);
    feed_u64(hasher, hdr.natms_per_type.len() as u64);
    for count in &hdr.natms_per_type {
        feed_u64(hasher, *count as u64);
    }
    feed_u64(hasher, hdr.masses_per_type.len() as u64);
    for mass in &hdr.masses_per_type {
        feed_f64(hasher, *mass);
    }
    feed_u64(hasher, hdr.sections.len() as u64);
    for section in &hdr.sections {
        feed_str(hasher, section);
    }
    let meta = serde_json::to_string(&hdr.metadata).unwrap_or_default();
    feed_str(hasher, &meta);
    hash_soa(hasher, frame);
    feed_u64(hasher, frame.atom_data.len() as u64);
    for atom in &frame.atom_data {
        feed_str(hasher, atom.symbol.as_ref());
        feed_f64(hasher, atom.x);
        feed_f64(hasher, atom.y);
        feed_f64(hasher, atom.z);
        hasher.update([
            u8::from(atom.fixed[0]),
            u8::from(atom.fixed[1]),
            u8::from(atom.fixed[2]),
        ]);
        feed_u64(hasher, atom.atom_id);
        feed_opt3(hasher, atom.velocity);
        feed_opt3(hasher, atom.force);
        feed_opt1(hasher, atom.energy);
        feed_opt1(hasher, atom.charge);
        feed_opt1(hasher, atom.spin);
        feed_opt3(hasher, atom.magmom);
        feed_opt3(hasher, atom.displacement);
        feed_opt3(hasher, atom.spread);
    }
}

fn hash_soa(hasher: &mut Sha256, frame: &ConFrame) {
    let n = frame.positions.nrows();
    feed_u64(hasher, n as u64);
    for i in 0..n {
        for value in frame.positions.as_f64_row(i) {
            feed_f64(hasher, value);
        }
    }
    hash_rows(hasher, frame.velocities.nrows(), |i| {
        frame.velocities.as_f64_row(i)
    });
    hash_rows(hasher, frame.forces.nrows(), |i| frame.forces.as_f64_row(i));
    hash_rows(hasher, frame.magmoms.nrows(), |i| frame.magmoms.as_f64_row(i));
    hash_rows(hasher, frame.displacements.nrows(), |i| {
        frame.displacements.as_f64_row(i)
    });
    hash_rows(hasher, frame.spreads.nrows(), |i| frame.spreads.as_f64_row(i));
    feed_u64(hasher, frame.atom_energies.len() as u64);
    for i in 0..frame.atom_energies.len() {
        feed_f64(hasher, frame.atom_energies.get_f64(i));
    }
    feed_u64(hasher, frame.charges.len() as u64);
    for i in 0..frame.charges.len() {
        feed_f64(hasher, frame.charges.get_f64(i));
    }
    feed_u64(hasher, frame.spins.len() as u64);
    for i in 0..frame.spins.len() {
        feed_f64(hasher, frame.spins.get_f64(i));
    }
    feed_u64(hasher, frame.masses.len() as u64);
    for i in 0..frame.masses.len() {
        feed_f64(hasher, frame.masses.get_f64(i));
    }
    feed_u64(hasher, frame.atom_ids.len() as u64);
    for id in frame.atom_ids.iter() {
        feed_u64(hasher, *id);
    }
}

fn hash_rows(hasher: &mut Sha256, n: usize, row: impl Fn(usize) -> [f64; 3]) {
    feed_u64(hasher, n as u64);
    for i in 0..n {
        for value in row(i) {
            feed_f64(hasher, value);
        }
    }
}

fn feed_u64(hasher: &mut Sha256, value: u64) {
    hasher.update(value.to_le_bytes());
}

fn feed_f64(hasher: &mut Sha256, value: f64) {
    hasher.update(value.to_bits().to_le_bytes());
}

fn feed_str(hasher: &mut Sha256, value: &str) {
    feed_u64(hasher, value.len() as u64);
    hasher.update(value.as_bytes());
}

fn feed_opt1(hasher: &mut Sha256, value: Option<f64>) {
    match value {
        Some(v) => {
            hasher.update([1]);
            feed_f64(hasher, v);
        }
        None => hasher.update([0]),
    }
}

fn feed_opt3(hasher: &mut Sha256, value: Option<[f64; 3]>) {
    match value {
        Some(v) => {
            hasher.update([1]);
            for item in v {
                feed_f64(hasher, item);
            }
        }
        None => hasher.update([0]),
    }
}

fn dump(path: &str) -> Result<(), String> {
    let frames = load(path, 1)?;
    let body: Vec<Value> = frames.iter().map(frame_json).collect();
    println!("{}", json!(body));
    Ok(())
}

fn frame_json(frame: &ConFrame) -> Value {
    let units = frame.header.metadata.get("units").cloned().unwrap_or(Value::Null);
    let atoms: Vec<Value> = frame
        .atom_data
        .iter()
        .map(|atom| {
            json!({
                "symbol": atom.symbol.as_ref(),
                "xyz": [atom.x, atom.y, atom.z],
                "fixed": atom.fixed,
                "id": atom.atom_id,
                "velocity": atom.velocity,
            })
        })
        .collect();
    json!({
        "spec_version": frame.header.spec_version,
        "minor": frame.header.metadata.get("con_spec_minor").cloned().unwrap_or(Value::Null),
        "units": units,
        "sections": frame.header.sections,
        "pbc": frame.header.metadata.get("pbc").cloned().unwrap_or(Value::Null),
        "lattice_vectors": frame.header.metadata.get("lattice_vectors").cloned().unwrap_or(Value::Null),
        "natoms": frame.atom_data.len(),
        "atoms": atoms,
    })
}

fn units() -> Result<(), String> {
    let natural = "(amu*angstrom^2/eV)^0.5";
    let (nat_si, _) = parse_unit_expression(natural).map_err(|e| e.to_string())?;
    let (fs_si, _) = parse_unit_expression("fs").map_err(|e| e.to_string())?;
    let canon = canonicalize_unit_expression(natural).map_err(|e| e.to_string())?;
    println!(
        "{}",
        json!({
            "spelling": natural,
            "canonical": canon,
            "fs": nat_si / fs_si,
            "eon_fs": 10.1805055_f64,
        })
    );
    Ok(())
}
