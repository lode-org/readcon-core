//! Reading a small XYZ aborted inside `rc_chemfiles_scan` at the base
//! commit. The prebuilt libchemfiles atom stride did not match the shim.

#[cfg(feature = "chemfiles")]
#[test]
fn xyz_scan_reads_three_symbols_without_aborting() {
    use readcon_core::chemfiles_import::con_frames_from_memory;

    let xyz = "\
3
water
O  0.000  0.000  0.000
H  0.957  0.000  0.000
H -0.240  0.927  0.000
";
    let frames = con_frames_from_memory(xyz, "XYZ").expect("xyz import");
    assert_eq!(frames.len(), 1);
    let frame = &frames[0];
    assert_eq!(frame.atom_data.len(), 3);
    let symbols: Vec<&str> = frame
        .atom_data
        .iter()
        .map(|atom| atom.symbol.as_ref())
        .collect();
    assert_eq!(symbols, ["O", "H", "H"]);
    assert_eq!(frame.header.masses_per_type.len(), 2);
    let oxygen = frame.header.masses_per_type[0];
    let hydrogen = frame.header.masses_per_type[1];
    assert!(oxygen > 10.0, "oxygen mass {oxygen}");
    assert!(hydrogen > 0.5 && hydrogen < 2.0, "hydrogen mass {hydrogen}");
}
