//! Cap'n Proto ↔ [`ConFrame`] conversion (CON v3 field parity).

use std::collections::BTreeMap;
use std::sync::Arc;

use super::read_con_capnp::con_frame_data;
use crate::error::ConvertError;
use crate::types::{
    AtomDatum, ConFrame, FrameHeader, FrameMeta, PreboxHeader, con_frame_from_atom_data,
    decode_fixed_bitmask_for_spec, encode_fixed_bitmask,
};

/// Fill one `ConFrameData` builder from a [`ConFrame`].
///
/// # Errors
///
/// [`ConvertError::Parse`] with [`crate::error::ParseError::NonFiniteValue`]
/// for a NaN or infinite cell length or angle, naming `boxl[i]` or
/// `angles[i]`. [`ConvertError::in_frame`] adds the frame.
pub fn fill_frame_builder(
    mut fb: con_frame_data::Builder<'_>,
    frame: &ConFrame,
) -> Result<(), ConvertError> {
    frame.header.check_cell_finite()?;
    let mut cell = fb.reborrow().init_cell(3);
    for (j, &v) in frame.header.boxl.iter().enumerate() {
        cell.set(j as u32, v);
    }
    let mut angles = fb.reborrow().init_angles(3);
    for (j, &v) in frame.header.angles.iter().enumerate() {
        angles.set(j as u32, v);
    }

    let mut prebox = fb.reborrow().init_prebox_header(2);
    prebox.set(0, frame.header.prebox_header.user.as_str());
    prebox.set(1, frame.header.prebox_header.metadata_line());

    let mut postbox = fb.reborrow().init_postbox_header(2);
    postbox.set(0, frame.header.postbox_header[0].as_str());
    postbox.set(1, frame.header.postbox_header[1].as_str());

    fb.set_has_velocities(frame.has_velocities());
    fb.set_spec_version(frame.header.spec_version);
    fb.set_has_forces(frame.has_forces());
    fb.set_has_energies(frame.atom_data.iter().any(|a| a.has_energy()));
    fb.set_has_charges(frame.atom_data.iter().any(|a| a.has_charge()));
    fb.set_has_spins(frame.atom_data.iter().any(|a| a.has_spin()));
    fb.set_has_magmoms(frame.atom_data.iter().any(|a| a.has_magmom()));
    fb.set_has_displacements(frame.atom_data.iter().any(|a| a.has_displacement()));
    fb.set_has_spreads(frame.atom_data.iter().any(|a| a.has_spread()));

    let mut masses = fb
        .reborrow()
        .init_masses_per_type(frame.header.masses_per_type.len() as u32);
    for (i, &m) in frame.header.masses_per_type.iter().enumerate() {
        masses.set(i as u32, m);
    }
    let mut counts = fb
        .reborrow()
        .init_natms_per_type(frame.header.natms_per_type.len() as u32);
    for (i, &n) in frame.header.natms_per_type.iter().enumerate() {
        counts.set(i as u32, n as u32);
    }

    let mut sections = fb
        .reborrow()
        .init_sections(frame.header.sections.len() as u32);
    for (i, s) in frame.header.sections.iter().enumerate() {
        sections.set(i as u32, s.as_str());
    }

    let meta_json = crate::writer::serialize_json_map_with_minor_raw(
        &frame.header.metadata.to_map(),
        frame.header.metadata.huge_minor_raw(),
    )
    .map_err(|e| format!("metadata json: {e}"))?;
    fb.set_metadata_json(&meta_json);
    fb.set_strict_validation(frame.header.strict_validation);
    fb.set_sections_declared(frame.header.sections_declared);
    fb.set_prebox_user(frame.header.prebox_header.user.as_str());

    let mut atoms_builder = fb.reborrow().init_atoms(frame.atom_data.len() as u32);
    for (k, atom) in frame.atom_data.iter().enumerate() {
        let mut ab = atoms_builder.reborrow().get(k as u32);
        ab.set_symbol(atom.symbol.as_ref());
        let xyz = frame.xyz_at(k);
        ab.set_x(xyz[0]);
        ab.set_y(xyz[1]);
        ab.set_z(xyz[2]);
        ab.set_fixed_mask(encode_fixed_bitmask(atom.fixed()));
        ab.set_atom_id(atom.atom_id);

        if let Some([vx, vy, vz]) = atom.velocity() {
            ab.set_has_velocity(true);
            ab.set_vx(vx);
            ab.set_vy(vy);
            ab.set_vz(vz);
        } else {
            ab.set_has_velocity(false);
        }
        if let Some([fx, fy, fz]) = atom.force() {
            ab.set_has_force(true);
            ab.set_fx(fx);
            ab.set_fy(fy);
            ab.set_fz(fz);
        } else {
            ab.set_has_force(false);
        }
        if let Some(e) = atom.energy() {
            ab.set_has_energy(true);
            ab.set_energy(e);
        } else {
            ab.set_has_energy(false);
        }
        if let Some(c) = atom.charge() {
            ab.set_has_charge(true);
            ab.set_charge(c);
        } else {
            ab.set_has_charge(false);
        }
        if let Some(s) = atom.spin() {
            ab.set_has_spin(true);
            ab.set_spin(s);
        } else {
            ab.set_has_spin(false);
        }
        if let Some([mx, my, mz]) = atom.magmom() {
            ab.set_has_magmom(true);
            ab.set_mx(mx);
            ab.set_my(my);
            ab.set_mz(mz);
        } else {
            ab.set_has_magmom(false);
        }
        if let Some([dx, dy, dz]) = atom.displacement() {
            ab.set_has_displacement(true);
            ab.set_dx(dx);
            ab.set_dy(dy);
            ab.set_dz(dz);
        } else {
            ab.set_has_displacement(false);
        }
        if let Some([sx, sy, sz]) = atom.spread() {
            ab.set_has_spread(true);
            ab.set_sx(sx);
            ab.set_sy(sy);
            ab.set_sz(sz);
        } else {
            ab.set_has_spread(false);
        }
    }
    Ok(())
}

/// Rebuild a [`ConFrame`] from a Cap'n Proto reader.
///
/// # Errors
///
/// [`ConvertError::Parse`] with [`crate::error::ParseError::NonFiniteValue`]
/// for a NaN or infinite cell on the wire, naming `boxl[i]` or `angles[i]`.
/// [`ConvertError::Message`] for a malformed message.
pub fn frame_from_reader(fd: con_frame_data::Reader<'_>) -> Result<ConFrame, ConvertError> {
    let cell_list = fd.get_cell().map_err(|e| e.to_string())?;
    let angles_list = fd.get_angles().map_err(|e| e.to_string())?;
    if cell_list.len() < 3 || angles_list.len() < 3 {
        return Err("cell/angles must have length 3".into());
    }
    let boxl = [cell_list.get(0), cell_list.get(1), cell_list.get(2)];
    let angles = [angles_list.get(0), angles_list.get(1), angles_list.get(2)];
    crate::types::check_cell_finite(&boxl, "boxl", &angles, "angles")?;

    let prebox_list = fd.get_prebox_header().map_err(|e| e.to_string())?;
    let postbox_list = fd.get_postbox_header().map_err(|e| e.to_string())?;

    let prebox_user = if fd.has_prebox_user() {
        fd.get_prebox_user()
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string()
    } else if !prebox_list.is_empty() {
        prebox_list
            .get(0)
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string()
    } else {
        String::new()
    };
    let prebox_metadata_line = if prebox_list.len() > 1 {
        prebox_list
            .get(1)
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string()
    } else {
        String::new()
    };
    let postbox_header = [
        if !postbox_list.is_empty() {
            postbox_list
                .get(0)
                .map_err(|e| e.to_string())?
                .to_str()
                .unwrap_or_default()
                .to_string()
        } else {
            String::new()
        },
        if postbox_list.len() > 1 {
            postbox_list
                .get(1)
                .map_err(|e| e.to_string())?
                .to_str()
                .unwrap_or_default()
                .to_string()
        } else {
            String::new()
        },
    ];

    let masses_list = fd.get_masses_per_type().map_err(|e| e.to_string())?;
    let mut masses_per_type: Vec<f64> =
        (0..masses_list.len()).map(|i| masses_list.get(i)).collect();
    let counts_list = fd.get_natms_per_type().map_err(|e| e.to_string())?;
    let mut natms_per_type: Vec<usize> = (0..counts_list.len())
        .map(|i| counts_list.get(i) as usize)
        .collect();

    let sections_list = fd.get_sections().map_err(|e| e.to_string())?;
    let mut sections = Vec::with_capacity(sections_list.len() as usize);
    for i in 0..sections_list.len() {
        let s = sections_list
            .get(i)
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string();
        sections.push(s);
    }

    let (metadata, minor_raw): (BTreeMap<String, serde_json::Value>, Option<String>) =
        if fd.has_metadata_json() {
            let raw = fd
                .get_metadata_json()
                .map_err(|e| e.to_string())?
                .to_str()
                .unwrap_or("{}");
            if raw.trim().is_empty() {
                (BTreeMap::new(), None)
            } else {
                crate::parser::parse_metadata_map_with_minor_raw(raw)
                    .map_err(|e| format!("metadataJson: {e}"))?
            }
        } else {
            (BTreeMap::new(), None)
        };

    let spec_version = fd.get_spec_version();
    let atoms_list = fd.get_atoms().map_err(|e| e.to_string())?;
    if natms_per_type.is_empty() {
        let mut current_symbol = String::new();
        let mut current_count = 0usize;
        for j in 0..atoms_list.len() {
            let a = atoms_list.get(j);
            let sym = a
                .get_symbol()
                .map_err(|e| e.to_string())?
                .to_str()
                .unwrap_or_default()
                .to_string();
            if sym != current_symbol {
                if current_count > 0 {
                    natms_per_type.push(current_count);
                    if masses_per_type.len() < natms_per_type.len() {
                        masses_per_type.push(0.0);
                    }
                }
                current_symbol = sym;
                current_count = 0;
            }
            current_count += 1;
        }
        if current_count > 0 {
            natms_per_type.push(current_count);
            while masses_per_type.len() < natms_per_type.len() {
                masses_per_type.push(0.0);
            }
        }
    }

    let mut atom_data = Vec::with_capacity(atoms_list.len() as usize);
    let mut coords = Vec::with_capacity(atoms_list.len() as usize);
    for j in 0..atoms_list.len() {
        let a = atoms_list.get(j);
        let sym = a
            .get_symbol()
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string();
        atom_data.push(AtomDatum::with_sections(
            Arc::from(sym),
            a.get_x(),
            a.get_y(),
            a.get_z(),
            decode_fixed_bitmask_for_spec(a.get_fixed_mask(), spec_version),
            a.get_atom_id(),
            if a.get_has_velocity() {
                Some([a.get_vx(), a.get_vy(), a.get_vz()])
            } else {
                None
            },
            if a.get_has_force() {
                Some([a.get_fx(), a.get_fy(), a.get_fz()])
            } else {
                None
            },
            if a.get_has_energy() {
                Some(a.get_energy())
            } else {
                None
            },
            if a.get_has_charge() {
                Some(a.get_charge())
            } else {
                None
            },
            if a.get_has_spin() {
                Some(a.get_spin())
            } else {
                None
            },
            if a.get_has_magmom() {
                Some([a.get_mx(), a.get_my(), a.get_mz()])
            } else {
                None
            },
            if a.get_has_displacement() {
                Some([a.get_dx(), a.get_dy(), a.get_dz()])
            } else {
                None
            },
            if a.get_has_spread() {
                Some([a.get_sx(), a.get_sy(), a.get_sz()])
            } else {
                None
            },
        ));
        coords.push([a.get_x(), a.get_y(), a.get_z()]);
    }

    let header = FrameHeader {
        prebox_header: PreboxHeader {
            user: prebox_user,
            metadata_line: std::sync::Arc::from(prebox_metadata_line),
        },
        boxl,
        angles,
        postbox_header,
        natm_types: natms_per_type.len(),
        natms_per_type,
        masses_per_type,
        spec_version: fd.get_spec_version(),
        metadata: FrameMeta::from_map_with_minor_raw(metadata, minor_raw.as_deref()),
        sections,
        strict_validation: fd.get_strict_validation(),
        sections_declared: fd.get_sections_declared(),
        ids_from_file: false,
    };

    Ok(con_frame_from_atom_data(header, atom_data, &coords))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;
    use capnp::message::Builder;
    use std::path::PathBuf;

    fn load_fixture(name: &str) -> ConFrame {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name);
        let text = std::fs::read_to_string(p).unwrap();
        ConFrameIterator::new(&text).next().unwrap().unwrap()
    }

    #[test]
    fn capnp_roundtrip_charges_spins_magmoms() {
        let frame = load_fixture("tiny_cuh2_charges_spins_magmoms.con");
        let mut message = Builder::new_default();
        {
            let root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root, &frame).unwrap();
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        let back = frame_from_reader(reader).unwrap();

        assert_eq!(back.atom_data.len(), frame.atom_data.len());
        assert_eq!(back.header.spec_version, frame.header.spec_version);
        for (i, (a, b)) in frame
            .atom_data
            .iter()
            .zip(back.atom_data.iter())
            .enumerate()
        {
            assert_eq!(a.symbol, b.symbol);
            assert!((frame.x_at(i) - back.x_at(i)).abs() < 1e-12);
            assert_eq!(a.fixed(), b.fixed());
            assert_eq!(a.atom_id, b.atom_id);
            assert_eq!(a.charge(), b.charge());
            assert_eq!(a.spin(), b.spin());
            assert_eq!(a.magmom(), b.magmom());
        }
        assert!(back.atom_data.iter().any(|a| a.has_charge()));
        assert!(back.atom_data.iter().any(|a| a.has_spin()));
        assert!(back.atom_data.iter().any(|a| a.has_magmom()));
    }

    #[test]
    fn capnp_roundtrip_displacements() {
        let frame = load_fixture("tiny_cuh2_displacements.con");
        let mut message = Builder::new_default();
        {
            let root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root, &frame).unwrap();
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        assert!(reader.get_has_displacements());
        let back = frame_from_reader(reader).unwrap();

        assert_eq!(back.atom_data.len(), frame.atom_data.len());
        for (a, b) in frame.atom_data.iter().zip(back.atom_data.iter()) {
            assert_eq!(a.symbol, b.symbol);
            assert_eq!(a.atom_id, b.atom_id);
            assert_eq!(a.displacement(), b.displacement());
        }
        assert!(back.atom_data.iter().all(|a| a.has_displacement()));
        assert!(back.has_displacements());
    }

    #[test]
    fn capnp_roundtrip_spreads() {
        let frame = load_fixture("tiny_cuh2_spreads.con");
        let mut message = Builder::new_default();
        {
            let root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root, &frame).unwrap();
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        assert!(reader.get_has_spreads());
        let back = frame_from_reader(reader).unwrap();

        assert_eq!(back.atom_data.len(), frame.atom_data.len());
        for (a, b) in frame.atom_data.iter().zip(back.atom_data.iter()) {
            assert_eq!(a.symbol, b.symbol);
            assert_eq!(a.atom_id, b.atom_id);
            assert_eq!(a.spread(), b.spread());
        }
        assert!(back.atom_data.iter().all(|a| a.has_spread()));
        assert!(back.has_spreads());
    }

    #[test]
    fn capnp_roundtrip_vel_forces() {
        let frame = load_fixture("tiny_cuh2_vel_forces.con");
        let mut message = Builder::new_default();
        {
            let root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root, &frame).unwrap();
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        let back = frame_from_reader(reader).unwrap();
        for (a, b) in frame.atom_data.iter().zip(back.atom_data.iter()) {
            assert_eq!(a.velocity(), b.velocity());
            assert_eq!(a.force(), b.force());
            assert_eq!(
                encode_fixed_bitmask(a.fixed()),
                encode_fixed_bitmask(b.fixed())
            );
        }
    }

    #[test]
    fn capnp_roundtrip_arbitrary_size_con_spec_minor() {
        let three_hundred = format!("1{}7", "0".repeat(298));
        for minor in [
            "18446744073709551616",
            "18446744073709551617",
            "1000000000000000000000000000000000000007",
            three_hundred.as_str(),
        ] {
            let text = format!(
                "gen\n{{\"con_spec_version\":3,\"con_spec_minor\":{minor},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n"
            );
            let frame = ConFrameIterator::new(&text).next().unwrap().unwrap();
            assert_eq!(frame.header.con_spec_minor_str(), minor);

            let mut message = Builder::new_default();
            {
                let root = message.init_root::<con_frame_data::Builder>();
                fill_frame_builder(root, &frame).unwrap();
            }
            let reader = message
                .get_root_as_reader::<con_frame_data::Reader>()
                .unwrap();
            let back = frame_from_reader(reader).unwrap();

            assert_eq!(back.header.spec_version, 3);
            assert_eq!(
                back.header.con_spec_minor_saturating(),
                crate::types::SATURATED_SPEC_MINOR
            );
            assert_eq!(back.header.con_spec_minor_str(), minor);

            let mut out = Vec::new();
            crate::writer::ConFrameWriter::new(&mut out)
                .write_frame(&back)
                .unwrap();
            let written = String::from_utf8(out).unwrap();
            let needle = format!("\"con_spec_minor\":{minor}");
            assert!(written.contains(&needle), "{written}");
        }
    }

    #[test]
    fn capnp_rejects_duplicate_con_spec_minor() {
        let frame = load_fixture("tiny_cuh2.con");
        let mut message = Builder::new_default();
        {
            let mut root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root.reborrow(), &frame).unwrap();
            root.set_metadata_json(
                r#"{"con_spec_version":3,"con_spec_minor":0,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}"#,
            );
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        let err = frame_from_reader(reader).unwrap_err();
        assert!(
            err.to_string().contains("duplicate con_spec_minor key"),
            "{err}"
        );
    }

    #[test]
    fn capnp_binary64_half_ulp_minor_matches_rust() {
        let (plus_one, last_finite, overflow) = crate::parser::f64_max_minor_edge_digits();
        for digits in [&plus_one, &last_finite] {
            let text = format!(
                "gen\n{{\"con_spec_version\":3,\"con_spec_minor\":{digits},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"}},\"sections\":[\"velocities\"]}}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n\nH\nVelocities of Component 1\n0.1 0.0 0.0 0 0\n"
            );
            let frame = ConFrameIterator::new(&text).next().unwrap().unwrap();
            assert_eq!(
                frame.header.con_spec_minor_saturating(),
                crate::types::SATURATED_SPEC_MINOR
            );
            assert_eq!(frame.header.con_spec_minor_str(), digits.as_str());

            let mut message = Builder::new_default();
            {
                let root = message.init_root::<con_frame_data::Builder>();
                fill_frame_builder(root, &frame).unwrap();
            }
            let reader = message
                .get_root_as_reader::<con_frame_data::Reader>()
                .unwrap();
            let back = frame_from_reader(reader).unwrap();
            assert_eq!(
                back.header.con_spec_minor_saturating(),
                crate::types::SATURATED_SPEC_MINOR
            );
            assert_eq!(back.header.con_spec_minor_str(), digits.as_str());
            let mut out = Vec::new();
            crate::writer::ConFrameWriter::new(&mut out)
                .write_frame(&back)
                .unwrap();
            let written = String::from_utf8(out).unwrap();
            assert!(written.contains(&format!("\"con_spec_minor\":{digits}")));
            assert!(written.contains("\"time\":\"fs\""));
            assert!(!written.contains("(amu*angstrom^2/eV)^0.5"));
        }

        let frame = load_fixture("tiny_cuh2.con");
        let mut message = Builder::new_default();
        {
            let mut root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root.reborrow(), &frame).unwrap();
            root.set_metadata_json(format!(
                "{{\"con_spec_version\":3,\"con_spec_minor\":{overflow},\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}"
            ));
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        let err = frame_from_reader(reader).unwrap_err();
        assert!(err.to_string().contains("number out of range"), "{err}");
    }

    fn frame_from_metadata_json(metadata_json: &str) -> Result<ConFrame, ConvertError> {
        let text = "gen\n{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\",\"time\":\"fs\"},\"sections\":[\"velocities\"]}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n\nH\nVelocities of Component 1\n0.1 0.0 0.0 0 0\n";
        let frame = ConFrameIterator::new(text).next().unwrap().unwrap();
        let mut message = Builder::new_default();
        {
            let mut root = message.init_root::<con_frame_data::Builder>();
            fill_frame_builder(root.reborrow(), &frame).unwrap();
            root.set_metadata_json(metadata_json);
        }
        let reader = message
            .get_root_as_reader::<con_frame_data::Reader>()
            .unwrap();
        frame_from_reader(reader)
    }

    /// Probe cases shared with the Rust, C, Python, and Julia tests
    /// (`tests/fixtures/minor_token_probes.json`).
    #[test]
    fn capnp_matches_minor_token_probe_table() {
        let root: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/minor_token_probes.json"))
                .unwrap();
        let cases = root["cases"].as_array().unwrap();
        assert_eq!(cases.len(), 59);
        for case in cases {
            let name = case["name"].as_str().unwrap();
            for (line_key, op) in [("line2_w", "rpc_w"), ("line2_n", "rpc_n")] {
                let line2 = case[line_key].as_str().unwrap();
                let expected = case[op].as_str().unwrap();
                let back = match frame_from_metadata_json(line2) {
                    Ok(back) => back,
                    Err(err) => {
                        let msg = err.to_string();
                        assert!(msg.starts_with("metadataJson: "), "{name} {op}: {msg}");
                        assert_eq!(
                            msg.contains("duplicate con_spec_minor key"),
                            expected == "dup",
                            "{name} {op}: {msg}"
                        );
                        assert!(matches!(expected, "dup" | "invalid"), "{name} {op}: {msg}");
                        continue;
                    }
                };
                let mut out = Vec::new();
                let result = crate::writer::ConFrameWriter::new(&mut out).write_frame(&back);
                match result {
                    Ok(()) => {
                        let text = String::from_utf8(out).unwrap();
                        assert_eq!(text.lines().nth(1).unwrap(), expected, "{name} {op}");
                    }
                    Err(err) => {
                        assert_eq!(expected, "units", "{name} {op}: {err}");
                        assert!(err.to_string().contains("units.time"), "{name} {op}: {err}");
                    }
                }
            }
        }
    }

    #[test]
    fn capnp_rejects_con_spec_minor_no_reader_accepts() {
        let (plus_one, last_finite, overflow) = crate::parser::f64_max_minor_edge_digits();
        let units = r#""units":{"length":"angstrom","energy":"eV","time":"fs"}"#;
        let typed = [
            "-1".to_string(),
            "-0".to_string(),
            "1.5".to_string(),
            "1.0".to_string(),
            "0.0".to_string(),
            "1e0".to_string(),
            "1e20".to_string(),
            "true".to_string(),
            "false".to_string(),
            "null".to_string(),
            r#""1""#.to_string(),
            "[1]".to_string(),
            r#"{"a":1}"#.to_string(),
            format!("-{plus_one}"),
            format!("{plus_one}.0"),
        ];
        for token in &typed {
            for key in [r#""con_spec_minor""#, r#""\u0063on_spec_minor""#] {
                let line = format!(r#"{{"con_spec_version":3,{key}:{token},{units}}}"#);
                let err = frame_from_metadata_json(&line).unwrap_err().to_string();
                assert_eq!(
                    err, "metadataJson: con_spec_minor must be a JSON integer >= 0",
                    "{line}"
                );
                let text = format!(
                    "gen\n{}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n1.0\nH\nCoordinates of Component 1\n0.0 0.0 0.0 0 0\n\nH\nVelocities of Component 1\n0.1 0.0 0.0 0 0\n",
                    line.replacen('}', r#"},"sections":["velocities"]"#, 1)
                );
                assert!(ConFrameIterator::new(&text).next().unwrap().is_err());
            }
        }
        let out_of_range = ["1e309".to_string(), "1E400".to_string(), overflow.clone()];
        for token in &out_of_range {
            let line = format!(r#"{{"con_spec_version":3,"con_spec_minor":{token},{units}}}"#);
            let err = frame_from_metadata_json(&line).unwrap_err().to_string();
            assert!(
                err.starts_with("metadataJson: number out of range"),
                "{err}"
            );
        }
        let bad_grammar = ["00", "000", "01", "+1", ".5"];
        for token in bad_grammar {
            let line = format!(r#"{{"con_spec_version":3,"con_spec_minor":{token},{units}}}"#);
            let err = frame_from_metadata_json(&line).unwrap_err().to_string();
            assert!(err.starts_with("metadataJson: "), "{err}");
        }
        for token in [
            "0",
            "1",
            "18446744073709551615",
            plus_one.as_str(),
            last_finite.as_str(),
        ] {
            let line = format!(r#"{{"con_spec_version":3,"con_spec_minor":{token},{units}}}"#);
            let back = frame_from_metadata_json(&line).unwrap();
            let mut out = Vec::new();
            crate::writer::ConFrameWriter::new(&mut out)
                .write_frame(&back)
                .unwrap();
            let written = String::from_utf8(out).unwrap();
            assert!(
                written.contains(&format!("\"con_spec_minor\":{token}")),
                "{written}"
            );
            let reread = ConFrameIterator::new(&written).next().unwrap().unwrap();
            assert_eq!(reread.header.con_spec_minor_str(), token);
        }
    }
}
