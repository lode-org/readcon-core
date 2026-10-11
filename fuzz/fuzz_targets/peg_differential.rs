#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::ConFrameIterator;

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
    if data.len() > 8_192 {
        return;
    }
    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    if declares_huge_count(text) {
        return;
    }
    // CON-token.4: the PEG is the surface grammar. It has no ParseError
    // class, and it may reject text the hand parser still accepts.
    // Both parsers run so a panic in either is a crash. A curated
    // accept/reject list lives in grammar.rs.
    let peg = readcon_core::grammar::parse_surface(text);
    let hand = ConFrameIterator::new(text).collect::<Result<Vec<_>, _>>();
    std::hint::black_box((peg.is_ok(), hand.is_ok()));
});
