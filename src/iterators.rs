//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::parse_single_frame;
use crate::{error, types};
use std::iter::Peekable;

pub struct ConFrameIterator<'a> {
    lines: Peekable<std::str::Lines<'a>>,
}

impl<'a> ConFrameIterator<'a> {
    pub fn new(file_contents: &'a str) -> Self {
        ConFrameIterator {
            lines: file_contents.lines().peekable(),
        }
    }
}

impl<'a> Iterator for ConFrameIterator<'a> {
    type Item = Result<types::ConFrame, error::ParseError>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.lines.peek().is_none() {
            return None;
        }
        Some(parse_single_frame(&mut self.lines))
    }
}
