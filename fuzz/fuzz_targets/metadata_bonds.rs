#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::types::parse_bonds_from_metadata;
use std::collections::BTreeMap;

fuzz_target!(|data: &[u8]| {
    let text = String::from_utf8_lossy(data);
    let value = match serde_json::from_str::<serde_json::Value>(&text) {
        Ok(v) => v,
        Err(_) => return,
    };
    let mut metadata = BTreeMap::new();
    match value {
        serde_json::Value::Object(obj) => {
            if let Some(bonds) = obj.get("bonds") {
                metadata.insert("bonds".to_string(), bonds.clone());
            } else {
                metadata.insert("bonds".to_string(), serde_json::Value::Object(obj));
            }
        }
        other => {
            metadata.insert("bonds".to_string(), other);
        }
    }
    let _ = parse_bonds_from_metadata(&metadata);
});
