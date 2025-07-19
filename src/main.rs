use std::env;
use std::fs;
use std::path::Path;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrame;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!(
            "Usage: {} <filename>\nbut got {} arguments",
            args[0],
            args.len()
        );
        std::process::exit(1);
    }
    let fname = Path::new(&args[1]);
    if !fname.exists() {
        eprintln!("Error: File not found at {}", fname.display());
    }
    let fdat = fs::read_to_string(&args[1]).expect("Failed to read.");
    let parser = ConFrameIterator::new(&fdat);
    let good_frames: Vec<ConFrame> = parser
        .filter_map(|result| match result {
            Ok(frame) => Some(frame),
            Err(e) => {
                eprintln!(
                    "-> Note: Discarding an incomplete or invalid frame. Error: {:?}\n",
                    e
                );
                None
            }
        })
        .collect();

    println!(
        "-> Parsing complete. Found {} valid frames.",
        good_frames.len()
    );

    if let Some(last_frame) = good_frames.last() {
        println!("\n-> Summary of last valid frame:");
        println!("  - Box vectors: {:?}", last_frame.header.boxl);
        println!("  - Angles: {:?}", last_frame.header.angles);
        println!("  - Atom masses: {:?}", last_frame.header.masses_per_type);
        println!("  - Number of atom types: {:?}", last_frame.header.natm_types);
        println!(
            "  - Atom numbers per type: {:?}",
            last_frame.header.natms_per_type
        );
        println!("  - Atom types: {}", last_frame.header.natm_types);
        println!("  - Total atoms: {}", last_frame.atom_data.len());
        if let Some(last_atom) = last_frame.atom_data.last() {
            println!("  - Last atom: {:?}", last_atom);
        }
    }
}
