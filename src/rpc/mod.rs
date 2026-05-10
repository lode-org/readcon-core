pub mod read_con_capnp {
    #![allow(unused_parens)]
    include!(concat!(env!("OUT_DIR"), "/ReadCon_capnp.rs"));
}

pub mod client;
pub mod server;
