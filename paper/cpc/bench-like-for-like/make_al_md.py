"""Write one aluminum EAM molecular-dynamics trajectory as a CON file.

The file is simulation output. Frames are successive Velocity Verlet steps,
not copies. The trajectory is not committed when it is larger than 5 MB.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
DEST = BENCH / "work" / "al_eam_md.con"

LATTICE_A = 4.05
REPEAT = (5, 5, 5)
N_FRAMES = 1000
TIMESTEP_FS = 2.0
TEMPERATURE_K = 300.0
SEED = 20261120
RGPOT_VERSION = "3.7.0"
ASE_VERSION = "3.29.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    import ase
    import rgpot
    from ase.build import bulk
    from ase.io.eon import write_eon
    from ase.md.velocitydistribution import Stationary, thermalize_momenta
    from ase.md.verlet import VelocityVerlet
    from ase.units import fs
    from rgpot.ase import RgpotCalculator

    if rgpot.__version__ != RGPOT_VERSION:
        raise SystemExit(f"rgpot {rgpot.__version__} != {RGPOT_VERSION}")
    if ase.__version__ != ASE_VERSION:
        raise SystemExit(f"ase {ase.__version__} != {ASE_VERSION}")
    atoms = bulk("Al", "fcc", a=LATTICE_A, cubic=True).repeat(REPEAT)
    if len(atoms) < 100:
        raise SystemExit(f"atom count {len(atoms)} is below the hundreds")
    atoms.calc = RgpotCalculator("eam_al")
    thermalize_momenta(
        atoms,
        temperature_K=TEMPERATURE_K,
        rng=np.random.default_rng(SEED),
    )
    Stationary(atoms)
    dynamics = VelocityVerlet(atoms, timestep=TIMESTEP_FS * fs)
    images = []
    totals = []
    for _step in range(N_FRAMES):
        dynamics.run(1)
        energy = float(atoms.get_potential_energy() + atoms.get_kinetic_energy())
        if not np.isfinite(energy):
            raise SystemExit("non-finite total energy")
        totals.append(energy)
        images.append(atoms.copy())
    drift = totals[-1] - totals[0]
    if abs(drift) > 5.0:
        raise SystemExit(f"total energy drift {drift} eV")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = DEST.with_name(DEST.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        write_eon(
            handle,
            images,
            comment="FCC Al 5x5x5 EAM molecular dynamics",
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, DEST)
    print("path work/al_eam_md.con")
    print(f"frames {len(images)}")
    print(f"atoms {len(atoms)}")
    print(f"bytes {DEST.stat().st_size}")
    print(f"sha256 {sha256(DEST)}")
    print(f"energy_first_eV {totals[0]:.8f}")
    print(f"energy_last_eV {totals[-1]:.8f}")
    print(f"energy_drift_eV {drift:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
