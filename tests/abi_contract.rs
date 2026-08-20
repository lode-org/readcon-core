use std::ffi::CStr;

#[test]
fn c_runtime_abi_stamp_matches_header_contract() {
    assert_eq!(readcon_core::ffi::rkr_abi_version_major(), 1);
    assert_eq!(readcon_core::ffi::rkr_abi_version_minor(), 0);
    assert_eq!(readcon_core::ffi::rkr_abi_layout_revision(), 1);

    let stamp = unsafe {
        CStr::from_ptr(readcon_core::ffi::rkr_abi_stamp())
            .to_str()
            .expect("ABI stamp is UTF-8")
    };
    assert_eq!(stamp, "readcon-core/abi-1.0/layout-1");
}
