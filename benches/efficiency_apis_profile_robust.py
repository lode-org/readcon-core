#!/usr/bin/env python3
"""Robust wall-clock profile; median-of-medians across outer trials."""
from __future__ import annotations
import json, statistics, tempfile, time
from pathlib import Path
import readcon

def med(xs): return float(statistics.median(xs))

def timeit(fn, repeats=21, warmup=5):
    for _ in range(warmup):
        fn()
    times=[]
    for _ in range(repeats):
        t0=time.perf_counter(); fn(); times.append(time.perf_counter()-t0)
    return med(times)

def main():
    import sys
    root=Path(sys.argv[1]); out=Path(sys.argv[2]); trials=int(sys.argv[3]) if len(sys.argv)>3 else 3
    tiny=root/"resources/test/tiny_cuh2.con"; cuh2=root/"resources/test/cuh2.con"
    cases=[("tiny_n50", tiny, 50), ("tiny_n200", tiny, 200), ("cuh2_n20", cuh2, 20), ("cuh2_n50", cuh2, 50)]
    all_trials=[]
    for trial in range(trials):
        rows=[]
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            for name,fix, n in cases:
                path=td/f"{name}.con"; path.write_text(fix.read_text()*n)
                size=path.stat().st_size
                p=str(path)
                m_batch=timeit(lambda p=p: readcon.read_all_frames(p))
                m_count=timeit(lambda p=p: readcon.count_frames(p))
                m_pos=timeit(lambda p=p: readcon.read_all_positions(p))
                m_first=timeit(lambda p=p: readcon.read_first_frame(p))
                row=dict(case=name,n_frames=n,bytes=size,parallel_gate_48kib=size>=48*1024,
                    read_all_frames_median_s=m_batch,count_frames_median_s=m_count,
                    read_all_positions_median_s=m_pos,read_first_frame_median_s=m_first,
                    ratio_count_vs_batch=m_count/m_batch,ratio_positions_vs_batch=m_pos/m_batch)
                rows.append(row)
                print(f"trial{trial} {name} batch={m_batch*1e3:.3f}ms count={m_count*1e3:.3f}ms pos={m_pos*1e3:.3f}ms "
                      f"count/b={row['ratio_count_vs_batch']:.3f} pos/b={row['ratio_positions_vs_batch']:.3f}", flush=True)
        all_trials.append(rows)
    # median of medians per case
    summary=[]
    for i, (name, fx, n) in enumerate(cases):
        def col(key):
            return med([t[i][key] for t in all_trials])
        summary.append(dict(
            case=name,n_frames=n,bytes=all_trials[0][i]["bytes"],
            parallel_gate_48kib=all_trials[0][i]["parallel_gate_48kib"],
            read_all_frames_median_s=col("read_all_frames_median_s"),
            count_frames_median_s=col("count_frames_median_s"),
            read_all_positions_median_s=col("read_all_positions_median_s"),
            read_first_frame_median_s=col("read_first_frame_median_s"),
            ratio_count_vs_batch=col("ratio_count_vs_batch"),
            ratio_positions_vs_batch=col("ratio_positions_vs_batch"),
        ))
    result=dict(host="rg.terra",protocol="median-of-medians over 3 trials; each trial median of 21 after 5 warmups",
                readcon=readcon.__file__,cases=summary,trials=all_trials)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    main()
