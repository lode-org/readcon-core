//! Wall times for the leaf I/O contract: parse CON vs decode RCSO, Unix vs TCP RPC.
//!
//! Usage (builder only):
//!
//! ```text
//! cargo run --release --example leaf_io_harness --features rpc -- \
//!     benches/results/leaf_io.json
//! ```
//!
//! Same fixture and repeat count as `wall_scale_harness`. Does not invent numbers.

use readcon_core::iterators::frames_from_text;
use readcon_core::rcso::{encode_batch, Rcso};
use readcon_core::rpc::client::RpcClient;
use readcon_core::rpc::server;
use std::env;
use std::fs;
use std::io::Write;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn fixture_text(name: &str) -> String {
    fs::read_to_string(repo_root().join("resources/test").join(name)).expect("fixture")
}

fn repeat_text(one: &str, n: usize) -> String {
    let mut buf = String::with_capacity(one.len() * n);
    for _ in 0..n {
        buf.push_str(one);
    }
    buf
}

fn median_ms(mut samples: Vec<f64>) -> f64 {
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    samples[samples.len() / 2]
}

fn time_ms<F: FnMut()>(repeat: usize, mut f: F) -> f64 {
    let mut samples = Vec::with_capacity(repeat);
    for _ in 0..repeat {
        let t0 = Instant::now();
        f();
        samples.push(t0.elapsed().as_secs_f64() * 1.0e3);
    }
    median_ms(samples)
}

fn git_commit() -> String {
    Command::new("git")
        .args(["rev-parse", "--short=8", "HEAD"])
        .current_dir(repo_root())
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

fn hostname() -> String {
    Command::new("hostname")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

fn chrono_like_utc() -> String {
    Command::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%MZ"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".into())
}

fn free_tcp_addr() -> String {
    let l = TcpListener::bind("127.0.0.1:0").expect("ephemeral tcp");
    let port = l.local_addr().expect("addr").port();
    drop(l);
    format!("127.0.0.1:{port}")
}

fn spawn_rpc(spec: String) {
    std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("rt");
        let local = tokio::task::LocalSet::new();
        let _ = rt.block_on(local.run_until(server::start_server(&spec)));
    });
}

fn wait_unix(path: &Path) {
    let t0 = Instant::now();
    while !path.exists() {
        assert!(t0.elapsed() < Duration::from_secs(10), "unix bind {path:?}");
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn wait_tcp(addr: &str) {
    let t0 = Instant::now();
    loop {
        if std::net::TcpStream::connect(addr).is_ok() {
            return;
        }
        assert!(t0.elapsed() < Duration::from_secs(10), "tcp bind {addr}");
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn main() {
    let out_path = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| repo_root().join("benches/results/leaf_io.json"));

    let repeats = 5usize;
    let n_frames = 100usize;
    let one = fixture_text("cuh2.con");
    let text = repeat_text(&one, n_frames);
    let frames = frames_from_text(&text, Some(1)).expect("parse payload");
    assert_eq!(frames.len(), n_frames);
    let n_atoms = frames[0].atom_data.len();

    let parse_ms = time_ms(repeats, || {
        let got = frames_from_text(&text, Some(1)).expect("parse");
        assert_eq!(got.len(), n_frames);
        std::hint::black_box(got);
    });

    let blobs: Vec<Vec<u8>> = frames
        .iter()
        .map(|f| Rcso::encode_frame(f).expect("encode"))
        .collect();
    let batch = encode_batch(&blobs).expect("rcsb");

    let pack_ms = time_ms(repeats, || {
        let b: Vec<Vec<u8>> = frames
            .iter()
            .map(|f| Rcso::encode_frame(f).expect("encode"))
            .collect();
        let env = encode_batch(&b).expect("rcsb");
        std::hint::black_box(env);
    });

    let decode_ms = time_ms(repeats, || {
        let parts = readcon_core::rcso::decode_batch(&batch).expect("split");
        let mut n = 0usize;
        for p in &parts {
            let s = Rcso::decode(p).expect("decode");
            n += s.positions.len();
        }
        assert_eq!(n, n_frames * n_atoms);
        std::hint::black_box(n);
    });

    let sock = std::env::temp_dir().join(format!("readcon-leaf-{}.sock", std::process::id()));
    let _ = fs::remove_file(&sock);
    let unix_spec = format!("unix:{}", sock.display());
    spawn_rpc(unix_spec.clone());
    wait_unix(&sock);
    let unix_client = RpcClient::new(&unix_spec).expect("unix client");
    let unix_ms = time_ms(repeats, || {
        let got = unix_client.parse_bytes(one.as_bytes()).expect("unix parse");
        assert_eq!(got[0].atom_data.len(), n_atoms);
        std::hint::black_box(got);
    });

    let tcp_spec = free_tcp_addr();
    spawn_rpc(tcp_spec.clone());
    wait_tcp(&tcp_spec);
    let tcp_client = RpcClient::new(&tcp_spec).expect("tcp client");
    let tcp_ms = time_ms(repeats, || {
        let got = tcp_client.parse_bytes(one.as_bytes()).expect("tcp parse");
        assert_eq!(got[0].atom_data.len(), n_atoms);
        std::hint::black_box(got);
    });
    let _ = fs::remove_file(&sock);

    let ncpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let ratio_parse_over_decode = if decode_ms > 0.0 {
        parse_ms / decode_ms
    } else {
        0.0
    };
    let ratio_tcp_over_unix = if unix_ms > 0.0 { tcp_ms / unix_ms } else { 0.0 };

    let mut json = String::new();
    json.push_str("{\n");
    json.push_str("  \"protocol\": \"cuh2.con x100: CON parse vs RCSO encode/decode; one-frame RpcClient parse_bytes Unix vs TCP loopback\",\n");
    json.push_str(&format!("  \"host\": \"{}\",\n", hostname()));
    json.push_str(&format!("  \"date_utc\": \"{}\",\n", chrono_like_utc()));
    json.push_str(&format!("  \"commit\": \"{}\",\n", git_commit()));
    json.push_str("  \"features\": \"rpc\",\n");
    json.push_str(&format!("  \"ncpus\": {},\n", ncpus));
    json.push_str(&format!("  \"n_frames\": {},\n", n_frames));
    json.push_str(&format!("  \"n_atoms\": {},\n", n_atoms));
    json.push_str(&format!("  \"repeats\": {},\n", repeats));
    json.push_str("  \"fixture\": \"resources/test/cuh2.con\",\n");
    json.push_str(&format!("  \"payload_bytes\": {},\n", text.len()));
    json.push_str(&format!("  \"one_frame_bytes\": {},\n", one.len()));
    json.push_str(&format!("  \"rcsb_bytes\": {},\n", batch.len()));
    json.push_str(&format!("  \"parse_100_frames_ms\": {:.6},\n", parse_ms));
    json.push_str(&format!("  \"rcso_pack_100_ms\": {:.6},\n", pack_ms));
    json.push_str(&format!("  \"rcso_decode_100_ms\": {:.6},\n", decode_ms));
    json.push_str(&format!("  \"parse_over_decode\": {:.4},\n", ratio_parse_over_decode));
    json.push_str(&format!("  \"rpc_unix_one_frame_ms\": {:.6},\n", unix_ms));
    json.push_str(&format!("  \"rpc_tcp_one_frame_ms\": {:.6},\n", tcp_ms));
    json.push_str(&format!("  \"tcp_over_unix\": {:.4}\n", ratio_tcp_over_unix));
    json.push_str("}\n");

    if let Some(parent) = out_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let mut f = fs::File::create(&out_path).expect("create json");
    f.write_all(json.as_bytes()).expect("write json");
    println!("wrote {}", Path::new(&out_path).display());
    print!("{json}");
}
