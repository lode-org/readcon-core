#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::ConFrameIterator;

/// Skip a count line whose integer would make the parser allocate a huge frame.
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

fuzz_target!(|data: &[u8]| {
    if data.len() > 65_536 {
        return;
    }
    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    if declares_huge_count(text) {
        return;
    }
    let mut iter = ConFrameIterator::new(text);
    while let Some(item) = iter.next() {
        let _ = item;
    }
});
