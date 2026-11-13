"""Drive the PR benchmark report from asv result files.

Snakemake invokes asv. This module does not time anything itself. It copies
asv result JSON, summarizes main-vs-main ratios, and writes the comment table.

Threshold, fixed before looking at a given run:

* Each main-vs-main repetition records r = median(later samples) / median(earlier samples).
* Time benchmarks use ``TIME_AA_ROUNDS`` rounds of ``TIME_REPEAT`` samples
  inside one ``asv run --interleave-rounds``. That is 72 samples. Odd rounds
  are one side and even rounds the other (36 and 36). The comparison records
  that same count with ``COMPARE_ROUNDS`` rounds of ``TIME_REPEAT``, one
  round of the base commit and then one round of the head commit.
* Memory benchmarks are one memray peak per ``asv run`` (asv does not keep
  that scalar in ``samples`` across rounds). ``MEM_AA_ROUNDS`` successive
  runs are split into odd and even rounds, ``MEM_AA_ROUNDS // 2`` peaks a side.
* From those within-run ratios: linear percentile p01 and p99, median, and
  median absolute deviation.
* Within-run upper bound = max(p99, median + 3*median absolute deviation).
* Within-run lower bound = min(p01, median - 3*median absolute deviation)
  when that bound is positive, otherwise p01.
* Each round is its own process of one installed build. A speed shift that
  covers an odd round and the following even round cancels in their ratio,
  so that bound sits closer to 1 than a ratio of two builds. Each repetition
  also keeps the two side medians. The between-run upper bound is a Student t
  prediction limit for a ratio of two of those medians, and the lower bound
  is the reciprocal. The widest side-median ratio, the pairwise 99th
  percentile, and the median-absolute-deviation fence of the side ratios are
  recorded. They do not set the bound.
* The timing upper bound is the wider of the within-run and between-run
  upper bounds. The timing lower bound is the smaller of the two lower
  bounds. The timing comparison runs after the timing repetitions and before
  the memory repetitions.
* Memory uses the within-run bound, widened so a change of one allocator
  granule is inside the band. The granule is the usable size of a one-byte
  malloc. On a base peak of P bytes the ratio band includes
  1 + granule/P. Timing does not use that granule.
* A base-vs-head ratio (head median / base median) is a significant slowdown
  when it is above the upper bound, a significant speedup when it is below
  the lower bound, and not significant otherwise.

With 10 to 20 repetitions the linear 99th percentile sits on the extreme
order statistics, so one noisy repetition can move it. Taking the wider of
that percentile and the 3*median-absolute-deviation fence keeps a result
that is still inside either description of the within-run noise from being
called significant. The between-run bound exists because that within-run
description still called unchanged builds a slowdown.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

# Keep in lockstep with the Snakefile, which imports these names.
# A round median of an even count is the mean of the two central samples.
# Six is the smallest even count with two samples strictly below that pair
# and two strictly above it, so one extreme sample is not the median and
# the median is not the mean of the two extremes (that would be a count of 2
# or 4). The round count uses the same width so each comparison side has
# TIME_REPEAT * COMPARE_ROUNDS samples and the main-vs-main split, which
# needs an even number of rounds, has that same count on each side.
TIME_REPEAT = 6
COMPARE_ROUNDS = TIME_REPEAT
TIME_AA_ROUNDS = COMPARE_ROUNDS * 2
MEM_AA_ROUNDS = COMPARE_ROUNDS * 2
TIME_SAMPLES_PER_SIDE = COMPARE_ROUNDS * TIME_REPEAT
MEM_SAMPLES_PER_SIDE = COMPARE_ROUNDS
# bounds_from_ratios accepts 10 to 20 ratios. At 10 the type-7 rank of the
# 99th percentile, 0.99*(n-1), is 8.91, so the second-to-last order statistic
# still has weight. At 20 that rank is 18.81 and the maximum still carries
# most of the weight; past that the percentile is no longer an extreme-order
# summary. Fifteen is the midpoint of that closed window.
AA_RUNS = (10 + 20) // 2
MACHINE = "pr-bench"
# asv_runner's TimeBenchmark default sample_time is 0.01 s. Each sample
# targets that default.
ASV_DEFAULT_SAMPLE_TIME = 0.01
SAMPLE_TIME = ASV_DEFAULT_SAMPLE_TIME
# The within-run percentile pair is the 1st and the 99th, the central 98%.
# The family-wise false-slowdown budget is the complement of that 99th
# percentile, so both describe the outer 1%. The budget is split across the
# timing rows of the one comparison this job judges. It is not divided by a
# count of other null runs.
WITHIN_RUN_UPPER_PERCENTILE = 99
FALSE_SLOWDOWN_BUDGET = (100 - WITHIN_RUN_UPPER_PERCENTILE) / 100
# A normal MAD is sigma * Phi^{-1}(0.75) ≈ sigma * 0.67448975, so three raw
# MADs are about 2.02 sigma, the same place as the normal 97.5th percentile
# (1.96 sigma). The fence is median + 3*MAD, not 3*1.4826*MAD.
MAD_FENCE_MULTIPLIER = 3

if TIME_AA_ROUNDS % 2 != 0:
    raise RuntimeError("TIME_AA_ROUNDS must split into two equal sides")
if TIME_AA_ROUNDS * TIME_REPEAT != TIME_SAMPLES_PER_SIDE * 2:
    raise RuntimeError("time A/A split does not match the comparison sample count")
if MEM_AA_ROUNDS % 2 != 0 or MEM_AA_ROUNDS // 2 != MEM_SAMPLES_PER_SIDE:
    raise RuntimeError("memory A/A split does not match the comparison peak count")


def format_lossless(value: float) -> str:
    """Decimal form that round-trips through float() for a float64 value.

    Seventeen significant digits is enough for a binary64 round trip. The
    comment table and the commenter threshold both use this form, so a ratio
    just above its upper bound still parses as greater than that bound.
    """
    return format(float(value), ".17g")


def samples_per_side(kind: str) -> int:
    if kind == "time":
        return TIME_SAMPLES_PER_SIDE
    if kind == "memory":
        return MEM_SAMPLES_PER_SIDE
    raise ValueError(kind)


def median(values: list[float]) -> float:
    ys = sorted(values)
    n = len(ys)
    if n == 0:
        raise ValueError("median of empty sample")
    mid = n // 2
    if n % 2:
        return ys[mid]
    return 0.5 * (ys[mid - 1] + ys[mid])


def mad(values: list[float]) -> float:
    center = median(values)
    return median([abs(v - center) for v in values])


def prediction_alpha(n_benchmarks: int) -> float:
    """One-sided miss probability for a single timing benchmark.

    ``FALSE_SLOWDOWN_BUDGET`` is the family-wise chance of any false timing
    slowdown in this one comparison. It is split evenly across the timing
    benchmarks in that comparison.
    """
    if n_benchmarks < 1:
        raise ValueError("need at least one timing benchmark")
    return FALSE_SLOWDOWN_BUDGET / n_benchmarks


def allocator_granule() -> int:
    """Usable bytes of a one-byte malloc in this process.

    Memray's peak moves by whole allocations. The allocator charges
    ``malloc_usable_size(malloc(1))`` for a one-byte request. That size is
    the granule. A base peak of P bytes cannot resolve a smaller change, so
    the memory ratio band includes ``1 + granule/P``.
    """
    import ctypes

    libc = ctypes.CDLL(None)
    malloc = libc.malloc
    malloc.argtypes = [ctypes.c_size_t]
    malloc.restype = ctypes.c_void_p
    usable = libc.malloc_usable_size
    usable.argtypes = [ctypes.c_void_p]
    usable.restype = ctypes.c_size_t
    free = libc.free
    free.argtypes = [ctypes.c_void_p]
    pointer = malloc(1)
    if not pointer:
        raise RuntimeError("malloc(1) failed")
    size = int(usable(pointer))
    free(pointer)
    if size < 1:
        raise RuntimeError(f"malloc usable size was {size}")
    return size


def memory_granule_bounds(peak: float, granule: int) -> tuple[float, float]:
    """Ratio band for one granule on a peak of ``peak`` bytes."""
    if peak <= 0 or not math.isfinite(peak):
        raise ValueError(f"peak must be positive, got {peak}")
    if granule < 1:
        raise ValueError(f"granule must be positive, got {granule}")
    upper = 1.0 + granule / peak
    return 1.0 / upper, upper


def _norm_ppf(p: float) -> float:
    """Inverse standard normal, Acklam's rational approximation."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability out of range: {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function."""
    max_iter = 200
    eps = 3e-14
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    raise ValueError("incomplete beta continued fraction did not converge")


def _reg_inc_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - log_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _student_t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * _reg_inc_beta(0.5 * df, 0.5, x)
    if t >= 0.0:
        return 1.0 - tail
    return tail


def _student_t_pdf(t: float, df: float) -> float:
    log_norm = (
        math.lgamma(0.5 * (df + 1.0))
        - math.lgamma(0.5 * df)
        - 0.5 * math.log(df * math.pi)
    )
    return math.exp(log_norm - 0.5 * (df + 1.0) * math.log1p((t * t) / df))


def student_t_ppf(probability: float, df: float) -> float:
    """Upper quantile of Student's t with ``df`` degrees of freedom."""
    if not 0.0 < probability < 1.0:
        raise ValueError(f"probability out of range: {probability}")
    if df <= 0:
        raise ValueError(f"degrees of freedom must be positive, got {df}")
    if probability == 0.5:
        return 0.0
    z = _norm_ppf(probability)
    guess = z + (z * z * z + z) / (4.0 * df)
    value = guess
    for _ in range(30):
        density = _student_t_pdf(value, df)
        if density <= 0.0 or not math.isfinite(density):
            break
        step = (_student_t_cdf(value, df) - probability) / density
        value -= step
        if abs(step) <= 1e-12 * max(1.0, abs(value)):
            break
    if not math.isfinite(value):
        raise ValueError("Student t quantile was not finite")
    return value


def _sample_variance(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        raise ValueError("variance needs two values")
    center = sum(values) / n
    return sum((value - center) ** 2 for value in values) / (n - 1)


def percentile_linear(values: list[float], pct: float) -> float:
    """Linear percentile, rank (pct/100)*(n-1), matching the usual type-7 definition."""
    ys = sorted(values)
    if len(ys) == 1:
        return ys[0]
    rank = (pct / 100.0) * (len(ys) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ys[lo]
    weight = rank - lo
    return ys[lo] * (1.0 - weight) + ys[hi] * weight


def finite_samples(samples) -> list[float]:
    out: list[float] = []
    if not isinstance(samples, list):
        return out
    for item in samples:
        if isinstance(item, list):
            raise ValueError("nested sample list; expected one list per parameter")
        if item is None:
            continue
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            out.append(value)
    return out


def load_result(path: Path) -> dict:
    data = json.loads(path.read_text())
    columns = data["result_columns"]
    parsed = {}
    for name, row in data["results"].items():
        parsed[name] = dict(zip(columns, row))
    data["_parsed"] = parsed
    return data


def iter_param_slots(entry: dict):
    params = entry.get("params") or []
    result = entry.get("result")
    samples = entry.get("samples")
    if not params:
        combos = [()]
    else:
        combos = list(itertools.product(*[list(axis) for axis in params]))
    n = len(combos)

    def slot(value, index):
        if value is None:
            return None
        if isinstance(value, list):
            if len(value) != n:
                raise ValueError(f"expected {n} parameter slots, got {len(value)}")
            return value[index]
        if n == 1:
            return value
        raise ValueError("scalar result for a parameterized benchmark")

    for index, combo in enumerate(combos):
        yield combo, slot(result, index), slot(samples, index)


def benchmark_label(name: str, combo: tuple) -> str:
    if not combo:
        return name
    rendered = ", ".join(str(part) for part in combo)
    return f"{name}({rendered})"


def is_memory(name: str) -> bool:
    return ".ray_" in name or name.startswith("ray_")


def is_time(name: str) -> bool:
    return ".time_" in name or name.startswith("time_")


def split_sides(samples: list[float], kind: str) -> tuple[list[float], list[float]]:
    if kind == "time":
        total = TIME_AA_ROUNDS * TIME_REPEAT
        per = TIME_SAMPLES_PER_SIDE
        if len(samples) != total:
            raise ValueError(
                f"time sample count {len(samples)} != {TIME_AA_ROUNDS}*{TIME_REPEAT}"
            )
        if per * 2 != total:
            raise ValueError("time A/A rounds do not split into two equal sides")
        earlier: list[float] = []
        later: list[float] = []
        for round_index in range(TIME_AA_ROUNDS):
            start = round_index * TIME_REPEAT
            chunk = samples[start : start + TIME_REPEAT]
            if round_index % 2 == 0:
                earlier.extend(chunk)
            else:
                later.extend(chunk)
        if len(earlier) != per or len(later) != per:
            raise ValueError("alternating time split was not even")
        return earlier, later
    if kind == "memory":
        if MEM_AA_ROUNDS % 2 != 0:
            raise ValueError("MEM_AA_ROUNDS must be even")
        per = MEM_AA_ROUNDS // 2
        if len(samples) != MEM_AA_ROUNDS:
            raise ValueError(f"memory sample count {len(samples)} != {MEM_AA_ROUNDS}")
        earlier = samples[0::2]
        later = samples[1::2]
        if len(earlier) != per or len(later) != per:
            raise ValueError("alternating memory split was not even")
        return earlier, later
    raise ValueError(kind)


def kind_of(name: str) -> str | None:
    if is_time(name):
        return "time"
    if is_memory(name):
        return "memory"
    return None


def bounds_from_ratios(ratios: list[float]) -> dict:
    if len(ratios) < 10 or len(ratios) > 20:
        raise ValueError(f"need 10-20 main-vs-main ratios, got {len(ratios)}")
    center = median(ratios)
    deviation = mad(ratios)
    p01 = percentile_linear(ratios, 100 - WITHIN_RUN_UPPER_PERCENTILE)
    p99 = percentile_linear(ratios, WITHIN_RUN_UPPER_PERCENTILE)
    upper_mad = center + MAD_FENCE_MULTIPLIER * deviation
    lower_mad = center - MAD_FENCE_MULTIPLIER * deviation
    upper = max(p99, upper_mad)
    if lower_mad > 0:
        lower = min(p01, lower_mad)
    else:
        lower = p01
    if not (math.isfinite(lower) and math.isfinite(upper) and lower <= upper):
        raise ValueError(f"invalid bounds lower={lower} upper={upper}")
    return {
        "n": len(ratios),
        "ratios": ratios,
        "median_ratio": center,
        "mad": deviation,
        "p01": p01,
        "p99": p99,
        "upper_mad": upper_mad,
        "lower_mad": lower_mad,
        "lower": lower,
        "upper": upper,
    }


def between_run_side_bounds(
    side_pairs: list[tuple[float, float]], alpha: float
) -> dict:
    """Student t prediction limit for a ratio of two side medians.

    Each pair is the odd-round median and the even-round median from one
    repetition. Those two rounds are separate processes of one build, so a
    shared speed shift cancels in their ratio and the within-run bound is
    too narrow for base versus head. A comparison ratio is a new ratio of
    two side medians. The limit uses the paired variance of the log medians
    and does not use the comparison samples. The widest measured ratio is
    recorded and does not set the limit.
    """
    if len(side_pairs) < 10:
        raise ValueError(f"need at least 10 repetitions, got {len(side_pairs)}")
    if not 0.0 < alpha < 0.5:
        raise ValueError(f"alpha out of range: {alpha}")
    side_medians: list[float] = []
    mids: list[float] = []
    diffs: list[float] = []
    for odd, even in side_pairs:
        if odd <= 0 or even <= 0 or not math.isfinite(odd) or not math.isfinite(even):
            raise ValueError("non-positive side median")
        side_medians.append(odd)
        side_medians.append(even)
        log_odd = math.log(odd)
        log_even = math.log(even)
        mids.append(0.5 * (log_odd + log_even))
        diffs.append(log_odd - log_even)
    # var(one side) = var(pair mean) + var(pair difference) / 4.
    # A new log ratio of two independent sides then has variance twice that.
    var_side = _sample_variance(mids) + _sample_variance(diffs) / 4.0
    if var_side < 0.0 or not math.isfinite(var_side):
        var_side = 0.0
    df = len(side_pairs) - 1
    scale = math.sqrt(var_side * 2.0)
    t_crit = student_t_ppf(1.0 - alpha, float(df))
    log_limit = t_crit * scale
    upper = math.exp(log_limit)
    lower = 1.0 / upper
    lo = min(side_medians)
    hi = max(side_medians)
    ratios = [
        side_medians[j] / side_medians[i]
        for i in range(len(side_medians))
        for j in range(len(side_medians))
        if i != j
    ]
    center = median(ratios)
    deviation = mad(ratios)
    p01 = percentile_linear(ratios, 100 - WITHIN_RUN_UPPER_PERCENTILE)
    p99 = percentile_linear(ratios, WITHIN_RUN_UPPER_PERCENTILE)
    upper_mad = center + MAD_FENCE_MULTIPLIER * deviation
    lower_mad = center - MAD_FENCE_MULTIPLIER * deviation
    return {
        "n_sides": len(side_medians),
        "side_min": lo,
        "side_max": hi,
        "pair_n": len(ratios),
        "pair_median": center,
        "pair_mad": deviation,
        "pair_p01": p01,
        "pair_p99": p99,
        "pair_upper_mad": upper_mad,
        "pair_lower_mad": lower_mad,
        "widest": hi / lo,
        "pred_df": df,
        "pred_alpha": alpha,
        "pred_t": t_crit,
        "pred_scale": scale,
        "lower": lower,
        "upper": upper,
    }


def combine_time_bounds(within: dict, between: dict) -> dict:
    """Use the wider timing description.

    A ratio inside the prediction limit is not a slowdown, even when it
    sits above the within-run fence. The lower bound uses the reciprocal
    of that limit when the reciprocal is smaller.
    """
    info = dict(within)
    info["within_lower"] = within["lower"]
    info["within_upper"] = within["upper"]
    info["between_lower"] = between["lower"]
    info["between_upper"] = between["upper"]
    info["between_n_sides"] = between["n_sides"]
    info["between_side_min"] = between["side_min"]
    info["between_side_max"] = between["side_max"]
    info["between_pair_n"] = between["pair_n"]
    info["between_pair_median"] = between["pair_median"]
    info["between_pair_mad"] = between["pair_mad"]
    info["between_pair_p01"] = between["pair_p01"]
    info["between_pair_p99"] = between["pair_p99"]
    info["between_pair_upper_mad"] = between["pair_upper_mad"]
    info["between_pair_lower_mad"] = between["pair_lower_mad"]
    info["between_widest"] = between["widest"]
    info["between_pred_df"] = between["pred_df"]
    info["between_pred_alpha"] = between["pred_alpha"]
    info["between_pred_t"] = between["pred_t"]
    info["between_pred_scale"] = between["pred_scale"]
    info["lower"] = min(within["lower"], between["lower"])
    info["upper"] = max(within["upper"], between["upper"])
    if not (math.isfinite(info["lower"]) and math.isfinite(info["upper"])):
        raise ValueError("non-finite timing bounds")
    if info["lower"] > info["upper"]:
        raise ValueError("timing lower bound exceeds upper bound")
    return info


def peaks_by_label(path: Path, kind: str) -> dict[str, float]:
    """One asv invocation, one value per benchmark parameter.

    Timing benchmarks keep a sample list. Memory benchmarks (memray) return a
    single peak; asv does not append that scalar across rounds, so each
    memory round is its own result file.
    """
    data = load_result(path)
    found: dict[str, float] = {}
    for name, entry in data["_parsed"].items():
        if kind_of(name) != kind:
            continue
        for combo, result, samples in iter_param_slots(entry):
            label = benchmark_label(name, combo)
            cleaned = finite_samples(samples) if samples is not None else []
            if cleaned:
                if len(cleaned) != 1:
                    raise SystemExit(
                        f"{path} {label}: expected one peak in a memory round, got {len(cleaned)} samples"
                    )
                found[label] = cleaned[0]
                continue
            if result is None:
                continue
            try:
                value = float(result)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                found[label] = value
    return found


def time_samples_by_label(path: Path) -> dict[str, list[float]]:
    data = load_result(path)
    found: dict[str, list[float]] = {}
    for name, entry in data["_parsed"].items():
        if kind_of(name) != "time":
            continue
        for combo, _result, samples in iter_param_slots(entry):
            label = benchmark_label(name, combo)
            cleaned = finite_samples(samples) if samples is not None else []
            if cleaned:
                found[label] = cleaned
    return found


def _ratio_row(
    label: str, kind: str, earlier: list[float], later: list[float]
) -> float:
    expected = samples_per_side(kind)
    if len(earlier) != expected or len(later) != expected:
        raise SystemExit(
            f"{label}: side lengths {len(earlier)}, {len(later)} != {expected}"
        )
    med_earlier = median(earlier)
    med_later = median(later)
    if med_earlier <= 0 or med_later <= 0:
        raise SystemExit(f"{label}: non-positive median")
    return med_later / med_earlier


def collect_noise(aa_dir: Path, *, time_only: bool = False) -> dict:
    time_paths = sorted(aa_dir.glob("time-*.json"))
    if len(time_paths) < 10 or len(time_paths) > 20:
        raise SystemExit(f"expected 10-20 time repetitions, got {len(time_paths)}")
    mem_groups: dict[str, list[tuple[int, Path]]] = {}
    if not time_only:
        for path in sorted(aa_dir.glob("memory-*.json")):
            # memory-<rep>-<round>.json
            parts = path.stem.split("-")
            if len(parts) != 3:
                raise SystemExit(f"unexpected memory result name {path.name}")
            rep, rnd = parts[1], int(parts[2])
            mem_groups.setdefault(rep, []).append((rnd, path))
        if len(mem_groups) < 10 or len(mem_groups) > 20:
            raise SystemExit(
                f"expected 10-20 memory repetitions, got {len(mem_groups)}"
            )
        if len(mem_groups) != len(time_paths):
            raise SystemExit(
                f"time repetitions {len(time_paths)} != memory repetitions {len(mem_groups)}"
            )

    benchmarks: dict[str, dict] = {}

    per_time = [time_samples_by_label(path) for path in time_paths]
    time_labels = sorted({label for found in per_time for label in found})
    alpha = prediction_alpha(len(time_labels)) if time_labels else None
    for label in time_labels:
        ratios = []
        side_pairs = []
        per_side = None
        for found in per_time:
            if label not in found:
                raise SystemExit(f"{label} missing from a time repetition")
            try:
                earlier, later = split_sides(found[label], "time")
            except ValueError as exc:
                raise SystemExit(f"{label}: {exc}") from exc
            ratios.append(_ratio_row(label, "time", earlier, later))
            side_pairs.append((median(earlier), median(later)))
            per_side = len(earlier)
        within = bounds_from_ratios(ratios)
        between = between_run_side_bounds(side_pairs, alpha)
        info = combine_time_bounds(within, between)
        info["kind"] = "time"
        info["samples_per_side"] = per_side
        benchmarks[label] = info

    if not time_only:
        _collect_memory(benchmarks, mem_groups)

    if not benchmarks:
        raise SystemExit("no time or memory benchmarks in the main-vs-main files")
    return _noise_document(len(time_paths), benchmarks, alpha)


def _collect_memory(
    benchmarks: dict[str, dict], mem_groups: dict[str, list[tuple[int, Path]]]
) -> None:
    for rep, items in sorted(mem_groups.items()):
        rounds = [rnd for rnd, _path in items]
        if rounds != list(range(1, MEM_AA_ROUNDS + 1)):
            raise SystemExit(
                f"memory repetition {rep} rounds {rounds} != 1..{MEM_AA_ROUNDS}"
            )
    mem_reps = []
    for rep, items in sorted(mem_groups.items()):
        ordered = [peaks_by_label(path, "memory") for _rnd, path in sorted(items)]
        mem_reps.append(ordered)
    mem_labels = sorted({label for rep in mem_reps for snap in rep for label in snap})
    per_side_mem = MEM_AA_ROUNDS // 2
    for label in mem_labels:
        ratios = []
        for rep in mem_reps:
            series = []
            for snap in rep:
                if label not in snap:
                    raise SystemExit(f"{label} missing from a memory round")
                series.append(snap[label])
            earlier = series[0::2]
            later = series[1::2]
            ratios.append(_ratio_row(label, "memory", earlier, later))
        info = bounds_from_ratios(ratios)
        info["within_lower"] = info["lower"]
        info["within_upper"] = info["upper"]
        peaks = [value for rep in mem_reps for value in (snap[label] for snap in rep)]
        peak = median(peaks)
        granule = allocator_granule()
        granule_lower, granule_upper = memory_granule_bounds(peak, granule)
        # One granule on the base peak is the smallest change memray can
        # charge. A one-byte request is one granule or less. Timing does
        # not use this width. The granule is not a timing threshold.
        info["upper"] = max(info["upper"], granule_upper)
        info["lower"] = min(info["lower"], granule_lower)
        info["allocator_granule"] = granule
        info["peak_median"] = peak
        info["kind"] = "memory"
        info["samples_per_side"] = per_side_mem
        benchmarks[label] = info


def _noise_document(n_time: int, benchmarks: dict, alpha: float | None) -> dict:
    return {
        "aa_runs": n_time,
        "time_repeat": TIME_REPEAT,
        "time_aa_rounds": TIME_AA_ROUNDS,
        "time_samples_per_side": TIME_SAMPLES_PER_SIDE,
        "memory_aa_rounds": MEM_AA_ROUNDS,
        "memory_samples_per_side": MEM_SAMPLES_PER_SIDE,
        "compare_rounds": COMPARE_ROUNDS,
        "false_slowdown_budget": FALSE_SLOWDOWN_BUDGET,
        "prediction_alpha": alpha,
        "allocator_granule": allocator_granule(),
        "sample_time": SAMPLE_TIME,
        "rule": (
            "Within-run upper = max(linear p99, median + 3*median absolute deviation); "
            "within-run lower = min(linear p01, median - 3*median absolute deviation) "
            "if that bound is positive, else p01. "
            "Each within-run ratio is median(later)/median(earlier). "
            "Time within one run: twelve asv rounds inside one --interleave-rounds run, "
            "odd rounds against even rounds, 36 samples a side, matching the comparison's "
            "six rounds of six repeats. "
            "The comparison runs one round of the base commit and then one round of the "
            "head commit, and repeats that pair. "
            "asv continuous --interleave-rounds reverses commit order on even rounds, "
            "so an even round count would give the commits different numbers of "
            "back-to-back rounds. "
            "Each round is its own process of one installed build. A speed shift that "
            "covers an odd round and the following even round cancels in their ratio. "
            "Time between runs: each repetition contributes the odd-round median and the "
            "even-round median. The between-run upper bound is a Student t prediction "
            "limit for a new ratio of two side medians. The log scale is the square root "
            "of twice the paired side-median variance. The degrees of freedom are one "
            "less than the repetition count. The one-sided miss probability is the "
            "false-slowdown budget divided by the number of timing benchmarks in this "
            "comparison. The between-run lower bound is the reciprocal. "
            "The widest side-median ratio, the pairwise 99th percentile, and median + "
            "3*median absolute deviation of those side ratios are logged and do not set "
            "the bound. "
            "The timing upper bound is the wider of the within-run and between-run upper "
            "bounds. The timing lower bound is the smaller of the two lower bounds. "
            "The timing comparison runs after the timing repetitions and before the "
            "memory repetitions. "
            "Memory: successive one-round asv runs, odd rounds vs even rounds, then "
            "widened by one allocator granule over the median base peak. The granule "
            "is malloc_usable_size of a one-byte malloc. Memray returns one peak per "
            "invocation and asv does not store that scalar in samples across rounds, "
            "so memory rounds are separate asv runs. Timing does not use the granule."
        ),
        "benchmarks": benchmarks,
    }


def interquartile_range(values: list[float]) -> float:
    """Type-7 75th percentile minus the type-7 25th percentile."""
    if len(values) < 2:
        raise ValueError("IQR needs two samples")
    return percentile_linear(values, 75) - percentile_linear(values, 25)


def _side_fields(samples: list[float]) -> dict:
    if len(samples) < 2:
        return {
            "n": len(samples),
            "median": None,
            "iqr": None,
        }
    return {
        "n": len(samples),
        "median": median(samples),
        "iqr": interquartile_range(samples),
    }


def human_value(value: float, kind: str) -> str:
    if kind == "memory":
        number = float(value)
        for unit, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
            if abs(number) >= scale:
                return f"{number / scale:.3g}{unit}"
        return f"{number:.0f}B"
    number = float(value)
    for unit, scale in (("s", 1.0), ("ms", 1e3), ("us", 1e6), ("ns", 1e9)):
        scaled = number * scale
        if abs(scaled) >= 1.0 or unit == "ns":
            return f"{scaled:.3g}{unit}"
    return f"{number:.3g}s"


def _series_from_result_file(path: Path, kind: str) -> dict[str, list[float]]:
    data = load_result(path)
    found: dict[str, list[float]] = {}
    for name, entry in data["_parsed"].items():
        if kind_of(name) != kind:
            continue
        for combo, _result, samples in iter_param_slots(entry):
            label = benchmark_label(name, combo)
            cleaned = finite_samples(samples) if samples is not None else []
            if cleaned:
                found[label] = cleaned
    return found


def memory_series(cmp_dir: Path, commit: str) -> dict[str, list[float]]:
    prefix = commit[:8]
    numbered = []
    for path in cmp_dir.glob(f"{prefix}-r*.json"):
        rnd = int(path.stem.rsplit("-r", 1)[1])
        numbered.append((rnd, path))
    numbered.sort()
    expected = list(range(1, COMPARE_ROUNDS + 1))
    if [rnd for rnd, _path in numbered] != expected:
        raise SystemExit(
            f"memory rounds for {prefix} are {[rnd for rnd, _p in numbered]}, expected {expected}"
        )
    snaps = [peaks_by_label(path, "memory") for _rnd, path in numbered]
    labels = sorted({label for snap in snaps for label in snap})
    series: dict[str, list[float]] = {}
    for label in labels:
        values = []
        for snap in snaps:
            if label not in snap:
                raise SystemExit(f"{label} missing from a {prefix} memory round")
            values.append(snap[label])
        series[label] = values
    return series


def _presence_row(
    label: str,
    kind: str,
    mark: str,
    call: str,
    base_samples: list[float],
    head_samples: list[float],
) -> dict:
    def side(samples: list[float]) -> str:
        if not samples:
            return "n/a"
        return human_value(median(samples), kind)

    base_stats = _side_fields(base_samples)
    head_stats = _side_fields(head_samples)
    return {
        "mark": mark,
        "before": side(base_samples),
        "after": side(head_samples),
        "ratio": "n/a",
        "ratio_num": math.nan,
        "benchmark": label,
        "kind": kind,
        "call": call,
        "base_n": base_stats["n"],
        "head_n": head_stats["n"],
        "base_median": base_stats["median"],
        "head_median": head_stats["median"],
        "base_iqr": base_stats["iqr"],
        "head_iqr": head_stats["iqr"],
    }


def _judge(
    label: str, kind: str, base_samples: list[float], head_samples: list[float], band
) -> dict:
    expected = samples_per_side(kind)
    base_ok = len(base_samples) == expected
    head_ok = len(head_samples) == expected
    # A benchmark only the head can run is new. One only the base can run
    # was removed. Neither fails the job.
    if head_ok and not base_ok:
        return _presence_row(
            label, kind, "new", "new benchmark", base_samples, head_samples
        )
    if base_ok and not head_ok:
        return _presence_row(
            label, kind, "removed", "removed benchmark", base_samples, head_samples
        )
    if not base_ok or not head_ok or band is None:
        return {
            "mark": "!",
            "before": "n/a" if not base_ok else human_value(median(base_samples), kind),
            "after": "n/a" if not head_ok else human_value(median(head_samples), kind),
            "ratio": "n/a",
            "ratio_num": math.nan,
            "benchmark": label,
            "kind": kind,
            "call": "missing noise band" if band is None else "wrong sample count",
        }
    before = median(base_samples)
    after = median(head_samples)
    if before <= 0:
        ratio_num = math.inf
        ratio_text = "n/a"
    else:
        ratio_num = after / before
        ratio_text = format_lossless(ratio_num)
    upper = band["upper"]
    lower = band["lower"]
    if math.isfinite(ratio_num) and ratio_num > upper:
        mark = "+"
        call = "significant slowdown"
    elif math.isfinite(ratio_num) and ratio_num < lower:
        mark = "-"
        call = "significant speedup"
    else:
        mark = " "
        call = "not significant"
        if math.isfinite(ratio_num):
            ratio_text = "~" + ratio_text
    return {
        "mark": mark,
        "before": human_value(before, kind),
        "after": human_value(after, kind),
        "ratio": ratio_text,
        "ratio_num": ratio_num,
        "benchmark": label,
        "kind": kind,
        "call": call,
        "lower": lower,
        "upper": upper,
        "within_upper": band.get("within_upper"),
        "between_upper": band.get("between_upper"),
        "base_n": len(base_samples),
        "head_n": len(head_samples),
        "base_median": before,
        "head_median": after,
        "base_iqr": interquartile_range(base_samples),
        "head_iqr": interquartile_range(head_samples),
    }


def comparison_rows(
    base_path: Path,
    head_path: Path,
    mem_dir: Path,
    base_commit: str,
    head_commit: str,
    noise: dict,
) -> list[dict]:
    base_time = _series_from_result_file(base_path, "time")
    head_time = _series_from_result_file(head_path, "time")
    base_mem = memory_series(mem_dir, base_commit)
    head_mem = memory_series(mem_dir, head_commit)
    rows = []
    for label in sorted(set(base_time) | set(head_time)):
        rows.append(
            _judge(
                label,
                "time",
                base_time.get(label, []),
                head_time.get(label, []),
                noise["benchmarks"].get(label),
            )
        )
    for label in sorted(set(base_mem) | set(head_mem)):
        rows.append(
            _judge(
                label,
                "memory",
                base_mem.get(label, []),
                head_mem.get(label, []),
                noise["benchmarks"].get(label),
            )
        )
    return rows


def _upper_text(value) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return format_lossless(number)


def render_table(rows: list[dict]) -> str:
    header = (
        "| Change | Before | After | Ratio | Benchmark | Upper "
        "| N | Base median | Head median | Base IQR | Head IQR |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for row in rows:
        mark = row["mark"] if row["mark"] != " " else " "
        base_n = row.get("base_n")
        head_n = row.get("head_n")
        if base_n == head_n and base_n is not None:
            count = str(base_n)
        elif base_n is None and head_n is None:
            count = "n/a"
        else:
            count = f"{base_n}/{head_n}"
        lines.append(
            "| {mark} | {before} | {after} | {ratio} | {benchmark} | {upper} "
            "| {count} | {base_median} | {head_median} | {base_iqr} | {head_iqr} |".format(
                mark=mark,
                before=row["before"],
                after=row["after"],
                ratio=row["ratio"],
                benchmark=row["benchmark"],
                upper=_upper_text(row.get("upper")),
                count=count,
                base_median=_upper_text(row.get("base_median")),
                head_median=_upper_text(row.get("head_median")),
                base_iqr=_upper_text(row.get("base_iqr")),
                head_iqr=_upper_text(row.get("head_iqr")),
            )
        )
    return "\n".join(lines)


def render_row_bounds(rows: list[dict]) -> str:
    """One line per judged benchmark. The upper column is the bound the row uses."""
    lines = ["benchmark\twithin_upper\tbetween_upper\tupper"]
    for row in rows:
        if "upper" not in row:
            continue
        lines.append(
            "\t".join(
                [
                    row["benchmark"],
                    _upper_text(row.get("within_upper")),
                    _upper_text(row.get("between_upper")),
                    _upper_text(row["upper"]),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def render_noise_block(noise: dict) -> str:
    lines = [
        "main-vs-main noise (same commit, same runner)",
        f"repetitions: {noise['aa_runs']}",
        (
            f"samples per side: time {TIME_SAMPLES_PER_SIDE} "
            f"({TIME_AA_ROUNDS} rounds of {TIME_REPEAT}, odd rounds vs even rounds), "
            f"memory {MEM_SAMPLES_PER_SIDE} (alternating rounds)"
        ),
        "within-run bound: upper = max(p99, median + 3*median absolute deviation) of median(later)/median(earlier); lower = min(p01, median - 3*median absolute deviation) when positive, else p01",
        (
            "timing between-run bound: Student t prediction limit for a ratio of two side "
            "medians (odd-round median and even-round median from each repetition). "
            f"false-slowdown budget {FALSE_SLOWDOWN_BUDGET} split across the timing rows "
            f"in this comparison, one-sided alpha {noise.get('prediction_alpha')}. "
            "The lower bound is the reciprocal"
        ),
        "timing derivation: the widest side-median ratio, the pairwise 99th percentile, and median + 3*median absolute deviation of those side ratios are recorded below and do not set the bound",
        "timing noise band: wider upper bound and smaller lower bound of the within-run and between-run bounds",
        "memory noise band: the within-run bound, widened by one allocator granule over the median base peak. Timing does not use that granule",
        "a row is significant only when the head/base median ratio is outside that benchmark's noise band",
        "a blank Change mark is not significant; the ratio is prefixed with ~",
        "+ is a significant slowdown; - is a significant speedup; ! is missing samples or no noise band",
        "",
        "\t".join(
            [
                "benchmark",
                "kind",
                "n",
                "samples_per_side",
                "median_ratio",
                "mad",
                "p01",
                "p99",
                "within_lower",
                "within_upper",
                "between_n_sides",
                "between_side_min",
                "between_side_max",
                "between_pair_p99",
                "between_pair_upper_mad",
                "between_widest",
                "between_pred_df",
                "between_pred_alpha",
                "between_pred_t",
                "between_pred_scale",
                "between_lower",
                "between_upper",
                "lower",
                "upper",
            ]
        ),
    ]
    for label, info in sorted(noise["benchmarks"].items()):
        lines.append(
            "\t".join(
                [
                    label,
                    info["kind"],
                    str(info["n"]),
                    str(info["samples_per_side"]),
                    format_lossless(info["median_ratio"]),
                    format_lossless(info["mad"]),
                    format_lossless(info["p01"]),
                    format_lossless(info["p99"]),
                    _fmt_opt(info.get("within_lower")),
                    _fmt_opt(info.get("within_upper")),
                    _fmt_opt(info.get("between_n_sides"), integer=True),
                    _fmt_opt(info.get("between_side_min")),
                    _fmt_opt(info.get("between_side_max")),
                    _fmt_opt(info.get("between_pair_p99")),
                    _fmt_opt(info.get("between_pair_upper_mad")),
                    _fmt_opt(info.get("between_widest")),
                    _fmt_opt(info.get("between_pred_df"), integer=True),
                    _fmt_opt(info.get("between_pred_alpha")),
                    _fmt_opt(info.get("between_pred_t")),
                    _fmt_opt(info.get("between_pred_scale")),
                    _fmt_opt(info.get("between_lower")),
                    _fmt_opt(info.get("between_upper")),
                    format_lossless(info["lower"]),
                    format_lossless(info["upper"]),
                ]
            )
        )
    return "\n".join(lines)


def _fmt_opt(value, integer: bool = False) -> str:
    if value is None:
        return ""
    if integer:
        return str(int(value))
    return format_lossless(value)


def perch_rows(table: str) -> list[dict]:
    """Mirror the comment action's pipe-table parser enough to catch a bad table."""
    parsed = []
    for line in table.splitlines():
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 7:
            continue
        second = cells[1]
        if second in {"Change", "Before"} or (
            len(second) >= 2 and set(second) <= {"-"}
        ):
            continue
        if not cells[5]:
            continue
        parsed.append(
            {
                "mark": second,
                "before": cells[2],
                "after": cells[3],
                "ratio": cells[4],
                "benchmark": cells[5],
            }
        )
    return parsed


def find_commit_result(results_dir: Path, commit: str) -> Path:
    prefix = commit[:8]
    matches = [
        path
        for path in results_dir.rglob("*.json")
        if path.name.startswith(prefix)
        and path.name != "benchmarks.json"
        and "machine" not in path.name
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one result for {commit} under {results_dir}, found {matches}"
        )
    return matches[0]


def resolve_commit(name: str) -> str:
    import subprocess

    out = subprocess.check_output(
        ["git", "rev-parse", f"{name}^{{commit}}"], text=True
    ).strip()
    return out


def assert_distinct_commits(base: str, head: str) -> None:
    """A PR comparison of one commit with itself is not a measurement."""
    if base == head:
        raise SystemExit(f"refusing to compare a commit with itself: {base}")


def regression_exit_code(rows: list[dict]) -> int:
    """Fail the job on a significant slowdown or on missing samples.

    A significant speedup stays in the table and does not fail the job.
    """
    if any(row["mark"] in {"+", "!"} for row in rows):
        return 1
    return 0


def cmd_derive_conf(args: argparse.Namespace) -> None:
    cfg = json.loads(Path(args.src).read_text())
    cfg["results_dir"] = args.results_dir
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, indent=4) + "\n")


def cmd_copy_result(args: argparse.Namespace) -> None:
    commit = resolve_commit(args.commit)
    src = find_commit_result(Path(args.results_dir), commit)
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text())


def kind_upper_bounds(noise: dict) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for info in noise["benchmarks"].values():
        grouped.setdefault(info["kind"], []).append(float(info["upper"]))
    return grouped


def kind_thresholds(noise: dict) -> dict[str, float]:
    """Minimum upper bound of each kind.

    The timing threshold is the minimum timing upper bound. A memory upper
    bound of 1 does not become that number.
    """
    return {kind: min(uppers) for kind, uppers in kind_upper_bounds(noise).items()}


def action_threshold(rows: list[dict], noise: dict) -> float:
    """Number the commenter compares with slowed rows.

    asv-perch keeps one threshold and applies it to rows marked slowed.
    Kinds that have a slowed row contribute their own minimum upper bound.
    With no slowed row, the timing threshold is the number on record.
    A memory upper bound of 1 is included only when a memory row slowed.
    """
    thresholds = kind_thresholds(noise)
    if "time" not in thresholds:
        raise SystemExit("no timing benchmarks in the noise file")
    slowed = {row["kind"] for row in rows if row["mark"] == "+"}
    if not slowed:
        return thresholds["time"]
    return min(thresholds[kind] for kind in slowed)


def commenter_should_draft(rows: list[dict], noise: dict) -> bool:
    """Per-kind form of the commenter's draft check.

    The commenter drafts when a slowed row's ratio is at least the
    threshold. Here the threshold is that row's kind, so a timing row is
    not judged by a memory bound.
    """
    thresholds = kind_thresholds(noise)
    for row in rows:
        if row["mark"] != "+":
            continue
        if row["ratio_num"] >= thresholds[row["kind"]]:
            return True
    return False


def cmd_aa_noise(args: argparse.Namespace) -> None:
    noise = collect_noise(Path(args.aa_dir), time_only=args.time_only)
    thresholds = kind_thresholds(noise)
    if "time" not in thresholds:
        raise SystemExit("no timing benchmarks in the noise file")
    time_uppers = kind_upper_bounds(noise)["time"]
    noise["time_regression_threshold"] = thresholds["time"]
    noise["memory_regression_threshold"] = thresholds.get("memory")
    # The file the commenter reads is chosen again after the comparison,
    # from the kinds that actually slowed. This copy is the timing bound.
    noise["regression_threshold"] = thresholds["time"]
    noise["asv_factor"] = max(max(time_uppers), 1.0)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(noise, indent=2) + "\n")
    if args.factor_out:
        Path(args.factor_out).write_text(format_lossless(noise["asv_factor"]) + "\n")
    if args.threshold_out:
        Path(args.threshold_out).write_text(format_lossless(thresholds["time"]) + "\n")
    if args.time_only:
        if not args.factor_out or not args.threshold_out:
            raise SystemExit("time-only noise needs --factor-out and --threshold-out")
        return
    memory_value = thresholds.get("memory")
    if memory_value is None:
        raise SystemExit("no memory benchmarks in the noise file")
    if not args.memory_threshold_out:
        raise SystemExit("full noise needs --memory-threshold-out")
    Path(args.memory_threshold_out).write_text(format_lossless(memory_value) + "\n")


def cmd_report(args: argparse.Namespace) -> None:
    noise = json.loads(Path(args.noise).read_text())
    base = resolve_commit(args.base)
    head = resolve_commit(args.head)
    assert_distinct_commits(base, head)
    base_path = find_commit_result(Path(args.results_dir), base)
    head_path = find_commit_result(Path(args.results_dir), head)
    rows = comparison_rows(base_path, head_path, Path(args.mem_dir), base, head, noise)
    table = render_table(rows)
    parsed = perch_rows(table)
    if len(parsed) != len(rows):
        raise SystemExit(
            f"table parse produced {len(parsed)} rows from {len(rows)} benchmarks"
        )
    significant = [row for row in rows if row["mark"] in {"+", "-"}]
    not_significant = [row for row in rows if row["mark"] == " "]
    failed = [row for row in rows if row["mark"] == "!"]
    thresholds = kind_thresholds(noise)
    chosen = action_threshold(rows, noise)
    draft = commenter_should_draft(rows, noise)
    summary = [
        f"significant: {len(significant)}",
        f"not significant: {len(not_significant)}",
        f"missing: {len(failed)}",
        (
            "minimum timing upper bound (smallest row upper, not the flag): "
            + format_lossless(thresholds["time"])
        ),
        (
            "memory regression threshold (minimum memory upper bound): "
            + format_lossless(thresholds["memory"])
        ),
        (
            "commenter threshold (minimum upper bound of slowed kinds, else timing): "
            + format_lossless(chosen)
        ),
        ("commenter draft: " + ("yes" if draft else "no")),
        (
            "asv compare --factor (maximum timing upper bound, at least 1): "
            + format_lossless(noise["asv_factor"])
        ),
        "",
    ]
    text = "\n".join(summary) + render_noise_block(noise) + "\n\n" + table + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    meta = Path(args.metadata)
    meta.write_text(
        f"main_sha={base}\npr_sha={head}\naa_runs={noise['aa_runs']}\n"
        f"time_regression_threshold={format_lossless(thresholds['time'])}\n"
        f"memory_regression_threshold={format_lossless(thresholds['memory'])}\n"
        f"minimum_timing_upper_bound={format_lossless(chosen)}\n"
        f"commenter_draft={'yes' if draft else 'no'}\n"
    )
    calls = Path(args.calls)
    calls.write_text(
        "\n".join(f"{row['call']}\t{row['benchmark']}" for row in rows) + "\n"
    )
    # Written after the table. The Snakefile check rule reads this and fails
    # the workflow without deleting the report the commenter posts.
    status = regression_exit_code(rows)
    status_path = Path(args.check_status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(f"{status}\n")
    bounds_path = Path(args.bounds_out)
    bounds_path.parent.mkdir(parents=True, exist_ok=True)
    bounds_path.write_text(render_row_bounds(rows))
    decision_path = Path(args.decision_out)
    decision_path.write_text(
        "\n".join(
            [
                "draft=" + ("yes" if draft else "no"),
                "time_threshold=" + format_lossless(thresholds["time"]),
                "memory_threshold=" + format_lossless(thresholds["memory"]),
                "action_threshold=" + format_lossless(chosen),
                "success_condition=not_met" if status else "success_condition=met",
                "",
            ]
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    derive = sub.add_parser("derive-conf")
    derive.add_argument("src")
    derive.add_argument("dest")
    derive.add_argument("results_dir")
    derive.set_defaults(func=cmd_derive_conf)

    copy = sub.add_parser("copy-result")
    copy.add_argument("results_dir")
    copy.add_argument("commit")
    copy.add_argument("dest")
    copy.set_defaults(func=cmd_copy_result)

    noise = sub.add_parser("aa-noise")
    noise.add_argument("aa_dir")
    noise.add_argument("--out", required=True)
    noise.add_argument("--factor-out")
    noise.add_argument("--threshold-out")
    noise.add_argument("--memory-threshold-out")
    noise.add_argument("--time-only", action="store_true")
    noise.set_defaults(func=cmd_aa_noise)

    report = sub.add_parser("report")
    report.add_argument("--noise", required=True)
    report.add_argument("--results-dir", required=True)
    report.add_argument("--mem-dir", required=True)
    report.add_argument("--base", required=True)
    report.add_argument("--head", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--metadata", required=True)
    report.add_argument("--calls", required=True)
    report.add_argument("--check-status", required=True)
    report.add_argument("--bounds-out", required=True)
    report.add_argument("--decision-out", required=True)
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
