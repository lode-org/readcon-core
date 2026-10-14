"""Asymmetric masked NEB, and a restart of a converged band.

The reaction is a Pd adatom hopping from an fcc site to an hcp site on Al(111)
with EMT. The two hollows are inequivalent, so the forward and reverse barriers
differ. One band holds the adsorbate height (mask 4). The other leaves it free.
Bottom-layer atoms stay fixed (mask 7) on both bands.

The restart writes the converged free band with the canonical CON writer,
reads it back, and continues the same optimiser. A converged band takes no
further step, so the continuation matches the loaded geometry bit for bit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import readcon
from ase.build import add_adsorbate, fcc111
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms, FixCartesian
from ase.mep import NEB
from ase.optimize import BFGS, FIRE

from clean_common import RESULTS, WORK, environment_row, write_csv

FMAX = 0.02
ENDPOINT_FMAX = 0.01
N_IMAGES = 5
K_SPRING = 0.1


def max_force(atoms) -> float:
    forces = atoms.get_forces()
    return float(np.sqrt((forces ** 2).sum(axis=1)).max())


def neb_residual(band) -> float:
    forces = np.asarray(band.get_forces(), dtype=float)
    return float(np.sqrt((forces ** 2).sum(axis=1)).max())


def relax(atoms, fmax: float, steps: int) -> dict:
    atoms.calc = EMT()
    opt = BFGS(atoms, logfile=None)
    converged = bool(opt.run(fmax=fmax, steps=steps))
    return {
        "steps": int(opt.nsteps),
        "converged": converged,
        "fmax_eV_A": max_force(atoms),
        "energy_eV": float(atoms.get_potential_energy()),
    }


def build_ends(mask_h: bool):
    def site(name: str):
        slab = fcc111("Al", size=(3, 3, 3), vacuum=6.0)
        add_adsorbate(slab, "Pd", height=1.8, position=name)
        return slab

    reactant = site("fcc")
    product = site("hcp")
    h = len(reactant) - 1
    order = np.argsort(reactant.positions[:, 2])
    bottom = sorted(int(i) for i in order[:9])
    if h in bottom:
        raise RuntimeError("Pd landed in the bottom layer")

    def constrain(atoms):
        constraints = [FixAtoms(indices=bottom)]
        if mask_h:
            constraints.append(FixCartesian(h, mask=(False, False, True)))
        atoms.set_constraint(constraints)

    constrain(reactant)
    constrain(product)
    masks = [0] * len(reactant)
    for index in bottom:
        masks[index] = 7
    if mask_h:
        masks[h] = 4
    return reactant, product, h, bottom, masks


def run_band(mask_h: bool) -> dict:
    reactant, product, h, bottom, masks = build_ends(mask_h)
    reactant_relax = relax(reactant, ENDPOINT_FMAX, 200)
    product_relax = relax(product, ENDPOINT_FMAX, 200)
    images = [reactant]
    for _ in range(N_IMAGES):
        images.append(reactant.copy())
    images.append(product)
    band = NEB(images, k=K_SPRING, climb=True, method="improvedtangent")
    # Straight-line images, then FixCartesian holds each image's height.
    band.interpolate(mic=True, apply_constraint=False)
    for image in images:
        image.calc = EMT()
    opt = FIRE(band, logfile=None)
    converged = bool(opt.run(fmax=FMAX, steps=300))
    neb_steps = int(opt.nsteps)
    if not converged:
        opt = FIRE(band, logfile=None, maxstep=0.05)
        converged = bool(opt.run(fmax=FMAX, steps=400)) or converged
        neb_steps += int(opt.nsteps)
    energies = np.array([image.get_potential_energy() for image in images])
    fmax = neb_residual(band)
    saddle = int(energies.argmax())
    if saddle == 0 or saddle == len(energies) - 1:
        raise RuntimeError(f"saddle sits on an endpoint (index {saddle})")
    forward = float(energies.max() - energies[0])
    reverse = float(energies.max() - energies[-1])
    return {
        "mask_h": mask_h,
        "masks": masks,
        "h_index": h,
        "bottom": bottom,
        "reactant_relax": reactant_relax,
        "product_relax": product_relax,
        "neb_steps": neb_steps,
        "converged": bool(converged and fmax <= FMAX),
        "fmax_eV_A": float(fmax),
        "energies_eV": energies.tolist(),
        "forward_barrier_eV": forward,
        "reverse_barrier_eV": reverse,
        "delta_endpoint_eV": float(energies[-1] - energies[0]),
        "images": images,
    }


def write_band(path: Path, images, masks: list[int]) -> None:
    frames = []
    for image in images:
        cell = image.cell.cellpar()
        atoms = []
        for index, (symbol, xyz, mask) in enumerate(
            zip(image.get_chemical_symbols(), image.get_positions(), masks, strict=True)
        ):
            atoms.append(
                readcon.Atom(
                    symbol=symbol,
                    x=float(xyz[0]),
                    y=float(xyz[1]),
                    z=float(xyz[2]),
                    fixed=[bool(mask & 1), bool(mask & 2), bool(mask & 4)],
                    atom_id=index,
                    mass=float(image.get_masses()[index]),
                )
            )
        frame = readcon.ConFrame(
            cell=[float(v) for v in cell[:3]],
            angles=[float(v) for v in cell[3:]],
            atoms=atoms,
            prebox_header=["asymmetric Pd fcc to hcp", ""],
            postbox_header=["", ""],
        )
        frame.metadata = {
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
            "pbc": [True, True, False],
        }
        frames.append(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), frames, canonical=True)


def bits(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values, dtype=np.float64).tobytes()


def restart(images, masks, path: Path) -> dict:
    before = np.array([image.get_positions() for image in images])
    before_e = np.array([image.get_potential_energy() for image in images])
    write_band(path, images, masks)
    loaded = readcon.read_con(str(path))
    after_read = np.array([[[atom.x, atom.y, atom.z] for atom in frame.atoms] for frame in loaded])
    read_bits_equal = bits(before) == bits(after_read)
    # Rebuild the band from the file and continue.
    restarted = []
    for frame, image in zip(loaded, images, strict=True):
        atoms = frame.to_ase()
        atoms.set_constraint(image.constraints)
        atoms.calc = EMT()
        restarted.append(atoms)
    band = NEB(restarted, k=K_SPRING, climb=True, method="improvedtangent")
    opt = FIRE(band, logfile=None)
    converged = bool(opt.run(fmax=FMAX, steps=50))
    after_opt = np.array([image.get_positions() for image in restarted])
    after_e = np.array([image.get_potential_energy() for image in restarted])
    return {
        "n_images": len(images),
        "nsteps": int(opt.nsteps),
        "converged": converged,
        "read_positions_bit_identical": read_bits_equal,
        "continuation_positions_bit_identical": bits(after_read) == bits(after_opt),
        "continuation_energy_bit_identical": bits(before_e) == bits(after_e) and bits(after_read) == bits(after_opt),
        "max_abs_read_delta_A": float(np.max(np.abs(before - after_read))),
        "max_abs_continue_delta_A": float(np.max(np.abs(after_read - after_opt))),
        "max_abs_energy_delta_eV": float(np.max(np.abs(before_e - after_e))),
        "energy_bits_equal_to_prerestart": bits(before_e) == bits(after_e),
    }


def main() -> None:
    info = environment_row()
    print("free band", flush=True)
    free = run_band(False)
    print("masked band", flush=True)
    masked = run_band(True)
    shift = masked["forward_barrier_eV"] - free["forward_barrier_eV"]
    reverse_shift = masked["reverse_barrier_eV"] - free["reverse_barrier_eV"]
    rows = []
    for band in (free, masked):
        rows.append(
            {
                **info,
                "band": "mask4" if band["mask_h"] else "free",
                "h_mask": 4 if band["mask_h"] else 0,
                "bottom_mask": 7,
                "n_images_movable": N_IMAGES,
                "k_spring": K_SPRING,
                "fmax_target_eV_A": FMAX,
                "converged": band["converged"],
                "neb_steps": band["neb_steps"],
                "fmax_eV_A": f"{band['fmax_eV_A']:.16g}",
                "forward_barrier_eV": f"{band['forward_barrier_eV']:.16g}",
                "reverse_barrier_eV": f"{band['reverse_barrier_eV']:.16g}",
                "delta_endpoint_eV": f"{band['delta_endpoint_eV']:.16g}",
                "reactant_energy_eV": f"{band['energies_eV'][0]:.16g}",
                "product_energy_eV": f"{band['energies_eV'][-1]:.16g}",
                "saddle_energy_eV": f"{max(band['energies_eV']):.16g}",
                "reactant_converged": band["reactant_relax"]["converged"],
                "product_converged": band["product_relax"]["converged"],
                "energies_json": json.dumps(band["energies_eV"]),
            }
        )
    rows.append(
        {
            **info,
            "band": "shift_mask_minus_free",
            "h_mask": "",
            "bottom_mask": 7,
            "n_images_movable": N_IMAGES,
            "k_spring": K_SPRING,
            "fmax_target_eV_A": FMAX,
            "converged": free["converged"] and masked["converged"],
            "neb_steps": "",
            "fmax_eV_A": "",
            "forward_barrier_eV": f"{shift:.16g}",
            "reverse_barrier_eV": f"{reverse_shift:.16g}",
            "delta_endpoint_eV": f"{masked['delta_endpoint_eV'] - free['delta_endpoint_eV']:.16g}",
            "reactant_energy_eV": "",
            "product_energy_eV": "",
            "saddle_energy_eV": "",
            "reactant_converged": "",
            "product_converged": "",
            "energies_json": "",
        }
    )
    write_csv(RESULTS / "clean_neb.csv", rows)
    if not free["converged"]:
        raise SystemExit("free band did not converge; restart would not be a converged continuation")
    path = WORK / "neb" / "free_band.con"
    restarted = restart(free["images"], free["masks"], path)
    restarted = {**info, "band": "free", **restarted}
    # JSON-friendly
    for key, value in list(restarted.items()):
        if isinstance(value, (bool, np.bool_)):
            restarted[key] = "yes" if value else "no"
    write_csv(RESULTS / "clean_neb_restart.csv", [restarted])
    print(restarted, flush=True)
    if restarted["nsteps"] != 0 or restarted["continuation_positions_bit_identical"] != "yes":
        raise SystemExit(f"continuation was not bit-identical: {restarted}")


if __name__ == "__main__":
    main()
