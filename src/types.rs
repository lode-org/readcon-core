//=============================================================================
// Data Structures - The shape of our parsed data
//=============================================================================

use std::rc::Rc;

/// Holds all metadata from the 9-line header of a simulation frame.
#[derive(Debug, PartialEq, Clone)]
pub struct FrameHeader {
    /// The two text lines preceding the box dimension data.
    pub prebox_header: [String; 2],
    /// The three box dimensions, typically Lx, Ly, and Lz.
    pub boxl: [f64; 3],
    /// The three box angles, typically alpha, beta, and gamma.
    pub angles: [f64; 3],
    /// The two text lines following the box angle data.
    pub postbox_header: [String; 2],
    /// The number of distinct atom types in the frame.
    pub natm_types: usize,
    /// A vector containing the count of atoms for each respective type.
    pub natms_per_type: Vec<usize>,
    /// A vector containing the mass for each respective atom type.
    pub masses_per_type: Vec<f64>,
}

/// Represents the data for a single atom in a frame.
#[derive(Debug, Clone)]
pub struct AtomDatum {
    /// The chemical symbol of the atom (e.g., "C", "H", "O").
    /// Using Rc<String> to avoid expensive clones for each atom of the same type.
    pub symbol: Rc<String>,
    /// The Cartesian x-coordinate.
    pub x: f64,
    /// The Cartesian y-coordinate.
    pub y: f64,
    /// The Cartesian z-coordinate.
    pub z: f64,
    /// A flag indicating if the atom's position is fixed during a simulation.
    pub is_fixed: bool,
    /// A unique integer identifier for the atom.
    pub atom_id: u64,
    /// The x-component of velocity (present only in `.convel` files).
    pub vx: Option<f64>,
    /// The y-component of velocity (present only in `.convel` files).
    pub vy: Option<f64>,
    /// The z-component of velocity (present only in `.convel` files).
    pub vz: Option<f64>,
}

impl AtomDatum {
    /// Returns `true` if this atom has velocity data.
    pub fn has_velocity(&self) -> bool {
        self.vx.is_some() && self.vy.is_some() && self.vz.is_some()
    }
}

// Manual implementation of PartialEq because Rc<T> doesn't derive it by default.
impl PartialEq for AtomDatum {
    fn eq(&self, other: &Self) -> bool {
        // Compare the string values, not the pointers.
        *self.symbol == *other.symbol
            && self.x == other.x
            && self.y == other.y
            && self.z == other.z
            && self.is_fixed == other.is_fixed
            && self.atom_id == other.atom_id
            && self.vx == other.vx
            && self.vy == other.vy
            && self.vz == other.vz
    }
}

/// Represents a single, complete simulation frame, including header and all atomic data.
#[derive(Debug, Clone)]
pub struct ConFrame {
    /// The `FrameHeader` containing the frame's metadata.
    pub header: FrameHeader,
    /// A vector holding all atomic data for the frame.
    pub atom_data: Vec<AtomDatum>,
}

impl ConFrame {
    /// Returns `true` if any atom in this frame has velocity data.
    pub fn has_velocities(&self) -> bool {
        self.atom_data.first().is_some_and(|a| a.has_velocity())
    }
}

// Manual implementation of PartialEq because of the change to AtomDatum.
impl PartialEq for ConFrame {
    fn eq(&self, other: &Self) -> bool {
        self.header == other.header && self.atom_data == other.atom_data
    }
}
