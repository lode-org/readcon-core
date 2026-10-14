#!/usr/bin/env python3
"""Interrupted climbing-image band, resumed through each format.

EMT Pt(100) slab (3x3x3, bottom layer held on every axis) with one adatom held
in z, hopping between neighbouring hollows. The band has five movable images
and uses the improved tangent with a climbing image. The optimiser is fixed-step
steepest descent on the projected NEB force. It stores no history, so any
difference after a resume comes from the file and from nothing else.

The uninterrupted band runs to a maximum NEB force of 0.01 eV/A. The
interrupted band stops at step K, writes every image with one writer, reads
the images back with the matching reader (constraints, if any, are whatever the
reader returns), and continues under the same rule.

Writes data/failure/restart_formats.csv and data/failure/restart_bands.json.
"""
from __future__ import annotations
import csv, json, tempfile, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "failure"
FMAX, ALPHA, K, NMAX = 0.01, 0.02, 25, 4000


def endpoints():
    from ase.build import fcc100, add_adsorbate
    from ase.calculators.emt import EMT
    from ase.constraints import FixAtoms, FixCartesian
    from ase.optimize import BFGS
    eps = []
    for site in [(0, 0), (1, 0)]:
        s = fcc100("Pt", (3, 3, 3), vacuum=6.0)
        a0 = s.cell[0, 0] / 3
        add_adsorbate(s, "Pt", 1.75, position=((0.5 + site[0]) * a0, (0.5 + site[1]) * a0))
        n = len(s)
        bottom = [i for i, t in enumerate(s.get_tags()) if t == 3]
        s.set_constraint([FixAtoms(indices=bottom), FixCartesian(n - 1, mask=(False, False, True))])
        s.calc = EMT()
        BFGS(s, logfile=None).run(fmax=0.002)
        eps.append(s)
    return eps


def make_band(eps, nimg=5):
    from ase.mep import NEB
    from ase.calculators.emt import EMT
    imgs = [eps[0].copy()] + [eps[0].copy() for _ in range(nimg)] + [eps[1].copy()]
    for im in imgs:
        im.calc = EMT()
    neb = NEB(imgs, climb=True, method="improvedtangent")
    neb.interpolate(apply_constraint=True)
    return imgs


def run(imgs, start=0, stop=None):
    from ase.mep import NEB
    from ase.calculators.emt import EMT
    for im in imgs:
        im.calc = EMT()
    neb = NEB(imgs, climb=True, method="improvedtangent")
    step = start
    while True:
        f = neb.get_forces()
        fmax = float(np.sqrt((f ** 2).sum(axis=1)).max())
        if fmax < FMAX or step >= NMAX or (stop is not None and step >= stop):
            break
        neb.set_positions(neb.get_positions() + ALPHA * f)
        step += 1
    e = np.array([im.get_potential_energy() for im in imgs])
    frc = [im.get_forces(apply_constraint=False).copy() for im in imgs]
    return dict(step=step, fmax=fmax, barrier=float(e.max() - e[0]), converged=bool(fmax < FMAX),
                pos=[im.get_positions().copy() for im in imgs], energies=e.tolist(), forces=frc)


def free_modes(atoms):
    from ase.constraints import FixAtoms, FixCartesian
    m = np.zeros((len(atoms), 3), bool)
    for c in atoms.constraints:
        if isinstance(c, FixAtoms): m[c.index] = True
        elif isinstance(c, FixCartesian): m[c.index] |= np.asarray(c.mask, bool)
    return int((~m).sum())


def _frame(readcon, im, i):
    a = im.copy(); a.set_tags(0)  # ids from row order; slab tags are layer numbers
    f = readcon.ConFrame.from_ase(a)
    # A non-empty first line: readcon-core 0.17.0 cannot re-read a multi-frame
    # file whose frames start with an empty line (reported separately).
    return readcon.ConFrame(f.cell, f.angles, f.atoms, prebox_header=[f"NEB image {i}", ""],
                            metadata=dict(f.metadata))


# writer/reader pairs; each returns a list of ASE Atoms
def via_readcon(imgs, d):
    import readcon
    frames = [_frame(readcon, im, i) for i, im in enumerate(imgs)]
    p = d / "band.con"; readcon.write_con(str(p), frames)
    return [f.to_ase() for f in readcon.read_con(str(p))]


def via_readcon_6dp(imgs, d):
    import readcon
    frames = [_frame(readcon, im, i) for i, im in enumerate(imgs)]
    p = d / "band6.con"; readcon.write_con(str(p), frames, precision=6)
    return [f.to_ase() for f in readcon.read_con(str(p))]


def via_ase(fmt, ext):
    def go(imgs, d):
        import ase.io
        out = []
        for i, im in enumerate(imgs):
            p = d / f"img{i}.{ext}"
            ase.io.write(str(p), im, format=fmt)
            out.append(ase.io.read(str(p), format=fmt))
        return out
    return go


def via_readcon_to_ase_eon(imgs, d):
    import readcon, ase.io
    out = []
    for i, im in enumerate(imgs):
        a = im.copy(); a.set_tags(0)
        p = d / f"img{i}.con"; readcon.write_con(str(p), [readcon.ConFrame.from_ase(a)])
        out.append(ase.io.read(str(p), format="eon"))
    return out


def via_readcon_to_ase_eon_pbc(imgs, d):
    out = via_readcon_to_ase_eon(imgs, d)
    for a, im in zip(out, imgs):
        a.pbc = im.pbc  # isolate the mask collapse from the lost periodicity
    return out


ROUTES = [
    ("CON 3.1, shortest round trip", via_readcon),
    ("CON 3.1, six decimals", via_readcon_6dp),
    ("CON 3.1 read by the ASE eon reader", via_readcon_to_ase_eon),
    ("same, periodicity restored by hand", via_readcon_to_ase_eon_pbc),
    ("extended XYZ (ASE)", via_ase("extxyz", "xyz")),
    ("ASE trajectory", via_ase("traj", "traj")),
    ("POSCAR (ASE)", via_ase("vasp", "vasp")),
    ("legacy CON (ASE eon writer)", via_ase("eon", "con")),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    eps = endpoints()
    ref = run(make_band(eps))
    print(f"uninterrupted: steps={ref['step']} barrier={ref['barrier']:.9f} fmax={ref['fmax']:.4f}")
    rows = [dict(route="uninterrupted", steps=ref["step"], converged=ref["converged"], barrier_eV=f"{ref['barrier']:.9f}",
                 d_barrier_eV="0", max_disp_A="0", file_dpos_A="", free_modes_mid=free_modes(make_band(eps)[3]), error="")]
    BANDS = OUT / "bands"; BANDS.mkdir(exist_ok=True)
    def dump(slug, res):
        np.savez(BANDS / f"{slug}.npz", pos=np.array(res["pos"]), energies=np.array(res["energies"]),
                 forces=np.array(res["forces"]), numbers=eps[0].numbers, cell=eps[0].cell.array)
    dump("uninterrupted", ref)
    bands = {"uninterrupted": ref["energies"]}
    for name, fn in ROUTES:
        imgs = make_band(eps)
        part = run(imgs, stop=K)
        try:
            with tempfile.TemporaryDirectory() as td:
                back = fn(imgs, Path(td))
            fm = free_modes(back[3])
            fdp = max(float(np.abs(b.get_positions() - a.get_positions()).max()) for a, b in zip(imgs, back))
            res = run(back, start=part["step"])
            disp = max(float(np.abs(a - b).max()) for a, b in zip(res["pos"], ref["pos"]))
            rows.append(dict(route=name, steps=res["step"], converged=res["converged"], barrier_eV=f"{res['barrier']:.9f}",
                             d_barrier_eV=f"{res['barrier'] - ref['barrier']:.2e}", max_disp_A=f"{disp:.2e}",
                             file_dpos_A=f"{fdp:.1e}", free_modes_mid=fm, error=""))
            bands[name] = res["energies"]
            dump("".join(c if c.isalnum() else "_" for c in name).strip("_"), res)
        except BaseException as e:
            rows.append(dict(route=name, steps="", converged="", barrier_eV="", d_barrier_eV="", max_disp_A="",
                             file_dpos_A="", free_modes_mid="", error=f"{type(e).__name__}: {e}"[:120]))
        print(rows[-1])
    with open(OUT / "restart_formats.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (OUT / "restart_bands.json").write_text(json.dumps(bands, indent=1))


if __name__ == "__main__":
    main()
