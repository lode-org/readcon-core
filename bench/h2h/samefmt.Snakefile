# Same-format pairs. One rule per reader or writer that handles a format
# readcon itself reads or writes. The arm list is the ARMS tuple in
# bench/h2h/samefmt.py. This file is separate from bench/h2h/Snakefile,
# which is the publication rerun.

import re
from pathlib import Path

_text = Path("bench/h2h/samefmt.py").read_text(encoding="utf-8")
_start = _text.index("ARMS = (")
_end = _text.index("\n)", _start)
SAMEFMT_ARMS = re.findall(r'"([^"]+)"', _text[_start:_end])


rule all:
    input:
        "bench/h2h/results/samefmt/summary.csv",


rule h2h_samefmt_prepare:
    output:
        touch("bench/h2h/work/samefmt/prepare.ok"),
    shell:
        """
        set -euo pipefail
        export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
        taskset -c 0 python3 bench/h2h/asv/drive.py samefmt prepare
        touch bench/h2h/work/samefmt/prepare.ok
        """


def _samefmt_rule(arm):
    # The arm is a parameter of this function. A loop variable would still
    # be the last value when Snakemake runs the shell.
    command = (
        "set -euo pipefail\n"
        "export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1\n"
        "mkdir -p bench/h2h/results/samefmt\n"
        f"taskset -c 0 python3 bench/h2h/asv/drive.py samefmt {arm}\n"
    )

    rule:
        name:
            f"h2h_same_{arm.replace('-', '_')}"
        input:
            "bench/h2h/work/samefmt/prepare.ok",
        output:
            f"bench/h2h/results/samefmt/{arm}.stdout",
        shell:
            command


for _arm in SAMEFMT_ARMS:
    _samefmt_rule(_arm)


SAMEFMT_SINGLE = [
    arm for arm in SAMEFMT_ARMS if not (arm.startswith("mf-") or arm.startswith("cc-"))
]
SAMEFMT_MULTI = [
    arm for arm in SAMEFMT_ARMS if arm.startswith("mf-") or arm.startswith("cc-")
]


rule h2h_table_1e6:
    input:
        expand("bench/h2h/results/samefmt/{arm}.stdout", arm=SAMEFMT_SINGLE),
    output:
        "bench/h2h/results/samefmt/table-1e6.csv",
    shell:
        """
        set -euo pipefail
        taskset -c 0 python3 bench/h2h/asv/drive.py samefmt report 1e6
        """


rule h2h_table_100k:
    input:
        expand("bench/h2h/results/samefmt/{arm}.stdout", arm=SAMEFMT_MULTI),
    output:
        "bench/h2h/results/samefmt/table-100k.csv",
    shell:
        """
        set -euo pipefail
        taskset -c 0 python3 bench/h2h/asv/drive.py samefmt report 100k
        """


rule h2h_samefmt:
    input:
        "bench/h2h/results/samefmt/table-1e6.csv",
        "bench/h2h/results/samefmt/table-100k.csv",
    output:
        "bench/h2h/results/samefmt/summary.csv",
    shell:
        """
        set -euo pipefail
        taskset -c 0 python3 bench/h2h/asv/drive.py samefmt report summary
        """
