pub mod read_con_capnp {
    include!(concat!(env!("OUT_DIR"), "/ReadCon_capnp.rs"));
}

pub mod server;
pub mod client;
