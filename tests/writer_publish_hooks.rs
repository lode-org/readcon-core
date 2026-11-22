//! Hooked publish-kill tests that run only with `--features test-hooks`.
#![cfg(unix)]

use readcon_core::types::ConFrameBuilder;
use readcon_core::writer::{rewrite_frame_refs_to_path, write_frame_refs_to_path};
use std::path::PathBuf;

fn wide_frame(n: usize) -> readcon_core::types::ConFrame {
    let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    for i in 0..n {
        builder.add_atom(
            "Cu",
            i as f64 * 0.01,
            1.0,
            -1.0,
            [false, false, false],
            i as u64,
            63.546,
        );
    }
    builder.build().expect("frame")
}

struct PublishHookPipes {
    ready_r: libc::c_int,
    ready_w: libc::c_int,
    release_r: libc::c_int,
    release_w: libc::c_int,
}

impl PublishHookPipes {
    fn new() -> Self {
        fn pipe_pair() -> (libc::c_int, libc::c_int) {
            let mut pair = [0; 2];
            let ok = unsafe { libc::pipe(pair.as_mut_ptr()) };
            assert_eq!(ok, 0, "pipe");
            (pair[0], pair[1])
        }
        let (ready_r, ready_w) = pipe_pair();
        let (release_r, release_w) = pipe_pair();
        Self {
            ready_r,
            ready_w,
            release_r,
            release_w,
        }
    }

    fn env_spec(&self) -> String {
        format!("{}:{}", self.ready_w, self.release_r)
    }

    fn wait_ready(&self) {
        let mut byte = [0_u8];
        let got = unsafe { libc::read(self.ready_r, byte.as_mut_ptr().cast(), 1) };
        assert_eq!(got, 1, "publish hook did not signal readiness");
    }

    fn close_parent_child_ends(&mut self) {
        unsafe {
            if self.ready_w >= 0 {
                libc::close(self.ready_w);
                self.ready_w = -1;
            }
            if self.release_r >= 0 {
                libc::close(self.release_r);
                self.release_r = -1;
            }
        }
    }
}

impl Drop for PublishHookPipes {
    fn drop(&mut self) {
        unsafe {
            if self.ready_r >= 0 {
                libc::close(self.ready_r);
            }
            if self.ready_w >= 0 {
                libc::close(self.ready_w);
            }
            if self.release_r >= 0 {
                libc::close(self.release_r);
            }
            if self.release_w >= 0 {
                libc::close(self.release_w);
            }
        }
    }
}

#[test]
fn a_killed_write_keeps_the_previous_file_or_a_complete_one() {
    if std::env::var_os("READCON_WRITE_CHILD").is_some() {
        let path = PathBuf::from(std::env::var("READCON_WRITE_PATH").expect("child path"));
        let frame = wide_frame(8_000);
        loop {
            let _ = write_frame_refs_to_path(&path, &[&frame], 4, None, false, false);
        }
    }

    use std::os::unix::process::ExitStatusExt;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let old = b"previous-complete\n".to_vec();
    std::fs::write(&path, &old).unwrap();
    let scratch = path.with_file_name(format!(
        ".readcon-write-{}.tmp",
        path.file_name().unwrap().to_string_lossy()
    ));
    let _ = std::fs::remove_file(&scratch);
    let mut hook = PublishHookPipes::new();
    let hook_env = hook.env_spec();
    let exe = std::env::current_exe().expect("test binary");
    let mut child = std::process::Command::new(exe)
        .arg("a_killed_write_keeps_the_previous_file_or_a_complete_one")
        .arg("--exact")
        .env("READCON_WRITE_CHILD", "1")
        .env("READCON_WRITE_PATH", &path)
        .env("READCON_TEST_PUBLISH_HOOK", hook_env)
        .spawn()
        .expect("spawn child");
    hook.close_parent_child_ends();
    hook.wait_ready();
    let _ = child.kill();
    let status = child.wait().expect("wait child");
    assert!(
        status.signal().is_some(),
        "the write child finished before the kill; status {status:?}"
    );

    let got = std::fs::read(&path).unwrap();
    assert_eq!(
        got, old,
        "published path must stay on the old complete file"
    );
    assert_ne!(
        got, b"readcon-test-partial-buffer\n",
        "partial test buffer was published"
    );
}

fn scratch_names(dir: &std::path::Path) -> Vec<String> {
    std::fs::read_dir(dir)
        .unwrap()
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .filter(|name| name.starts_with(".readcon-write-"))
        .collect()
}

#[cfg(all(target_os = "linux", not(tsan_run)))]
#[test]
fn a_write_killed_while_linking_publishes_and_leaves_no_scratch() {
    if std::env::var_os("READCON_LINK_CHILD").is_some() {
        let path = PathBuf::from(std::env::var("READCON_LINK_PATH").expect("child path"));
        let frame = wide_frame(2_000);
        let _ = write_frame_refs_to_path(&path, &[&frame], 1, None, false, false);
        std::process::exit(0);
    }

    use std::os::unix::process::ExitStatusExt;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let complete = dir.path().join("complete.con");
    write_frame_refs_to_path(&complete, &[&wide_frame(2_000)], 1, None, false, false).unwrap();
    let published = std::fs::read(&complete).unwrap();
    std::fs::remove_file(&complete).unwrap();
    let old = b"previous-complete\n".to_vec();
    std::fs::write(&path, &old).unwrap();
    let mut hook = PublishHookPipes::new();
    let hook_env = hook.env_spec();
    let exe = std::env::current_exe().expect("test binary");
    let mut child = std::process::Command::new(exe)
        .arg("a_write_killed_while_linking_publishes_and_leaves_no_scratch")
        .arg("--exact")
        .env("READCON_LINK_CHILD", "1")
        .env("READCON_LINK_PATH", &path)
        .env("READCON_TEST_LINK_HOOK", hook_env)
        .spawn()
        .expect("spawn child");
    hook.close_parent_child_ends();
    let mut byte = [0_u8];
    let got = unsafe { libc::read(hook.ready_r, byte.as_mut_ptr().cast(), 1) };
    if got != 1 {
        // No O_TMPFILE here: the named scratch is renamed in-process and
        // the link hook never runs.
        assert!(child.wait().expect("wait child").success());
        eprintln!("skipping: the store was not an unnamed file");
        return;
    }
    let _ = child.kill();
    let status = child.wait().expect("wait child");
    assert!(
        status.signal().is_some(),
        "the write child finished before the kill; status {status:?}"
    );
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while std::time::Instant::now() < deadline
        && (std::fs::read(&path).unwrap() != published || !scratch_names(dir.path()).is_empty())
    {
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let left = scratch_names(dir.path());
    assert!(left.is_empty(), "scratch left behind: {left:?}");
    assert_eq!(
        std::fs::read(&path).unwrap(),
        published,
        "a publish already linking must finish after the kill"
    );
}

#[test]
fn a_killed_rewrite_leaves_the_published_file_whole() {
    if std::env::var_os("READCON_REWRITE_CHILD").is_some() {
        let path = PathBuf::from(std::env::var("READCON_REWRITE_PATH").expect("child path"));
        let frame = wide_frame(8_000);
        loop {
            let _ = rewrite_frame_refs_to_path(&path, &[&frame], 4, None, false, false, true);
        }
    }

    use std::os::unix::process::ExitStatusExt;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.con");
    let previous = wide_frame(64);
    write_frame_refs_to_path(&path, &[&previous], 1, None, false, false).unwrap();
    let previous_bytes = std::fs::read(&path).unwrap();
    let spare = path.with_file_name(format!(
        "{}.rewrite",
        path.file_name().unwrap().to_string_lossy()
    ));
    let _ = std::fs::remove_file(&spare);
    let mut hook = PublishHookPipes::new();
    let hook_env = hook.env_spec();
    let exe = std::env::current_exe().expect("test binary");
    let mut child = std::process::Command::new(exe)
        .arg("a_killed_rewrite_leaves_the_published_file_whole")
        .arg("--exact")
        .env("READCON_REWRITE_CHILD", "1")
        .env("READCON_REWRITE_PATH", &path)
        .env("READCON_TEST_PUBLISH_HOOK", hook_env)
        .spawn()
        .expect("spawn child");
    hook.close_parent_child_ends();
    hook.wait_ready();
    let _ = child.kill();
    let status = child.wait().expect("wait child");
    assert!(
        status.signal().is_some(),
        "the rewrite child finished before the kill; status {status:?}"
    );
    let got = std::fs::read(&path).unwrap();
    assert_eq!(
        got, previous_bytes,
        "rewrite publish must not happen before the kill signal"
    );
    assert_ne!(
        got, b"readcon-test-partial-buffer\n",
        "partial test buffer was published"
    );
    let _ = std::fs::remove_file(&spare);
}
