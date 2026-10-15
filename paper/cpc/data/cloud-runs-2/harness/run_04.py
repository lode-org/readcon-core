#!/usr/bin/env python3
"""MPI strong and weak scaling for readcon-core and readcon-db.

Cold repeats drop the page cache first. Warm repeats follow one untimed
warmup and do not drop the cache. Times are the harness timings
(distributed read, collective write, MPI ingest), not the serial reference
that the same process runs afterwards.
"""
from __future__ import annotations

import json, os, re, shutil, statistics, subprocess, sys, time
from pathlib import Path

ROOT = Path("/tmp/campaign")
DATA = Path("/var/tmp/mpi-campaign")
OUT = Path("/workspace/paper/cpc/data/cloud-runs-2/04")
CORE = Path("/tmp/readcon-core-main/target/release/examples")
DB = Path("/tmp/readcon-db/target/release/examples")
READ = CORE / "mpi_read_check"
WRITE = CORE / "mpi_write_check"
INGEST = DB / "mpi_ingest_check"
GEN = Path("/tmp/readcon-db/bench/gen_con.py")
TINY = Path("/workspace/resources/test/tiny_multi_cuh2.con")
RANKS = [1, 2, 4, 8]
REPS = 5
COPIES = 4

ENV = os.environ.copy()
ENV["PATH"] = "/opt/mpich-4.2.3/bin:" + ENV.get("PATH", "")
ENV["LD_LIBRARY_PATH"] = "/opt/mpich-4.2.3/lib:" + ENV.get("LD_LIBRARY_PATH", "")
ENV["UCX_TLS"] = "tcp"
ENV["FI_PROVIDER"] = "tcp"
ENV["RAYON_NUM_THREADS"] = "1"
ENV["OMP_NUM_THREADS"] = "1"


def run(cmd, timeout=1800, env=None):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout, env=env or ENV)
    return p.returncode, p.stdout, p.stderr


def drop_caches():
    subprocess.check_call(["sudo", "-n", "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"])


def repeat_file(src: Path, n_copies: int, dest: Path):
    raw = src.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunk_n = 20000
    chunk = raw * chunk_n
    full, rem = divmod(n_copies, chunk_n)
    with dest.open("wb") as fh:
        for _ in range(full):
            fh.write(chunk)
        if rem:
            fh.write(raw * rem)
    return dest.stat().st_size


def parse_core(text: str):
    line = [ln for ln in text.splitlines() if "identical=" in ln]
    if not line:
        raise RuntimeError("no timing line:\n" + text[-2000:])
    last = line[-1]
    mm = re.search(r"frames=(\d+)", last)
    tm = re.search(r"(?:distributed_ms|write_ms)=([0-9.]+)", last)
    ident = re.search(r"identical=(true|false)", last)
    if not (mm and tm and ident):
        raise RuntimeError("unparsed: " + last)
    return int(mm.group(1)), float(tm.group(1)) / 1000.0, ident.group(1) == "true", last


def parse_db(text: str):
    line = [ln for ln in text.splitlines() if "match=" in ln]
    if not line:
        raise RuntimeError("no timing line:\n" + text[-2000:])
    last = line[-1]
    mm = re.search(r"frames=(\d+)", last)
    tm = re.search(r"mpi_s=([0-9.]+)", last)
    ident = re.search(r"match=(true|false)", last)
    if not (mm and tm and ident):
        raise RuntimeError("unparsed: " + last)
    return int(mm.group(1)), float(tm.group(1)), ident.group(1) == "true", last


def launch(n, args, tag, logdir):
    cmd = ["mpiexec", "-bind-to", "core", "-n", str(n), *args]
    code, out, err = run(cmd)
    (logdir / f"{tag}.out").write_text(out)
    (logdir / f"{tag}.err").write_text(err)
    (logdir / f"{tag}.cmd").write_text(" ".join(cmd) + f"\nexit={code}\n")
    if code != 0:
        raise RuntimeError(f"exit {code}\n{out[-1500:]}\n{err[-1500:]}")
    return out


def summarise(samples):
    xs = sorted(s["seconds"] for s in samples)
    return xs[len(xs) // 2], xs[0], xs[-1], all(s["sha_match"] for s in samples)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logdir = OUT / "logs"
    logdir.mkdir(exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    host = []
    for cmd in (["lscpu"], ["nproc"], ["free", "-g"], ["uname", "-a"],
                ["findmnt", "-T", "/", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
                ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,TRAN,ROTA,MODEL"]):
        host.append("$ " + " ".join(cmd))
        c, o, e = run(cmd, env=os.environ.copy())
        host.append(o or e)
    c, o, e = run(["/opt/mpich-4.2.3/bin/mpicc", "-v"], env=ENV)
    host.append("$ mpicc -v\n" + (e or o))
    c, o, e = run(["/opt/mpich-4.2.3/bin/mpiexec", "-n", "1", "true"], env=ENV)
    host.append("mpiexec smoke exit " + str(c) + "\n" + e)
    core_sha = subprocess.check_output(["git", "-C", "/tmp/readcon-core-main", "rev-parse", "HEAD"], text=True).strip()
    db_sha = subprocess.check_output(["git", "-C", "/tmp/readcon-db", "rev-parse", "HEAD"], text=True).strip()
    host.append(f"readcon-core origin/main {core_sha}\nreadcon-db main {db_sha}\n")
    host.append("FI_PROVIDER=tcp UCX_TLS=tcp RAYON_NUM_THREADS=1 mpiexec -bind-to core\n")
    host.append("Host has 8 cores and 47 GB RAM, virtio ext4, not the 16-core 64 GB NVMe box in the spec. Ranks stop at 8.\n")
    (OUT / "host.txt").write_text("".join(host))

    # Files. tiny_multi_cuh2.con is 678 bytes and 2 frames.
    # 1,583,691 copies = 3,167,382 frames = 1,073,742,498 bytes (PR #55).
    strong = DATA / "core-strong.con"
    if not strong.exists() or strong.stat().st_size != 1_073_742_498:
        print("writing core strong file", flush=True)
        n = repeat_file(TINY, 1_583_691, strong)
        assert n == 1_073_742_498, n
    weak_files = {}
    for p in RANKS:
        copies = 200_000 * p  # 400,000 frames per rank, 2 frames per copy
        path = DATA / f"core-weak-r{p}.con"
        expect = copies * 678
        if not path.exists() or path.stat().st_size != expect:
            print(f"writing core weak r={p}", flush=True)
            n = repeat_file(TINY, copies, path)
            assert n == expect, n
        weak_files[p] = path
    db_strong = DATA / "db-strong.con"
    if not db_strong.exists():
        print("writing db strong file", flush=True)
        subprocess.check_call(["/tmp/benchenv/bin/python", str(GEN), str(db_strong), "30965", "1000"], env=ENV)
    db_weak = {}
    for p in RANKS:
        path = DATA / f"db-weak-r{p}.con"
        frames = 7700 * p
        if not path.exists():
            print(f"writing db weak r={p} frames={frames}", flush=True)
            subprocess.check_call(["/tmp/benchenv/bin/python", str(GEN), str(path), str(frames), "1000"], env=ENV)
        db_weak[p] = path
    print("db strong bytes", db_strong.stat().st_size, flush=True)

    jobs = []
    # core strong
    for mode in ("shared", "scatter"):
        for p in RANKS:
            jobs.append(dict(system="readcon-core", operation="read", mode=mode, ranks=p,
                             path=strong, kind="read"))
    for mode in ("mpiio", "gather"):
        for p in RANKS:
            jobs.append(dict(system="readcon-core", operation="write", mode=mode, ranks=p,
                             path=strong, kind="write"))
    # core weak
    for mode in ("shared", "scatter"):
        for p in RANKS:
            jobs.append(dict(system="readcon-core", operation="read", mode=mode, ranks=p,
                             path=weak_files[p], kind="read", weak=True))
    for mode in ("mpiio", "gather"):
        for p in RANKS:
            jobs.append(dict(system="readcon-core", operation="write", mode=mode, ranks=p,
                             path=weak_files[p], kind="write", weak=True))
    for mode in ("single", "sharded"):
        for p in RANKS:
            jobs.append(dict(system="readcon-db", operation="ingest", mode=mode, ranks=p,
                             path=db_strong, kind="ingest"))
    for mode in ("single", "sharded"):
        for p in RANKS:
            jobs.append(dict(system="readcon-db", operation="ingest", mode=mode, ranks=p,
                             path=db_weak[p], kind="ingest", weak=True))

    done_path = OUT / "repeats.jsonl"
    done = {}
    if done_path.exists():
        for line in done_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            # Keys written before the scale field are the strong series only.
            parts = rec["key"].split("|")
            if len(parts) == 6:
                rec["key"] = "|".join(parts[:4] + ["strong"] + parts[4:])
                rec["scale"] = "strong"
            done[rec["key"]] = rec

    def key_of(job, cache, rep):
        scale = "weak" if job.get("weak") else "strong"
        return f"{job['system']}|{job['operation']}|{job['mode']}|{job['ranks']}|{scale}|{cache}|{rep}"

    with done_path.open("a") as sink:
        for job in jobs:
            for cache in ("cold", "warm"):
                have = [r for r in done.get(
                    f"{job['system']}|{job['operation']}|{job['mode']}|{job['ranks']}|{cache}|group", [])]
                # per-repeat keys
                pending = [rep for rep in range(1, REPS + 1) if key_of(job, cache, rep) not in done]
                if not pending:
                    scale = "weak" if job.get("weak") else "strong"
                    print("skip", job["system"], job["mode"], job["ranks"], scale, cache, flush=True)
                    continue
                if cache == "warm":
                    # one untimed warmup so the timed series is hot
                    try:
                        one(job, "warmup", logdir)
                    except Exception as exc:
                        print("warmup failed", exc, flush=True)
                for rep in pending:
                    scale = "weak" if job.get("weak") else "strong"
                    tag = f"{job['system']}-{job['operation']}-{job['mode']}-r{job['ranks']}-{scale}-{cache}-{rep}"
                    print(time.strftime("%H:%M:%S"), tag, flush=True)
                    if cache == "cold":
                        drop_caches()
                    rec = dict(key=key_of(job, cache, rep), system=job["system"], operation=job["operation"],
                               mode=job["mode"], ranks=job["ranks"], scale=scale, cache=cache, rep=rep,
                               bytes_file=job["path"].stat().st_size)
                    try:
                        frames, seconds, match, line = one(job, tag, logdir)
                        rec.update(frames=frames, seconds=seconds, sha_match=match, line=line, error="")
                    except Exception as exc:
                        rec.update(frames=None, seconds=None, sha_match=False, line="", error=str(exc)[:2000])
                        print("FAIL", tag, str(exc)[:400], flush=True)
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    done[rec["key"]] = [rec]

    rows = []
    # regroup
    groups = {}
    for line in done_path.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("rep") is None:
            continue
        g = (rec["system"], rec["operation"], rec["mode"], rec["ranks"], rec["cache"])
        groups.setdefault(g, []).append(rec)
    for g, samples in groups.items():
        system, operation, mode, ranks, cache = g
        ok = [s for s in samples if s.get("seconds") is not None]
        if len(ok) != REPS:
            med = min_s = max_s = ""
            sha = False
        else:
            med, min_s, max_s, sha = summarise(ok)
        frames = next((s["frames"] for s in ok if s.get("frames")), "")
        nbytes = ok[0]["bytes_file"] if ok else ""
        if system == "readcon-db" and nbytes != "":
            nbytes = nbytes * COPIES
        fpr = (frames / ranks) if frames != "" else ""
        rows.append(dict(system=system, operation=operation, mode=mode, ranks=ranks,
                         frames_per_rank=fpr, bytes_total=nbytes, median_s=med, min_s=min_s,
                         max_s=max_s, cache=cache, sha_match=str(sha).lower(),
                         n_ok=len(ok), error=next((s["error"] for s in samples if s.get("error")), "")))
    # split strong/weak by bytes: weak core files differ; tag was not stored.
    # Re-derive from the job list instead.
    write_tables(jobs, done_path)


def one(job, tag, logdir):
    work = DATA / "work" / tag
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    p = job["ranks"]
    try:
        if job["kind"] == "read":
            out = launch(p, [str(READ), str(job["path"]), job["mode"], str(work / "out"), "1"], tag, logdir)
            return parse_core(out)
        if job["kind"] == "write":
            out = launch(p, [str(WRITE), str(job["path"]), str(work / "out"), job["mode"], "1"], tag, logdir)
            return parse_core(out)
        files = [str(job["path"])] * COPIES
        out = launch(p, [str(INGEST), job["mode"], str(work / "db"), "4096", "4", "1", *files], tag, logdir)
        return parse_db(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_tables(jobs, done_path):
    recs = [json.loads(l) for l in done_path.read_text().splitlines() if l.strip()]
    by = {}
    for r in recs:
        parts = r["key"].split("|")
        if len(parts) == 6:
            r["key"] = "|".join(parts[:4] + ["strong"] + parts[4:])
        by[r["key"]] = r
    def rows_for(predicate, name):
        lines = ["system,operation,mode,ranks,frames_per_rank,bytes_total,median_s,min_s,max_s,cache,sha_match"]
        for job in jobs:
            if predicate(job) != name:
                continue
            for cache in ("cold", "warm"):
                samples = []
                for rep in range(1, REPS + 1):
                    scale = "weak" if job.get("weak") else "strong"
                    k = f"{job['system']}|{job['operation']}|{job['mode']}|{job['ranks']}|{scale}|{cache}|{rep}"
                    samples.append(by.get(k))
                ok = [s for s in samples if s and s.get("seconds") is not None]
                if len(ok) == REPS:
                    xs = sorted(s["seconds"] for s in ok)
                    med, lo, hi = xs[len(xs)//2], xs[0], xs[-1]
                    sha = all(s["sha_match"] for s in ok)
                    frames = ok[0]["frames"]
                    nbytes = ok[0]["bytes_file"] * (COPIES if job["system"] == "readcon-db" else 1)
                    fpr = frames / job["ranks"]
                    lines.append(",".join(map(str, [
                        job["system"], job["operation"], job["mode"], job["ranks"],
                        f"{fpr:.6g}", nbytes, f"{med:.6g}", f"{lo:.6g}", f"{hi:.6g}",
                        cache, str(sha).lower()])))
                else:
                    err = next((s.get("error") for s in samples if s and s.get("error")), "missing")
                    lines.append(",".join([
                        job["system"], job["operation"], job["mode"], str(job["ranks"]),
                        "", "", "", "", "", cache, "false"]) + f"  # {err[:180].replace(',', ';')}")
        path = OUT / f"{name}.csv"
        path.write_text("\n".join(lines) + "\n")
        print("wrote", path, flush=True)
    rows_for(lambda j: "weak" if j.get("weak") else "strong", "strong")
    rows_for(lambda j: "weak" if j.get("weak") else "strong", "weak")


if __name__ == "__main__":
    main()
