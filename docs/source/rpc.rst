=======================
Cap'n Proto RPC serving
=======================



Overview
--------

readcon-core provides an optional Cap'n Proto RPC interface (behind
the ``rpc`` feature flag) that allows any language with a Cap'n Proto
implementation to request frame parsing and writing over the network.

Schema
------

The schema defines a ``ReadConService`` interface with two methods:

``parseFrames``
    Accepts raw file bytes, returns parsed frame data.

``writeFrames``
    Accepts structured frame data, returns serialized
    file bytes.

The schema file is at ``schema/ReadCon.capnp``.

****CON v3 field parity**** (wire shape of a parsed ``ConFrame``, not an on-disk
bcon file):

.. table::

    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | Cap'n Proto                                                                      | Maps to                                                    |
    +==================================================================================+============================================================+
    | ``ConAtom.fixedMask`` (u8, 0–7)                                                  | per-axis constraints (``encode_fixed_bitmask``)            |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``ConAtom`` velocity / force / energy / charge / spin / magmom                   | ``AtomDatum`` optional sections                            |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``ConFrameData.specVersion``                                                     | ``FrameHeader.spec_version`` (default 2)                   |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``hasForces`` / ``hasEnergies`` / ``hasCharges`` / ``hasSpins`` / ``hasMagmoms`` | section presence                                           |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``massesPerType`` / ``natmsPerType``                                             | type table                                                 |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``sections``                                                                     | declared section names                                     |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``metadataJson``                                                                 | free-form + reserved JSON keys (``units``, energy, NEB, …) |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+
    | ``strictValidation`` / ``sectionsDeclared``                                      | parse policy flags                                         |
    +----------------------------------------------------------------------------------+------------------------------------------------------------+

Round-trip helpers live in ``src/rpc/convert.rs`` (``fill_frame_builder`` /
``frame_from_reader``). Text ``.con`` remains the on-disk interchange authority.

**Breaking note:** pre-v3 wire used a single ``isFixed: Bool`` and velocity-only
atoms. Clients must regenerate from the current schema (0.x RPC surface).

Building
--------

.. code:: shell

    # Requires capnproto installed (via pixi or system package)
    cargo build --features rpc

    # Or via pixi (capnproto is a dependency)
    pixi r build-rpc

Server
------

.. code:: rust

    // Start a TCP RPC server
    #[tokio::main]
    async fn main() {
        readcon_core::rpc::server::start_server("127.0.0.1:9876")
            .await
            .unwrap();
    }

Client
------

.. code:: rust

    use readcon_core::rpc::client::RpcClient;
    use std::path::Path;

    let client = RpcClient::new("127.0.0.1:9876").unwrap();
    let frames = client.parse_file(Path::new("input.con")).unwrap();
    let output = client.write_frames(&frames).unwrap();

Protocol
--------

The RPC uses Cap'n Proto two-party as the encoding. The byte pipe is
not UCX, libfabric, Mercury, or ADIOS.

- ``host:port`` or ``[ipv6]:port`` is TCP.
- ``unix:/abs/path``, ``unix:///abs/path``, or ``/abs/path`` is a Unix
  domain socket.

Same-node HPC jobs should use a Unix socket. TCP is for inet. UCX,
ADIOS, and DAOS are optional later adapters if a campaign consumer
exists; they are not this crate and they are not the CON store.

.. code:: rust

    readcon_core::rpc::server::start_server("unix:/tmp/readcon.sock")
    let client = RpcClient::new("unix:/tmp/readcon.sock").unwrap();
