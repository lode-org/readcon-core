//! Standalone Rust usage example for readcon-core.
//!
//! Run with: cargo run --example rust_usage -- resources/test/tiny_cuh2.con
//! Or for convel: cargo run --example rust_usage -- resources/test/tiny_cuh2.convel

use std::env;
use std::fs;

use readcon_core::iterators::ConFrameIterator;
use readcon_core::writer::ConFrameWriter;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: {} <input.con|convel> [output.con]", args[0]);
        std::process::exit(1);
    }

    let input_path = &args[1];
    let contents = fs::read_to_string(input_path).expect("Failed to read input file");

    // Parse all frames lazily via the iterator
    let iter = ConFrameIterator::new(&contents);
    let mut frames = Vec::new();

    for result in iter {
        let frame = result.expect("Failed to parse frame");
        frames.push(frame);
    }

    println!("Parsed {} frame(s) from '{}'", frames.len(), input_path);

    for (i, frame) in frames.iter().enumerate() {
        println!("\n--- Frame {} ---", i + 1);
        println!(
            "  Cell:   [{:.4}, {:.4}, {:.4}]",
            frame.header.boxl[0], frame.header.boxl[1], frame.header.boxl[2]
        );
        println!(
            "  Angles: [{:.4}, {:.4}, {:.4}]",
            frame.header.angles[0], frame.header.angles[1], frame.header.angles[2]
        );
        println!("  Atom types: {}", frame.header.natm_types);
        println!("  Total atoms: {}", frame.atom_data.len());
        println!("  Has velocities: {}", frame.has_velocities());

        // Print first few atoms
        for (j, atom) in frame.atom_data.iter().take(5).enumerate() {
            print!(
                "  Atom {}: {} ({:.4}, {:.4}, {:.4}) fixed={} id={}",
                j, atom.symbol, atom.x, atom.y, atom.z, atom.is_fixed, atom.atom_id
            );
            if atom.has_velocity() {
                print!(
                    " vel=({:.6}, {:.6}, {:.6})",
                    atom.vx.unwrap(),
                    atom.vy.unwrap(),
                    atom.vz.unwrap()
                );
            }
            println!();
        }
        if frame.atom_data.len() > 5 {
            println!("  ... and {} more atoms", frame.atom_data.len() - 5);
        }
    }

    // Optionally write output
    if args.len() >= 3 {
        let output_path = &args[2];
        let file = fs::File::create(output_path).expect("Failed to create output file");
        let mut writer = ConFrameWriter::new(file);
        for frame in &frames {
            writer.write_frame(frame).expect("Failed to write frame");
        }
        println!("\nWrote {} frame(s) to '{}'", frames.len(), output_path);
    }
}
