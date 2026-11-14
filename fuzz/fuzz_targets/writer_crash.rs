//! Kill a threaded write and check the destination.
//!
//! The path is either the previous complete file or a finished replacement.
//! A scratch name must not remain in the directory.

#![no_main]

use libfuzzer_sys::fuzz_target;
use readcon_core::iterators::frames_from_text;
use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{
    publish_ranked_slices, rewrite_frame_refs_to_path, write_frame_refs_to_path,
};

fn frame(atoms: usize, scale: f64) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([8.0, 8.0, 8.0], [90.0, 90.0, 90.0]);
    for index in 0..atoms {
        builder.add_atom(
            "H",
            index as f64 * scale,
            0.25,
            -0.5,
            [index % 2 == 0, false, false],
            index as u64,
            1.008,
        );
    }
    builder.build().expect("frame")
}

fn scratches(dir: &std::path::Path) -> Vec<String> {
    let mut names = Vec::new();
    for entry in std::fs::read_dir(dir).expect("dir") {
        let name = entry.expect("entry").file_name();
        let name = name.to_string_lossy().into_owned();
        if name.starts_with(".readcon-write-") {
            names.push(name);
        }
    }
    names
}

fn kill_child(pid: i32, pause_ms: u64) {
    if pause_ms > 0 {
        std::thread::sleep(std::time::Duration::from_millis(pause_ms));
    }
    unsafe {
        libc::kill(pid, libc::SIGKILL);
        let mut status = 0;
        libc::waitpid(pid, &mut status, 0);
    }
}

fn whole_file(got: &[u8], previous: &[u8], published: &[u8], atoms_if_new: usize) {
    if got == previous || got == published {
        return;
    }
    let text = String::from_utf8(got.to_vec()).expect("published text");
    let parsed = frames_from_text(&text, Some(1)).expect("published file is partial");
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].atom_data.len(), atoms_if_new);
    panic!("published bytes match neither complete file");
}

fuzz_target!(|data: &[u8]| {
    let atoms = 2_000 + usize::from(data.first().copied().unwrap_or(0)) * 40;
    let workers = [2usize, 4, 8][usize::from(data.get(1).copied().unwrap_or(0) % 3)];
    let pause = u64::from(data.get(2).copied().unwrap_or(8) % 40);
    let Ok(dir) = tempfile::tempdir() else {
        return;
    };
    let path = dir.path().join("out.con");
    let old = b"previous-complete\n".to_vec();
    if std::fs::write(&path, &old).is_err() {
        return;
    }
    let path_bytes = path.clone();
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return;
    }
    if pid == 0 {
        let frame = frame(atoms, 0.01);
        loop {
            let _ = write_frame_refs_to_path(&path_bytes, &[&frame], workers, None, false, false);
        }
    }
    kill_child(pid, pause);
    // The publish helper is a child of the writer. Give it time to finish
    // the rename after the writer is gone.
    for _ in 0..20 {
        if scratches(dir.path()).is_empty() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let got = std::fs::read(&path).expect("dest");
    if got != old {
        let text = String::from_utf8(got).expect("utf8");
        let parsed = frames_from_text(&text, Some(1)).expect("complete publish");
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].atom_data.len(), atoms);
    }
    let left = scratches(dir.path());
    assert!(left.is_empty(), "scratch left behind: {left:?}");

    // Two frames on one worker are spelled into the fresh file with
    // fallocate, not copied out of a second buffer.
    let serial = [frame(atoms, 0.01), frame(atoms.min(64), 0.04)];
    let serial_refs = [&serial[0], &serial[1]];
    let serial_complete = dir.path().join("serial-complete.con");
    if write_frame_refs_to_path(&serial_complete, &serial_refs, 1, None, false, false).is_err() {
        return;
    }
    let serial_bytes = std::fs::read(&serial_complete).expect("serial bytes");
    let serial_path = dir.path().join("serial.con");
    if std::fs::write(&serial_path, &old).is_err() {
        return;
    }
    let serial_path_bytes = serial_path.clone();
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return;
    }
    if pid == 0 {
        let serial = [frame(atoms, 0.01), frame(atoms.min(64), 0.04)];
        loop {
            let _ = write_frame_refs_to_path(
                &serial_path_bytes,
                &[&serial[0], &serial[1]],
                1,
                None,
                false,
                false,
            );
        }
    }
    kill_child(pid, pause);
    for _ in 0..20 {
        if scratches(dir.path()).is_empty() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let got = std::fs::read(&serial_path).expect("serial dest");
    if got != old && got != serial_bytes {
        panic!("serial fresh-file publish is partial ({} bytes)", got.len());
    }
    assert!(
        scratches(dir.path()).is_empty(),
        "serial fresh-file publish left a scratch"
    );

    // A kill while rewriting must leave `path` as one complete file: the
    // bytes already published, or the finished replacement. `keep_spare`
    // false drops the parked inode after that rename; a kill before the
    // rename still leaves the previous file in place.
    let rewrite_workers = [1usize, 2, 4, 8][usize::from(data.get(5).copied().unwrap_or(0) % 4)];
    let keep_spare = data.get(7).copied().unwrap_or(0) % 2 == 0;
    let same_length = data.get(6).copied().unwrap_or(0) % 2 == 0;
    let new_atoms = if same_length {
        atoms
    } else {
        1_500 + usize::from(data.get(4).copied().unwrap_or(3)) * 25
    };
    let previous = frame(atoms, 0.01);
    let replacement = frame(new_atoms, 0.02);
    if write_frame_refs_to_path(&path, &[&previous], rewrite_workers, None, false, false).is_err() {
        return;
    }
    let previous_bytes = std::fs::read(&path).expect("published");
    let complete = dir.path().join("complete.con");
    if write_frame_refs_to_path(
        &complete,
        &[&replacement],
        rewrite_workers,
        None,
        false,
        false,
    )
    .is_err()
    {
        return;
    }
    let published = std::fs::read(&complete).expect("complete rewrite");
    let path_bytes = path.clone();
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return;
    }
    if pid == 0 {
        let frame = frame(new_atoms, 0.02);
        loop {
            let _ = rewrite_frame_refs_to_path(
                &path_bytes,
                &[&frame],
                rewrite_workers,
                None,
                false,
                false,
                keep_spare,
            );
        }
    }
    kill_child(pid, pause);
    let got = std::fs::read(&path).expect("rewritten dest");
    whole_file(&got, &previous_bytes, &published, new_atoms);

    // Default ranked publish is a fresh file and leaves no `.rewrite`.
    // Spare reuse is opt-in: `rewrite` plus `keep_spare`. A separate path
    // so a spare left by the rewrite above is not this publish's.
    let rewrite = data.get(8).copied().unwrap_or(0) % 3 != 0;
    let ranked_keep = data.get(9).copied().unwrap_or(1) % 2 == 0;
    let ranks = 2 + usize::from(data.get(10).copied().unwrap_or(0) % 3);
    let path = dir.path().join("ranked.con");
    if std::fs::write(&path, &previous_bytes).is_err() {
        return;
    }
    let path_bytes = path.clone();
    let owned = published.clone();
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return;
    }
    if pid == 0 {
        loop {
            let mut slices = Vec::new();
            let mut at = 0usize;
            for rank in 0..ranks {
                let end = if rank + 1 == ranks {
                    owned.len()
                } else {
                    (rank + 1) * owned.len() / ranks
                };
                slices.push(owned[at..end].to_vec());
                at = end;
            }
            let refs: Vec<&[u8]> = slices.iter().map(|slice| slice.as_slice()).collect();
            let _ = publish_ranked_slices(&path_bytes, &refs, rewrite, ranked_keep);
        }
    }
    kill_child(pid, pause);
    let got = std::fs::read(&path).expect("ranked dest");
    whole_file(&got, &previous_bytes, &published, new_atoms);
    let spare = path.with_file_name(format!(
        "{}.rewrite",
        path.file_name().unwrap().to_string_lossy()
    ));
    if got == published {
        if !rewrite || !ranked_keep {
            assert!(
                !spare.exists(),
                "ranked publish left a spare (rewrite={rewrite} keep={ranked_keep})"
            );
        } else {
            assert!(spare.exists(), "opt-in ranked spare was dropped");
        }
    }
});
