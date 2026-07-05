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

Each ``ConFrameData`` message includes a ``specVersion`` field (default 2)
indicating the CON format spec version. Clients that do not set this
field receive the default (spec version 2). Older clients that do not
know this field will silently ignore it (standard Cap'n Proto evolution).

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

The RPC uses Cap'n Proto two-party protocol over TCP. The server
listens on a configurable host:port and handles one connection per
accepted socket using tokio for async I/O.
