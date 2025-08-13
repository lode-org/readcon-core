use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;
use readcon_core::writer::write_con_file;
use std::env;
use std::fs::{self, File};
use std::io::BufWriter;
use std::path::Path;

fn main() {
    let args: Vec<String> = env::args().collect();
    // One mandatory argument (input) and one optional (output).
    if args.len() < 2 || args.len() > 3 {
        eprintln!("Usage: {} <input.con> [output.con]", args[0]);
        std::process::exit(1);
    }

    // --- Reading Logic ---
    let input_fname = Path::new(&args[1]);
    if !input_fname.exists() {
        eprintln!("Error: Input file not found at {}", input_fname.display());
        std::process::exit(1);
    }

    println!("-> Reading from '{}'...", input_fname.display());
    let fdat = fs::read_to_string(input_fname).expect("Failed to read input file.");
    let parser = ConFrameIterator::new(&fdat);

    // Collect all valid frames from the input file.
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
        std::process::exit(1);
    }
    println!("-> Successfully parsed {} valid frames.", all_frames.len());

    // --- Summary Logic (restored from older version) ---
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

    // --- Optional Writing Logic ---
    // Check if the optional output filename was provided.
    if let Some(output_fname_str) = args.get(2) {
        let output_fname = Path::new(output_fname_str);
        println!("\n-> Writing all frames to '{}'...", output_fname.display());

        let output_file = File::create(output_fname).expect("Failed to create output file.");
        let mut writer = BufWriter::new(output_file);

        // Pass an iterator over the collected frames to the writer function.
        match write_con_file(all_frames.iter(), &mut writer) {
            Ok(_) => println!("-> Successfully wrote all frames to the output file."),
            Err(e) => eprintln!("Error writing to output file: {}", e),
        }
    }
}
