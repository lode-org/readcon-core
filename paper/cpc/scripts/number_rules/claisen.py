"""Rules for the numbers that the Claisen atom-order subsection of ``rg_main.tex`` prints."""

from __future__ import annotations

import re

from numbers_lib import Rule, jget, load_json

DOC = "rg_main.tex"
REC = "data/claisen/results.json"
HERE = (f"{DOC}~Baker transition-state set|band reaches a largest atomic force|"
        "IRA shape matching|permuted onto the reactant|PET-MAD-S",)
UNIT = (f"{DOC}~161i",)

NEB = load_json(REC)["neb"]
if NEB["stage2"]["images"] != 24 or NEB["converged_force_eV_A"] != 0.05:
    raise SystemExit(f"{REC}: the refinement band no longer has 24 images at 0.05 eV/A")
if not load_json(REC)["identity"]["converged"]:
    raise SystemExit(f"{REC}: the Baker-order band is not converged")
if load_json(REC)["ira_reordered"]["connected_components"] != 3:
    raise SystemExit(f"{REC}: the IRA-order highest image is not in three fragments")
SORTED = load_json(REC)["round_trip"]["poscar_ase_sort_true_grouped_by_element"]
CON = load_json(REC)["round_trip"]["con_3_1"]
if not CON["atom_id_restores_insertion_order"]:
    raise SystemExit(f"{REC}: atom_id no longer restores the Baker order")
if SORTED["file_slot_source_index"][-1] != 3:
    raise SystemExit(f"{REC}: ASE sort=True no longer puts Baker atom 3 (O) last")
# ``161i`` is one scanner token, so 161 is not a printed number. Keep the guard here.
_FREQ = abs(jget(REC, "identity.hessian.most_negative_cm-1"))
if abs(_FREQ - 161) > 0.5:
    raise SystemExit(f"{REC}: imaginary frequency {_FREQ} does not round to 161")

RULES: list[Rule] = [
    Rule("17", int(re.search(r"entry (\d+)", jget(REC, "case")).group(1)), REC,
         "Baker entry number in case", HERE),
    Rule("14", jget(REC, "atoms"), REC, "atoms", HERE),
    Rule("0.05", NEB["converged_force_eV_A"], REC, "neb.converged_force_eV_A", HERE),
    Rule("24", NEB["stage2"]["images"], REC, "neb.stage2.images", HERE),
    Rule("0.008", NEB["stage2"]["max_move_A"], REC, "neb.stage2.max_move_A", HERE),
    Rule("0.631", jget(REC, "identity.barrier_eV"), REC, "identity.barrier_eV", HERE),
    # 161i is one token, so the scanner never emits 161. cm^{-1} is the printed -1.
    Rule("-1", -1, REC, "exponent of cm^{-1} beside the imaginary frequency", UNIT),
    Rule("2.11", jget(REC, "ira.hausdorff_reported_A"), REC,
         "ira.hausdorff_reported_A", HERE),
    Rule("9.97", jget(REC, "ira_reordered.barrier_eV"), REC,
         "ira_reordered.barrier_eV", HERE),
    Rule("3000", NEB["stage2"]["max_iterations"], REC, "neb.stage2.max_iterations", HERE),
    Rule("0.995", jget(REC, "ira_reordered.final_max_atom_force_eV_A"), REC,
         "ira_reordered.final_max_atom_force_eV_A", HERE),
    Rule("v1.1.0", jget(REC, "potential.version").lstrip("v"), REC, "potential.version", HERE),
    Rule("3.6.0", jget(REC, "engine.requested"), REC, "engine.requested", HERE),
]
