//! Formal CON/convel surface grammar ([Pest](https://pest.rs) PEG).
//!
//! Enable with `--features grammar`. The production parser in [`crate::parser`]
//! remains the hot path; this module exists so the repo ships a machine-checkable
//! PEG next to the prose specification (`docs/orgmode/spec.org`, source file
//! `grammar/con.pest`).
//!
//! Semantic constraints (per-type atom counts, component indices, JSON metadata)
//! are **not** fully encoded in the PEG — see comments in `grammar/con.pest`.

#![cfg(feature = "grammar")]

use pest::Parser;
use pest_derive::Parser;

/// Pest-generated parser for [`Rule`].
#[derive(Parser)]
#[grammar = "../grammar/con.pest"]
pub struct ConGrammar;

/// Parse `input` as a full CON/convel multi-frame buffer under the surface PEG.
///
/// Returns `Ok(())` when the grammar accepts the input. Does not construct
/// [`crate::types::ConFrame`] values.
pub fn parse_surface(input: &str) -> Result<(), pest::error::Error<Rule>> {
    ConGrammar::parse(Rule::file, input).map(|_| ())
}

/// Whether `input` is accepted by the surface grammar (convenience for tests).
pub fn accepts(input: &str) -> bool {
    parse_surface(input).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn fixture(name: &str) -> String {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name);
        fs::read_to_string(&p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
    }

    #[test]
    fn grammar_accepts_core_fixtures() {
        for name in [
            "tiny_cuh2.con",
            "cuh2.con",
            "tiny_multi_cuh2.con",
            "tiny_cuh2_vel_forces.con",
            "tiny_multi_cuh2.convel",
        ] {
            let text = fixture(name);
            assert!(
                accepts(&text),
                "grammar rejected fixture {name}: {:?}",
                parse_surface(&text).err()
            );
        }
    }

    #[test]
    fn grammar_rejects_obvious_garbage() {
        assert!(!accepts(""));
        assert!(!accepts("not a con file\n"));
        assert!(!accepts("only one line"));
    }

    #[test]
    fn grammar_file_is_shipped() {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("grammar/con.pest");
        assert!(p.is_file(), "expected shipped grammar at {}", p.display());
        let body = fs::read_to_string(&p).unwrap();
        assert!(body.contains("file = {"), "grammar should define file rule");
        assert!(body.contains("Coordinates of Component"));
    }
}
