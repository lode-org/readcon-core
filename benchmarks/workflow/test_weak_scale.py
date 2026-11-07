"""Weak-scaling relation, efficiency, and the refusal to invent a curve."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


weak = _load("weak_scale", ROOT / "benchmarks" / "weak_scale.py")
threads = _load("bench_threads", ROOT / "benches" / "weak_asv" / "bench_threads.py")


def _flat_curve(physical: int = 32) -> dict:
    points = []
    for workers in weak.ladder_for_cores(physical):
        n_frames = weak.frames_for_workers(workers, 64)
        points.append(
            {
                "workers": workers,
                "n_frames": n_frames,
                "bytes": 16771 * n_frames,
                "samples_s": [1.0, 1.2, 1.1, 1.3, 1.05, 1.15],
            }
        )
    return {
        "kind": "threads",
        "relation": weak.RELATION,
        "frames_per_worker": 64,
        "fixture": "resources/test/cuh2.con",
        "host": "Intel Xeon Processor",
        "ncpus": physical,
        "physical_cores": physical,
        "serial_match": True,
        "mpi": "absent",
        "gpu": "absent",
        "commit": "abc",
        "date_utc": "2026-11-05T00:00Z",
        "points": points,
    }


class Relation(unittest.TestCase):
    def test_frames_grow_and_work_stays_constant(self) -> None:
        self.assertEqual(weak.REPEATS, 6)
        self.assertEqual(weak.ladder_for_cores(1), (1,))
        self.assertEqual(weak.ladder_for_cores(8), (1, 2, 4, 8))
        self.assertEqual(weak.ladder_for_cores(6), (1, 2, 4, 6))
        self.assertEqual(weak.ladder_for_cores(24), (1, 2, 4, 8, 16, 24))
        self.assertEqual(weak.ladder_for_cores(32), (1, 2, 4, 8, 16, 32))
        self.assertEqual(weak.DEFAULT_LADDER[0], 1)
        self.assertLessEqual(max(weak.DEFAULT_LADDER), weak.physical_cores())
        shares = []
        for workers in weak.ladder_for_cores(32):
            n_frames = weak.frames_for_workers(workers, 64)
            self.assertEqual(n_frames, 64 * workers)
            shares.append(weak.work_per_worker(n_frames, workers))
        self.assertEqual(set(shares), {64})

    def test_gate_frames_rounds_up(self) -> None:
        self.assertEqual(weak.gate_frames(16771, 49152), 3)
        self.assertEqual(weak.gate_frames(100, 100), 1)

    def test_physical_ladder_fits_and_oversubscribed_fails(self) -> None:
        self.assertTrue(weak.ladder_fits((1, 2, 4, 8), 8))
        self.assertTrue(weak.ladder_fits((1, 2, 4, 8, 16, 32), 32))
        self.assertTrue(weak.ladder_fits((1, 2, 4, 6), 6))
        self.assertFalse(weak.ladder_fits((1, 2, 4, 8, 16, 32), 8))
        self.assertFalse(weak.ladder_fits((1, 2, 4, 8, 16), 8))
        self.assertFalse(weak.ladder_fits((1, 2, 4), 8))
        self.assertFalse(weak.ladder_fits((2, 4, 8, 16, 32, 64), 64))
        self.assertEqual(weak.iqr_type7([1, 2, 3, 4, 5, 6]), 2.5)
        self.assertEqual(weak.total_wall([1, 2, 3, 4, 5, 6]), 21.0)

    def test_median_of_six_is_the_mean_of_the_central_pair(self) -> None:
        self.assertEqual(weak.median_samples([1, 2, 3, 4, 5, 6]), 3.5)
        with self.assertRaises(ValueError):
            weak.median_samples([1, 2, 3, 4, 5])

    def test_efficiency_is_the_reciprocal_of_relative_time(self) -> None:
        self.assertEqual(weak.efficiency(2.0, 2.0), 1.0)
        self.assertEqual(weak.efficiency(2.0, 4.0), 0.5)
        self.assertEqual(weak.relative_time(2.0, 4.0), 2.0)
        self.assertEqual(weak.efficiency(2.0, 4.0) * weak.relative_time(2.0, 4.0), 1.0)


class Report(unittest.TestCase):
    def test_summary_recomputes_a_flat_efficiency(self) -> None:
        summary = weak.summarise(_flat_curve())
        self.assertTrue(summary["complete"])
        self.assertEqual(len(summary["points"]), 6)
        self.assertTrue(summary["serial_match"])
        self.assertEqual(summary["physical_cores"], 32)
        for point in summary["points"]:
            self.assertEqual(point["efficiency"], 1.0)
            self.assertEqual(point["relative_time"], 1.0)
            self.assertEqual(point["median_s"], weak.median_samples(point["samples_s"]))
            self.assertEqual(point["iqr_s"], weak.iqr_type7(point["samples_s"]))
            self.assertEqual(point["total_wall_s"], weak.total_wall(point["samples_s"]))

    def test_summary_rejects_oversubscribe_and_a_changed_share(self) -> None:
        raw = _flat_curve(8)
        summary = weak.summarise(raw)
        self.assertEqual(
            [point["workers"] for point in summary["points"]], [1, 2, 4, 8]
        )
        raw = _flat_curve(32)
        raw["physical_cores"] = 8
        with self.assertRaises(ValueError):
            weak.summarise(raw)
        raw = _flat_curve()
        raw["points"] = raw["points"][:5]
        with self.assertRaises(ValueError):
            weak.summarise(raw)
        raw = _flat_curve()
        raw["points"][1]["n_frames"] += 1
        with self.assertRaises(ValueError):
            weak.summarise(raw)

    def test_table_is_named_from_the_cpu_model(self) -> None:
        summary = weak.summarise(_flat_curve())
        self.assertEqual(
            weak.table_filename("threads", summary["host"]),
            "weak_threads_Intel_Xeon_Processor.tex",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / weak.table_filename("threads", summary["host"])
            weak.write_table(path, summary)
            text = path.read_text(encoding="utf-8")
            weak.assert_no_machine_name(text)
            self.assertIn("Intel Xeon Processor", text)
            self.assertIn("1.000000", text)
            self.assertNotIn("cursor", text)

    def test_curve_lists_every_coordinate_and_the_ideal(self) -> None:
        summary = weak.summarise(_flat_curve())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.tex"
            weak.write_curve(path, summary)
            text = path.read_text(encoding="utf-8")
            for point in summary["points"]:
                self.assertIn(f"% curve {point['workers']} 1.000000", text)
            self.assertIn("dashed ideal", text)

    def test_stubs_have_no_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            weak.write_stubs(directory)
            for name in (
                "weak_scale_table_stub.tex",
                "weak_scale_figure_stub.tex",
                "weak_scale_gpu_stub.tex",
            ):
                text = (directory / name).read_text(encoding="utf-8")
                self.assertNotIn("1.000000", text)
                if name == "weak_scale_gpu_stub.tex":
                    self.assertIn("DLPack", text)
                else:
                    self.assertIn(r"n\_frames", text)
            paper = ROOT / "paper" / "cpc" / "src" / "weak"
            for name in (
                "weak_scale_table_stub.tex",
                "weak_scale_figure_stub.tex",
                "weak_scale_gpu_stub.tex",
            ):
                self.assertEqual(
                    (directory / name).read_text(encoding="utf-8"),
                    (paper / name).read_text(encoding="utf-8"),
                )

    def test_plot_draws_a_pdf_from_the_samples(self) -> None:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib is not installed")
        summary = weak.summarise(_flat_curve())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.pdf"
            weak.write_plot(path, summary)
            self.assertGreater(path.stat().st_size, 1000)


class HostAndLaunch(unittest.TestCase):
    def test_this_host_publishes_the_physical_ladder(self) -> None:
        host = weak.capture_host()
        text = json.dumps(host)
        weak.assert_no_machine_name(text)
        self.assertNotIn("cursor", text)
        self.assertGreaterEqual(host["ncpus"], 1)
        self.assertEqual(
            host["physical_cores"], host["cores_per_socket"] * host["sockets"]
        )
        self.assertLessEqual(host["physical_cores"], host["ncpus"])
        self.assertEqual(
            host["physical_cores"] * host["threads_per_core"],
            host["ncpus"],
        )
        plan = weak.make_plan(host)
        self.assertTrue(plan["ladder_fits"])
        self.assertEqual(
            plan["ladder"], list(weak.ladder_for_cores(host["physical_cores"]))
        )
        self.assertTrue(
            all(worker <= host["physical_cores"] for worker in plan["ladder"])
        )
        self.assertTrue(plan["threads_asv"]["run"])
        self.assertFalse(plan["gpu"]["run"])
        self.assertIn("DLPack", plan["gpu"]["reason"])
        over = list(plan["ladder"]) + [host["physical_cores"] + 1]
        refused = weak.make_plan(host, over)
        self.assertFalse(refused["ladder_fits"])
        self.assertFalse(refused["threads_asv"]["run"])
        self.assertFalse(refused["ranks_mpi"]["run"])
        if host.get("hypervisor") == "KVM":
            self.assertIn("KVM", host["topology_note"])

    def test_mpi_binding_follows_the_implementation(self) -> None:
        self.assertEqual(weak.bind_args("Open MPI 4.1.6"), ["--bind-to", "core"])
        self.assertEqual(weak.bind_args("HYDRA build of MPICH"), ["-bind-to", "core"])
        self.assertEqual(weak.bind_args("unknown mpi"), [])
        with self.assertRaises(ValueError):
            weak.bind_args("absent")
        argv = weak.mpirun_argv("MPICH 4.2.3", 4, "bin", "in.con", "out.json", 6)
        self.assertEqual(argv[:4], ["mpirun", "-bind-to", "core", "-n"])
        argv = weak.asv_thread_argv("asv.weak.conf.json", weak.ASV_MACHINE, 6)
        self.assertIn("asv", argv)
        self.assertIn("time_weak_threads", argv)
        self.assertIn("--machine", argv)
        self.assertIn("optbench-ci", argv)
        self.assertNotIn("--quick", argv)
        self.assertEqual(weak.ASV_MACHINE, "optbench-ci")

    def test_from_asv_uses_the_raw_samples(self) -> None:
        payload = {
            "commit_hash": "abc",
            "results": {
                "bench_threads.TimeWeakThreads.time_weak_threads": {
                    "params": [["1", "2", "4", "8", "16", "32"]],
                    "result": [9, 9, 9, 9, 9, 9],
                    "samples": [[1, 2, 3, 4, 5, 6] for _ in range(6)],
                }
            },
        }
        host = {
            "cpu_model": "Intel Xeon Processor",
            "ncpus": 32,
            "mpi": "absent",
            "gpu": "absent",
        }
        record = weak.from_asv(payload, host, 64, "resources/test/cuh2.con", 10)
        summary = weak.summarise(record)
        self.assertEqual(summary["points"][0]["median_s"], 3.5)
        self.assertNotEqual(summary["points"][0]["median_s"], 9)

    def test_from_asv_reads_column_samples(self) -> None:
        columns = ["result", "params", "samples"]
        samples = [[1, 2, 3, 4, 5, 6] for _ in range(6)]
        payload = {
            "commit_hash": "abc",
            "result_columns": columns,
            "results": {
                "bench_threads.TimeWeakThreads.time_weak_threads": [
                    [9, 9, 9, 9, 9, 9],
                    [["1", "2", "4", "8", "16", "32"]],
                    samples,
                ]
            },
        }
        host = {
            "cpu_model": "Intel Xeon Processor",
            "ncpus": 32,
            "physical_cores": 32,
            "mpi": "absent",
            "gpu": "absent",
        }
        record = weak.from_asv(payload, host, 64, "resources/test/cuh2.con", 10)
        summary = weak.summarise(record)
        self.assertEqual(summary["points"][0]["median_s"], 3.5)
        self.assertNotEqual(summary["points"][0]["median_s"], 9)
        self.assertEqual(summary["points"][-1]["workers"], 32)

    def test_derive_conf_leaves_the_pr_directory_alone(self) -> None:
        pr = json.loads((ROOT / "asv.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(pr["benchmark_dir"], "benchmarks")
        self.assertFalse(list((ROOT / "benchmarks").glob("**/bench_threads.py")))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "asv.weak.conf.json"
            weak.derive_asv_conf(ROOT / "asv.conf.json", dest)
            derived = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(derived["benchmark_dir"], "benches/weak_asv")
        self.assertEqual(derived["build_command"], pr["build_command"])

    def test_asv_class_uses_the_ladder_and_six_repeats(self) -> None:
        self.assertEqual(tuple(threads.TimeWeakThreads.params), weak.DEFAULT_LADDER)
        self.assertEqual(threads.TimeWeakThreads.repeat, 6)
        self.assertNotIn("setup", threads.TimeWeakThreads.__dict__)
        self.assertNotIn("number", threads.TimeWeakThreads.__dict__)

    def test_refusing_the_campaign_writes_a_headed_log(self) -> None:
        host = weak.capture_host()
        over = list(weak.ladder_for_cores(host["physical_cores"]))
        over.append(host["physical_cores"] * 2)
        plan = weak.make_plan(host, over)
        self.assertFalse(plan["ladder_fits"])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            host_path = directory / "host.json"
            plan_path = directory / "plan.json"
            log_path = directory / "threads.log"
            host_path.write_text(json.dumps(host), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            code = weak.main(
                [
                    "run-threads",
                    "--plan",
                    str(plan_path),
                    "--host",
                    str(host_path),
                    "--json",
                    str(directory / "threads.json"),
                    "--log",
                    str(log_path),
                ]
            )
            self.assertEqual(code, 2)
            self.assertFalse((directory / "threads.json").exists())
            text = log_path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("HEAD "))
            self.assertIn("\ntree ", text)
            self.assertIn("\n$ python3 benchmarks/weak_scale.py run-threads\n", text)
            self.assertNotIn("/tmp", text)
            self.assertNotIn("/agent", text)
            self.assertTrue(text.endswith("exit_code 2\n"))
            weak.assert_no_machine_name(text)
            gpu_log = directory / "gpu.log"
            gpu_code = weak.main(
                [
                    "run-gpu",
                    "--host",
                    str(host_path),
                    "--out",
                    str(directory / "stubs"),
                    "--log",
                    str(gpu_log),
                ]
            )
            self.assertEqual(gpu_code, 2)
            gpu_text = gpu_log.read_text(encoding="utf-8")
            self.assertIn("DLPack", gpu_text)
            self.assertTrue(gpu_text.endswith("exit_code 2\n"))

    def test_sources_do_not_call_hostname_and_do_not_touch_src(self) -> None:
        for path in (
            ROOT / "examples" / "weak_scale_threads.rs",
            ROOT / "examples" / "weak_scale_mpi.rs",
            ROOT / "benches" / "weak_asv" / "bench_threads.py",
            ROOT / "benchmarks" / "weak_scale.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("gethostname", text)
            self.assertNotIn('Command::new("hostname")', text)
            self.assertIn("n_frames = frames_per_worker * workers", text)
        snakefile = (ROOT / "benchmarks" / "workflow" / "weak" / "Snakefile").read_text(
            encoding="utf-8"
        )
        self.assertIn("run-threads", snakefile)
        self.assertIn("run-ranks", snakefile)
        for template in (ROOT / "benchmarks" / "workflow" / "weak" / "templates").glob(
            "*.tpl"
        ):
            lines = template.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "HEAD {{GIT_HEAD}}")
            self.assertTrue(lines[2].startswith("$ "))
            self.assertEqual(lines[-1], "exit_code {{EXIT_CODE}}")


if __name__ == "__main__":
    unittest.main()
