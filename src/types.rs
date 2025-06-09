#[derive(Debug)]
pub struct FrameHeader {
    pub prebox_header: [String; 2],
    pub boxl: [f64; 3],
    pub angles: [f64; 3],
    pub postbox_header: [String; 2],
    pub natm_types: u32,
    pub natms_per_type: Vec<u32>,
    pub masses_per_type: Vec<f64>,
}

#[derive(Debug)]
pub struct AtomDatum {
    pub symbol: String,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub is_fixed: bool,
    pub atom_id: u64,
}

#[derive(Debug)]
pub struct ConFrame {
    pub header: FrameHeader,
    pub atom_data: Vec<AtomDatum>,
}
