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

/// A builder for constructing `ConFrame` objects from in-memory data.
///
/// Atoms are accumulated and grouped by symbol on `build()` to compute the
/// header fields (`natm_types`, `natms_per_type`, `masses_per_type`).
///
/// # Example
///
/// ```
/// use readcon_core::types::ConFrameBuilder;
///
/// let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
/// builder.add_atom("Cu", 0.0, 0.0, 0.0, true, 0, 63.546);
/// builder.add_atom("H", 1.0, 2.0, 3.0, false, 1, 1.008);
/// let frame = builder.build();
/// assert_eq!(frame.header.natm_types, 2);
/// assert_eq!(frame.atom_data.len(), 2);
/// ```
pub struct ConFrameBuilder {
    prebox_header: [String; 2],
    cell: [f64; 3],
    angles: [f64; 3],
    postbox_header: [String; 2],
    atoms: Vec<BuilderAtom>,
}

struct BuilderAtom {
    symbol: String,
    x: f64,
    y: f64,
    z: f64,
    is_fixed: bool,
    atom_id: u64,
    mass: f64,
    vx: Option<f64>,
    vy: Option<f64>,
    vz: Option<f64>,
}

impl ConFrameBuilder {
    /// Creates a new builder with the given cell dimensions and angles.
    pub fn new(cell: [f64; 3], angles: [f64; 3]) -> Self {
        Self {
            prebox_header: [String::new(), String::new()],
            cell,
            angles,
            postbox_header: [String::new(), String::new()],
            atoms: Vec::new(),
        }
    }

    /// Sets the two pre-box header lines.
    pub fn prebox_header(mut self, h: [String; 2]) -> Self {
        self.prebox_header = h;
        self
    }

    /// Sets the two post-box header lines.
    pub fn postbox_header(mut self, h: [String; 2]) -> Self {
        self.postbox_header = h;
        self
    }

    /// Adds an atom without velocity data.
    pub fn add_atom(
        &mut self,
        symbol: &str,
        x: f64,
        y: f64,
        z: f64,
        is_fixed: bool,
        atom_id: u64,
        mass: f64,
    ) {
        self.atoms.push(BuilderAtom {
            symbol: symbol.to_string(),
            x,
            y,
            z,
            is_fixed,
            atom_id,
            mass,
            vx: None,
            vy: None,
            vz: None,
        });
    }

    /// Adds an atom with velocity data (for .convel output).
    pub fn add_atom_with_velocity(
        &mut self,
        symbol: &str,
        x: f64,
        y: f64,
        z: f64,
        is_fixed: bool,
        atom_id: u64,
        mass: f64,
        vx: f64,
        vy: f64,
        vz: f64,
    ) {
        self.atoms.push(BuilderAtom {
            symbol: symbol.to_string(),
            x,
            y,
            z,
            is_fixed,
            atom_id,
            mass,
            vx: Some(vx),
            vy: Some(vy),
            vz: Some(vz),
        });
    }

    /// Consumes the builder and produces a `ConFrame`.
    ///
    /// Atoms are grouped by symbol (in encounter order) to compute
    /// `natm_types`, `natms_per_type`, and `masses_per_type`.
    pub fn build(self) -> ConFrame {
        // Group atoms by symbol in encounter order
        let mut type_order: Vec<String> = Vec::new();
        let mut type_counts: Vec<usize> = Vec::new();
        let mut type_masses: Vec<f64> = Vec::new();

        for atom in &self.atoms {
            if let Some(idx) = type_order.iter().position(|s| s == &atom.symbol) {
                type_counts[idx] += 1;
            } else {
                type_order.push(atom.symbol.clone());
                type_counts.push(1);
                type_masses.push(atom.mass);
            }
        }

        // Sort atoms by type order (group same symbols together)
        let mut sorted_atoms: Vec<&BuilderAtom> = Vec::with_capacity(self.atoms.len());
        for symbol in &type_order {
            for atom in &self.atoms {
                if &atom.symbol == symbol {
                    sorted_atoms.push(atom);
                }
            }
        }

        let atom_data: Vec<AtomDatum> = sorted_atoms
            .iter()
            .map(|a| {
                let symbol = Rc::new(a.symbol.clone());
                AtomDatum {
                    symbol,
                    x: a.x,
                    y: a.y,
                    z: a.z,
                    is_fixed: a.is_fixed,
                    atom_id: a.atom_id,
                    vx: a.vx,
                    vy: a.vy,
                    vz: a.vz,
                }
            })
            .collect();

        let header = FrameHeader {
            prebox_header: self.prebox_header,
            boxl: self.cell,
            angles: self.angles,
            postbox_header: self.postbox_header,
            natm_types: type_order.len(),
            natms_per_type: type_counts,
            masses_per_type: type_masses,
        };

        ConFrame { header, atom_data }
    }
}

impl ConFrame {
    /// Creates a new builder for constructing a `ConFrame`.
    pub fn builder(cell: [f64; 3], angles: [f64; 3]) -> ConFrameBuilder {
        ConFrameBuilder::new(cell, angles)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_builder_basic() {
        let mut builder = ConFrameBuilder::new([10.0, 20.0, 30.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, true, 0, 63.546);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, true, 1, 63.546);
        builder.add_atom("H", 2.0, 3.0, 4.0, false, 2, 1.008);
        let frame = builder.build();

        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![2, 1]);
        assert_eq!(frame.header.masses_per_type, vec![63.546, 1.008]);
        assert_eq!(frame.atom_data.len(), 3);
        assert_eq!(&*frame.atom_data[0].symbol, "Cu");
        assert_eq!(&*frame.atom_data[2].symbol, "H");
    }

    #[test]
    fn test_builder_with_velocities() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom_with_velocity("Cu", 0.0, 0.0, 0.0, true, 0, 63.546, 0.1, 0.2, 0.3);
        let frame = builder.build();

        assert!(frame.has_velocities());
        assert_eq!(frame.atom_data[0].vx, Some(0.1));
        assert_eq!(frame.atom_data[0].vy, Some(0.2));
        assert_eq!(frame.atom_data[0].vz, Some(0.3));
    }

    #[test]
    fn test_builder_with_headers() {
        let frame = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0])
            .prebox_header(["line1".to_string(), "line2".to_string()])
            .postbox_header(["line3".to_string(), "line4".to_string()])
            .build();

        assert_eq!(frame.header.prebox_header, ["line1", "line2"]);
        assert_eq!(frame.header.postbox_header, ["line3", "line4"]);
    }

    #[test]
    fn test_builder_groups_atoms_by_symbol() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        // Add interleaved symbols
        builder.add_atom("H", 0.0, 0.0, 0.0, false, 0, 1.008);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, true, 1, 63.546);
        builder.add_atom("H", 2.0, 0.0, 0.0, false, 2, 1.008);
        let frame = builder.build();

        // H appears first, so it should be first type
        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![2, 1]);
        // Atoms should be grouped: H, H, Cu
        assert_eq!(&*frame.atom_data[0].symbol, "H");
        assert_eq!(&*frame.atom_data[1].symbol, "H");
        assert_eq!(&*frame.atom_data[2].symbol, "Cu");
    }
}
