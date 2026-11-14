//! Serial path-read resident set, against ASE's eon reader.
//!
//! ASE added 384 MiB on a 100_000-frame, 32-atom CON file. This test
//! reads a file of that shape in a fresh process and requires the added
//! peak to stay at or below that rate.

#[path = "common/scratch.rs"]
mod scratch_dir;

use std::io::Write;
use std::path::Path;
use std::process::Command;

const FRAMES: usize = 100_000;
const ATOMS: usize = 32;
/// 384 MiB added on 100_000 frames.
const ASE_BYTES_PER_FRAME: f64 = 384.0 * 1024.0 * 1024.0 / 100_000.0;

#[test]
fn path_read_rss_within_ase() {
    if std::env::var_os("READCON_RSS_CHILD").is_some() {
        child();
        return;
    }
    let dir = scratch_dir::scratch().join(format!("readcon-rss-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("frames.con");
    write_frames(&path, FRAMES, ATOMS, 1);
    let exe = std::env::current_exe().unwrap();
    let output = Command::new(&exe)
        .args([
            "--exact",
            "path_read_rss_within_ase",
            "--test-threads",
            "1",
            "--nocapture",
        ])
        .env("READCON_RSS_CHILD", "1")
        .env("READCON_RSS_PATH", &path)
        .output()
        .unwrap();
    let _ = std::fs::remove_dir_all(&dir);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "child failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let added: u64 = field(&stdout, "added_kib");
    let frames: u64 = field(&stdout, "frames");
    let sum: f64 = field_f64(&stdout, "sum");
    assert_eq!(frames, FRAMES as u64);
    let expected = (0..FRAMES).map(|frame| coord(frame, 0, 0)).sum::<f64>();
    assert!(
        (sum - expected).abs() < 1e-6,
        "sum {sum} expected {expected}"
    );
    let per = (added as f64) * 1024.0 / frames as f64;
    assert!(
        per <= ASE_BYTES_PER_FRAME,
        "added {added} KiB over {frames} frames is {per:.1} B/frame, bound {ASE_BYTES_PER_FRAME:.1}"
    );
}

#[test]
fn wide_two_species_keeps_its_coordinates() {
    let dir = scratch_dir::scratch().join(format!("readcon-wide-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("wide.con");
    let per_type = 4096usize;
    write_frames(&path, 1, per_type, 2);
    let frames = readcon_core::iterators::read_all_frames_with_threads(&path, Some(2)).unwrap();
    let _ = std::fs::remove_dir_all(&dir);
    assert_eq!(frames.len(), 1);
    let frame = &frames[0];
    assert_eq!(frame.atom_data.len(), per_type * 2);
    let check = |index: usize| {
        let atom = &frame.atom_data[index];
        let (species, local) = if index < per_type {
            (0usize, index)
        } else {
            (1usize, index - per_type)
        };
        let x = coord(0, local + species * per_type, 0);
        assert!(
            (atom.x() - x).abs() < 1e-8,
            "atom {index} x {} expected {x}",
            atom.x()
        );
        assert!((frame.positions.as_f64_row(index)[0] - x).abs() < 1e-8);
    };
    check(0);
    check(per_type - 1);
    check(per_type);
    check(per_type * 2 - 1);
}

fn child() {
    let path = std::env::var("READCON_RSS_PATH").unwrap();
    let before = vm_hwm_kib();
    let frames = readcon_core::iterators::read_all_frames(Path::new(&path)).unwrap();
    let after = vm_hwm_kib();
    let sum: f64 = frames.iter().map(|frame| frame.atom_data[0].x()).sum();
    println!("frames={}", frames.len());
    println!("added_kib={}", after.saturating_sub(before));
    println!("sum={sum}");
}

fn value_after<'a>(text: &'a str, key: &str) -> &'a str {
    let marker = format!("{key}=");
    for line in text.lines() {
        if let Some(at) = line.find(&marker) {
            return line[at + marker.len()..].split_whitespace().next().unwrap();
        }
    }
    panic!("missing {key} in {text}")
}

fn field(text: &str, key: &str) -> u64 {
    value_after(text, key).parse().unwrap()
}

fn field_f64(text: &str, key: &str) -> f64 {
    value_after(text, key).parse().unwrap()
}

fn vm_hwm_kib() -> u64 {
    let text = std::fs::read_to_string("/proc/self/status").unwrap();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            return rest.split_whitespace().next().unwrap().parse().unwrap();
        }
    }
    panic!("VmHWM missing");
}

fn coord(frame: usize, atom: usize, axis: usize) -> f64 {
    let value = ((frame as f64) * 17.0 + (atom as f64) * 3.0 + (axis as f64)) % 10_000.0 / 1_000.0;
    (value * 1e8).round() / 1e8
}

fn write_frames(path: &Path, frames: usize, atoms_per_type: usize, n_types: usize) {
    let file = std::fs::File::create(path).unwrap();
    let mut out = std::io::BufWriter::new(file);
    let header = format!(
        "{{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n\
         20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n{n_types}\n{}\n{}\n",
        std::iter::repeat_n(atoms_per_type.to_string(), n_types)
            .collect::<Vec<_>>()
            .join(" "),
        std::iter::repeat_n("63.546".to_string(), n_types)
            .collect::<Vec<_>>()
            .join(" ")
    );
    writeln!(out).unwrap();
    for frame in 0..frames {
        write!(out, "{header}").unwrap();
        for species in 0..n_types {
            let symbol = if species == 0 { "Cu" } else { "Al" };
            write!(out, "{symbol}\nCoordinates of Component {}\n", species + 1).unwrap();
            for local in 0..atoms_per_type {
                let atom = species * atoms_per_type + local;
                let id = atom;
                writeln!(
                    out,
                    "{:.8} {:.8} {:.8} 0 {id}",
                    coord(frame, atom, 0),
                    coord(frame, atom, 1),
                    coord(frame, atom, 2)
                )
                .unwrap();
            }
        }
        writeln!(out).unwrap();
    }
    out.flush().unwrap();
}
