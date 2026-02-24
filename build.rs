fn main() {
    // Cap'n Proto schema compilation (behind rpc feature)
    #[cfg(feature = "rpc")]
    {
        let schema_path = std::path::Path::new("schema/ReadCon.capnp");
        if schema_path.exists() {
            capnpc::CompilerCommand::new()
                .file(schema_path)
                .run()
                .expect("Cap'n Proto schema compilation failed");
        } else {
            println!(
                "cargo:warning=Cap'n Proto schema not found at {}, RPC stubs will not be generated",
                schema_path.display()
            );
        }
    }
}
