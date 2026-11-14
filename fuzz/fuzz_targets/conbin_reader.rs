#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::conbin::{map_file, read_header, read_owned_f64, sum_mapped};

fuzz_target!(|data: &[u8]| {
    if data.len() > 64 * 1024 {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz.conbin");
    if std::fs::write(&path, data).is_err() {
        return;
    }
    let _ = read_header(&path);
    // The owned reader sizes its columns from the header. A count the
    // file cannot hold must fail before that reservation.
    let _ = read_owned_f64(&path, 1);
    let _ = read_owned_f64(&path, 2);
    if let Ok(mapped) = map_file(&path, 1) {
        if let Ok(positions) = mapped.positions_f64() {
            let _ = positions.iter().take(32).copied().sum::<f64>();
        }
        if let Ok(velocities) = mapped.velocities_f64() {
            let _ = velocities.iter().take(32).copied().sum::<f64>();
        }
        if let Ok(positions) = mapped.positions_f32() {
            let _ = positions.iter().take(32).copied().sum::<f32>();
        }
    }
    let _ = sum_mapped(&path, 1);
    let _ = sum_mapped(&path, 2);
});
