# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Chemfiles → CON ingress (executable tutorial)
#
# Papermill parameters are in the next cell. Run with:
#
# ```bash
# scripts/run-chemfiles-notebook.sh
# # or:
# papermill docs/notebooks/chemfiles_ingress.py docs/notebooks/out/chemfiles_ingress.ipynb
# ```
#
# Requires a chemfiles-linked build (`readcon-chemfiles` or
# `maturin develop --features python,chemfiles`).

# %% tags=["parameters"]
# Papermill injects overrides here (see scripts/run-chemfiles-notebook.sh).
work_dir = "docs/notebooks/out/work"
xyz_name = "water.xyz"
con_name = "water_from_xyz.con"
bonded_con_name = "water_with_bonds.con"
require_chemfiles = True

# %%
from __future__ import annotations

import json
import sys
from pathlib import Path

import readcon

work = Path(work_dir)
work.mkdir(parents=True, exist_ok=True)

ok = readcon.has_chemfiles_support()
print("readcon", getattr(readcon, "__version__", "?"), "has_chemfiles_support=", ok)
if require_chemfiles and not ok:
    raise SystemExit(
        "chemfiles not linked: install readcon-chemfiles or "
        "`maturin develop --features python,chemfiles`"
    )

# %% [markdown]
# ## Write a minimal XYZ (foreign format ingress)

# %%
xyz_path = work / xyz_name
xyz_path.write_text(
    "3\n"
    "water demo — papermill / org executable tutorial\n"
    "O  0.000  0.000  0.000\n"
    "H  0.957  0.000  0.000\n"
    "H -0.240  0.927  0.000\n",
    encoding="utf-8",
)
print("wrote", xyz_path.resolve())

# %% [markdown]
# ## Convert XYZ → CON (`read_chemfiles*`)

# %%
frame = readcon.read_chemfiles_first(str(xyz_path))
print("atoms", len(frame.atoms), "has_bonds", frame.has_bonds)
for i, a in enumerate(frame.atoms):
    print(f"  [{i}] {a.symbol} id={a.atom_id} ({a.x:.3f}, {a.y:.3f}, {a.z:.3f})")

con_path = work / con_name
frame.write_con(str(con_path))
assert con_path.is_file()
print("wrote", con_path.resolve())

# Round-trip via memory API (format name is chemfiles's)
mem = readcon.read_chemfiles_memory(xyz_path.read_text(encoding="utf-8"), "XYZ")
assert len(mem) == 1 and len(mem[0].atoms) == 3

all_frames = readcon.read_chemfiles(str(xyz_path))
assert len(all_frames) == 1

# %% [markdown]
# ## Topology + selection (angles need bonds)
#
# Plain XYZ has no bonds. Attach CON `metadata['bonds']` in atom_data order
# (demo), then run chemfiles selection grammar.

# %%
atoms = list(frame.atoms)
# For O,H,H without type-group surprises in this tiny file, indices 0,1,2 work.
bonded = readcon.ConFrame(
    cell=list(frame.cell),
    angles=list(frame.angles),
    atoms=atoms,
    metadata={"con_spec_version": 2, "bonds": [[0, 1], [0, 2]]},
)
assert bonded.has_bonds
oxy = bonded.select_atoms("name O")
assert oxy == [0], oxy
angles = bonded.select("angles: all")
assert angles["context_size"] == 3
assert len(angles["matches"]) >= 1
print("oxygens", oxy)
print("angles", angles["matches"])

bonded_path = work / bonded_con_name
bonded.write_con(str(bonded_path))
print("wrote", bonded_path.resolve())

# %% [markdown]
# ## Multi-format habit: same API, different paths
#
# Only files that exist are converted (parameterized batch in CI can pass a list).

# %%
candidates = [xyz_path]  # extend with PDB/GRO paths in papermill -p overrides
converted = []
for path in candidates:
    path = Path(path)
    if not path.is_file():
        continue
    frames = readcon.read_chemfiles(str(path))
    out = work / f"{path.stem}.converted.con"
    readcon.write_con(str(out), frames)
    converted.append((str(path), str(out), len(frames)))
print(json.dumps({"converted": converted}, indent=2))

# %% [markdown]
# ## Checkpoint

# %%
summary = {
    "has_chemfiles_support": ok,
    "xyz": str(xyz_path),
    "con": str(con_path),
    "bonded_con": str(bonded_path),
    "n_atoms": len(frame.atoms),
    "n_angle_matches": len(angles["matches"]),
}
(work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
print("OK — chemfiles ingress notebook finished", file=sys.stderr)
