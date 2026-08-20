pub mod read_con_capnp {
    #![allow(unused_parens)]
    include!(concat!(env!("OUT_DIR"), "/ReadCon_capnp.rs"));
}

pub mod client;
pub mod convert;
pub mod server;

use read_con_capnp::compatibility_stamp;

/// Fill a wire compatibility record with this library's negotiated contract.
pub fn set_compatibility_stamp(mut stamp: compatibility_stamp::Builder<'_>) {
    stamp.set_abi_major(crate::ffi::RKR_ABI_VERSION_MAJOR);
    stamp.set_abi_minor(crate::ffi::RKR_ABI_VERSION_MINOR);
    stamp.set_abi_layout_revision(crate::ffi::RKR_ABI_LAYOUT_REVISION);
    stamp.set_con_spec_version(crate::CON_SPEC_VERSION);
}

/// Reject a wire compatibility record that this library cannot safely consume.
pub fn validate_compatibility_stamp(
    stamp: compatibility_stamp::Reader<'_>,
) -> Result<(), String> {
    if stamp.get_abi_major() != crate::ffi::RKR_ABI_VERSION_MAJOR {
        return Err(format!(
            "incompatible readcon-core ABI major: {}",
            stamp.get_abi_major()
        ));
    }
    if stamp.get_abi_layout_revision() != crate::ffi::RKR_ABI_LAYOUT_REVISION {
        return Err(format!(
            "incompatible readcon-core ABI layout: {}",
            stamp.get_abi_layout_revision()
        ));
    }
    if stamp.get_con_spec_version() > crate::CON_SPEC_VERSION {
        return Err(format!(
            "unsupported CON spec version: {}",
            stamp.get_con_spec_version()
        ));
    }
    Ok(())
}
