//! CLI for CON I/O and foreign → CON conversion (migration entry point).
//!
//! ```text
//! readcon-core <input.con> [output.con]           # inspect / optional CON write
//! readcon-core convert <input> <output.con>       # CON or chemfiles format → CON
//! readcon-core --help
//! ```
//!
//! Foreign formats need a build with `--features chemfiles`.

use std::env;
use std::path::Path;
use std::process;

use readcon_core::convert::{convert_path_to_con, path_looks_like_con};
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use readcon_core::writer::ConFrameWriter;
use readcon_core::{CON_SPEC_VERSION, VERSION};

fn usage(argv0: &str) {
    eprintln!(
        "readcon-core {VERSION} (CON spec v{CON_SPEC_VERSION})

Usage:
  {argv0} <input.con> [output.con]
      Inspect a CON/convel file; optionally rewrite all frames to output.con

  {argv0} convert <input> <output.con>
      Convert a structure or trajectory into CON.
      - .con / .convel (and .gz/.zst): native reader
      - other formats (XYZ, PDB, GRO, …): requires --features chemfiles

Why CON: per-direction constraints, atom_id, optional sections (forces,
velocities, charges, …), multi-language hourglass ABI, campaign-storeable text.
See docs/orgmode/migrate.org.
"
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        usage(&args[0]);
        process::exit(2);
    }
    if args[1] == "--help" || args[1] == "-h" {
        usage(&args[0]);
        process::exit(0);
    }
    if args[1] == "convert" {
        if args.len() != 4 {
            eprintln!("Usage: {} convert <input> <output.con>", args[0]);
            process::exit(2);
        }
        let input = Path::new(&args[2]);
        let output = Path::new(&args[3]);
        match convert_path_to_con(input, output) {
            Ok(report) => {
                let kind = if report.native_con {
                    "native CON"
                } else {
                    "chemfiles import"
                };
                println!(
                    "-> convert ({kind}): {} frame(s), last frame {} atom(s) → {}",
                    report.n_frames,
                    report.n_atoms_last,
                    output.display()
                );
                if !report.native_con && !path_looks_like_con(input) {
                    println!(
                        "-> tip: keep this .con as the interchange file; link C/Fortran/Python via rkr_* / readcon"
                    );
                }
            }
            Err(e) => {
                eprintln!("Error: {e}");
                process::exit(1);
            }
        }
        return;
    }

    // Legacy: inspect / optional rewrite
    if args.len() > 3 {
        usage(&args[0]);
        process::exit(2);
    }
    let input_fname = Path::new(&args[1]);
    if !input_fname.exists() {
        eprintln!("Error: Input file not found at {}", input_fname.display());
        process::exit(1);
    }

    println!("-> Reading from '{}'...", input_fname.display());
    let fdat = std::fs::read_to_string(input_fname).expect("Failed to read input file.");
    let parser = ConFrameIterator::new(&fdat);

    let all_frames: Vec<ConFrame> = parser
        .filter_map(|result| match result {
            Ok(frame) => Some(frame),
            Err(e) => {
                eprintln!("-> Note: Discarding an incomplete frame. Error: {:?}", e);
                None
            }
        })
        .collect();

    if all_frames.is_empty() {
        eprintln!("Error: No valid frames found in the input file.");
        process::exit(1);
    }
    println!("-> Successfully parsed {} valid frames.", all_frames.len());

    if let Some(last_frame) = all_frames.last() {
        println!("\n-> Summary of last valid frame:");
        println!("  - Box vectors: {:?}", last_frame.header.boxl);
        println!("  - Angles: {:?}", last_frame.header.angles);
        println!("  - Atom masses: {:?}", last_frame.header.masses_per_type);
        println!("  - Number of atom types: {}", last_frame.header.natm_types);
        println!(
            "  - Atom numbers per type: {:?}",
            last_frame.header.natms_per_type
        );
        println!("  - Total atoms: {}", last_frame.atom_data.len());
        if let Some(last_atom) = last_frame.atom_data.last() {
            println!("  - Last atom: {:?}", last_atom);
        }
    }

    if let Some(output_fname_str) = args.get(2) {
        println!("\n-> Writing all frames to '{}'...", output_fname_str);
        match ConFrameWriter::from_path(output_fname_str) {
            Ok(mut writer) => {
                if let Err(e) = writer.extend(all_frames.iter()) {
                    eprintln!("Error writing to output file: {}", e);
                    process::exit(1);
                } else {
                    println!("-> Successfully wrote all frames to the output file.");
                }
            }
            Err(e) => {
                eprintln!("Failed to create output file: {}", e);
                process::exit(1);
            }
        }
    }
}
