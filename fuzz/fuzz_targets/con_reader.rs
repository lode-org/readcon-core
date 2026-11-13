#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::{frames_from_bytes, read_all_frames};
use readcon_core::types::ConFrame;
use readcon_core::writer::ConFrameWriter;

fn touch_metadata(frames: &[ConFrame]) {
    for frame in frames {
        // Lattice vectors must not pin the metadata map. A keyed lookup may.
        let _ = frame.header.lattice_vectors();
        let _ = frame.header.metadata.get("lattice_vectors");
        let _ = frame.header.lattice_vectors();
    }
}

fn rewrite_gzip(frames: &[ConFrame]) {
    if frames.is_empty() || frames.len() > 4 {
        return;
    }
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("fuzz.con.gz");
    let Ok(mut writer) = ConFrameWriter::from_path_gzip(&path) else {
        return;
    };
    for frame in frames {
        if writer.write_frame(frame).is_err() {
            return;
        }
    }
    if writer.flush().is_err() {
        return;
    }
    drop(writer);
    if let Ok(back) = read_all_frames(&path) {
        assert_eq!(back.len(), frames.len());
        touch_metadata(&back);
    }
}

fuzz_target!(|data: &[u8]| {
    if data.len() > 128 * 1024 {
        return;
    }
    for threads in [1usize, 8] {
        let mut parsed = 0usize;
        match frames_from_bytes(data, Some(threads)) {
            Ok(frames) => {
                parsed = frames.len();
                touch_metadata(&frames);
                if data.len() <= 4096 {
                    rewrite_gzip(&frames);
                }
            }
            Err(_) => {}
        }
        assert!(parsed <= data.len().saturating_add(1));
    }
    // The chemfiles memory reader is the path through
    // `chemfiles_import_imp` and `rc_chemfiles_atom_view`. Without the
    // feature it returns FeatureDisabled and does not touch that code.
    if let Ok(text) = std::str::from_utf8(data) {
        let text = &text[..text.len().min(16 * 1024)];
        if let Ok(frames) = readcon_core::chemfiles_import::con_frames_from_memory(text, "XYZ") {
            assert!(frames.len() <= text.len().saturating_add(1));
            touch_metadata(&frames);
        }
    }
});
