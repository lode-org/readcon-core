//! Print ok or the error text for one CON path.
fn main() {
    let path = std::env::args().nth(1).expect("path");
    match readcon_core::iterators::read_all_frames(std::path::Path::new(&path)) {
        Ok(frames) => println!("ok {}", frames.len()),
        Err(err) => println!("err {err}"),
    }
}
