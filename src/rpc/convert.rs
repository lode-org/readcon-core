//! Cap'n Proto ↔ [`ConFrame`] conversion (CON v3 field parity).

use std::collections::BTreeMap;
use std::sync::Arc;

use super::read_con_capnp::con_frame_data;
use crate::types::{
    con_frame_from_atom_data, decode_fixed_bitmask_for_spec, encode_fixed_bitmask, AtomDatum, ConFrame,
    FrameHeader, PreboxHeader,
};

/// Fill one `ConFrameData` builder from a [`ConFrame`].
pub fn fill_frame_builder(
    mut fb: con_frame_data::Builder<'_>,
    frame: &ConFrame,
) -> Result<(), String> {
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

    let meta_json = serde_json::to_string(&frame.header.metadata)
        .map_err(|e| format!("metadata json: {e}"))?;
    fb.set_metadata_json(&meta_json);
    fb.set_strict_validation(frame.header.strict_validation);
    fb.set_sections_declared(frame.header.sections_declared);
    fb.set_prebox_user(frame.header.prebox_header.user.as_str());

    let mut atoms_builder = fb.reborrow().init_atoms(frame.atom_data.len() as u32);
    for (k, atom) in frame.atom_data.iter().enumerate() {
        let mut ab = atoms_builder.reborrow().get(k as u32);
        ab.set_symbol(atom.symbol.as_ref());
        ab.set_x(atom.x);
        ab.set_y(atom.y);
        ab.set_z(atom.z);
        ab.set_fixed_mask(encode_fixed_bitmask(atom.fixed));
        ab.set_atom_id(atom.atom_id);

        if let Some([vx, vy, vz]) = atom.velocity {
            ab.set_has_velocity(true);
            ab.set_vx(vx);
            ab.set_vy(vy);
            ab.set_vz(vz);
        } else {
            ab.set_has_velocity(false);
        }
        if let Some([fx, fy, fz]) = atom.force {
            ab.set_has_force(true);
            ab.set_fx(fx);
            ab.set_fy(fy);
            ab.set_fz(fz);
        } else {
            ab.set_has_force(false);
        }
        if let Some(e) = atom.energy {
            ab.set_has_energy(true);
            ab.set_energy(e);
        } else {
            ab.set_has_energy(false);
        }
        if let Some(c) = atom.charge {
            ab.set_has_charge(true);
            ab.set_charge(c);
        } else {
            ab.set_has_charge(false);
        }
        if let Some(s) = atom.spin {
            ab.set_has_spin(true);
            ab.set_spin(s);
        } else {
            ab.set_has_spin(false);
        }
        if let Some([mx, my, mz]) = atom.magmom {
            ab.set_has_magmom(true);
            ab.set_mx(mx);
            ab.set_my(my);
            ab.set_mz(mz);
        } else {
            ab.set_has_magmom(false);
        }
    }
    Ok(())
}

/// Rebuild a [`ConFrame`] from a Cap'n Proto reader.
pub fn frame_from_reader(fd: con_frame_data::Reader<'_>) -> Result<ConFrame, String> {
    let cell_list = fd.get_cell().map_err(|e| e.to_string())?;
    let angles_list = fd.get_angles().map_err(|e| e.to_string())?;
    if cell_list.len() < 3 || angles_list.len() < 3 {
        return Err("cell/angles must have length 3".into());
    }
    let boxl = [cell_list.get(0), cell_list.get(1), cell_list.get(2)];
    let angles = [angles_list.get(0), angles_list.get(1), angles_list.get(2)];

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
    let mut masses_per_type: Vec<f64> = (0..masses_list.len())
        .map(|i| masses_list.get(i))
        .collect();
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

    let metadata: BTreeMap<String, serde_json::Value> = if fd.has_metadata_json() {
        let raw = fd
            .get_metadata_json()
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or("{}");
        if raw.trim().is_empty() {
            BTreeMap::new()
        } else {
            serde_json::from_str(raw).map_err(|e| format!("metadataJson: {e}"))?
        }
    } else {
        BTreeMap::new()
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
    for j in 0..atoms_list.len() {
        let a = atoms_list.get(j);
        let sym = a
            .get_symbol()
            .map_err(|e| e.to_string())?
            .to_str()
            .unwrap_or_default()
            .to_string();
        atom_data.push(AtomDatum {
            symbol: Arc::from(sym),
            x: a.get_x(),
            y: a.get_y(),
            z: a.get_z(),
            fixed: decode_fixed_bitmask_for_spec(a.get_fixed_mask(), spec_version),
            atom_id: a.get_atom_id(),
            velocity: if a.get_has_velocity() {
                Some([a.get_vx(), a.get_vy(), a.get_vz()])
            } else {
                None
            },
            force: if a.get_has_force() {
                Some([a.get_fx(), a.get_fy(), a.get_fz()])
            } else {
                None
            },
            energy: if a.get_has_energy() {
                Some(a.get_energy())
            } else {
                None
            },
            charge: if a.get_has_charge() {
                Some(a.get_charge())
            } else {
                None
            },
            spin: if a.get_has_spin() {
                Some(a.get_spin())
            } else {
                None
            },
            magmom: if a.get_has_magmom() {
                Some([a.get_mx(), a.get_my(), a.get_mz()])
            } else {
                None
            },
        });
    }

    let header = FrameHeader {
        prebox_header: PreboxHeader {
            user: prebox_user,
            metadata_line: prebox_metadata_line,
        },
        boxl,
        angles,
        postbox_header,
        natm_types: natms_per_type.len(),
        natms_per_type,
        masses_per_type,
        spec_version: fd.get_spec_version(),
        metadata,
        sections,
        strict_validation: fd.get_strict_validation(),
        sections_declared: fd.get_sections_declared(),
    };

    Ok(con_frame_from_atom_data(header, atom_data))
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
        for (a, b) in frame.atom_data.iter().zip(back.atom_data.iter()) {
            assert_eq!(a.symbol, b.symbol);
            assert!((a.x - b.x).abs() < 1e-12);
            assert_eq!(a.fixed, b.fixed);
            assert_eq!(a.atom_id, b.atom_id);
            assert_eq!(a.charge, b.charge);
            assert_eq!(a.spin, b.spin);
            assert_eq!(a.magmom, b.magmom);
        }
        assert!(back.atom_data.iter().any(|a| a.has_charge()));
        assert!(back.atom_data.iter().any(|a| a.has_spin()));
        assert!(back.atom_data.iter().any(|a| a.has_magmom()));
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
            assert_eq!(a.velocity, b.velocity);
            assert_eq!(a.force, b.force);
            assert_eq!(encode_fixed_bitmask(a.fixed), encode_fixed_bitmask(b.fixed));
        }
    }
}
