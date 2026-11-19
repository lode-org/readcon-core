//! CON 4.0.0: units.time, the cell window, and persistent ids.

use readcon_core::error::ParseError;
use readcon_core::iterators::ConFrameIterator;
use readcon_core::types::ConFrameBuilder;
use readcon_core::units::{NATURAL_TIME_UNIT, velocity_file_time_unit};

fn text(meta: &str, angles: &str, body: &str) -> String {
    format!("t\n{meta}\n10 10 10\n{angles}\n0 0\n0 0 0\n{body}")
}

fn atoms() -> &'static str {
    "1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 1\n"
}

fn with_velocity(meta: &str) -> String {
    text(
        meta,
        "90 90 90",
        &format!("{}\nH\nVelocities of Component 1\n0.1 0 0 0 1\n", atoms()),
    )
}

fn parse(body: &str) -> Result<Vec<readcon_core::types::ConFrame>, ParseError> {
    ConFrameIterator::new(body).collect()
}

fn class_of(body: &str) -> String {
    parse(body).unwrap_err().class_name().to_string()
}

/// CON-status.3, CON-status.4, CON-status.5, CON-status.6, CON-line2.15, CON-line2.16, CON-line2.17.
/// The identity is major.minor.patch. A missing patch means patch 0, and a
/// patch that is not an integer is InvalidMetadataJson. A minor does not
/// change the meaning of units.time: major 3 keeps the old meaning at every minor.
#[test]
fn patch_identity_and_major3_time() {
    let units = r#""units":{"length":"angstrom","energy":"eV","mass":"amu"}"#;
    let ok = parse(&text(
        &format!(r#"{{"con_spec_version":4,"con_spec_minor":0,{units},"sections":[]}}"#),
        "90 90 90",
        atoms(),
    ))
    .unwrap();
    assert!(ok[0].header.metadata.get("con_spec_patch").is_none());
    assert_eq!(
        class_of(&text(
            &format!(r#"{{"con_spec_version":4,{units},"sections":[],"con_spec_patch":"0"}}"#),
            "90 90 90",
            atoms(),
        )),
        "InvalidMetadataJson"
    );
    let header = r#"{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"},"sections":["velocities"]}"#;
    let frames = parse(&with_velocity(header)).unwrap();
    let map = serde_json::Value::Object(frames[0].header.metadata.to_map().into_iter().collect());
    assert_eq!(
        velocity_file_time_unit(
            frames[0].header.spec_version,
            map.as_object().unwrap(),
            None
        )
        .unwrap(),
        NATURAL_TIME_UNIT
    );
    let bare = r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","mass":"amu"},"sections":["velocities"]}"#;
    assert!(parse(&with_velocity(bare)).is_ok());
}

#[test]
fn major3_keeps_case_insensitive_unit_compatibility() {
    let legacy = r#"{"con_spec_version":3,"units":{"length":"ANGSTROM","energy":"ha","mass":"AMU"},"sections":[]}"#;
    assert!(parse(&text(legacy, "90 90 90", atoms())).is_ok());
    let metadata = serde_json::Map::new();
    assert_eq!(
        velocity_file_time_unit(3, &metadata, Some("not-a-time-unit")).unwrap(),
        NATURAL_TIME_UNIT
    );
}

/// CON-units.3, CON-units.8, CON-units.9, CON-units.10, CON-units.11, CON-units.12.
/// Major 4 reads units.time and rejects velocities that omit it. The builder
/// writes the natural time unit for in-memory velocities.
#[test]
fn major4_time_is_authoritative() {
    let fs = r#"{"con_spec_version":4,"con_spec_minor":0,"con_spec_patch":0,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"},"sections":["velocities"]}"#;
    let frames = parse(&with_velocity(fs)).unwrap();
    let map = serde_json::Value::Object(frames[0].header.metadata.to_map().into_iter().collect());
    assert_eq!(
        velocity_file_time_unit(4, map.as_object().unwrap(), None).unwrap(),
        "fs"
    );
    let missing = r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV","mass":"amu"},"sections":["velocities"]}"#;
    assert_eq!(class_of(&with_velocity(missing)), "InvalidUnits");

    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0)
        .with_velocity([0.1, 0.0, 0.0]);
    let built = builder.build().unwrap();
    assert_eq!(built.header.spec_version, 4);
    assert_eq!(
        built
            .header
            .metadata
            .get("con_spec_patch")
            .and_then(|v| v.as_u64()),
        Some(0)
    );
    assert_eq!(
        built
            .header
            .metadata
            .get("units")
            .and_then(|u| u.get("time"))
            .and_then(|v| v.as_str()),
        Some(NATURAL_TIME_UNIT)
    );
}

/// CON-cell.7. A radicand inside -1e-12 is accepted. The next angle is not.
#[test]
fn cell_window_boundary() {
    let meta = r#"{"con_spec_version":4,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV"},"sections":[]}"#;
    assert!(parse(&text(meta, "60 60 120.00000000003307", atoms())).is_ok());
    assert_eq!(
        class_of(&text(meta, "60 60 120.00000000003308", atoms())),
        "ValidationError"
    );
}

/// CON-id.10, CON-id.11, CON-id.12. A true ids_persistent links the id set.
/// Absent on every frame, ids are not linked. A non-boolean is InvalidMetadataJson.
#[test]
fn persistent_ids() {
    let on = r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"},"sections":[],"ids_persistent":true}"#;
    let off = r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"},"sections":[]}"#;
    let one = |meta: &str, id: u64| {
        text(
            meta,
            "90 90 90",
            &format!("1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 {id}\n"),
        )
    };
    assert_eq!(parse(&(one(on, 7) + &one(on, 7))).unwrap().len(), 2);
    assert_eq!(class_of(&(one(on, 7) + &one(on, 8))), "ValidationError");
    assert_eq!(parse(&(one(off, 7) + &one(off, 8))).unwrap().len(), 2);
    let bad = r#"{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"},"sections":[],"ids_persistent":1}"#;
    assert_eq!(class_of(&one(bad, 7)), "InvalidMetadataJson");
}

/// CON-line2.2, CON-line2.21. Only a JSON number that overflows binary64 is
/// relaxed under an unreserved key. A token outside the JSON number grammar
/// is malformed JSON.
#[test]
fn con_line2_21_relaxes_overflow_not_malformed_numbers() {
    let units = r#""units":{"length":"angstrom","energy":"eV"}"#;
    let line = |value: &str| format!(r#"{{"con_spec_version":4,{units},"x":{value}}}"#);
    for value in ["1e999", "-1e999", "[1e999]"] {
        assert!(
            parse(&text(&line(value), "90 90 90", atoms())).is_ok(),
            "{value}"
        );
    }
    for value in [
        "1.2.3", "-", "1e", "1e+", "2-3", "1.5e3e4", "--1", "1.", "[1.2.3]",
    ] {
        assert_eq!(
            class_of(&text(&line(value), "90 90 90", atoms())),
            "InvalidMetadataJson",
            "{value}"
        );
    }
}
