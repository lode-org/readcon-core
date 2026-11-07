"""Checks for the PR benchmark noise band.

The boundary case is a ratio just above its upper bound. Four-decimal table
text can fall below an eight-decimal threshold; the lossless form must not.
"""

from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_bench = _load("pr_bench", Path(__file__).with_name("pr_bench.py"))
bench = _load("bench_readcon", ROOT / "benchmarks" / "bench_readcon.py")


class SplitAndLayout(unittest.TestCase):
    def test_time_sides_match_comparison(self) -> None:
        self.assertEqual(pr_bench.TIME_SAMPLES_PER_SIDE, 36)
        self.assertEqual(
            pr_bench.TIME_SAMPLES_PER_SIDE,
            pr_bench.COMPARE_ROUNDS * pr_bench.TIME_REPEAT,
        )
        self.assertEqual(pr_bench.TIME_AA_ROUNDS, 12)
        samples = [float(i) for i in range(72)]
        earlier, later = pr_bench.split_sides(samples, "time")
        self.assertEqual(len(earlier), 36)
        self.assertEqual(len(later), 36)
        odd = []
        even = []
        for round_index in range(12):
            chunk = samples[round_index * 6 : (round_index + 1) * 6]
            if round_index % 2 == 0:
                odd.extend(chunk)
            else:
                even.extend(chunk)
        self.assertEqual(earlier, odd)
        self.assertEqual(later, even)
        self.assertNotEqual(earlier, samples[:36])

    def test_memory_sides_stay_six(self) -> None:
        self.assertEqual(pr_bench.MEM_SAMPLES_PER_SIDE, 6)
        self.assertEqual(pr_bench.MEM_AA_ROUNDS, 12)

    def test_number_one_only_on_ray_classes(self) -> None:
        timing = (
            bench.TimeReadConTiny,
            bench.TimeReadConCuh2,
            bench.TimeChemfilesXyz,
            bench.TimeSelectAtoms,
        )
        memory = (
            bench.RayReadConTiny,
            bench.RayReadConCuh2,
            bench.RayChemfilesXyz,
            bench.RaySelectAtoms,
        )
        for cls in timing:
            self.assertNotIn("number", cls.__dict__, cls.__name__)
            self.assertNotIn("setup", cls.__dict__, cls.__name__)
            self.assertEqual(cls.sample_time, bench.SAMPLE_TIME)
            self.assertEqual(bench.SAMPLE_TIME, bench.ASV_DEFAULT_SAMPLE_TIME)
            names = [name for name in cls.__dict__ if name.startswith("time_")]
            self.assertTrue(names, cls.__name__)
            self.assertFalse(any(name.startswith("ray_") for name in cls.__dict__))
        for cls in memory:
            self.assertEqual(cls.number, 1, cls.__name__)
            names = [name for name in cls.__dict__ if name.startswith("ray_")]
            self.assertTrue(names, cls.__name__)
            self.assertFalse(any(name.startswith("time_") for name in cls.__dict__))


class Boundary(unittest.TestCase):
    def test_ratio_just_over_bound_stays_above_serialized_threshold(self) -> None:
        upper = 1.000049
        ratio = math.nextafter(upper, math.inf)
        self.assertGreater(ratio, upper)

        # The previous four-decimal ratio against an eight-decimal threshold
        # drops this ratio to or below the upper bound the commenter would read.
        old_ratio = format(ratio, ".4f")
        old_threshold = format(upper, ".8f")
        self.assertLess(float(old_ratio), float(old_threshold))

        base = [1.0] * pr_bench.TIME_SAMPLES_PER_SIDE
        head = [ratio] * pr_bench.TIME_SAMPLES_PER_SIDE
        row = pr_bench._judge(
            "bench.time_boundary",
            "time",
            base,
            head,
            {"lower": 0.5, "upper": upper},
        )
        self.assertEqual(row["mark"], "+")
        self.assertGreater(row["ratio_num"], upper)

        serialized_ratio = row["ratio"]
        serialized_threshold = pr_bench.format_lossless(upper)
        self.assertEqual(serialized_ratio, pr_bench.format_lossless(ratio))
        self.assertGreater(float(serialized_ratio), float(serialized_threshold))
        self.assertEqual(float(serialized_ratio), ratio)
        self.assertEqual(float(serialized_threshold), upper)

        table = pr_bench.render_table([row])
        parsed = pr_bench.perch_rows(table)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["mark"], "+")
        commenter_ratio = float(parsed[0]["ratio"].removeprefix("~"))
        commenter_threshold = float(serialized_threshold)
        self.assertGreaterEqual(commenter_ratio, commenter_threshold)


class GateExit(unittest.TestCase):
    def test_equal_commits_are_refused(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            pr_bench.assert_distinct_commits("abc", "abc")
        self.assertIn("abc", str(caught.exception))
        pr_bench.assert_distinct_commits("abc", "def")

    def test_slowdown_or_missing_samples_fail_the_job(self) -> None:
        self.assertEqual(pr_bench.regression_exit_code([{"mark": " "}]), 0)
        self.assertEqual(pr_bench.regression_exit_code([{"mark": "-"}]), 0)
        self.assertEqual(pr_bench.regression_exit_code([{"mark": "+"}]), 1)
        self.assertEqual(pr_bench.regression_exit_code([{"mark": "!"}]), 1)
        self.assertEqual(
            pr_bench.regression_exit_code([{"mark": "-"}, {"mark": "+"}]),
            1,
        )
        self.assertEqual(pr_bench.regression_exit_code([{"mark": "new"}]), 0)
        self.assertEqual(pr_bench.regression_exit_code([{"mark": "removed"}]), 0)


def _kind_noise(time_upper: float, memory_upper: float) -> dict:
    return {
        "benchmarks": {
            "time.sample": {"kind": "time", "upper": time_upper},
            "memory.sample": {"kind": "memory", "upper": memory_upper},
        }
    }


class Presence(unittest.TestCase):
    def test_head_only_benchmark_is_new_and_does_not_fail(self) -> None:
        row = pr_bench._judge(
            "bench.time_new",
            "time",
            [],
            [1.0] * pr_bench.TIME_SAMPLES_PER_SIDE,
            None,
        )
        self.assertEqual(row["mark"], "new")
        self.assertEqual(row["call"], "new benchmark")
        self.assertEqual(pr_bench.regression_exit_code([row]), 0)

    def test_base_only_benchmark_is_removed(self) -> None:
        row = pr_bench._judge(
            "bench.time_old",
            "time",
            [1.0] * pr_bench.TIME_SAMPLES_PER_SIDE,
            [],
            {"lower": 0.5, "upper": 1.5},
        )
        self.assertEqual(row["mark"], "removed")
        self.assertEqual(pr_bench.regression_exit_code([row]), 0)


class BetweenRunTiming(unittest.TestCase):
    def test_prediction_limit_matches_the_t_quantile(self) -> None:
        pairs = [(1.0, 1.02 if i % 2 == 0 else 1.0) for i in range(15)]
        alpha = pr_bench.prediction_alpha(13)
        between = pr_bench.between_run_side_bounds(pairs, alpha)
        self.assertAlmostEqual(between["lower"] * between["upper"], 1.0)
        self.assertGreater(between["upper"], between["widest"])
        self.assertAlmostEqual(between["pred_alpha"], 0.01 / 13)
        self.assertEqual(between["pred_df"], 14)
        within = pr_bench.bounds_from_ratios([1.0] * 15)
        self.assertEqual(within["upper"], 1.0)
        band = pr_bench.combine_time_bounds(within, between)
        self.assertAlmostEqual(band["upper"], between["upper"])
        self.assertAlmostEqual(band["between_upper"], between["upper"])
        row = pr_bench._judge(
            "bench.time_shift",
            "time",
            [1.0] * pr_bench.TIME_SAMPLES_PER_SIDE,
            [1.015] * pr_bench.TIME_SAMPLES_PER_SIDE,
            band,
        )
        self.assertEqual(row["mark"], " ")
        self.assertEqual(pr_bench.regression_exit_code([row]), 0)
        slow = pr_bench._judge(
            "bench.time_sleep",
            "time",
            [1.0] * pr_bench.TIME_SAMPLES_PER_SIDE,
            [50.0] * pr_bench.TIME_SAMPLES_PER_SIDE,
            band,
        )
        self.assertEqual(slow["mark"], "+")
        self.assertEqual(pr_bench.regression_exit_code([slow]), 1)

    def test_within_run_bound_still_wins_when_it_is_wider(self) -> None:
        between = pr_bench.between_run_side_bounds(
            [(1.0, 1.0)] * 15, pr_bench.prediction_alpha(1)
        )
        self.assertEqual(between["upper"], 1.0)
        within = pr_bench.bounds_from_ratios([1.0] * 14 + [1.05])
        band = pr_bench.combine_time_bounds(within, between)
        self.assertGreaterEqual(band["upper"], within["upper"])
        self.assertGreater(band["upper"], 1.02)

    def test_student_t_quantiles(self) -> None:
        self.assertAlmostEqual(pr_bench._norm_ppf(0.975), 1.959963984540054, places=8)
        self.assertAlmostEqual(
            pr_bench.student_t_ppf(0.975, 14), 2.144786687917804, places=8
        )
        self.assertAlmostEqual(
            pr_bench.student_t_ppf(0.995, 14), 2.9768427343708344, places=8
        )
        self.assertAlmostEqual(
            pr_bench.student_t_ppf(0.999, 14), 3.7873902375233457, places=6
        )
        self.assertAlmostEqual(
            pr_bench.student_t_ppf(1.0 - 0.01 / 13, 14),
            pr_bench.student_t_ppf(1.0 - pr_bench.prediction_alpha(13), 14),
            places=8,
        )


class MemoryGranule(unittest.TestCase):
    def test_one_byte_passes_and_one_frame_fails(self) -> None:
        granule = pr_bench.allocator_granule()
        self.assertGreaterEqual(granule, 1)
        peak = 100000.0
        lower, upper = pr_bench.memory_granule_bounds(peak, granule)
        self.assertGreater(upper, 1.0)
        self.assertAlmostEqual(lower * upper, 1.0)
        one_byte = pr_bench._judge(
            "bench.ray_one_byte",
            "memory",
            [peak] * pr_bench.MEM_SAMPLES_PER_SIDE,
            [peak + 1.0] * pr_bench.MEM_SAMPLES_PER_SIDE,
            {"lower": lower, "upper": upper},
        )
        self.assertEqual(one_byte["mark"], " ")
        self.assertEqual(pr_bench.regression_exit_code([one_byte]), 0)
        # One frame of resources/test/tiny_cuh2.con is 499 bytes, many granules.
        frame = 499
        self.assertGreater(frame, granule)
        grown = pr_bench._judge(
            "bench.ray_one_frame",
            "memory",
            [peak] * pr_bench.MEM_SAMPLES_PER_SIDE,
            [peak + frame] * pr_bench.MEM_SAMPLES_PER_SIDE,
            {"lower": lower, "upper": upper},
        )
        self.assertEqual(grown["mark"], "+")
        self.assertEqual(pr_bench.regression_exit_code([grown]), 1)


class CommenterThreshold(unittest.TestCase):
    def test_timing_threshold_is_not_the_memory_floor(self) -> None:
        noise = _kind_noise(1.15, 1.0)
        thresholds = pr_bench.kind_thresholds(noise)
        self.assertEqual(thresholds["time"], 1.15)
        self.assertEqual(thresholds["memory"], 1.0)

    def test_speedup_does_not_draft(self) -> None:
        noise = _kind_noise(1.15, 1.0)
        rows = [{"mark": "-", "kind": "time", "ratio_num": 0.994, "benchmark": "t"}]
        self.assertFalse(pr_bench.commenter_should_draft(rows, noise))
        self.assertEqual(pr_bench.action_threshold(rows, noise), 1.15)

    def test_timing_slowdown_drafts_on_the_timing_bound(self) -> None:
        noise = _kind_noise(1.15, 1.0)
        rows = [
            {"mark": "+", "kind": "time", "ratio_num": 50.0, "benchmark": "t"},
            {"mark": " ", "kind": "memory", "ratio_num": 1.0, "benchmark": "m"},
        ]
        self.assertTrue(pr_bench.commenter_should_draft(rows, noise))
        self.assertEqual(pr_bench.action_threshold(rows, noise), 1.15)
        self.assertNotEqual(pr_bench.action_threshold(rows, noise), 1.0)

    def test_memory_slowdown_uses_the_memory_bound(self) -> None:
        noise = _kind_noise(1.15, 1.0)
        rows = [{"mark": "+", "kind": "memory", "ratio_num": 1.02, "benchmark": "m"}]
        self.assertTrue(pr_bench.commenter_should_draft(rows, noise))
        self.assertEqual(pr_bench.action_threshold(rows, noise), 1.0)


class CommentShowsRowBound(unittest.TestCase):
    def test_table_shows_each_rows_own_upper(self) -> None:
        n = pr_bench.TIME_SAMPLES_PER_SIDE
        quiet = pr_bench._judge(
            "bench.time_quiet",
            "time",
            [1.0] * n,
            [1.0] * n,
            {
                "lower": 0.98,
                "upper": 1.0192061275646016,
                "within_upper": 1.0094152557969125,
                "between_upper": 1.0192061275646016,
            },
        )
        wide = pr_bench._judge(
            "bench.time_wide",
            "time",
            [1.0] * n,
            [1.0609785924146939] * n,
            {
                "lower": 0.74,
                "upper": 1.3521498689127784,
                "within_upper": 1.0660939134246985,
                "between_upper": 1.3521498689127784,
            },
        )
        self.assertEqual(quiet["mark"], " ")
        self.assertEqual(wide["mark"], " ")
        self.assertGreater(wide["ratio_num"], quiet["upper"])
        self.assertLess(wide["ratio_num"], wide["upper"])
        table = pr_bench.render_table([quiet, wide])
        self.assertIn("| Upper |", table)
        self.assertIn("| N |", table)
        self.assertIn("| Base median |", table)
        self.assertIn("| Head median |", table)
        self.assertIn("| Base IQR |", table)
        self.assertIn("| Head IQR |", table)
        self.assertIn(str(n), table)
        for row in (quiet, wide):
            line = next(item for item in table.splitlines() if row["benchmark"] in item)
            self.assertIn(pr_bench.format_lossless(row["upper"]), line)
            other = quiet if row is wide else wide
            self.assertNotIn(pr_bench.format_lossless(other["upper"]), line)
        bounds = pr_bench.render_row_bounds([quiet, wide])
        self.assertTrue(
            bounds.startswith("benchmark\twithin_upper\tbetween_upper\tupper\n")
        )
        self.assertIn(
            "bench.time_wide\t1.0660939134246985\t1.3521498689127784\t1.3521498689127784\n",
            bounds,
        )
        slowed = pr_bench._judge(
            "bench.time_sleep",
            "time",
            [1.0] * n,
            [50.0] * n,
            {
                "lower": 0.74,
                "upper": 1.3521498689127784,
                "within_upper": 1.06,
                "between_upper": 1.3521498689127784,
            },
        )
        self.assertEqual(slowed["mark"], "+")
        self.assertGreater(slowed["ratio_num"], slowed["upper"])
        sleep_line = next(
            item
            for item in pr_bench.render_table([slowed]).splitlines()
            if "time_sleep" in item
        )
        self.assertIn("| + |", sleep_line)
        self.assertIn(pr_bench.format_lossless(slowed["upper"]), sleep_line)


if __name__ == "__main__":
    unittest.main()
