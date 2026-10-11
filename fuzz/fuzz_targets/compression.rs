#![no_main]

use flate2::read::MultiGzDecoder;
use libfuzzer_sys::fuzz_target;
use readcon_core::compression::{detect_compression, read_file_contents, Compression};
use readcon_core::iterators::ConFrameIterator;
use std::io::Read;
use std::sync::atomic::{AtomicU64, Ordering};

static TEMP_SEQ: AtomicU64 = AtomicU64::new(0);

const CAP: usize = 1 << 20;

fn declares_huge_count(text: &str) -> bool {
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let mut huge = false;
        for token in line.split_whitespace() {
            match token.parse::<u64>() {
                Ok(n) if n > 20_000 => huge = true,
                Ok(_) => {}
                Err(_) => {
                    huge = false;
                    break;
                }
            }
        }
        if huge {
            return true;
        }
    }
    false
}

fn decompress_capped(bytes: &[u8]) -> Option<String> {
    let mut out = Vec::new();
    match detect_compression(bytes) {
        Compression::Gzip => {
            let mut limited = MultiGzDecoder::new(bytes).take(CAP as u64);
            limited.read_to_end(&mut out).ok()?;
        }
        Compression::Zstd => {
            let decoder = zstd::stream::read::Decoder::new(bytes).ok()?;
            let mut limited = decoder.take(CAP as u64);
            limited.read_to_end(&mut out).ok()?;
        }
        Compression::None => out.extend_from_slice(bytes),
    }
    if out.len() >= CAP {
        return None;
    }
    String::from_utf8(out).ok()
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 16_384 {
        return;
    }
    let Some(text) = decompress_capped(data) else {
        return;
    };
    let seq = TEMP_SEQ.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!("readcon-fuzz-{}-{seq}", std::process::id()));
    if std::fs::write(&path, data).is_ok() {
        if let Ok(contents) = read_file_contents(&path) {
            let _ = contents.as_str();
        }
        let _ = std::fs::remove_file(&path);
    }
    if declares_huge_count(&text) {
        return;
    }
    let mut iter = ConFrameIterator::new(&text);
    while let Some(item) = iter.next() {
        let _ = item;
    }
});
