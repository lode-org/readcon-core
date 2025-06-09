use std::env;
use std::fs;

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
    let fname = &args[1];
    println!("Attempting to open file {}", fname);
    let fdat = fs::read_to_string(&args[1]).expect("Failed to read.");
    let lines: Vec<&str> = fdat.split("\n").collect();
    println!("{}", lines[0]);
}
