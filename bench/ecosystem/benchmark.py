#!/usr/bin/env python3
"""Ecosystem exchange benchmarks for readcon-core."""

from __future__ import annotations

import argparse
import csv
import ctypes
import gc
import json
import os
import platform
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

SIZES = (1_000, 10_000, 100_000, 1_000_000)
REPEATS = 6
WARMUPS = 2
CSV_COLUMNS = (
    "item",
    "arm",
    "n_atoms",
    "dtype",
    "repeat",
    "wall_s",
    "device",
    "status",
)


class DLDataType(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_uint8),
        ("bits", ctypes.c_uint8),
        ("lanes", ctypes.c_uint16),
    ]


class DLDevice(ctypes.Structure):
    _fields_ = [("device_type", ctypes.c_int32), ("device_id", ctypes.c_int32)]


class DLTensor(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("device", DLDevice),
        ("ndim", ctypes.c_int32),
        ("dtype", DLDataType),
        ("shape", ctypes.POINTER(ctypes.c_int64)),
        ("strides", ctypes.POINTER(ctypes.c_int64)),
        ("byte_offset", ctypes.c_uint64),
    ]


class DLPackVersion(ctypes.Structure):
    _fields_ = [("major", ctypes.c_uint32), ("minor", ctypes.c_uint32)]


class DLManagedTensorVersioned(ctypes.Structure):
    pass


DLManagedTensorVersioned._fields_ = [
    ("version", DLPackVersion),
    ("manager_ctx", ctypes.c_void_p),
    ("deleter", ctypes.c_void_p),
    ("flags", ctypes.c_uint64),
    ("dl_tensor", DLTensor),
]


class RKRDlpackExportOptions(ctypes.Structure):
    _fields_ = [("dtype", DLDataType), ("device", DLDevice)]


@dataclass
class Row:
    item: str
    arm: str
    n_atoms: int
    dtype: str
    repeat: int
    wall_s: float | None
    device: str
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "item": self.item,
            "arm": self.arm,
            "n_atoms": self.n_atoms,
            "dtype": self.dtype,
            "repeat": self.repeat,
            "wall_s": "" if self.wall_s is None else f"{self.wall_s:.9e}",
            "device": self.device,
            "status": self.status,
        }


class Native:
    def __init__(self, library: Path, probe: Path):
        self.lib = ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
        self.probe = ctypes.CDLL(str(probe))
        self.lib.rkr_read_first_frame.argtypes = [ctypes.c_char_p]
        self.lib.rkr_read_first_frame.restype = ctypes.c_void_p
        self.lib.free_rkr_frame.argtypes = [ctypes.c_void_p]
        self.lib.free_rkr_frame.restype = None
        self.lib.rkr_frame_positions_dlpack_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(RKRDlpackExportOptions),
            ctypes.POINTER(ctypes.POINTER(DLManagedTensorVersioned)),
        ]
        self.lib.rkr_frame_positions_dlpack_ex.restype = ctypes.c_int
        self.lib.rkr_dlpack_delete.argtypes = [ctypes.POINTER(DLManagedTensorVersioned)]
        self.lib.rkr_dlpack_delete.restype = None
        self.lib.rkr_frame_metatensor_positions_block.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.lib.rkr_frame_metatensor_positions_block.restype = ctypes.c_int
        self.lib.rkr_mts_block_free.argtypes = [ctypes.c_void_p]
        self.lib.rkr_mts_block_free.restype = None
        self.probe.bench_block_shape.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.probe.bench_block_shape.restype = ctypes.c_int
        self.probe.bench_block_copy_f64.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_size_t,
        ]
        self.probe.bench_block_copy_f64.restype = ctypes.c_int

    def read(self, path: Path) -> ctypes.c_void_p:
        frame = self.lib.rkr_read_first_frame(os.fsencode(path))
        if not frame:
            raise RuntimeError(f"native read failed for {path.name}")
        return ctypes.c_void_p(frame)

    def export(self, frame: ctypes.c_void_p, bits: int):
        options = RKRDlpackExportOptions(
            DLDataType(2, bits, 1),
            DLDevice(1, 0),
        )
        tensor = ctypes.POINTER(DLManagedTensorVersioned)()
        status = self.lib.rkr_frame_positions_dlpack_ex(
            frame, ctypes.byref(options), ctypes.byref(tensor)
        )
        if status != 0 or not tensor:
            raise RuntimeError(f"DLPack export failed with status {status}")
        return tensor

    def numpy_view(self, managed) -> np.ndarray:
        tensor = managed.contents.dl_tensor
        if tensor.device.device_type != 1 or tensor.dtype.code != 2:
            raise RuntimeError("benchmark expected a CPU floating-point tensor")
        shape = tuple(int(tensor.shape[i]) for i in range(tensor.ndim))
        count = int(np.prod(shape, dtype=np.int64))
        address = int(tensor.data) + int(tensor.byte_offset)
        ctype = ctypes.c_float if tensor.dtype.bits == 32 else ctypes.c_double
        flat = np.ctypeslib.as_array((ctype * count).from_address(address))
        if tensor.strides:
            itemsize = ctypes.sizeof(ctype)
            strides = tuple(
                int(tensor.strides[i]) * itemsize for i in range(tensor.ndim)
            )
            return np.lib.stride_tricks.as_strided(flat, shape=shape, strides=strides)
        return flat.reshape(shape)

    def metatensor_values(self, block: ctypes.c_void_p, n: int) -> np.ndarray:
        rows = ctypes.c_size_t()
        cols = ctypes.c_size_t()
        status = self.probe.bench_block_shape(
            block, ctypes.byref(rows), ctypes.byref(cols)
        )
        if status != 0 or (rows.value, cols.value) != (n, 3):
            raise AssertionError(
                f"unexpected TensorBlock shape/status: {rows.value}x{cols.value}/{status}"
            )
        values = np.empty((n, 3), dtype=np.float64)
        status = self.probe.bench_block_copy_f64(
            block,
            values.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            values.size,
        )
        if status != 0:
            raise AssertionError(f"TensorBlock value copy failed with status {status}")
        return values


def write_seed(path: Path, n: int, dtype: str) -> None:
    metadata = {
        "con_spec_version": 3,
        "units": {"length": "angstrom", "energy": "eV"},
        "storage_dtypes": {"positions": dtype},
    }
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ecosystem benchmark\n")
        handle.write(json.dumps(metadata, separators=(",", ":")) + "\n")
        handle.write("1000 1000 1000\n90 90 90\n0 0\n0 0 0\n1\n")
        handle.write(f"{n}\n1.00794\nH\nCoordinates of Component 1\n")
        for index in range(n):
            x = (index % 997) * 0.001
            y = (index % 499) * 0.002
            z = (index % 251) * 0.003
            handle.write(f"{x:.6f} {y:.6f} {z:.6f} 0 {index}\n")


def create_frames(readcon, work: Path) -> dict[tuple[int, str], Path]:
    paths = {}
    for n in SIZES:
        for dtype in ("float64", "float32"):
            output = work / f"frame-{n}-{dtype}.con"
            seed = work / f"seed-{n}-{dtype}.con"
            write_seed(seed, n, dtype)
            frames = readcon.read_con(str(seed))
            if len(frames) != 1 or len(frames[0]) != n:
                raise AssertionError(f"seed parse failed for {n}/{dtype}")
            readcon.write_con(str(output), frames)
            seed.unlink()
            reparsed = readcon.read_con(str(output))
            if len(reparsed) != 1 or len(reparsed[0]) != n:
                raise AssertionError(
                    f"readcon output verification failed for {n}/{dtype}"
                )
            paths[n, dtype] = output
    return paths


def elapsed(call: Callable[[], object]) -> float:
    gc.disable()
    try:
        start = time.perf_counter()
        result = call()
        end = time.perf_counter()
        del result
        return end - start
    finally:
        gc.enable()


def measure_pair(
    rows: list[Row],
    *,
    item: str,
    n: int,
    dtype: str,
    device: str,
    first: tuple[str, Callable[[], object]],
    second: tuple[str, Callable[[], object]],
) -> None:
    for _ in range(WARMUPS):
        first[1]()
        second[1]()
    lead_order = ("A", "B", "B", "A")
    for repeat in range(REPEATS):
        pair = (first, second) if lead_order[repeat % 4] == "A" else (second, first)
        for name, call in pair:
            rows.append(
                Row(
                    item,
                    name,
                    n,
                    dtype,
                    repeat,
                    elapsed(call),
                    device,
                    "MEASURED",
                )
            )


def no_cuda_rows(rows: list[Row]) -> None:
    arms = (
        "positions_readcon_cuda",
        "positions_numpy_cupy",
        "positions_torch_cuda",
        "forces_readcon_cuda",
        "forces_numpy_cupy",
        "forces_torch_cuda",
    )
    for n in SIZES:
        for arm in arms:
            for repeat in range(REPEATS):
                rows.append(
                    Row(
                        "1_cuda_dlpack",
                        arm,
                        n,
                        "float64",
                        repeat,
                        None,
                        "cuda",
                        "NO_CUDA",
                    )
                )


def pointer_of(value) -> int:
    if isinstance(value, np.ndarray):
        return int(value.ctypes.data)
    if hasattr(value, "data_ptr"):
        return int(value.data_ptr())
    if hasattr(value, "unsafe_buffer_pointer"):
        return int(value.unsafe_buffer_pointer())
    raise TypeError(f"no pointer accessor for {type(value)!r}")


def item_two(rows: list[Row], readcon, paths) -> dict[str, bool]:
    import jax
    import jax.numpy as jnp
    import torch

    jax.config.update("jax_enable_x64", True)
    pointer_checks: dict[str, bool] = {}
    for n in SIZES:
        frame = readcon.read_con(str(paths[n, "float64"]))[0]
        base = np.ascontiguousarray(frame.xyz)

        torch_view = torch.from_dlpack(base)
        pointer_checks[f"torch_n{n}"] = pointer_of(torch_view) == pointer_of(base)
        if not pointer_checks[f"torch_n{n}"]:
            raise AssertionError("torch.from_dlpack did not alias the readcon array")

        def torch_dlpack():
            return torch.from_dlpack(base)

        def torch_copy():
            return torch.tensor(base)

        measure_pair(
            rows,
            item="2_python_zero_copy",
            n=n,
            dtype="float64",
            device="cpu",
            first=("torch_from_dlpack", torch_dlpack),
            second=("torch_tensor_copy", torch_copy),
        )

        jax_view = jax.dlpack.from_dlpack(base, copy=False)
        jax.block_until_ready(jax_view)
        pointer_checks[f"jax_n{n}"] = pointer_of(jax_view) == pointer_of(base)
        if not pointer_checks[f"jax_n{n}"]:
            raise AssertionError(
                "jax.dlpack.from_dlpack did not alias the readcon array"
            )

        def jax_dlpack():
            value = jax.dlpack.from_dlpack(base, copy=False)
            return jax.block_until_ready(value)

        def jax_copy():
            copied = np.array(base, copy=True)
            value = jnp.array(copied, copy=True)
            return jax.block_until_ready(value)

        measure_pair(
            rows,
            item="2_python_zero_copy",
            n=n,
            dtype="float64",
            device="cpu",
            first=("jax_from_dlpack", jax_dlpack),
            second=("jax_explicit_copy", jax_copy),
        )

        numpy_view = np.from_dlpack(base)
        pointer_checks[f"numpy_n{n}"] = pointer_of(numpy_view) == pointer_of(base)
        if not pointer_checks[f"numpy_n{n}"]:
            raise AssertionError("numpy.from_dlpack did not alias the readcon array")

        measure_pair(
            rows,
            item="2_python_zero_copy",
            n=n,
            dtype="float64",
            device="cpu",
            first=("numpy_from_dlpack", lambda: np.from_dlpack(base)),
            second=("numpy_copy", lambda: np.array(base, copy=True)),
        )

        for repeat in range(REPEATS):
            rows.append(
                Row(
                    "2_python_zero_copy",
                    "cupy_from_dlpack",
                    n,
                    "float64",
                    repeat,
                    None,
                    "cuda",
                    "NO_CUDA",
                )
            )
    return pointer_checks


def item_three(rows: list[Row], native: Native, paths) -> None:
    for n in SIZES:
        frame = native.read(paths[n, "float32"])

        def direct_f32():
            tensor = native.export(frame, 32)
            try:
                value = native.numpy_view(tensor)
                if value.dtype != np.float32 or value.shape != (n, 3):
                    raise AssertionError("bad direct float32 export")
                return value[0, 0]
            finally:
                native.lib.rkr_dlpack_delete(tensor)

        def f64_then_cast():
            tensor = native.export(frame, 64)
            try:
                value = native.numpy_view(tensor).astype(np.float32)
                if value.dtype != np.float32 or value.shape != (n, 3):
                    raise AssertionError("bad float64 cast result")
                return value
            finally:
                native.lib.rkr_dlpack_delete(tensor)

        measure_pair(
            rows,
            item="3_storage_dtype",
            n=n,
            dtype="float32",
            device="cpu",
            first=("float32_export", direct_f32),
            second=("float64_export_astype_float32", f64_then_cast),
        )
        native.lib.free_rkr_frame(frame)


def make_python_block(metatensor, positions: np.ndarray):
    n = len(positions)
    samples = metatensor.Labels(
        ["atom_id"], np.arange(n, dtype=np.int32).reshape(-1, 1)
    )
    properties = metatensor.Labels(["xyz"], np.arange(3, dtype=np.int32).reshape(-1, 1))
    return metatensor.TensorBlock(
        values=np.array(positions, dtype=np.float64, copy=True),
        samples=samples,
        components=[],
        properties=properties,
    )


def item_four(rows: list[Row], native: Native, readcon, paths) -> None:
    import ase.io
    import metatensor

    for n in SIZES:
        path = paths[n, "float64"]
        py_frame = readcon.read_con(str(path))[0]
        expected = np.asarray(py_frame.xyz)
        atoms = ase.io.read(path, format="eon")
        ase_positions = np.asarray(atoms.positions)
        if expected.shape != ase_positions.shape or not np.array_equal(
            expected, ase_positions
        ):
            raise AssertionError(f"readcon/ASE positions differ for n={n}")
        python_block = make_python_block(metatensor, ase_positions)
        if python_block.values.shape != (n, 3) or not np.array_equal(
            np.asarray(python_block.values), expected
        ):
            raise AssertionError(f"Python TensorBlock differs for n={n}")

        frame = native.read(path)
        block = ctypes.c_void_p()
        status = native.lib.rkr_frame_metatensor_positions_block(
            frame, ctypes.byref(block)
        )
        if status != 0 or not block:
            raise AssertionError(
                f"readcon TensorBlock export failed with status {status}"
            )
        native_values = native.metatensor_values(block, n)
        native.lib.rkr_mts_block_free(block)
        native.lib.free_rkr_frame(frame)
        if not np.array_equal(native_values, expected):
            raise AssertionError(f"native TensorBlock values differ for n={n}")

        def readcon_block():
            local_frame = native.read(path)
            local_block = ctypes.c_void_p()
            local_status = native.lib.rkr_frame_metatensor_positions_block(
                local_frame, ctypes.byref(local_block)
            )
            if local_status != 0 or not local_block:
                native.lib.free_rkr_frame(local_frame)
                raise RuntimeError(f"TensorBlock export status {local_status}")
            native.lib.rkr_mts_block_free(local_block)
            native.lib.free_rkr_frame(local_frame)

        def ase_block():
            local_atoms = ase.io.read(path, format="eon")
            return make_python_block(metatensor, np.asarray(local_atoms.positions))

        measure_pair(
            rows,
            item="4_metatensor",
            n=n,
            dtype="float64",
            device="cpu",
            first=("readcon_tensorblock", readcon_block),
            second=("ase_tensorblock", ase_block),
        )


def write_results(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(row.as_dict() for row in rows)


def write_summary(path: Path, rows: list[Row]) -> None:
    grouped: dict[tuple[str, str, int, str, str, str], list[float]] = {}
    for row in rows:
        key = (row.item, row.arm, row.n_atoms, row.dtype, row.device, row.status)
        grouped.setdefault(key, [])
        if row.wall_s is not None:
            grouped[key].append(row.wall_s)
    medians = {
        key: statistics.median(values) for key, values in grouped.items() if values
    }
    baseline = {
        "2_python_zero_copy": {
            "torch_from_dlpack": "torch_tensor_copy",
            "jax_from_dlpack": "jax_explicit_copy",
            "numpy_from_dlpack": "numpy_copy",
        },
        "3_storage_dtype": {
            "float32_export": "float64_export_astype_float32",
        },
        "4_metatensor": {
            "readcon_tensorblock": "ase_tensorblock",
        },
    }
    fields = (
        "item",
        "arm",
        "n_atoms",
        "dtype",
        "device",
        "status",
        "n_repeat",
        "median_s",
        "q1_s",
        "q3_s",
        "iqr_s",
        "ratio_vs_comparator",
        "comparator",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for key in sorted(grouped):
            item, arm, n, dtype, device, status = key
            values = grouped[key]
            comparator = baseline.get(item, {}).get(arm, "")
            ratio = ""
            if values and comparator:
                other_key = (item, comparator, n, dtype, device, status)
                if other_key in medians:
                    ratio = statistics.median(values) / medians[other_key]
            if values:
                q1, median, q3 = np.percentile(
                    np.asarray(values), [25, 50, 75], method="linear"
                )
                numeric = {
                    "median_s": f"{median:.9e}",
                    "q1_s": f"{q1:.9e}",
                    "q3_s": f"{q3:.9e}",
                    "iqr_s": f"{q3 - q1:.9e}",
                }
            else:
                numeric = dict.fromkeys(("median_s", "q1_s", "q3_s", "iqr_s"), "")
            writer.writerow(
                {
                    "item": item,
                    "arm": arm,
                    "n_atoms": n,
                    "dtype": dtype,
                    "device": device,
                    "status": status,
                    "n_repeat": len(values),
                    **numeric,
                    "ratio_vs_comparator": "" if ratio == "" else f"{ratio:.6f}",
                    "comparator": comparator,
                }
            )


def command_output(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        return f"unavailable ({type(error).__name__})"


def write_run_metadata(path: Path, pointer_checks: dict[str, bool]) -> None:
    packages = {}
    for name in ("numpy", "torch", "cupy", "jax", "metatensor", "ase", "readcon"):
        try:
            module = __import__(name)
            packages[name] = getattr(module, "__version__", "unknown")
        except Exception as error:
            packages[name] = f"unavailable ({type(error).__name__})"
    metadata = {
        "cpu_model": platform.processor() or command_output(["lscpu"]),
        "lscpu": command_output(["lscpu"]),
        "memory_gib": command_output(["free", "-g"]),
        "nvidia_smi": command_output(["nvidia-smi"]),
        "rustc": command_output(["rustc", "+1.88.0", "--version"]),
        "cargo": command_output(["cargo", "+1.88.0", "--version"]),
        "python": platform.python_version(),
        "packages": packages,
        "pointer_checks": pointer_checks,
    }
    path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    import readcon

    native = Native(args.library.resolve(), args.probe.resolve())
    paths = create_frames(readcon, args.work)
    rows: list[Row] = []
    no_cuda_rows(rows)
    pointer_checks = item_two(rows, readcon, paths)
    item_three(rows, native, paths)
    item_four(rows, native, readcon, paths)
    write_results(args.results, rows)
    write_summary(args.summary, rows)
    write_run_metadata(args.metadata, pointer_checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
