//! Pair mapped prefetch plans with the eight-thread O_DIRECT read.
//!
//! The clock starts before the read and stops after a float64 sum of both
//! columns. O_DIRECT is the lazy two-buffer form: `MADV_HUGEPAGE` on the
//! destination, then `pread` with `O_DIRECT`, faults taken during that read.

#[cfg(target_os = "linux")]
use std::env;
#[cfg(target_os = "linux")]
use std::fs::File;
#[cfg(target_os = "linux")]
use std::os::fd::AsRawFd;
#[cfg(target_os = "linux")]
use std::path::Path;
#[cfg(target_os = "linux")]
use std::ptr;
#[cfg(target_os = "linux")]
use std::time::Instant;

#[cfg(target_os = "linux")]
use readcon_core::conbin::{Prefetch, QueueLimits, map_file_with, sum_mapped, sum_split_streams};

#[cfg(target_os = "linux")]
fn page_size() -> usize {
    let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    assert!(page > 0 && (page as usize).is_power_of_two());
    page as usize
}

#[cfg(target_os = "linux")]
fn max_rw_count(page: usize) -> usize {
    (i32::MAX as usize) & !(page - 1)
}

#[cfg(target_os = "linux")]
fn logical_block(path: &Path) -> usize {
    QueueLimits::of(path).expect("queue").logical_block
}

#[cfg(target_os = "linux")]
fn sum_f64(data: &[f64]) -> f64 {
    let mut acc = 0.0f64;
    for &value in data {
        acc += value;
    }
    acc
}

#[cfg(target_os = "linux")]
fn sum_bytes(ptr: *const u8, nbytes: usize) -> f64 {
    assert!(nbytes % 8 == 0);
    let data = unsafe { std::slice::from_raw_parts(ptr.cast::<f64>(), nbytes / 8) };
    sum_f64(data)
}

#[cfg(target_os = "linux")]
struct Anon {
    ptr: *mut u8,
    len: usize,
}

#[cfg(target_os = "linux")]
impl Anon {
    fn new(len: usize) -> Self {
        let ptr = unsafe {
            libc::mmap(
                ptr::null_mut(),
                len,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        assert_ne!(ptr, libc::MAP_FAILED);
        Self {
            ptr: ptr.cast(),
            len,
        }
    }

    fn hint_huge(&self) {
        unsafe {
            libc::madvise(self.ptr.cast(), self.len, libc::MADV_HUGEPAGE);
        }
    }
}

#[cfg(target_os = "linux")]
impl Drop for Anon {
    fn drop(&mut self) {
        unsafe { libc::munmap(self.ptr.cast(), self.len) };
    }
}

#[cfg(target_os = "linux")]
fn pread_all(
    fd: i32,
    dest: *mut u8,
    len: usize,
    mut offset: u64,
    cap: usize,
) -> std::io::Result<()> {
    let mut done = 0usize;
    while done < len {
        let want = (len - done).min(cap);
        let n = unsafe { libc::pread(fd, dest.add(done).cast(), want, offset as libc::off_t) };
        if n < 0 {
            let err = std::io::Error::last_os_error();
            if err.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        if n == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "short pread",
            ));
        }
        done += n as usize;
        offset += n as u64;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn pread_parallel(
    fd: i32,
    dest: *mut u8,
    len: usize,
    offset: u64,
    threads: usize,
    page: usize,
    cap: usize,
) -> std::io::Result<()> {
    let addr = dest as usize;
    let threads = threads.max(1);
    let workers = if len < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    if workers == 1 {
        return pread_all(fd, dest, len, offset, cap);
    }
    let chunk = (len / workers) & !(page - 1);
    std::thread::scope(|scope| {
        let mut off = 0usize;
        let mut handles = Vec::with_capacity(workers);
        for worker in 0..workers {
            let take = if worker + 1 == workers {
                len - off
            } else {
                chunk
            };
            let start = off;
            let file_off = offset + start as u64;
            off += take;
            handles.push(
                scope.spawn(move || pread_all(fd, (addr + start) as *mut u8, take, file_off, cap)),
            );
        }
        for handle in handles {
            handle.join().expect("pread thread")?;
        }
        Ok(())
    })
}

#[cfg(target_os = "linux")]
fn pread_lazy2(path: &Path, threads: usize) -> (f64, i64) {
    let page = page_size();
    let cap = max_rw_count(page);
    let file = File::open(path).expect("open");
    let len = file.metadata().expect("meta").len() as usize;
    let payload = len - page;
    let column = payload / 2;
    let pos = Anon::new(column);
    let vel = Anon::new(column);
    let fd = file.as_raw_fd();
    unsafe { libc::posix_fadvise(fd, 0, 0, libc::POSIX_FADV_SEQUENTIAL) };
    pread_parallel(fd, pos.ptr, column, page as u64, threads, page, cap).expect("positions");
    pread_parallel(
        fd,
        vel.ptr,
        column,
        page as u64 + column as u64,
        threads,
        page,
        cap,
    )
    .expect("velocities");
    let sum = sum_bytes(pos.ptr, column) + sum_bytes(vel.ptr, column);
    let rss = vm_hwm_kb();
    (sum, rss)
}

#[cfg(target_os = "linux")]
fn odirect_lazy2(path: &Path, threads: usize) -> (f64, i64) {
    let page = page_size();
    let cap = max_rw_count(page);
    let len = std::fs::metadata(path).unwrap().len() as usize;
    let payload = len - page;
    assert_eq!(payload % 2, 0);
    let column = payload / 2;
    let block = logical_block(path);
    assert_eq!(column % block, 0);
    let pos = Anon::new(column);
    let vel = Anon::new(column);
    pos.hint_huge();
    vel.hint_huge();
    let c = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
    let fd = unsafe {
        libc::open(
            c.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECT | libc::O_CLOEXEC,
        )
    };
    assert!(
        fd >= 0,
        "open O_DIRECT: {}",
        std::io::Error::last_os_error()
    );
    let first = pread_parallel(fd, pos.ptr, column, page as u64, threads, page, cap);
    let second = pread_parallel(
        fd,
        vel.ptr,
        column,
        page as u64 + column as u64,
        threads,
        page,
        cap,
    );
    unsafe { libc::close(fd) };
    first.expect("positions");
    second.expect("velocities");
    let sum = sum_bytes(pos.ptr, column) + sum_bytes(vel.ptr, column);
    let rss = vm_hwm_kb();
    (sum, rss)
}

/// One `readahead` stream of `max_sectors_kb` pieces, overlapped with the sum.
/// The sum runs on this thread while the requests are submitted.
#[cfg(target_os = "linux")]
fn stream_sum(path: &Path) -> (f64, i64) {
    let limits = QueueLimits::of(path).expect("queue");
    let file = File::open(path).expect("open");
    let len = file.metadata().expect("meta").len() as usize;
    let page = limits.page;
    let ptr = unsafe {
        libc::mmap(
            ptr::null_mut(),
            len,
            libc::PROT_READ,
            libc::MAP_PRIVATE,
            file.as_raw_fd(),
            0,
        )
    };
    assert_ne!(ptr, libc::MAP_FAILED);
    unsafe {
        libc::madvise(ptr, len, libc::MADV_SEQUENTIAL);
    }
    let base = ptr as usize;
    let request = (limits.max_request & !(page - 1)).max(page);
    let sum = std::thread::scope(|scope| {
        scope.spawn(move || {
            let fd = File::open(path).expect("stream open");
            let mut off = 0usize;
            while off < len {
                let n = request.min(len - off);
                let rc = unsafe { libc::readahead(fd.as_raw_fd(), off as i64, n) };
                assert!(rc == 0, "readahead: {}", std::io::Error::last_os_error());
                off += n;
            }
        });
        sum_bytes((base + page) as *const u8, len - page)
    });
    let rss = vm_hwm_kb();
    unsafe { libc::munmap(ptr, len) };
    (sum, rss)
}

#[cfg(target_os = "linux")]
fn pipeline_sum(path: &Path, threads: usize) -> (f64, i64) {
    let limits = QueueLimits::of(path).expect("queue");
    let file = File::open(path).expect("open");
    let len = file.metadata().expect("meta").len() as usize;
    let page = limits.page;
    let ptr = unsafe {
        libc::mmap(
            ptr::null_mut(),
            len,
            libc::PROT_READ,
            libc::MAP_PRIVATE,
            file.as_raw_fd(),
            0,
        )
    };
    assert_ne!(ptr, libc::MAP_FAILED);
    unsafe {
        libc::madvise(ptr, len, libc::MADV_SEQUENTIAL);
        libc::madvise(ptr, len, libc::MADV_HUGEPAGE);
    }
    let base = ptr as usize;
    // One queue share per worker: nr_requests/workers requests of max_sectors_kb.
    let request = limits.worker_span(threads.max(1));
    let threads = threads.max(1);
    let workers = if len < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    let chunk = if workers == 1 {
        len
    } else {
        (len / workers) & !(page - 1)
    };
    // Each worker submits readahead for the next queue-sized piece of its
    // span, then sums the piece just submitted. The sum is the consumer.
    // The pieces are disjoint, so the workers do not share a byte.
    let sum = std::thread::scope(|scope| {
        let mut start = 0usize;
        let mut partials = Vec::with_capacity(workers);
        for worker in 0..workers {
            let take = if worker + 1 == workers {
                len - start
            } else {
                chunk
            };
            let span = start;
            start += take;
            partials.push(scope.spawn(move || {
                let fd = File::open(path).expect("worker open");
                let end = span + take;
                let mut acc = 0.0f64;
                let mut off = span;
                if off < end {
                    let n = request.min(end - off);
                    let rc = unsafe { libc::readahead(fd.as_raw_fd(), off as i64, n) };
                    assert!(rc == 0, "readahead: {}", std::io::Error::last_os_error());
                }
                while off < end {
                    let n = request.min(end - off);
                    let next = off + n;
                    if next < end {
                        let m = request.min(end - next);
                        let rc = unsafe { libc::readahead(fd.as_raw_fd(), next as i64, m) };
                        assert!(rc == 0, "readahead: {}", std::io::Error::last_os_error());
                    }
                    let from = off.max(page);
                    let to = next.min(len);
                    if to > from {
                        acc += sum_bytes((base + from) as *const u8, to - from);
                    }
                    off = next;
                }
                acc
            }));
        }
        partials
            .into_iter()
            .map(|handle| handle.join().expect("pipeline"))
            .sum::<f64>()
    });
    let rss = vm_hwm_kb();
    unsafe { libc::munmap(ptr, len) };
    (sum, rss)
}

#[cfg(target_os = "linux")]
fn mapped_sum(path: &Path, threads: usize, prefetch: Prefetch) -> (f64, i64) {
    let mapped = map_file_with(path, threads, prefetch).expect("map");
    let pos = mapped.positions_f64().expect("positions");
    let vel = mapped.velocities_f64().expect("velocities");
    let sum = sum_f64(pos) + sum_f64(vel);
    let rss = vm_hwm_kb();
    (sum, rss)
}

#[cfg(target_os = "linux")]
fn rusage_minflt() -> i64 {
    rusage_count(|raw| raw.ru_minflt)
}

#[cfg(target_os = "linux")]
fn rusage_majflt() -> i64 {
    rusage_count(|raw| raw.ru_majflt)
}

#[cfg(target_os = "linux")]
fn rusage_count(field: impl FnOnce(&libc::rusage) -> libc::c_long) -> i64 {
    let mut raw: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut raw) };
    field(&raw)
}

#[cfg(target_os = "linux")]
fn proc_io_read_bytes() -> u64 {
    let text = std::fs::read_to_string("/proc/self/io").unwrap_or_default();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("read_bytes:") {
            return rest.trim().parse().unwrap_or(0);
        }
    }
    0
}

#[cfg(target_os = "linux")]
fn vm_hwm_kb() -> i64 {
    let text = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            return rest
                .split_whitespace()
                .next()
                .unwrap_or("0")
                .parse()
                .unwrap_or(0);
        }
    }
    -1
}

#[cfg(target_os = "linux")]
fn main() {
    let mut file = None;
    let mut mode = "span".to_string();
    let mut threads = 1usize;
    let args: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--file" => {
                i += 1;
                file = Some(args[i].clone());
            }
            "--mode" => {
                i += 1;
                mode = args[i].clone();
            }
            "--threads" => {
                i += 1;
                threads = args[i].parse().expect("threads");
            }
            other => panic!("unknown argument {other}"),
        }
        i += 1;
    }
    let path = Path::new(file.as_deref().expect("--file"));
    let before_min = rusage_minflt();
    let before_maj = rusage_majflt();
    let before_io = proc_io_read_bytes();
    let t0 = Instant::now();
    let (sum, rss) = match mode.as_str() {
        "auto" => {
            let sum = sum_mapped(path, threads).expect("sum");
            (sum, vm_hwm_kb())
        }
        "split" => {
            let sum = sum_split_streams(path, threads).expect("split");
            (sum, vm_hwm_kb())
        }
        "span" => mapped_sum(path, threads, Prefetch::Span),
        "chunk-populate" => mapped_sum(path, threads, Prefetch::ChunkPopulate),
        "chunk-willneed" => mapped_sum(path, threads, Prefetch::ChunkWillneed),
        "hybrid" => mapped_sum(path, threads, Prefetch::Hybrid),
        "odirect-lazy2" => odirect_lazy2(path, threads),
        "pipeline" => pipeline_sum(path, threads),
        "stream" => stream_sum(path),
        "pread2" => pread_lazy2(path, threads),
        other => panic!("unknown mode {other}"),
    };
    let seconds = t0.elapsed().as_secs_f64();
    let minflt = rusage_minflt() - before_min;
    let majflt = rusage_majflt() - before_maj;
    let read_bytes = proc_io_read_bytes().saturating_sub(before_io);
    std::hint::black_box(sum);
    println!(
        "{{\"mode\":\"{mode}\",\"threads\":{threads},\"seconds\":{seconds:.6},\"sum\":{sum:.16e},\"minflt\":{minflt},\"majflt\":{majflt},\"read_bytes\":{read_bytes},\"rss_kb\":{rss}}}"
    );
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("conbin_scale reads a Linux block queue");
    std::process::exit(1);
}
