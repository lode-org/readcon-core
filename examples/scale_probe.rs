//! Release timings for the publication ladder.
//!
//! `scale_probe pos|fmt PATH threads` prints one median line and the samples.

use std::time::Instant;

fn median(samples: &[f64]) -> f64 {
    let mut ordered = samples.to_vec();
    ordered.sort_by(|left, right| left.partial_cmp(right).unwrap());
    let mid = ordered.len() / 2;
    if ordered.len().is_multiple_of(2) {
        (ordered[mid - 1] + ordered[mid]) / 2.0
    } else {
        ordered[mid]
    }
}

fn time_it(repeats: usize, mut body: impl FnMut()) -> Vec<f64> {
    body();
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        body();
        samples.push(started.elapsed().as_secs_f64());
    }
    samples
}

/// One warmup, then `repeats` samples. Both are printed, one line each.
fn time_logged(label: &str, repeats: usize, mut body: impl FnMut()) -> Vec<f64> {
    let started = Instant::now();
    body();
    println!("warmup {:.9}", started.elapsed().as_secs_f64());
    let mut samples = Vec::with_capacity(repeats);
    for _ in 0..repeats {
        let started = Instant::now();
        body();
        let elapsed = started.elapsed().as_secs_f64();
        samples.push(elapsed);
        println!("{label} {elapsed:.9}");
    }
    samples
}

fn main() {
    let mut args = std::env::args().skip(1);
    let which = args.next().unwrap_or_else(|| "pos".into());
    let path = args.next().expect("path");
    if which == "mkvel" {
        let dest = args.next().expect("dest");
        let text = std::fs::read_to_string(&path).unwrap();
        let mut frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
        let frame = &mut frames[0];
        for (index, atom) in frame.atom_data.iter_mut().enumerate() {
            atom.set_velocity(Some([0.01, -0.02, (index as f64) * 0.001]));
        }
        let refs = vec![&frames[0]];
        readcon_core::writer::write_frame_refs_to_path(
            std::path::Path::new(&dest),
            &refs,
            1,
            None,
            false,
            true,
        )
        .unwrap();
        println!("mkvel bytes={}", std::fs::metadata(&dest).unwrap().len());
        return;
    }
    let workers: usize = args.next().unwrap_or_else(|| "1".into()).parse().unwrap();
    let samples = match which.as_str() {
        "pos" => {
            let repeats = std::env::var("READCON_PROBE_REPEATS")
                .ok()
                .and_then(|text| text.parse().ok())
                .unwrap_or(12);
            time_logged("read", repeats, || {
                let block = readcon_core::iterators::read_positions_with_threads(
                    std::path::Path::new(&path),
                    Some(workers),
                )
                .unwrap();
                std::hint::black_box(block.values.len());
            })
        }
        "fmt" => {
            let text = std::fs::read_to_string(&path).unwrap();
            let frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
            let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
            let repeats = std::env::var("READCON_PROBE_REPEATS")
                .ok()
                .and_then(|text| text.parse().ok())
                .unwrap_or(6);
            // The file writer formats into per-worker buffers. Ranking
            // formats each frame on its own, which is what an MPI rank does.
            let ranked = std::env::var("READCON_PROBE_FMT").ok().as_deref() == Some("ranked");
            time_logged("fmt", repeats, || {
                if ranked {
                    #[cfg(feature = "mpi")]
                    {
                        let (bytes, starts) =
                            readcon_core::distrib_write::format_frames(&refs, None).unwrap();
                        std::hint::black_box((bytes, starts));
                    }
                    #[cfg(not(feature = "mpi"))]
                    {
                        let _ = &refs;
                        panic!("ranked format needs the mpi feature");
                    }
                } else {
                    let parts = readcon_core::writer::format_frame_refs_unstored(
                        &refs, workers, None, false, true,
                    )
                    .unwrap();
                    std::hint::black_box(parts);
                }
            })
        }
        "write" => {
            let text = std::fs::read_to_string(&path).unwrap();
            let frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
            let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
            let out_owned = std::env::var("READCON_PROBE_OUT")
                .unwrap_or_else(|_| "/dev/shm/r7-rust-write.con".to_string());
            let out = std::path::PathBuf::from(&out_owned);
            let repeats = std::env::var("READCON_PROBE_REPEATS")
                .ok()
                .and_then(|text| text.parse().ok())
                .unwrap_or(6);
            let fsync = std::env::var_os("READCON_PROBE_FSYNC").is_some();
            time_logged("write", repeats, || {
                let _ = std::fs::remove_file(&out);
                readcon_core::writer::write_frame_refs_to_path(
                    &out, &refs, workers, None, false, true,
                )
                .unwrap();
                if fsync {
                    if let Ok(file) = std::fs::File::open(&out) {
                        let _ = file.sync_all();
                    }
                }
            })
        }
        "rewrite" => {
            let text = std::fs::read_to_string(&path).unwrap();
            let frames = readcon_core::iterators::frames_from_text(&text, Some(1)).unwrap();
            let refs: Vec<&readcon_core::types::ConFrame> = frames.iter().collect();
            let out_owned = std::env::var("READCON_PROBE_OUT")
                .unwrap_or_else(|_| "/dev/shm/r7-rust-rewrite.con".to_string());
            let out = std::path::PathBuf::from(&out_owned);
            let repeats = std::env::var("READCON_PROBE_REPEATS")
                .ok()
                .and_then(|text| text.parse().ok())
                .unwrap_or(6);
            // The warmup rewrite allocates the spare. The samples fill it.
            let _ = std::fs::remove_file(&out);
            readcon_core::writer::write_frame_refs_to_path(&out, &refs, workers, None, false, true)
                .unwrap();
            time_logged("rewrite", repeats, || {
                readcon_core::writer::rewrite_frame_refs_to_path(
                    &out, &refs, workers, None, false, true, true,
                )
                .unwrap();
            })
        }
        "floats" => {
            let n = 1_000_000usize;
            let values: Vec<f64> = (0..n).map(|i| (i as f64) * 0.001 + 1.25).collect();
            time_it(6, || {
                let chunk = n.div_ceil(workers.max(1));
                let mut parts: Vec<Vec<u8>> = (0..workers.max(1)).map(|_| Vec::new()).collect();
                if workers < 2 {
                    parts[0].reserve(n * 24);
                    for value in &values {
                        readcon_core::extxyz_scan::append_extxyz_number(&mut parts[0], *value);
                        parts[0].push(b' ');
                    }
                } else {
                    let owned = std::thread::scope(|scope| {
                        let mut handles = Vec::new();
                        for worker in 0..workers.max(1) {
                            let from = worker * chunk;
                            if from >= n {
                                break;
                            }
                            let to = (from + chunk).min(n);
                            let values = &values;
                            handles.push(scope.spawn(move || {
                                let mut part = Vec::with_capacity((to - from) * 24);
                                for value in &values[from..to] {
                                    readcon_core::extxyz_scan::append_extxyz_number(
                                        &mut part, *value,
                                    );
                                    part.push(b' ');
                                }
                                part
                            }));
                        }
                        handles
                            .into_iter()
                            .map(|handle| handle.join().unwrap())
                            .collect::<Vec<_>>()
                    });
                    parts = owned;
                }
                std::hint::black_box(parts.iter().map(|part| part.len()).sum::<usize>());
            })
        }
        "xfmt" => {
            let bytes = std::fs::read(&path).unwrap();
            let tables =
                readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads(&bytes, 1)
                    .unwrap();
            let symbols = if let Some(symbol) = &tables.uniform_species {
                vec![symbol.clone(); tables.n_frames * tables.n_atoms]
            } else if !tables.species_ids.is_empty() {
                tables
                    .species_ids
                    .iter()
                    .map(|id| tables.species_pool[*id as usize].clone())
                    .collect()
            } else {
                tables.species.clone()
            };
            let mut columns = tables.columns;
            if let Some(column) = columns.iter_mut().find(|column| column.name == "species") {
                column.text = symbols;
            }
            if let Some(column) = columns.iter_mut().find(|column| column.name == "pos") {
                column.real.clone_from(&tables.positions);
            }
            if let Some(column) = columns.iter_mut().find(|column| column.name == "masses") {
                column.real.clone_from(&tables.masses);
            }
            let sources: Vec<&(dyn readcon_core::extxyz_scan::ExtxyzSource + Sync)> = columns
                .iter()
                .map(|column| column as &(dyn readcon_core::extxyz_scan::ExtxyzSource + Sync))
                .collect();
            time_it(6, || {
                let out = readcon_core::extxyz_scan::extxyz_bytes_with_threads(
                    tables.n_frames,
                    tables.n_atoms,
                    &tables.cell,
                    &sources,
                    workers,
                )
                .unwrap();
                std::hint::black_box(out.len());
            })
        }
        "xyz" => {
            let bytes = std::fs::read(&path).unwrap();
            time_it(6, || {
                let tables = readcon_core::extxyz_scan::tables_from_extxyz_bytes_with_threads(
                    &bytes, workers,
                )
                .unwrap();
                std::hint::black_box(tables.positions.len());
            })
        }
        other => {
            eprintln!("unknown {other}");
            std::process::exit(2);
        }
    };
    let text = samples
        .iter()
        .map(|sample| format!("{sample:.6}"))
        .collect::<Vec<_>>()
        .join(",");
    println!(
        "kind={which} workers={workers} median={:.6} samples={text}",
        median(&samples)
    );
}
