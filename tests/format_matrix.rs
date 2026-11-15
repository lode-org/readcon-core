//! Round trip across formats, compression, thread counts, and species layouts.
//!
//! Each file is written by the Rust member writer and by the C writer, then
//! read back by the phased reader, the threaded reader, and
//! `rkr_read_all_frames_n_threads`. A coordinate frame also goes through the
//! fused gzip and zstd writers. Extended XYZ uses the threaded formatter,
//! the member compressors, and the threaded scanner.

use readcon_core::compression::{read_file_bytes, with_decode_threads, with_serial_decode};
use readcon_core::extxyz_scan::{
    ExtxyzSource, XyzColumn, XyzTables, extxyz_bytes_with_threads,
    tables_from_extxyz_bytes_with_threads,
};
use readcon_core::ffi::{
    CAtom, CFrame, RKRConFrame, RKRStatus, create_writer_from_path_c, create_writer_gzip_c,
    free_c_frame, free_rkr_frame_array, free_rkr_writer, rkr_frame_to_c_frame,
    rkr_last_error_message, rkr_read_all_frames_n_threads, rkr_writer_extend,
};
use readcon_core::iterators::{read_all_frames_phased, read_all_frames_with_threads};
use readcon_core::types::{ConFrame, ConFrameBuilder};
use readcon_core::writer::write_frame_refs_to_path;
use std::ffi::{CStr, CString};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use readcon_core::compression::write_gzip_members_limited;
#[cfg(feature = "zstd")]
use readcon_core::compression::write_zstd_members_limited;
#[cfg(feature = "zstd")]
use readcon_core::ffi::create_writer_zstd_c;

static NEXT: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy)]
enum Layout {
    One,
    Many,
    Wide,
}

#[derive(Clone, Copy)]
enum Kind {
    Con,
    Convel,
}

#[derive(Clone, Copy)]
enum Codec {
    None,
    Gzip,
    Zstd,
}

fn codecs() -> Vec<Codec> {
    #[cfg(feature = "zstd")]
    {
        vec![Codec::None, Codec::Gzip, Codec::Zstd]
    }
    #[cfg(not(feature = "zstd"))]
    {
        vec![Codec::None, Codec::Gzip]
    }
}

fn layout_name(layout: Layout) -> &'static str {
    match layout {
        Layout::One => "one",
        Layout::Many => "many",
        Layout::Wide => "wide",
    }
}

fn kind_name(kind: Kind) -> &'static str {
    match kind {
        Kind::Con => "con",
        Kind::Convel => "convel",
    }
}

fn codec_name(codec: Codec) -> &'static str {
    match codec {
        Codec::None => "none",
        Codec::Gzip => "gz",
        Codec::Zstd => "zst",
    }
}

fn species(layout: Layout) -> Vec<(&'static str, f64)> {
    match layout {
        Layout::One => vec![("Cu", 64.0); 5],
        Layout::Many => vec![
            ("Cu", 64.0),
            ("Cu", 64.0),
            ("Cu", 64.0),
            ("H", 1.0),
            ("H", 1.0),
            ("O", 16.0),
            ("C", 12.0),
            ("Fe", 56.0),
            ("Ne", 20.0),
        ],
        Layout::Wide => {
            let mut atoms = Vec::new();
            atoms.extend(std::iter::repeat_n(("Cu", 64.0), 20));
            atoms.extend(std::iter::repeat_n(("H", 1.0), 17));
            atoms.extend(std::iter::repeat_n(("O", 16.0), 11));
            atoms
        }
    }
}

fn frame(atoms: &[(&str, f64)], shift: f64, velocities: bool, id_base: u64) -> ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder
        .set_units(serde_json::json!({
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": readcon_core::units::NATURAL_TIME_UNIT,
        }))
        .expect("units");
    for (index, (symbol, mass)) in atoms.iter().enumerate() {
        let fixed = if index == 0 {
            [true, false, true]
        } else {
            [false, false, false]
        };
        builder.add_atom(
            symbol,
            index as f64 + shift,
            0.25,
            0.125,
            fixed,
            id_base + index as u64,
            *mass,
        );
        if velocities {
            builder.with_velocity([0.5, shift, index as f64 * 0.25]);
        }
    }
    builder.build().expect("frame")
}

fn frames(layout: Layout, kind: Kind) -> Vec<ConFrame> {
    let atoms = species(layout);
    let velocities = matches!(kind, Kind::Convel);
    vec![
        frame(&atoms, 0.0, velocities, 1),
        frame(&atoms, 1.0, velocities, 1001),
    ]
}

fn path_for(dir: &Path, kind: Kind, codec: Codec) -> PathBuf {
    let id = NEXT.fetch_add(1, Ordering::Relaxed);
    let ext = match (kind, codec) {
        (Kind::Con, Codec::None) => "con",
        (Kind::Con, Codec::Gzip) => "con.gz",
        (Kind::Con, Codec::Zstd) => "con.zst",
        (Kind::Convel, Codec::None) => "convel",
        (Kind::Convel, Codec::Gzip) => "convel.gz",
        (Kind::Convel, Codec::Zstd) => "convel.zst",
    };
    dir.join(format!("m{id}.{ext}"))
}

fn bits(value: f64) -> u64 {
    value.to_bits()
}

fn assert_atoms(label: &str, expected: &[ConFrame], got: &[ConFrame]) {
    assert_eq!(expected.len(), got.len(), "{label} frame count");
    for (index, (left, right)) in expected.iter().zip(got.iter()).enumerate() {
        let tag = format!("{label} frame {index}");
        assert_eq!(left.header.boxl, right.header.boxl, "{tag} box");
        assert_eq!(left.header.angles, right.header.angles, "{tag} angles");
        assert_eq!(
            left.header.natms_per_type, right.header.natms_per_type,
            "{tag} counts"
        );
        assert_eq!(
            left.header.masses_per_type.len(),
            right.header.masses_per_type.len(),
            "{tag} masses"
        );
        for (mass_left, mass_right) in left
            .header
            .masses_per_type
            .iter()
            .zip(right.header.masses_per_type.iter())
        {
            assert_eq!(bits(*mass_left), bits(*mass_right), "{tag} mass");
        }
        assert_eq!(left.atom_data.len(), right.atom_data.len(), "{tag} atoms");
        for (atom_left, atom_right) in left.atom_data.iter().zip(right.atom_data.iter()) {
            assert_eq!(
                atom_left.symbol.as_ref(),
                atom_right.symbol.as_ref(),
                "{tag} symbol"
            );
            assert_eq!(bits(atom_left.x()), bits(atom_right.x()), "{tag} x");
            assert_eq!(bits(atom_left.y()), bits(atom_right.y()), "{tag} y");
            assert_eq!(bits(atom_left.z()), bits(atom_right.z()), "{tag} z");
            assert_eq!(atom_left.fixed(), atom_right.fixed(), "{tag} fixed");
            assert_eq!(atom_left.atom_id, atom_right.atom_id, "{tag} id");
            match (atom_left.velocity(), atom_right.velocity()) {
                (None, None) => {}
                (Some(left_v), Some(right_v)) => {
                    assert_eq!(left_v.map(bits), right_v.map(bits), "{tag} velocity");
                }
                (left_v, right_v) => panic!("{tag} velocity {left_v:?} vs {right_v:?}"),
            }
        }
    }
}

fn read_phased(path: &Path, threads: usize) -> Vec<ConFrame> {
    read_all_frames_phased(path, Some(threads))
        .unwrap_or_else(|err| panic!("{} phased {threads}: {err}", path.display()))
        .frames
}

fn read_threaded(path: &Path, threads: usize) -> Vec<ConFrame> {
    read_all_frames_with_threads(path, Some(threads))
        .unwrap_or_else(|err| panic!("{} threads {threads}: {err}", path.display()))
}

fn last_error() -> String {
    let message = rkr_last_error_message();
    if message.is_null() {
        return String::new();
    }
    unsafe { CStr::from_ptr(message).to_string_lossy().into_owned() }
}

fn per_atom_masses(frame: &ConFrame) -> Vec<f64> {
    frame
        .header
        .natms_per_type
        .iter()
        .zip(frame.header.masses_per_type.iter())
        .flat_map(|(count, mass)| std::iter::repeat_n(*mass, *count))
        .collect()
}

fn assert_c_frame(label: &str, expected: &ConFrame, c_frame: *mut CFrame) {
    assert!(!c_frame.is_null(), "{label} c frame");
    let frame = unsafe { &*c_frame };
    let atoms = unsafe { std::slice::from_raw_parts(frame.atoms, frame.num_atoms) };
    assert_eq!(atoms.len(), expected.atom_data.len(), "{label} c atoms");
    assert_eq!(frame.cell, expected.header.boxl, "{label} c box");
    assert_eq!(frame.angles, expected.header.angles, "{label} c angles");
    let masses = per_atom_masses(expected);
    for (index, (atom, c_atom)) in expected.atom_data.iter().zip(atoms.iter()).enumerate() {
        let tag = format!("{label} c atom {index}");
        assert_c_atom(&tag, atom, masses[index], c_atom);
    }
    unsafe { free_c_frame(c_frame) };
}

fn assert_c_atom(label: &str, atom: &readcon_core::types::AtomDatum, mass: f64, c_atom: &CAtom) {
    assert_eq!(bits(c_atom.x), bits(atom.x()), "{label} x");
    assert_eq!(bits(c_atom.y), bits(atom.y()), "{label} y");
    assert_eq!(bits(c_atom.z), bits(atom.z()), "{label} z");
    assert_eq!(bits(c_atom.mass), bits(mass), "{label} mass");
    assert_eq!(c_atom.atom_id, atom.atom_id, "{label} id");
    assert_eq!(
        [c_atom.fixed_x, c_atom.fixed_y, c_atom.fixed_z],
        atom.fixed(),
        "{label} fixed"
    );
    match atom.velocity() {
        Some(velocity) => {
            assert!(c_atom.has_velocity, "{label} velocity flag");
            assert_eq!(bits(c_atom.vx), bits(velocity[0]), "{label} vx");
            assert_eq!(bits(c_atom.vy), bits(velocity[1]), "{label} vy");
            assert_eq!(bits(c_atom.vz), bits(velocity[2]), "{label} vz");
        }
        None => assert!(!c_atom.has_velocity, "{label} velocity flag"),
    }
}

fn check_readers(label: &str, path: &Path, threads: usize, expected: &[ConFrame]) {
    assert_eq!(
        expected,
        read_phased(path, threads).as_slice(),
        "{label} phased {threads}"
    );
    assert_eq!(
        expected,
        read_threaded(path, threads).as_slice(),
        "{label} reader {threads}"
    );
    let text = CString::new(path.to_str().expect("path")).unwrap();
    let mut count = 0usize;
    let handles = unsafe { rkr_read_all_frames_n_threads(text.as_ptr(), &mut count, threads) };
    assert!(
        !handles.is_null(),
        "{label} c read {threads}: {}",
        last_error()
    );
    assert_eq!(count, expected.len(), "{label} c count");
    let slice = unsafe { std::slice::from_raw_parts(handles, count) };
    for (index, handle) in slice.iter().enumerate() {
        let frame = unsafe { &*(*handle as *const ConFrame) };
        assert_eq!(&expected[index], frame, "{label} c frame {index}");
        let c_frame = unsafe { rkr_frame_to_c_frame(*handle) };
        assert_c_frame(&format!("{label} t{threads}"), &expected[index], c_frame);
    }
    unsafe { free_rkr_frame_array(handles, count) };
}

fn write_plain(path: &Path, frames: &[ConFrame], threads: usize) {
    let refs: Vec<&ConFrame> = frames.iter().collect();
    write_frame_refs_to_path(path, &refs, threads, None, false, false)
        .unwrap_or_else(|err| panic!("{} plain: {err}", path.display()));
}

fn formatted(frames: &[ConFrame], threads: usize) -> Vec<u8> {
    readcon_core::writer::write_frames_to_vec_with_threads(frames, threads, None, false)
        .expect("format")
}

fn write_codec(path: &Path, frames: &[ConFrame], codec: Codec, threads: usize) {
    match codec {
        Codec::None => write_plain(path, frames, threads),
        Codec::Gzip => {
            let bytes = formatted(frames, threads);
            let members = threads.max(1);
            write_gzip_members_limited(path, &bytes, members, members)
                .unwrap_or_else(|err| panic!("{} gzip: {err}", path.display()));
        }
        Codec::Zstd => {
            #[cfg(feature = "zstd")]
            {
                let bytes = formatted(frames, threads);
                let members = threads.max(1);
                write_zstd_members_limited(path, &bytes, members, members)
                    .unwrap_or_else(|err| panic!("{} zstd: {err}", path.display()));
            }
            #[cfg(not(feature = "zstd"))]
            {
                let _ = (path, frames, threads);
                panic!("zstd");
            }
        }
    }
}

fn write_c(path: &Path, frames: &[ConFrame], codec: Codec) {
    let text = CString::new(path.to_str().expect("path")).unwrap();
    let writer = unsafe {
        match codec {
            Codec::None => create_writer_from_path_c(text.as_ptr()),
            Codec::Gzip => create_writer_gzip_c(text.as_ptr()),
            Codec::Zstd => {
                #[cfg(feature = "zstd")]
                {
                    create_writer_zstd_c(text.as_ptr())
                }
                #[cfg(not(feature = "zstd"))]
                {
                    std::ptr::null_mut()
                }
            }
        }
    };
    assert!(
        !writer.is_null(),
        "{} c writer: {}",
        path.display(),
        last_error()
    );
    let handles: Vec<*const RKRConFrame> = frames
        .iter()
        .map(|frame| frame as *const ConFrame as *const RKRConFrame)
        .collect();
    let status = unsafe { rkr_writer_extend(writer, handles.as_ptr(), handles.len()) };
    assert_eq!(status, RKRStatus::RKR_STATUS_SUCCESS, "{}", last_error());
    unsafe { free_rkr_writer(writer) };
}

fn write_fused(path: &Path, frame: &ConFrame, codec: Codec, threads: usize) {
    let members = threads.max(2);
    match codec {
        Codec::Gzip => {
            readcon_core::compression::write_fused_gzip_frame(path, frame, members, threads.max(1))
                .unwrap_or_else(|err| panic!("{} fused gzip: {err}", path.display()));
        }
        Codec::Zstd => {
            #[cfg(feature = "zstd")]
            {
                readcon_core::compression::write_fused_zstd_frame(
                    path,
                    frame,
                    members,
                    threads.max(1),
                )
                .unwrap_or_else(|err| panic!("{} fused zstd: {err}", path.display()));
            }
            #[cfg(not(feature = "zstd"))]
            {
                let _ = (path, frame, threads);
                panic!("zstd");
            }
        }
        Codec::None => panic!("fused"),
    }
}

fn oracle(dir: &Path, built: &[ConFrame], kind: Kind) -> Vec<ConFrame> {
    let path = path_for(dir, kind, Codec::None);
    write_plain(&path, built, 1);
    let parsed = read_phased(&path, 1);
    assert_atoms("oracle", built, &parsed);
    parsed
}

fn column(name: &str, kind: u8, width: usize, text: Vec<String>, real: Vec<f64>) -> XyzColumn {
    XyzColumn {
        name: name.to_string(),
        kind,
        width,
        text,
        real,
    }
}

fn xyz_case(layout: Layout) -> (Vec<XyzColumn>, usize, Vec<f64>) {
    let atoms = species(layout);
    let n_atoms = atoms.len();
    let n_frames = 2usize;
    let mut text = Vec::with_capacity(n_frames * n_atoms);
    let mut pos = Vec::with_capacity(n_frames * n_atoms * 3);
    let mut masses = Vec::with_capacity(n_frames * n_atoms);
    let mut forces = Vec::with_capacity(n_frames * n_atoms * 3);
    let mut mom = Vec::with_capacity(n_frames * n_atoms * 2);
    for frame_index in 0..n_frames {
        let shift = frame_index as f64;
        for (index, (symbol, mass)) in atoms.iter().enumerate() {
            text.push((*symbol).to_string());
            pos.extend_from_slice(&[index as f64 + shift, 0.25, 0.125]);
            masses.push(*mass);
            forces.extend_from_slice(&[0.5, shift, index as f64 * 0.25]);
            mom.extend_from_slice(&[index as f64 + 0.5, shift + 1.5]);
        }
    }
    let mut columns = vec![
        column("species", b'S', 1, text, Vec::new()),
        column("pos", b'R', 3, Vec::new(), pos),
        column("masses", b'R', 1, Vec::new(), masses),
    ];
    if matches!(layout, Layout::Wide) {
        columns.push(column("forces", b'R', 3, Vec::new(), forces));
        columns.push(column("mom", b'R', 2, Vec::new(), mom));
    }
    let cell = vec![
        10.0, 10.0, 10.0, 90.0, 90.0, 90.0, 10.0, 10.0, 10.0, 90.0, 90.0, 90.0,
    ];
    (columns, n_atoms, cell)
}

fn species_of(tables: &XyzTables) -> Vec<String> {
    if let Some(symbol) = &tables.uniform_species {
        return vec![symbol.clone(); tables.n_frames * tables.n_atoms];
    }
    if !tables.species_ids.is_empty() {
        return tables
            .species_ids
            .iter()
            .map(|id| tables.species_pool[*id as usize].clone())
            .collect();
    }
    if !tables.species.is_empty() {
        return tables.species.clone();
    }
    tables
        .columns
        .iter()
        .find(|column| column.name == "species")
        .map(|column| column.text.clone())
        .unwrap_or_default()
}

fn column_real<'a>(tables: &'a XyzTables, name: &str) -> Option<&'a [f64]> {
    tables
        .columns
        .iter()
        .find(|column| column.name == name)
        .map(|column| column.real.as_slice())
}

fn assert_bits(label: &str, left: &[f64], right: &[f64]) {
    assert_eq!(left.len(), right.len(), "{label} len");
    for (index, (lhs, rhs)) in left.iter().zip(right.iter()).enumerate() {
        assert_eq!(bits(*lhs), bits(*rhs), "{label} [{index}] {lhs} vs {rhs}");
    }
}

fn assert_xyz(label: &str, columns: &[XyzColumn], n_atoms: usize, tables: &XyzTables) {
    assert_eq!(tables.n_frames, 2, "{label} frames");
    assert_eq!(tables.n_atoms, n_atoms, "{label} atoms");
    let species = columns[0].text.clone();
    assert_eq!(species_of(tables), species, "{label} species");
    assert_bits(&format!("{label} pos"), &columns[1].real, &tables.positions);
    assert_bits(&format!("{label} mass"), &columns[2].real, &tables.masses);
    let cell = [
        10.0, 10.0, 10.0, 90.0, 90.0, 90.0, 10.0, 10.0, 10.0, 90.0, 90.0, 90.0,
    ];
    assert_bits(&format!("{label} cell"), &cell, &tables.cell);
    if columns.len() > 3 {
        let forces = column_real(tables, "forces").unwrap_or(&[]);
        assert_bits(&format!("{label} forces"), &columns[3].real, forces);
        let mom = column_real(tables, "mom").unwrap_or(&[]);
        assert_bits(&format!("{label} mom"), &columns[4].real, mom);
    }
}

fn read_xyz(path: &Path, threads: usize) -> XyzTables {
    let bytes = if threads <= 1 {
        with_serial_decode(|| read_file_bytes(path).expect("extxyz bytes"))
    } else {
        with_decode_threads(threads, || read_file_bytes(path).expect("extxyz bytes"))
    };
    tables_from_extxyz_bytes_with_threads(&bytes, threads)
        .unwrap_or_else(|err| panic!("{} extxyz {threads}: {err}", path.display()))
}

#[test]
fn formats_round_trip_across_codecs_and_threads() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    for layout in [Layout::One, Layout::Many, Layout::Wide] {
        for kind in [Kind::Con, Kind::Convel] {
            let built = frames(layout, kind);
            let expected = oracle(root, &built, kind);
            for codec in codecs() {
                for write_threads in [1usize, 2, 8] {
                    let path = path_for(root, kind, codec);
                    write_codec(&path, &built, codec, write_threads);
                    for read_threads in [1usize, 2, 8] {
                        let label = format!(
                            "{} {} {} write {write_threads}",
                            layout_name(layout),
                            kind_name(kind),
                            codec_name(codec)
                        );
                        check_readers(&label, &path, read_threads, &expected);
                    }
                }
                let path = path_for(root, kind, codec);
                write_c(&path, &built, codec);
                for read_threads in [1usize, 2, 8] {
                    let label = format!(
                        "{} {} {} c-writer",
                        layout_name(layout),
                        kind_name(kind),
                        codec_name(codec)
                    );
                    check_readers(&label, &path, read_threads, &expected);
                }
            }
        }
        let atoms = species(layout);
        let one = frame(&atoms, 0.0, false, 1);
        let expected = oracle(root, std::slice::from_ref(&one), Kind::Con);
        for codec in [Codec::Gzip, Codec::Zstd] {
            #[cfg(not(feature = "zstd"))]
            if matches!(codec, Codec::Zstd) {
                continue;
            }
            for threads in [1usize, 2, 8] {
                let path = path_for(root, Kind::Con, codec);
                write_fused(&path, &one, codec, threads);
                for read_threads in [1usize, 2, 8] {
                    let label = format!(
                        "{} fused {} write {threads}",
                        layout_name(layout),
                        codec_name(codec)
                    );
                    check_readers(&label, &path, read_threads, &expected);
                }
            }
        }
        let (columns, n_atoms, cell) = xyz_case(layout);
        let sources: Vec<&(dyn ExtxyzSource + Sync)> =
            columns.iter().map(|column| column as _).collect();
        for write_threads in [1usize, 2, 8] {
            let bytes = extxyz_bytes_with_threads(2, n_atoms, &cell, &sources, write_threads)
                .expect("extxyz");
            for codec in codecs() {
                let id = NEXT.fetch_add(1, Ordering::Relaxed);
                let ext = match codec {
                    Codec::None => "extxyz",
                    Codec::Gzip => "extxyz.gz",
                    Codec::Zstd => "extxyz.zst",
                };
                let path = root.join(format!("x{id}.{ext}"));
                match codec {
                    Codec::None => fs::write(&path, &bytes).unwrap(),
                    Codec::Gzip => {
                        write_gzip_members_limited(
                            &path,
                            &bytes,
                            write_threads.max(1),
                            write_threads.max(1),
                        )
                        .unwrap();
                    }
                    Codec::Zstd => {
                        #[cfg(feature = "zstd")]
                        write_zstd_members_limited(
                            &path,
                            &bytes,
                            write_threads.max(1),
                            write_threads.max(1),
                        )
                        .unwrap();
                        #[cfg(not(feature = "zstd"))]
                        panic!("zstd");
                    }
                }
                for read_threads in [1usize, 2, 8] {
                    let label = format!(
                        "{} extxyz {} write {write_threads} read {read_threads}",
                        layout_name(layout),
                        codec_name(codec)
                    );
                    let tables = read_xyz(&path, read_threads);
                    assert_xyz(&label, &columns, n_atoms, &tables);
                }
            }
        }
    }
}
