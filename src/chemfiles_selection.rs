//! Chemfiles selection grammar on CON frames.
//!
//! Real evaluation requires the `chemfiles` Cargo feature. Without it, APIs
//! return [`ChemfilesImportError::FeatureDisabled`](crate::chemfiles_import::ChemfilesImportError::FeatureDisabled).

#[cfg(not(feature = "chemfiles"))]
use crate::chemfiles_import::ChemfilesImportError;
#[cfg(not(feature = "chemfiles"))]
use crate::types::ConFrame;

/// One selection match (up to 4 atom indices, chemfiles-style).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectionMatch {
    /// Number of valid entries in [`Self::atoms`] (1–4).
    pub size: usize,
    /// Atom indices in CON `atom_data` order.
    pub atoms: [usize; 4],
}

impl SelectionMatch {
    /// Slice of valid atom indices for this match.
    pub fn indices(&self) -> &[usize] {
        &self.atoms[..self.size.min(4)]
    }
}

/// Result of evaluating a chemfiles selection string on a [`ConFrame`].
#[derive(Debug, Clone)]
pub struct SelectionResult {
    /// Selection string that was evaluated.
    pub selection: String,
    /// 1 = atom, 2 = pair/bond, 3 = angle, 4 = dihedral.
    pub context_size: usize,
    /// Matches in CON `atom_data` index space.
    pub matches: Vec<SelectionMatch>,
}

impl SelectionResult {
    /// First atom index of each match (chemfiles “primary” index).
    pub fn primary_indices(&self) -> Vec<usize> {
        self.matches
            .iter()
            .filter_map(|m| m.indices().first().copied())
            .collect()
    }
}

/// One frame’s contribution to a multi-frame selection.
#[derive(Debug, Clone)]
pub struct FrameSelectionSlice {
    /// Index of this frame in the input slice (0-based).
    pub frame_index: usize,
    /// Full selection result on this frame.
    pub result: SelectionResult,
    /// For atom-context selections (`context_size == 1`): xyz of each selected
    /// atom in `atom_data` order for that frame (same length as sorted unique
    /// primary indices). Empty for pair/angle/dihedral contexts (use `result.matches`).
    pub positions: Vec<[f64; 3]>,
    /// Atom-context indices that produced [`Self::positions`] (sorted unique).
    pub atom_indices: Vec<usize>,
}

/// Multi-frame chemfiles selection: evaluate the same string on each frame.
#[derive(Debug, Clone)]
pub struct MultiFrameSelectionResult {
    /// Selection string evaluated on every frame.
    pub selection: String,
    /// Per-frame slices (same length as the input frame list).
    pub frames: Vec<FrameSelectionSlice>,
}

impl MultiFrameSelectionResult {
    /// Atom-context trajectory positions: for each frame, the `positions` vec
    /// (empty if that frame’s selection was not atom context or had no matches).
    pub fn positions_per_frame(&self) -> impl Iterator<Item = &Vec<[f64; 3]>> {
        self.frames.iter().map(|f| &f.positions)
    }
}

#[cfg(feature = "chemfiles")]
#[path = "chemfiles_selection_imp.rs"]
mod imp;

#[cfg(feature = "chemfiles")]
pub use imp::{
    apply_con_bonds_to_chemfiles_frame, chemfiles_frame_from_con_frame,
    evaluate_selection_on_chemfiles_frame, evaluate_selection_on_con_frame,
    evaluate_selection_on_frames, parse_selection_string, select_atom_indices,
    select_atom_positions_on_frames,
};

#[cfg(not(feature = "chemfiles"))]
/// Evaluate a chemfiles selection-language string on a [`ConFrame`].
///
/// Always returns [`ChemfilesImportError::FeatureDisabled`] without the feature.
pub fn evaluate_selection_on_con_frame(
    _selection: &str,
    _frame: &ConFrame,
) -> Result<SelectionResult, ChemfilesImportError> {
    Err(ChemfilesImportError::FeatureDisabled)
}

#[cfg(not(feature = "chemfiles"))]
/// Atom-context selection: sorted unique atom indices.
///
/// Always returns [`ChemfilesImportError::FeatureDisabled`] without the feature.
pub fn select_atom_indices(
    _selection: &str,
    _frame: &ConFrame,
) -> Result<Vec<usize>, ChemfilesImportError> {
    Err(ChemfilesImportError::FeatureDisabled)
}

#[cfg(not(feature = "chemfiles"))]
/// Parse-only check for a selection string (returns context size).
///
/// Always returns [`ChemfilesImportError::FeatureDisabled`] without the feature.
pub fn parse_selection_string(_selection: &str) -> Result<usize, ChemfilesImportError> {
    Err(ChemfilesImportError::FeatureDisabled)
}

#[cfg(not(feature = "chemfiles"))]
/// Multi-frame selection (stub without `chemfiles` feature).
pub fn evaluate_selection_on_frames(
    _selection: &str,
    _frames: &[ConFrame],
) -> Result<MultiFrameSelectionResult, ChemfilesImportError> {
    Err(ChemfilesImportError::FeatureDisabled)
}

#[cfg(not(feature = "chemfiles"))]
/// Atom-context multi-frame positions (stub without `chemfiles` feature).
pub fn select_atom_positions_on_frames(
    _selection: &str,
    _frames: &[ConFrame],
) -> Result<MultiFrameSelectionResult, ChemfilesImportError> {
    Err(ChemfilesImportError::FeatureDisabled)
}

#[cfg(all(test, not(feature = "chemfiles")))]
mod stub_tests {
    use super::*;
    use crate::chemfiles_import::ChemfilesImportError;
    use crate::types::ConFrameBuilder;

    #[test]
    fn selection_stub_is_feature_disabled() {
        let frame = ConFrameBuilder::new([10.0; 3], [90.0; 3]).build();
        let err = evaluate_selection_on_con_frame("name O", &frame).unwrap_err();
        assert!(matches!(err, ChemfilesImportError::FeatureDisabled));
    }

    #[test]
    fn multi_frame_selection_stub_is_feature_disabled() {
        let frame = ConFrameBuilder::new([10.0; 3], [90.0; 3]).build();
        let err = evaluate_selection_on_frames("name H", &[frame]).unwrap_err();
        assert!(matches!(err, ChemfilesImportError::FeatureDisabled));
        let frame2 = ConFrameBuilder::new([10.0; 3], [90.0; 3]).build();
        let err2 = select_atom_positions_on_frames("name H", &[frame2]).unwrap_err();
        assert!(matches!(err2, ChemfilesImportError::FeatureDisabled));
    }
}
