use std::env;
use std::fs;
use std::path::Path;

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
    let lines: Vec<&str> = fdat.split("\n").collect();
    let res: Vec<f64> = lines[11]
        .split_whitespace()
        .map(|num| num.parse::<f64>().unwrap_or(0.))
        .collect();
    println!("{:?}", res);
}
