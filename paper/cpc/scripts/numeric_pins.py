"""Numerical kernels of the band scripts, fixed before NumPy loads.

A residue at roundoff depends on the kernels that sum it.  One OpenBLAS thread
on its Nehalem kernels and NumPy held to its x86-64-v2 baseline select the same
kernels on every x86-64-v2 host, whatever wider vector units the host has.
RC_KERNELS names another set of KERNEL_SETS: the OpenBLAS kernels and NumPy
dispatch targets that a host of a later generation selects when nothing is
pinned, so that one host can rerun a band on the kernels of other hosts.
Import this module before NumPy.  ``in_effect()`` reports the kernels the process
runs and fails unless they are the selected ones, so a band record cannot be
written on other kernels.
"""

from __future__ import annotations

import os

KERNEL_SETS = {
    "nehalem": {"OPENBLAS_CORETYPE": "Nehalem", "NPY_DISABLE_CPU_FEATURES": "X86_V3 X86_V4 AVX512_ICL AVX512_SPR"},
    "haswell": {"OPENBLAS_CORETYPE": "Haswell", "NPY_DISABLE_CPU_FEATURES": "X86_V4 AVX512_ICL AVX512_SPR"},
    "skylakex": {"OPENBLAS_CORETYPE": "SkylakeX", "NPY_DISABLE_CPU_FEATURES": "AVX512_ICL AVX512_SPR"},
    "cooperlake": {"OPENBLAS_CORETYPE": "Cooperlake", "NPY_DISABLE_CPU_FEATURES": ""},
}
SELECTED = os.environ.get("RC_KERNELS") or "nehalem"
if SELECTED not in KERNEL_SETS:
    raise SystemExit(f"RC_KERNELS={SELECTED!r} is none of {', '.join(KERNEL_SETS)}")

PINS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    **KERNEL_SETS[SELECTED],
}

os.environ.update(PINS)


def in_effect() -> dict:
    """The pins, the NumPy dispatch targets enabled and the BLAS kernels loaded; fails unless they hold."""
    import numpy as np
    import threadpoolctl
    from numpy._core._multiarray_umath import __cpu_dispatch__, __cpu_features__

    np.linalg.solve(np.eye(3), np.ones(3))
    blas = [(i["internal_api"], i.get("architecture"), i["num_threads"])
            for i in threadpoolctl.threadpool_info() if i["user_api"] == "blas"]
    dispatched = [name for name in __cpu_dispatch__ if __cpu_features__.get(name)]
    disabled = PINS["NPY_DISABLE_CPU_FEATURES"].split()
    wanted = [name for name in __cpu_dispatch__ if name not in disabled]
    if dispatched != wanted or any(arch != PINS["OPENBLAS_CORETYPE"] or threads != 1 for _, arch, threads in blas):
        raise SystemExit(f"kernels not pinned: NumPy dispatches {dispatched}, BLAS {blas}")
    pinned = {"environment": dict(PINS), "numpy_dispatch": dispatched,
              "blas": [f"{api} {arch} kernels, {threads} thread" for api, arch, threads in blas]}
    return pinned if SELECTED == "nehalem" else {"kernel_set": SELECTED, **pinned}
