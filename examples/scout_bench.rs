//! Head-to-head of the scout prototypes against the current reader.
//!
//! One core, one warmup, six samples, type-7 median and interquartile range.
//! Correctness runs before the clock. RSS is a fresh process: peak VmHWM
//! minus the file that process read.

use readcon_core::compression::read_file_contents;
use readcon_core::extxyz_scan::tables_from_extxyz_path;
use readcon_core::iterators::{read_all_frames_with_threads, read_positions_with_threads};
use readcon_core::scout::{
    bench_float_kernels, compress_zstd, decode_dict_frames, decode_dict_whole, decode_lowrank,
    decode_shuffled, encode_dict_frames, encode_dict_whole, encode_shuffled, fit_positions,
    positions_from_con_bytes, positions_from_extxyz_bytes,
};
use std::env;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Instant;

const WARMUP: usize = 1;
const SAMPLES: usize = 6;
const N_FRAMES: usize = 100_000;
const N_ATOMS: usize = 32;
const N_MILLION: usize = 1_000_000;

fn main() {
    let mut args = env::args().skip(1);
    match args.next().as_deref() {
        Some("rss") => {
            let kind = args.next().expect("kind");
            let path = args.next().expect("path");
            rss_main(&kind, Path::new(&path));
        }
        Some("campaign") => campaign(),
        Some("thermal") => thermal(),
        _ => {
            eprintln!("usage: scout_bench campaign | scout_bench rss <kind> <path>");
            std::process::exit(2);
        }
    }
}

fn campaign() {
    ensure_pinned();
    // These are process-wide and read by libraries on first use. Nothing else
    // in this process has started a thread pool yet.
    unsafe {
        env::set_var("OMP_NUM_THREADS", "1");
        env::set_var("OPENBLAS_NUM_THREADS", "1");
        env::set_var("MKL_NUM_THREADS", "1");
        env::set_var("RAYON_NUM_THREADS", "1");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let inputs = ensure_inputs(&root);
    let scratch = root.join("bench/h2h/work/scout");
    fs::create_dir_all(&scratch).unwrap();
    let log_dir = root.join("bench/h2h/scout/raw");
    fs::create_dir_all(&log_dir).unwrap();

    eprintln!("preparing codecs");
    let prepared = prepare(&inputs, &scratch);
    eprintln!("checking coordinates");
    let checks = check_all(&inputs, &prepared);
    if checks
        .iter()
        .any(|row| !row.bit_exact && row.bound.is_none())
    {
        write_outputs(&root, &log_dir, &prepared, &checks, &[], &[]);
        eprintln!("lossless check failed");
        std::process::exit(1);
    }

    eprintln!("timing");
    let mut timed = Vec::new();
    for spec in arm_specs(&inputs, &prepared) {
        eprintln!("  {}", spec.name);
        timed.push(time_arm(&spec));
    }
    eprintln!("float kernels");
    let floats = float_report(&inputs.million);
    eprintln!("rss");
    let mut rss = Vec::new();
    for spec in arm_specs(&inputs, &prepared) {
        rss.push(rss_child(&spec));
    }
    write_outputs(&root, &log_dir, &prepared, &checks, &timed, &rss);
    write_floats(&log_dir, &floats);
    let massif = massif_sample(&inputs, &prepared, &scratch);
    write_massif(&log_dir, &massif);
    eprintln!(
        "wrote {}",
        root.join("bench/h2h/scout/results.json").display()
    );
}

struct Inputs {
    con: PathBuf,
    convel: PathBuf,
    extxyz: PathBuf,
    million: PathBuf,
}

struct Prepared {
    shuffle_con: PathBuf,
    shuffle_million: PathBuf,
    raw_con: PathBuf,
    raw_million: PathBuf,
    zstd_con: PathBuf,
    zstd_convel: PathBuf,
    zstd_million: PathBuf,
    dict_frames_con: PathBuf,
    dict_whole_con: PathBuf,
    dict_frames_convel: PathBuf,
    low_loose: Option<PathBuf>,
    low_tight: Option<PathBuf>,
    notes: Vec<String>,
    sizes: Vec<(String, u64)>,
}

struct Arm {
    name: String,
    kind: String,
    path: PathBuf,
}

struct Check {
    name: String,
    bit_exact: bool,
    max_abs: f64,
    bound: Option<f64>,
    detail: String,
}

struct Timed {
    name: String,
    warmup_s: f64,
    samples: Vec<f64>,
    median_s: f64,
    q25_s: f64,
    q75_s: f64,
    iqr_s: f64,
    n: usize,
}

struct Rss {
    name: String,
    hwm_kib: u64,
    file_bytes: u64,
    over_input_kib: i64,
}

fn arm_specs(inputs: &Inputs, prepared: &Prepared) -> Vec<Arm> {
    let mut arms = vec![
        arm("readcon-frames-con", "frames", &inputs.con),
        arm("readcon-frames-convel", "frames", &inputs.convel),
        arm("readcon-frames-million", "frames", &inputs.million),
        arm("readcon-positions-con", "positions", &inputs.con),
        arm("readcon-positions-convel", "positions", &inputs.convel),
        arm("readcon-positions-million", "positions", &inputs.million),
        arm("column-con", "column-con", &inputs.con),
        arm("column-convel", "column-con", &inputs.convel),
        arm("column-million", "column-con", &inputs.million),
        arm("readcon-extxyz", "extxyz", &inputs.extxyz),
        arm("column-extxyz", "column-xyz", &inputs.extxyz),
        arm("zstd-positions-con", "positions", &prepared.zstd_con),
        arm("zstd-positions-convel", "positions", &prepared.zstd_convel),
        arm(
            "zstd-positions-million",
            "positions",
            &prepared.zstd_million,
        ),
        arm("shuffle-con", "shuffle", &prepared.shuffle_con),
        arm("shuffle-million", "shuffle", &prepared.shuffle_million),
        arm("raw-f64-con", "raw", &prepared.raw_con),
        arm("raw-f64-million", "raw", &prepared.raw_million),
        arm("dict-frames-con", "dict-frames", &prepared.dict_frames_con),
        arm(
            "dict-frames-convel",
            "dict-frames",
            &prepared.dict_frames_convel,
        ),
        arm("dict-whole-con", "dict-whole", &prepared.dict_whole_con),
    ];
    if let Some(path) = &prepared.low_loose {
        arms.push(arm("lowrank-1e-3-con", "lowrank", path));
    }
    if let Some(path) = &prepared.low_tight {
        arms.push(arm("lowrank-1e-8-con", "lowrank", path));
    }
    arms
}

fn arm(name: &str, kind: &str, path: &Path) -> Arm {
    Arm {
        name: name.to_string(),
        kind: kind.to_string(),
        path: path.to_path_buf(),
    }
}

fn run_kind(kind: &str, path: &Path) -> Result<usize, String> {
    match kind {
        "frames" => {
            let frames =
                read_all_frames_with_threads(path, Some(1)).map_err(|err| err.to_string())?;
            std::hint::black_box(&frames);
            Ok(frames.len())
        }
        "positions" => {
            let block =
                read_positions_with_threads(path, Some(1)).map_err(|err| err.to_string())?;
            std::hint::black_box(&block.values);
            Ok(block.values.len())
        }
        "column-con" => {
            let contents = read_file_contents(path).map_err(|err| err.to_string())?;
            let got =
                positions_from_con_bytes(contents.as_bytes()).map_err(|err| err.to_string())?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        "extxyz" => {
            let tables = tables_from_extxyz_path(path)?;
            std::hint::black_box(&tables.positions);
            Ok(tables.positions.len())
        }
        "column-xyz" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let got = positions_from_extxyz_bytes(&bytes)?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        "shuffle" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let (values, _, _, _) = decode_shuffled(&bytes).map_err(|err| err.to_string())?;
            std::hint::black_box(&values);
            Ok(values.len())
        }
        "dict-frames" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let text = decode_dict_frames(&bytes).map_err(|err| err.to_string())?;
            let got = positions_from_con_bytes(&text).map_err(|err| err.to_string())?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        "dict-whole" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let text = decode_dict_whole(&bytes).map_err(|err| err.to_string())?;
            let got = positions_from_con_bytes(&text).map_err(|err| err.to_string())?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        "raw" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let mut values = Vec::with_capacity(bytes.len() / 8);
            for chunk in bytes.chunks_exact(8) {
                values.push(f64::from_le_bytes(chunk.try_into().unwrap()));
            }
            std::hint::black_box(&values);
            Ok(values.len())
        }
        "lowrank" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let values = decode_lowrank(&bytes)?;
            std::hint::black_box(&values);
            Ok(values.len())
        }
        "fzstd" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let raw = zstd::bulk::decompress(&bytes, 512 << 20).map_err(|err| err.to_string())?;
            let mut values = Vec::with_capacity(raw.len() / 8);
            for chunk in raw.chunks_exact(8) {
                values.push(f64::from_le_bytes(chunk.try_into().unwrap()));
            }
            std::hint::black_box(&values);
            Ok(values.len())
        }
        "gzip-positions" => {
            use std::io::Read;
            let file = File::open(path).map_err(|err| err.to_string())?;
            let mut decoder = flate2::read::GzDecoder::new(file);
            let mut text = Vec::new();
            decoder
                .read_to_end(&mut text)
                .map_err(|err| err.to_string())?;
            let got = positions_from_con_bytes(&text).map_err(|err| err.to_string())?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        "zstd-positions" => {
            let bytes = fs::read(path).map_err(|err| err.to_string())?;
            let text = zstd::bulk::decompress(&bytes, 512 << 20).map_err(|err| err.to_string())?;
            let got = positions_from_con_bytes(&text).map_err(|err| err.to_string())?;
            std::hint::black_box(&got.positions);
            Ok(got.positions.len())
        }
        other => Err(format!("unknown kind {other}")),
    }
}

fn time_arm(spec: &Arm) -> Timed {
    let started = Instant::now();
    let n = run_kind(&spec.kind, &spec.path)
        .unwrap_or_else(|err| panic!("{} warmup: {err}", spec.name));
    let warmup_s = started.elapsed().as_secs_f64();
    let _ = WARMUP;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let started = Instant::now();
        let got =
            run_kind(&spec.kind, &spec.path).unwrap_or_else(|err| panic!("{}: {err}", spec.name));
        samples.push(started.elapsed().as_secs_f64());
        assert_eq!(got, n, "{}", spec.name);
    }
    let q25_s = type7(&samples, 0.25);
    let median_s = type7(&samples, 0.5);
    let q75_s = type7(&samples, 0.75);
    Timed {
        name: spec.name.clone(),
        warmup_s,
        samples,
        median_s,
        q25_s,
        q75_s,
        iqr_s: q75_s - q25_s,
        n,
    }
}

fn type7(values: &[f64], probability: f64) -> f64 {
    let mut ordered = values.to_vec();
    ordered.sort_by(|left, right| left.partial_cmp(right).unwrap());
    let n = ordered.len();
    if n == 1 {
        return ordered[0];
    }
    let h = (n - 1) as f64 * probability;
    let lo = h.floor() as usize;
    let hi = h.ceil() as usize;
    if lo == hi {
        ordered[lo]
    } else {
        ordered[lo] + (h - lo as f64) * (ordered[hi] - ordered[lo])
    }
}

fn compare_bits(got: &[f64], expect: &[f64]) -> (bool, f64) {
    if got.len() != expect.len() {
        return (false, f64::INFINITY);
    }
    let mut worst = 0.0f64;
    let mut exact = true;
    for (left, right) in got.iter().zip(expect) {
        if left.to_bits() != right.to_bits() {
            exact = false;
        }
        worst = worst.max((left - right).abs());
    }
    (exact, worst)
}

fn check_all(inputs: &Inputs, prepared: &Prepared) -> Vec<Check> {
    let mut rows = Vec::new();
    let con = load_positions(&inputs.con);
    let convel = load_positions(&inputs.convel);
    let million = load_positions(&inputs.million);
    let xyz = tables_from_extxyz_path(&inputs.extxyz).unwrap();
    rows.push(check_column("column-con", &inputs.con, &con.0));
    rows.push(check_column("column-convel", &inputs.convel, &convel.0));
    rows.push(check_column("column-million", &inputs.million, &million.0));
    let (exact, worst) = compare_bits(&xyz.positions, &column_xyz(&inputs.extxyz));
    rows.push(Check {
        name: "column-extxyz".into(),
        bit_exact: exact,
        max_abs: worst,
        bound: None,
        detail: format!("frames {}", xyz.n_frames),
    });
    rows.push(check_decode(
        "shuffle-con",
        &prepared.shuffle_con,
        &con.0,
        "shuffle",
    ));
    rows.push(check_decode(
        "shuffle-million",
        &prepared.shuffle_million,
        &million.0,
        "shuffle",
    ));
    rows.push(check_decode(
        "raw-f64-con",
        &prepared.raw_con,
        &con.0,
        "raw",
    ));
    rows.push(check_decode(
        "raw-f64-million",
        &prepared.raw_million,
        &million.0,
        "raw",
    ));
    rows.push(check_positions_file(
        "zstd-positions-con",
        &prepared.zstd_con,
        &con.0,
    ));
    rows.push(check_positions_file(
        "zstd-positions-convel",
        &prepared.zstd_convel,
        &convel.0,
    ));
    rows.push(check_positions_file(
        "zstd-positions-million",
        &prepared.zstd_million,
        &million.0,
    ));
    rows.push(check_dict(
        "dict-frames-con",
        &prepared.dict_frames_con,
        &con.0,
        true,
    ));
    rows.push(check_dict(
        "dict-frames-convel",
        &prepared.dict_frames_convel,
        &convel.0,
        true,
    ));
    rows.push(check_dict(
        "dict-whole-con",
        &prepared.dict_whole_con,
        &con.0,
        false,
    ));
    if let Some(path) = &prepared.low_loose {
        rows.push(check_lowrank("lowrank-1e-3-con", path, &con.0, 1e-3));
    }
    if let Some(path) = &prepared.low_tight {
        rows.push(check_lowrank("lowrank-1e-8-con", path, &con.0, 1e-8));
    }
    for row in &rows {
        eprintln!(
            "  {} bit_exact={} max_abs={:.3e} {}",
            row.name, row.bit_exact, row.max_abs, row.detail
        );
    }
    rows
}

fn load_positions(path: &Path) -> (Vec<f64>, usize, usize) {
    let block = read_positions_with_threads(path, Some(1)).unwrap();
    (block.values, block.n_frames, block.n_atoms)
}

fn check_column(name: &str, path: &Path, expect: &[f64]) -> Check {
    let contents = read_file_contents(path).unwrap();
    let got = positions_from_con_bytes(contents.as_bytes()).unwrap();
    let (exact, worst) = compare_bits(&got.positions, expect);
    Check {
        name: name.into(),
        bit_exact: exact,
        max_abs: worst,
        bound: None,
        detail: format!("frames {}", got.n_frames),
    }
}

fn column_xyz(path: &Path) -> Vec<f64> {
    let bytes = fs::read(path).unwrap();
    positions_from_extxyz_bytes(&bytes).unwrap().positions
}

fn check_decode(name: &str, path: &Path, expect: &[f64], kind: &str) -> Check {
    let values = match kind {
        "shuffle" => decode_shuffled(&fs::read(path).unwrap()).unwrap().0,
        "raw" => {
            let bytes = fs::read(path).unwrap();
            bytes
                .chunks_exact(8)
                .map(|chunk| f64::from_le_bytes(chunk.try_into().unwrap()))
                .collect()
        }
        _ => unreachable!(),
    };
    let (exact, worst) = compare_bits(&values, expect);
    Check {
        name: name.into(),
        bit_exact: exact,
        max_abs: worst,
        bound: None,
        detail: String::new(),
    }
}

fn check_positions_file(name: &str, path: &Path, expect: &[f64]) -> Check {
    let block = read_positions_with_threads(path, Some(1)).unwrap();
    let (exact, worst) = compare_bits(&block.values, expect);
    Check {
        name: name.into(),
        bit_exact: exact,
        max_abs: worst,
        bound: None,
        detail: String::new(),
    }
}

fn check_dict(name: &str, path: &Path, expect: &[f64], frames: bool) -> Check {
    let bytes = fs::read(path).unwrap();
    let text = if frames {
        decode_dict_frames(&bytes).unwrap()
    } else {
        decode_dict_whole(&bytes).unwrap()
    };
    let got = positions_from_con_bytes(&text).unwrap();
    let (exact, worst) = compare_bits(&got.positions, expect);
    Check {
        name: name.into(),
        bit_exact: exact,
        max_abs: worst,
        bound: None,
        detail: format!("text_bytes {}", text.len()),
    }
}

fn check_lowrank(name: &str, path: &Path, expect: &[f64], bound: f64) -> Check {
    let values = decode_lowrank(&fs::read(path).unwrap()).unwrap();
    let (_, worst) = compare_bits(&values, expect);
    Check {
        name: name.into(),
        bit_exact: false,
        max_abs: worst,
        bound: Some(bound),
        detail: format!("met={}", worst <= bound),
    }
}

fn prepare(inputs: &Inputs, scratch: &Path) -> Prepared {
    let mut notes = Vec::new();
    let mut sizes = Vec::new();
    for (label, path) in [
        ("text-con", &inputs.con),
        ("text-convel", &inputs.convel),
        ("text-extxyz", &inputs.extxyz),
        ("text-million", &inputs.million),
    ] {
        sizes.push((label.into(), fs::metadata(path).unwrap().len()));
    }
    let (con, n_frames, n_atoms) = load_positions(&inputs.con);
    let (million, m_frames, m_atoms) = load_positions(&inputs.million);
    let raw_con = scratch.join("con.f64");
    let raw_million = scratch.join("million.f64");
    write_f64(&raw_con, &con);
    write_f64(&raw_million, &million);
    let shuffle_con = scratch.join("con.rcshuf");
    let shuffle_million = scratch.join("million.rcshuf");
    fs::write(
        &shuffle_con,
        encode_shuffled(
            &con,
            n_frames as u64,
            n_atoms as u64,
            [20.0, 20.0, 20.0, 90.0, 90.0, 90.0],
            3,
        )
        .unwrap(),
    )
    .unwrap();
    let side = side_for(N_MILLION) as f64;
    fs::write(
        &shuffle_million,
        encode_shuffled(
            &million,
            m_frames as u64,
            m_atoms as u64,
            [side, side, side, 90.0, 90.0, 90.0],
            3,
        )
        .unwrap(),
    )
    .unwrap();
    let zstd_con = scratch.join("frames.con.zst");
    let zstd_convel = scratch.join("frames.convel.zst");
    let zstd_million = scratch.join("million.con.zst");
    write_zstd(&inputs.con, &zstd_con);
    write_zstd(&inputs.convel, &zstd_convel);
    write_zstd(&inputs.million, &zstd_million);
    eprintln!("  dictionary");
    let dict_frames_con = scratch.join("con.rcdict");
    let dict_whole_con = scratch.join("con.rczdct");
    let dict_frames_convel = scratch.join("convel.rcdict");
    write_dict(&inputs.con, &dict_frames_con, &dict_whole_con, &mut notes);
    write_dict_frames_only(&inputs.convel, &dict_frames_convel, &mut notes);
    eprintln!("  low rank");
    let (low_loose, low_tight) = write_lowrank(&con, n_frames, n_atoms, scratch, &mut notes);
    for path in [
        &raw_con,
        &raw_million,
        &shuffle_con,
        &shuffle_million,
        &zstd_con,
        &zstd_convel,
        &zstd_million,
        &dict_frames_con,
        &dict_whole_con,
        &dict_frames_convel,
    ] {
        sizes.push((
            path.file_name().unwrap().to_string_lossy().into_owned(),
            fs::metadata(path).unwrap().len(),
        ));
    }
    if let Some(path) = &low_loose {
        sizes.push(("lowrank-1e-3".into(), fs::metadata(path).unwrap().len()));
    }
    if let Some(path) = &low_tight {
        sizes.push(("lowrank-1e-8".into(), fs::metadata(path).unwrap().len()));
    }
    Prepared {
        shuffle_con,
        shuffle_million,
        raw_con,
        raw_million,
        zstd_con,
        zstd_convel,
        zstd_million,
        dict_frames_con,
        dict_whole_con,
        dict_frames_convel,
        low_loose,
        low_tight,
        notes,
        sizes,
    }
}

fn write_f64(path: &Path, values: &[f64]) {
    let mut file = BufWriter::new(File::create(path).unwrap());
    for value in values {
        file.write_all(&value.to_le_bytes()).unwrap();
    }
}

fn write_zstd(src: &Path, dest: &Path) {
    let bytes = fs::read(src).unwrap();
    fs::write(dest, compress_zstd(&bytes, 3).unwrap()).unwrap();
}

fn write_dict(src: &Path, frames_out: &Path, whole_out: &Path, notes: &mut Vec<String>) {
    let text = fs::read(src).unwrap();
    let parsed = positions_from_con_bytes(&text).unwrap();
    let samples: Vec<&[u8]> = parsed
        .spans
        .iter()
        .map(|span| &text[span.start..span.end])
        .collect();
    match encode_dict_frames(&samples, 3, 16 * 1024, 200) {
        Ok(bytes) => {
            notes.push(format!(
                "dict-frames {} bytes {} samples {}",
                src.display(),
                bytes.len(),
                samples.len()
            ));
            fs::write(frames_out, bytes).unwrap();
        }
        Err(err) => notes.push(format!("dict-frames failed: {err}")),
    }
    match encode_dict_whole(&text, &samples, 3, 16 * 1024, 200) {
        Ok(bytes) => {
            notes.push(format!(
                "dict-whole {} bytes {}",
                src.display(),
                bytes.len()
            ));
            fs::write(whole_out, bytes).unwrap();
        }
        Err(err) => notes.push(format!("dict-whole failed: {err}")),
    }
}

fn write_dict_frames_only(src: &Path, frames_out: &Path, notes: &mut Vec<String>) {
    let text = fs::read(src).unwrap();
    let parsed = positions_from_con_bytes(&text).unwrap();
    let samples: Vec<&[u8]> = parsed
        .spans
        .iter()
        .map(|span| &text[span.start..span.end])
        .collect();
    match encode_dict_frames(&samples, 3, 16 * 1024, 200) {
        Ok(bytes) => {
            notes.push(format!(
                "dict-frames {} bytes {}",
                src.display(),
                bytes.len()
            ));
            fs::write(frames_out, bytes).unwrap();
        }
        Err(err) => notes.push(format!("dict-frames convel failed: {err}")),
    }
}

fn write_lowrank(
    values: &[f64],
    n_frames: usize,
    n_atoms: usize,
    scratch: &Path,
    notes: &mut Vec<String>,
) -> (Option<PathBuf>, Option<PathBuf>) {
    let mut loose = None;
    let mut tight = None;
    for (label, bound) in [("1e-3", 1e-3), ("1e-8", 1e-8)] {
        match fit_positions(values, n_frames, n_atoms, bound) {
            Ok(fit) => {
                let path = scratch.join(format!("con.lowrank-{label}"));
                fs::write(&path, &fit.bytes).unwrap();
                let curve: Vec<String> = fit
                    .err_at_rank
                    .iter()
                    .filter(|(rank, _)| {
                        *rank == 1 || rank.is_power_of_two() || *rank == fit.err_at_rank.len()
                    })
                    .map(|(rank, err)| format!("{rank}:{err:.3e}"))
                    .collect();
                notes.push(format!(
                    "lowrank bound {bound} rank {} met {} achieved {:.3e} tt_r2 {:?} tt_bytes {:?} file {} curve {}",
                    fit.rank,
                    fit.met_bound,
                    fit.achieved_max_abs,
                    fit.tt_r2,
                    fit.tt_bytes,
                    fit.bytes.len(),
                    curve.join(",")
                ));
                if label == "1e-3" {
                    loose = Some(path);
                } else {
                    tight = Some(path);
                }
            }
            Err(err) => notes.push(format!("lowrank {bound} skipped: {err}")),
        }
    }
    (loose, tight)
}

fn rss_child(spec: &Arm) -> Rss {
    let exe = env::current_exe().unwrap();
    let output = Command::new(exe)
        .args(["rss", &spec.kind, &spec.path.to_string_lossy()])
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .output()
        .unwrap();
    if !output.status.success() {
        panic!("{} rss exited {}", spec.name, output.status);
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let line = text.lines().last().unwrap_or("");
    let hwm_kib = json_u64(line, "hwm_kib");
    let file_bytes = json_u64(line, "file_bytes");
    Rss {
        name: spec.name.clone(),
        hwm_kib,
        file_bytes,
        over_input_kib: hwm_kib as i64 - (file_bytes / 1024) as i64,
    }
}

fn rss_main(kind: &str, path: &Path) {
    let file_bytes = fs::metadata(path).unwrap().len();
    let n = run_kind(kind, path).unwrap();
    let hwm_kib = vm_kib("VmHWM:");
    println!("{{\"hwm_kib\":{hwm_kib},\"file_bytes\":{file_bytes},\"n\":{n}}}");
}

fn json_u64(line: &str, key: &str) -> u64 {
    let needle = format!("\"{key}\":");
    let at = line
        .find(&needle)
        .unwrap_or_else(|| panic!("missing {key} in {line}"));
    let rest = &line[at + needle.len()..];
    let end = rest.find([',', '}']).unwrap_or(rest.len());
    rest[..end].trim().parse().unwrap()
}

fn vm_kib(key: &str) -> u64 {
    let text = fs::read_to_string("/proc/self/status").unwrap_or_default();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix(key) {
            return rest
                .split_whitespace()
                .next()
                .unwrap_or("0")
                .parse()
                .unwrap_or(0);
        }
    }
    0
}

fn float_report(path: &Path) -> readcon_core::scout::FloatReport {
    let contents = read_file_contents(path).unwrap();
    bench_float_kernels(contents.as_bytes(), 3_000_000)
}

struct MassifRow {
    name: String,
    peak_bytes: Option<u64>,
    file_bytes: u64,
    note: String,
}

fn massif_sample(inputs: &Inputs, prepared: &Prepared, scratch: &Path) -> Vec<MassifRow> {
    if Command::new("valgrind").arg("--version").output().is_err() {
        return vec![MassifRow {
            name: "valgrind".into(),
            peak_bytes: None,
            file_bytes: 0,
            note: "valgrind is not installed".into(),
        }];
    }
    let jobs = [
        ("readcon-positions-con", "positions", inputs.con.clone()),
        ("column-con", "column-con", inputs.con.clone()),
        ("shuffle-con", "shuffle", prepared.shuffle_con.clone()),
        (
            "readcon-positions-million",
            "positions",
            inputs.million.clone(),
        ),
        ("column-million", "column-con", inputs.million.clone()),
        (
            "shuffle-million",
            "shuffle",
            prepared.shuffle_million.clone(),
        ),
    ];
    let mut rows = Vec::new();
    for (name, kind, path) in jobs {
        eprintln!("  massif {name}");
        let out = scratch.join(format!("{name}.massif"));
        let exe = env::current_exe().unwrap();
        let status = Command::new("timeout")
            .args(["180", "valgrind", "--tool=massif", "--pages-as-heap=yes"])
            .arg(format!("--massif-out-file={}", out.display()))
            .arg(exe)
            .args(["rss", kind, &path.to_string_lossy()])
            .status();
        let peak = match status {
            Ok(code) if code.success() => massif_peak(&out),
            Ok(code) => {
                rows.push(MassifRow {
                    name: name.into(),
                    peak_bytes: None,
                    file_bytes: fs::metadata(&path).map(|m| m.len()).unwrap_or(0),
                    note: format!("exit {code}"),
                });
                continue;
            }
            Err(err) => {
                rows.push(MassifRow {
                    name: name.into(),
                    peak_bytes: None,
                    file_bytes: 0,
                    note: err.to_string(),
                });
                continue;
            }
        };
        rows.push(MassifRow {
            name: name.into(),
            peak_bytes: peak,
            file_bytes: fs::metadata(&path).map(|m| m.len()).unwrap_or(0),
            note: if peak.is_some() {
                "pages-as-heap".into()
            } else {
                "massif output had no peak".into()
            },
        });
    }
    rows
}

fn massif_peak(path: &Path) -> Option<u64> {
    let text = fs::read_to_string(path).ok()?;
    let mut peak = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("mem_heap_B=") {
            if let Ok(value) = rest.parse::<u64>() {
                peak = Some(peak.unwrap_or(0).max(value));
            }
        }
    }
    peak
}

fn ensure_inputs(root: &Path) -> Inputs {
    let parallel = root.join("bench/h2h/work/parallel-frames");
    let inputs = Inputs {
        con: parallel.join("frames-32x100000.con"),
        convel: parallel.join("frames-32x100000.convel"),
        extxyz: parallel.join("copper-32x100000.extxyz"),
        million: root.join("bench/h2h/work/inputs/con-1000000x1.con"),
    };
    fs::create_dir_all(&parallel).unwrap();
    fs::create_dir_all(inputs.million.parent().unwrap()).unwrap();
    if !(inputs.con.is_file()
        && inputs.convel.is_file()
        && inputs.extxyz.is_file()
        && fs::metadata(&inputs.con)
            .map(|m| m.len() > 1_000_000)
            .unwrap_or(false))
    {
        eprintln!("writing 100000-frame inputs");
        write_trajectory(&inputs);
    }
    if fs::metadata(&inputs.million)
        .map(|m| m.len() < 1_000_000)
        .unwrap_or(true)
    {
        eprintln!("writing million-atom CON");
        write_million(&inputs.million);
    }
    inputs
}

fn write_trajectory(inputs: &Inputs) {
    let header = format!(
        "{{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}}}}\n20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n{N_ATOMS}\n63.546\nCu\nCoordinates of Component 1\n"
    );
    let vel_header = format!(
        "grid\n{{\"con_spec_version\":2}}\n20.0 20.0 20.0\n90.0 90.0 90.0\n0 0\n0 0 0\n1\n{N_ATOMS}\n63.546\nCu\nCoordinates of Component 1\n"
    );
    let lattice = "Lattice=\"20.0 0.0 0.0 0.0 20.0 0.0 0.0 0.0 20.0\" Properties=species:S:1:pos:R:3 pbc=\"T T T\"";
    let mut con = BufWriter::new(File::create(&inputs.con).unwrap());
    let mut vel = BufWriter::new(File::create(&inputs.convel).unwrap());
    let mut xyz = BufWriter::new(File::create(&inputs.extxyz).unwrap());
    for frame in 0..N_FRAMES {
        con.write_all(b"\n").unwrap();
        con.write_all(header.as_bytes()).unwrap();
        vel.write_all(vel_header.as_bytes()).unwrap();
        xyz.write_all(format!("{N_ATOMS}\n{lattice}\n").as_bytes())
            .unwrap();
        for atom in 0..N_ATOMS {
            let x = coord(frame, atom, 0);
            let y = coord(frame, atom, 1);
            let z = coord(frame, atom, 2);
            writeln!(con, "{x:.8} {y:.8} {z:.8} 0 {atom}").unwrap();
            writeln!(vel, "{x:.8} {y:.8} {z:.8} 0 {atom}").unwrap();
            writeln!(xyz, "Cu {x:.8} {y:.8} {z:.8}").unwrap();
        }
        writeln!(vel, "\nCu\nVelocities of Component 1").unwrap();
        for atom in 0..N_ATOMS {
            let vx = (atom + 1) as f64 * 1.0e-4;
            writeln!(vel, "{vx:.8} 0.00020000 -0.00010000 0 {atom}").unwrap();
        }
        if frame % 20_000 == 19_999 {
            eprintln!("  wrote {} frames", frame + 1);
        }
    }
    con.write_all(b"\n").unwrap();
}

fn write_million(path: &Path) {
    let side = side_for(N_MILLION);
    let span = side as f64;
    let mut file = BufWriter::new(File::create(path).unwrap());
    writeln!(file, "grid").unwrap();
    writeln!(file, "{{\"con_spec_version\":2}}").unwrap();
    writeln!(file, "{span:.6} {span:.6} {span:.6}").unwrap();
    writeln!(file, "90.000000 90.000000 90.000000").unwrap();
    writeln!(file, "0 0").unwrap();
    writeln!(file, "0 0").unwrap();
    writeln!(file, "1").unwrap();
    writeln!(file, "{N_MILLION}").unwrap();
    writeln!(file, "63.546000").unwrap();
    writeln!(file, "Cu").unwrap();
    writeln!(file, "Coordinates of Component 1").unwrap();
    let mut written = 0usize;
    for z in 0..side {
        for y in 0..side {
            for x in 0..side {
                if written >= N_MILLION {
                    return;
                }
                writeln!(
                    file,
                    " {x:.6} {y:.6} {z:.6} 0 {written}",
                    x = x as f64,
                    y = y as f64,
                    z = z as f64
                )
                .unwrap();
                written += 1;
            }
        }
    }
}

fn coord(frame: usize, atom: usize, axis: usize) -> f64 {
    let value = ((frame as f64 * 17.0 + atom as f64 * 3.0 + axis as f64) % 10000.0) / 1000.0;
    (value * 1e8).round() / 1e8
}

fn side_for(n_atoms: usize) -> usize {
    let mut side = 1usize;
    while side.saturating_mul(side).saturating_mul(side) < n_atoms {
        side += 1;
    }
    side
}

fn ensure_pinned() {
    if pinned_to_cpu0() {
        return;
    }
    let exe = env::current_exe().unwrap();
    let status = Command::new("taskset")
        .arg("-c")
        .arg("0")
        .arg(exe)
        .args(env::args().skip(1))
        .status()
        .expect("taskset");
    std::process::exit(status.code().unwrap_or(1));
}

fn pinned_to_cpu0() -> bool {
    let text = fs::read_to_string("/proc/self/status").unwrap_or_default();
    text.lines().any(|line| {
        line.starts_with("Cpus_allowed_list:") && line.split(':').nth(1).unwrap_or("").trim() == "0"
    })
}

fn hardware_line() -> String {
    let mut model = "unknown".to_string();
    if let Ok(text) = fs::read_to_string("/proc/cpuinfo") {
        for line in text.lines() {
            if line.to_ascii_lowercase().starts_with("model name") {
                model = line.split(':').nth(1).unwrap_or("").trim().to_string();
                break;
            }
        }
    }
    model = model.replace("(R)", "").replace("(TM)", "");
    let memory = fs::read_to_string("/proc/meminfo")
        .unwrap_or_default()
        .lines()
        .find_map(|line| line.strip_prefix("MemTotal:"))
        .and_then(|rest| rest.split_whitespace().next().map(|n| n.to_string()))
        .unwrap_or_else(|| "0".into());
    format!(
        "hardware {} uname_m {} nproc {} memory_kib {}",
        model.split_whitespace().collect::<Vec<_>>().join(" "),
        env::consts::ARCH,
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(0),
        memory
    )
}

fn write_outputs(
    root: &Path,
    log_dir: &Path,
    prepared: &Prepared,
    checks: &[Check],
    timed: &[Timed],
    rss: &[Rss],
) {
    let mut body = String::new();
    body.push_str(&hardware_line());
    body.push('\n');
    body.push_str("pinned taskset -c 0\n");
    body.push_str("warmup 1\n");
    body.push_str("samples 6\n");
    body.push_str("quantile type 7\n");
    for note in &prepared.notes {
        body.push_str(note);
        body.push('\n');
    }
    for (name, bytes) in &prepared.sizes {
        body.push_str(&format!("size {name} {bytes}\n"));
    }
    for row in checks {
        body.push_str(&format!(
            "check {} bit_exact={} max_abs={:.9e} bound={:?} {}\n",
            row.name, row.bit_exact, row.max_abs, row.bound, row.detail
        ));
    }
    for row in timed {
        let mem = rss.iter().find(|item| item.name == row.name);
        body.push_str(&format!(
            "arm {} median_s={:.9e} iqr_s={:.9e} q25_s={:.9e} q75_s={:.9e} warmup_s={:.9e} n={} samples={:?}\n",
            row.name, row.median_s, row.iqr_s, row.q25_s, row.q75_s, row.warmup_s, row.n, row.samples
        ));
        if let Some(mem) = mem {
            body.push_str(&format!(
                "rss {} hwm_kib={} file_bytes={} over_input_kib={}\n",
                mem.name, mem.hwm_kib, mem.file_bytes, mem.over_input_kib
            ));
        }
    }
    fs::write(log_dir.join("campaign.log"), &body).unwrap();
    let mut json = String::from("{\n");
    json.push_str(&format!(
        "  \"hardware\": \"{}\",\n",
        escape(&hardware_line())
    ));
    json.push_str("  \"sizes\": [\n");
    for (index, (name, bytes)) in prepared.sizes.iter().enumerate() {
        let comma = if index + 1 == prepared.sizes.len() {
            ""
        } else {
            ","
        };
        json.push_str(&format!(
            "    {{\"name\": \"{name}\", \"bytes\": {bytes}}}{comma}\n"
        ));
    }
    json.push_str("  ],\n  \"checks\": [\n");
    for (index, row) in checks.iter().enumerate() {
        let comma = if index + 1 == checks.len() { "" } else { "," };
        json.push_str(&format!(
            "    {{\"name\": \"{}\", \"bit_exact\": {}, \"max_abs\": {:.9e}, \"bound\": {}, \"detail\": \"{}\"}}{comma}\n",
            row.name,
            row.bit_exact,
            row.max_abs,
            row.bound
                .map(|v| format!("{v:.9e}"))
                .unwrap_or_else(|| "null".into()),
            escape(&row.detail)
        ));
    }
    json.push_str("  ],\n  \"timed\": [\n");
    for (index, row) in timed.iter().enumerate() {
        let comma = if index + 1 == timed.len() { "" } else { "," };
        let samples: Vec<String> = row.samples.iter().map(|v| format!("{v:.9e}")).collect();
        let mem = rss.iter().find(|item| item.name == row.name);
        json.push_str(&format!(
            "    {{\"name\": \"{}\", \"median_s\": {:.9e}, \"iqr_s\": {:.9e}, \"q25_s\": {:.9e}, \"q75_s\": {:.9e}, \"warmup_s\": {:.9e}, \"n\": {}, \"samples\": [{}], \"hwm_kib\": {}, \"file_bytes\": {}, \"over_input_kib\": {}}}{comma}\n",
            row.name,
            row.median_s,
            row.iqr_s,
            row.q25_s,
            row.q75_s,
            row.warmup_s,
            row.n,
            samples.join(", "),
            mem.map(|m| m.hwm_kib.to_string()).unwrap_or_else(|| "null".into()),
            mem.map(|m| m.file_bytes.to_string()).unwrap_or_else(|| "null".into()),
            mem.map(|m| m.over_input_kib.to_string()).unwrap_or_else(|| "null".into())
        ));
    }
    json.push_str("  ],\n  \"notes\": [\n");
    for (index, note) in prepared.notes.iter().enumerate() {
        let comma = if index + 1 == prepared.notes.len() {
            ""
        } else {
            ","
        };
        json.push_str(&format!("    \"{}\"{comma}\n", escape(note)));
    }
    json.push_str("  ]\n}\n");
    fs::create_dir_all(root.join("bench/h2h/scout")).unwrap();
    fs::write(root.join("bench/h2h/scout/results.json"), json).unwrap();
    fs::write(log_dir.join("campaign.log"), body).unwrap();
}

fn write_floats(log_dir: &Path, report: &readcon_core::scout::FloatReport) {
    let med_dec = type7(&report.fast_dec_s, 0.5);
    let iqr_dec = type7(&report.fast_dec_s, 0.75) - type7(&report.fast_dec_s, 0.25);
    let med_ff = type7(&report.fast_float_s, 0.5);
    let iqr_ff = type7(&report.fast_float_s, 0.75) - type7(&report.fast_float_s, 0.25);
    let text = format!(
        "numbers {}\nfallbacks {}\nmismatches {}\nfast_dec median_s={med_dec:.9e} iqr_s={iqr_dec:.9e} samples={:?}\nfast_float median_s={med_ff:.9e} iqr_s={iqr_ff:.9e} samples={:?}\n",
        report.n_numbers,
        report.fallbacks,
        report.mismatches,
        report.fast_dec_s,
        report.fast_float_s
    );
    fs::write(log_dir.join("float-kernels.log"), text).unwrap();
}

fn write_massif(log_dir: &Path, rows: &[MassifRow]) {
    let mut text = String::new();
    for row in rows {
        text.push_str(&format!(
            "{} peak_bytes={:?} file_bytes={} over_input_bytes={:?} {}\n",
            row.name,
            row.peak_bytes,
            row.file_bytes,
            row.peak_bytes
                .map(|peak| peak as i64 - row.file_bytes as i64),
            row.note
        ));
    }
    fs::write(log_dir.join("massif.log"), text).unwrap();
}

fn escape(text: &str) -> String {
    text.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Size and decode time for one thermal CON trajectory.
///
/// Arms: the CON text, gzip of that text, zstd of that text, shuffle+zstd of
/// the parsed f64 column, and plain zstd of the same column. Checks are
/// bit-exact before the clock.
fn thermal() {
    ensure_pinned();
    let path = PathBuf::from(env::args().nth(2).expect("thermal CON path"));
    let scratch = path.parent().unwrap().join("codecs");
    fs::create_dir_all(&scratch).unwrap();
    let text = fs::read(&path).unwrap();
    let authority = read_positions_with_threads(&path, Some(1)).unwrap();
    let parsed = positions_from_con_bytes(&text).unwrap();
    assert_eq!(parsed.positions.len(), authority.values.len());
    for (got, expect) in parsed.positions.iter().zip(&authority.values) {
        assert_eq!(got.to_bits(), expect.to_bits());
    }
    let gz_path = scratch.join("thermal.con.gz");
    {
        use std::io::Write as _;
        let mut encoder = flate2::write::GzEncoder::new(
            File::create(&gz_path).unwrap(),
            flate2::Compression::new(6),
        );
        encoder.write_all(&text).unwrap();
        encoder.finish().unwrap();
    }
    let zst_path = scratch.join("thermal.con.zst");
    fs::write(&zst_path, compress_zstd(&text, 3).unwrap()).unwrap();
    let shuffle_path = scratch.join("thermal.rcshuf");
    let n_atoms = authority.n_atoms as u64;
    fs::write(
        &shuffle_path,
        encode_shuffled(
            &authority.values,
            authority.n_frames as u64,
            n_atoms,
            [0.0; 6],
            3,
        )
        .unwrap(),
    )
    .unwrap();
    let raw: Vec<u8> = authority
        .values
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect();
    let fzstd_path = scratch.join("thermal.f64.zst");
    fs::write(&fzstd_path, compress_zstd(&raw, 3).unwrap()).unwrap();
    let gz_back = {
        use std::io::Read;
        let mut decoder = flate2::read::GzDecoder::new(File::open(&gz_path).unwrap());
        let mut buf = Vec::new();
        decoder.read_to_end(&mut buf).unwrap();
        buf
    };
    assert_eq!(gz_back, text, "gzip round trip");
    let zst_back = zstd::bulk::decompress(&fs::read(&zst_path).unwrap(), text.len()).unwrap();
    assert_eq!(zst_back, text, "zstd text round trip");
    let (shuffled, _, _, _) = decode_shuffled(&fs::read(&shuffle_path).unwrap()).unwrap();
    for (got, expect) in shuffled.iter().zip(&authority.values) {
        assert_eq!(got.to_bits(), expect.to_bits());
    }
    let fz = zstd::bulk::decompress(&fs::read(&fzstd_path).unwrap(), raw.len()).unwrap();
    assert_eq!(fz, raw, "plain f64 zstd round trip");
    let arms = [
        arm("thermal-text", "positions", &path),
        arm("thermal-gzip", "gzip-positions", &gz_path),
        arm("thermal-zstd", "zstd-positions", &zst_path),
        arm("thermal-shuffle", "shuffle", &shuffle_path),
        arm("thermal-f64-zstd", "fzstd", &fzstd_path),
    ];
    println!(
        "thermal-check bit_exact=yes frames={} atoms={}",
        authority.n_frames, authority.n_atoms
    );
    for spec in &arms {
        let timed = time_arm(spec);
        let mem = rss_child(spec);
        println!(
            "arm {} bytes={} median_s={:.9e} iqr_s={:.9e} q25_s={:.9e} q75_s={:.9e} warmup_s={:.9e} hwm_kib={} over_input_kib={} samples={:?}",
            spec.name,
            mem.file_bytes,
            timed.median_s,
            timed.iqr_s,
            timed.q25_s,
            timed.q75_s,
            timed.warmup_s,
            mem.hwm_kib,
            mem.over_input_kib,
            timed.samples
        );
    }
}
