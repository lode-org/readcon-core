import json, statistics, tempfile, time, threading, sys
from pathlib import Path
import readcon

def med(xs): return float(statistics.median(xs))

def timeit(fn, repeats=15, warmup=4):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return med(ts)

def main(label, out_path):
    root = Path("/home/rgoswami/Git/Github/LODE/readcon-core")
    cuh2 = (root / "resources/test/cuh2.con").read_text()
    tiny = (root / "resources/test/tiny_cuh2.con").read_text()
    cases = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name, text, n in [("tiny_n200", tiny, 200), ("cuh2_n50", cuh2, 50), ("cuh2_n100", cuh2, 100)]:
            p = td / f"{name}.con"
            p.write_text(text * n)
            ps = str(p)
            m_batch = timeit(lambda ps=ps: readcon.read_all_frames(ps))
            m_coords = timeit(
                lambda ps=ps: [f.coords_array() for f in readcon.read_all_frames(ps)]
            )
            m_count = timeit(lambda ps=ps: readcon.count_frames(ps))
            cases.append(
                dict(
                    case=name,
                    n_frames=n,
                    bytes=p.stat().st_size,
                    batch_s=m_batch,
                    pos_s=m_coords,
                    count_s=m_count,
                )
            )
            print(
                f"{label} {name} batch={m_batch*1e3:.3f}ms "
                f"batch+coords_array={m_coords*1e3:.3f}ms count={m_count*1e3:.3f}ms",
                flush=True,
            )

    long_path = "/tmp/ab_long.con"
    Path(long_path).write_text(cuh2 * 80)
    ticks = {"n": 0, "done": False}

    def worker():
        while not ticks["done"]:
            ticks["n"] += 1
            _ = sum(i * i for i in range(300))

    ticks["n"] = 0
    ticks["done"] = False
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t0 = time.perf_counter()
    for _ in range(10):
        readcon.read_all_frames(long_path)
    elapsed = time.perf_counter() - t0
    ticks["done"] = True
    t.join(timeout=2)
    concurrent = dict(
        elapsed_s=elapsed,
        worker_ticks=ticks["n"],
        ticks_per_s=ticks["n"] / elapsed if elapsed else 0.0,
    )
    print(
        f"{label} concurrent: elapsed={elapsed:.3f}s ticks={ticks['n']} ticks/s={concurrent['ticks_per_s']:.1f}",
        flush=True,
    )
    Path(out_path).write_text(
        json.dumps(dict(variant=label, cases=cases, concurrent=concurrent), indent=2) + "\n"
    )

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
