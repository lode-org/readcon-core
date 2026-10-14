# Cloud runs
Measurements for the three cloud specs, taken on 2026-10-14. Manuscript prose (`.org`, `.tex`, `.bib`, generated paper tables) was not edited. The library that was built and measured is readcon-core 0.17.0 at commit `318030186ea25dc036e1a858a2d382e624d1416b`. The three later commits on `paper/cpc-v4a` (`d9aed13`, `1525081`, `5f53154`) change the manuscript and MPI tables only; they do not change the library sources.
## Hardware
- Architecture: x86_64, little endian
- CPU: Intel(R) Xeon(R) Processor, vendor GenuineIntel, family 6, model 207, stepping 2
- Sockets: 1. Cores per socket: 8. Threads per core: 1. CPU(s): 8. On-line: 0-7
- BogoMIPS: 4800.00
- Caches: L1d 384 KiB (8 instances), L1i 256 KiB (8 instances), L2 16 MiB (8 instances), L3 320 MiB (1 instance)
- NUMA nodes: 1 (CPUs 0-7)
- Hypervisor: KVM, full virtualization, VT-x
- `nproc` = 1. `nproc --all` = 8. Process affinity covers CPUs 0-7. No cgroup `cpu.max` quota file was present.
- CPU frequency governor: not set. `/sys/devices/system/cpu/cpu0/cpufreq` is absent, so no governor could be pinned. Spec 03 pinned the process with `taskset -c 0-7`.
- Full `lscpu` text: `paper/cpc/data/cloud-runs/spec03/lscpu.txt`.
## Versions
- rustc 1.99.0 (b940084d7 2026-09-28). Crate `readcon-core` version 0.17.0, edition 2024, rust-version 1.88. Commit `318030186ea25dc036e1a858a2d382e624d1416b`.
- C library: `cargo build --release` without the `python` feature. Artifact `target/release/libreadcon_core.so` (and the static archive). Headers are the shipped `include/readcon-core.h` (cbindgen is maintainer-only and was not rerun).
- Julia 1.11.7 at `/opt/julia/bin/julia`. Package `julia/ReadCon` v0.17.0, UUID `db9801e4`. `READCON_CORE_LIB` pointed at the release cdylib. `Pkg.test`: 220 pass, 1 broken, 221 total, 3.4 s. Transcript: `paper/cpc/data/cloud-runs/spec01/logs/julia-test.txt`.
- gfortran 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1). fpm 0.13.0. `fpm test` in `fortran/ReadCon` with `LIBRARY_PATH` set to the release directory: `OK fortran conformance goldens valid=10 invalid=8`. Lean build: metatensor status -11 (`FEATURE_DISABLED`), zstd writer null. Transcript: `paper/cpc/data/cloud-runs/spec01/logs/fpm-test.txt`.
- Python 3.12.3 (GCC 13.3.0). Virtualenv `/tmp/rc-venv`. ase 3.29.0, numpy 2.5.4, scipy 1.18.1, matplotlib 3.11.2, chemparseplot 1.11.0, rgpycrumbs 1.11.0, maturin 1.15.0, meson 1.12.1. `readcon` 0.17.0 installed editable with `maturin develop --release`. `readcon-db` 0.1.8.
- eOn 3.6.0, commit `2d2adada2f64c4c5a063065abc0d9a8a56d74b2c`, version string `3.6.0 (2d2adad)`, compiled Wed Oct 14 02:03:13 PM GMT 2026. Binary `/tmp/eon-build/client/eonclient`. readcon-core subproject is this tree (0.17.0). Potential `morse_pt`, rgpot 3.2.0 (from `results.dat`).
## Spec 01: Julia and Fortran conformance
Corpus: `resources/conformance/valid/*.con` (10) and `resources/conformance/invalid/*.con` (8), plus seven header variants dumped by `paper/cpc/scripts/version_safety.py --dump` into `paper/cpc/data/cloud-runs/spec01/variants/`.
Variant rules, in order:
1. variant0: 3.1, natural unit declared. Expected accept.
2. variant1: 3.1, no time unit. Expected reject.
3. variant2: 3.0, labelled fs. Expected accept.
4. variant3: 3.2, unknown key. Expected accept.
5. variant4: 4.0. Expected reject.
6. variant5: missing version. Expected reject.
7. variant6: 3.1, mask 9. Expected reject.
Accept/reject agrees for Python, the C ABI (`rkr_read_all_frames`), Julia, and Fortran on all 25 files. Disagreements on the accept/reject columns: 0.
Rewrite SHA-256, first 12 hex digits, and a second rewrite of the rewritten text (`rewrite_stable_*` = yes on every accepted file, all three bindings).
Python and Julia digests match on every accepted file. Fortran matches Python and Julia on variant0 (`7f4518a5a5b1`) and variant3 (`cd0b86aa9a38`). Fortran differs on 11 accepted files because `open_writer` / `extend_one` keeps the parsed metadata object and does not insert `con_spec_minor`. The Python and Julia builders stamp `"con_spec_minor":1` and a canonical key order. Coordinates match. Minimal reproducer: `resources/conformance/valid/v3_units.con`. The only difference is line 2 of the rewrite (`paper/cpc/data/cloud-runs/spec01/reproducer/v3_units.diff`):
```
Python/Julia: {"con_spec_minor":1,"con_spec_version":3,"units":{"energy":"eV","length":"angstrom"}}
Fortran:      {"con_spec_version":3,"units":{"energy":"eV","length":"angstrom"}}
```
SHA-256/12 disagreements (Python = Julia, then Fortran):
- column4_spec1_all_fixed.con: `75195463d711` vs `03686cb8a301`
- column4_spec2_all_fixed.con: `7feaa7c4d483` vs `5b8da9e25c7f`
- column4_spec2_x_only.con: `dd07bc2dd0b9` vs `209ad7ce3eb5`
- column4_spec2_xz.con: `26c0bc7a8662` vs `99b51bab21ef`
- column4_spec2_y_only.con: `b67790cbb895` vs `f8126e4d60be`
- v2_minimal.con: `ca6e4a4278b8` vs `96d39060f60c`
- v3_units.con: `1e12f65fd88a` vs `5db10e464745`
- zero_atom.con: `07b78214eef7` vs `fcae463b33be`
- zero_atom_eof.con: `240e375b7fab` vs `1251a44c2c82`
- zero_atom_then_frame.con: `556a5f848913` vs `d3e55a655124`
- variant2.con: `539b622083f2` vs `b64e7dc4482c`
Rejected files have no digest (`-`). Julia `read_con` returns an empty vector on an invalid file; the driver treats that as reject. A valid zero-atom file still yields one frame.
`paper/cpc/data/failure/drift_con.csv` was left as it is in the tree (Python and C ABI already agreed). `paper/cpc/data/failure/drift_extxyz.csv` was not changed. A host rerun of the extxyz peer section could not import extxyz, chemfiles, or MDAnalysis; that host transcript is `paper/cpc/data/cloud-runs/spec01/logs/drift_extxyz.host.csv` and `drift_py.txt`. Spec 03 does not redo the paired peer timings.
Merged table `paper/cpc/data/failure/drift_bindings.csv` (same bytes as `paper/cpc/data/cloud-runs/spec01/drift_bindings.csv`):
```
file,expected,python,c_abi,julia,fortran,sha_python,sha_julia,sha_fortran,rewrite_stable_python,rewrite_stable_julia,rewrite_stable_fortran
column4_out_of_range.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
missing_spec_version.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
per_type_zero.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
unknown_section.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
unsupported_spec_version.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
v3_bad_units.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
v3_missing_units.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
validate_true_missing_sections.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
column4_spec1_all_fixed.con,accept,accept,accept,accept,accept,75195463d711,75195463d711,03686cb8a301,yes,yes,yes
column4_spec2_all_fixed.con,accept,accept,accept,accept,accept,7feaa7c4d483,7feaa7c4d483,5b8da9e25c7f,yes,yes,yes
column4_spec2_x_only.con,accept,accept,accept,accept,accept,dd07bc2dd0b9,dd07bc2dd0b9,209ad7ce3eb5,yes,yes,yes
column4_spec2_xz.con,accept,accept,accept,accept,accept,26c0bc7a8662,26c0bc7a8662,99b51bab21ef,yes,yes,yes
column4_spec2_y_only.con,accept,accept,accept,accept,accept,b67790cbb895,b67790cbb895,f8126e4d60be,yes,yes,yes
v2_minimal.con,accept,accept,accept,accept,accept,ca6e4a4278b8,ca6e4a4278b8,96d39060f60c,yes,yes,yes
v3_units.con,accept,accept,accept,accept,accept,1e12f65fd88a,1e12f65fd88a,5db10e464745,yes,yes,yes
zero_atom.con,accept,accept,accept,accept,accept,07b78214eef7,07b78214eef7,fcae463b33be,yes,yes,yes
zero_atom_eof.con,accept,accept,accept,accept,accept,240e375b7fab,240e375b7fab,1251a44c2c82,yes,yes,yes
zero_atom_then_frame.con,accept,accept,accept,accept,accept,556a5f848913,556a5f848913,d3e55a655124,yes,yes,yes
variant0.con,accept,accept,accept,accept,accept,7f4518a5a5b1,7f4518a5a5b1,7f4518a5a5b1,yes,yes,yes
variant1.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
variant2.con,accept,accept,accept,accept,accept,539b622083f2,539b622083f2,b64e7dc4482c,yes,yes,yes
variant3.con,accept,accept,accept,accept,accept,cd0b86aa9a38,cd0b86aa9a38,cd0b86aa9a38,yes,yes,yes
variant4.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
variant5.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
variant6.con,reject,reject,reject,reject,reject,-,-,-,-,-,-
```
## Spec 02: masked asymmetric CI-NEB
Geometry (`paper/cpc/scripts/e4_masked_neb.py`, `build_step_hop`). ASE `fcc100("Pt", size=(4, 4, 4), vacuum=8.0, orthogonal=True)`. Every top-layer atom is deleted except the one nearest the cell centre, then that island is shifted +0.35 Å in y. A frozen blocker is appended at `[0.15, y0+0.35, z_island]`. The adatom is appended at `[2.71, 5.55, z_island]` and the product moves it to `[8.38, 5.55, z_island]`. Header of the written frames: `e4 Pt(100) step-edge hop`.
After the build, the reactant has 51 atoms. Masks: 34 atoms mask 7 (bottom two layers, the island, and the blocker), 1 atom mask 4 (the adatom, z held), 16 atoms mask 0. Cell from `neb.con`: `11.08743432900506498 11.08743432900506498 21.87999999999999901` Å, angles 90, 90, 90.
Endpoints were minimized (converged force 0.0001 eV/Å, max iterations 400) and xy-wrapped into the cell. The band is 7 interior images (9 frames). Potential `morse_pt`. Spring 1. Climbing image on from the start (`climbing_image_method` enabled; `setup_mmf_peaks` and `ci_mmf` off). Improved tangent (`old_tangent` false). `converged_force` 0.01 eV/Å. Steepest descent: `sd_alpha` 0.01, `sd_two_point` false (memoryless), `max_move` 0.05. L-BFGS: `max_move` 0.20. Uninterrupted caps: 2500 (SD) and 500 (L-BFGS). Both converged inside the cap.
Interrupt index K = round(0.30 × N). Resume `max_iterations` = N − K + 1, because eOn logs an iteration before the first step and stops when the counter reaches `max_iterations` without taking that step. SD: N = 481, K = 144, remaining = 338. L-BFGS: N = 91, K = 27, remaining = 65.
Off-line distance is |d| of the climbing image in the (s, d) projection onto the endpoint chord (`chemparseplot.parse.projection`). The check is > 0.1 Å.
- SD climbing image index 3, s = 0.19754764314323858, d = off_line = 0.1407059062693008 Å.
- L-BFGS climbing image index 3, s = 0.19734555358192546, d = off_line = 0.14071937747703683 Å.
Both clear 0.1 Å.
Pass (a), steepest descent, shortest Python round trip, matched step count: saddle minimum-image RMSD to the uninterrupted saddle is 0.0 Å, which is within 1e-12 Å. Barrier 2.033834 eV and final force 0.0023626 eV/Å match the uninterrupted run. L-BFGS is not memoryless; its round-trip RMSD is 0.0008169448215099377 Å and is reported as measured.
Six-decimal rewrite: SD RMSD 2.0597828798875996e-07 Å, barrier 2.033835 eV. L-BFGS RMSD 0.0008188916265442222 Å, barrier 2.033649 eV.
Masks collapsed to a full freeze (ASE eon reader): the band leaves the uninterrupted saddle. SD: 82 steps, barrier 1.679825 eV, force 0.0099694 eV/Å, RMSD 0.3439301548646094 Å, no negative saddle eigenvalue. L-BFGS: 16 steps, barrier 1.607404 eV, force 0.0085555 eV/Å, RMSD 0.34497022921906384 Å, no negative saddle eigenvalue.
Masks dropped (ASE POSCAR round trip): SD ran the matched 338 steps and did not converge (force 0.52504 eV/Å), barrier 0.570366 eV, RMSD 0.06290062996500298 Å, one imaginary frequency -1.408717e+12 Hz. L-BFGS ran 65 steps, force 2.0892 eV/Å, barrier 1.64593 eV, RMSD 0.42722862363504904 Å, imaginary frequencies -1.361602e+12 and -7.031861e+11 Hz.
Vineyard prefactor is `no imaginary mode` on every row. eOn writes eigenvalues of the mass-weighted Hessian to `freqs.dat` (not Hz). `freq.dat` is empty. Conversion used by eOn is sqrt(λ) / (2 π × 10.18e-15). On the SD full saddle the two negative eigenvalues are λ = -0.016565 and λ = -0.012095, which convert to -2.012186e+12 Hz and -1.719394e+12 Hz. The reactant minimum has λ = -0.003557 and the product minimum has λ = -0.001392, so each endpoint Hessian also has a negative eigenvalue. Prefactor.cpp refuses the Vineyard ratio in that case. A positive eigenvalue 0.048076 is present at the reactant, consistent with the held-z curvature being positive; the extra negative mode is an in-plane soft mode. Freeze variants have no negative saddle eigenvalue, so the imaginary-frequency column is also `no imaginary mode`.
SD full `results.dat` also records: termination GOOD, potential_energy -2.167223371833e+02 eV, total_force_calls 3369, force_calls_neb 3.367000000000e+03, energy_reference -2.167223371833e+02, time_seconds 5.399154230000e-01, user_time 5.451230000000e-01, system_time 1.194790000000e-01. Image energies (eV) and forces (eV/Å) from that file: image0 0.000000 / 0.000066, image1 1.423924 / 0.758421, image2 0.904679 / 0.042003, image3 2.033834 / 0.002363, image4 0.652754 / 0.346015, image5 2.012854 / 0.527211, image6 1.039594 / 0.574070, image7 1.480917 / 1.105093, image8 -0.133609 / 0.000098.
Figure: `paper/cpc/data/cloud-runs/spec02/e4_restart_formats.pdf` (296225 bytes) and `e4_restart_formats.png` (224018 bytes). Five panels (full, round, six, freeze, dropmask) of the steepest-descent bands in the uninterrupted (s, d) basis. Each panel marks its own saddle and the other panels' saddles. `paper/cpc/scripts/plot_restart_formats.py` still writes the manuscript figure when invoked without `--e4`. The manuscript figure was not regenerated.
Table `paper/cpc/data/failure/e4_restart.csv`:
```
optimizer,variant,iterations,barrier_eV,final_force_eV_A,saddle_mic_rmsd_A,off_line_A,imaginary_frequency_Hz,prefactor_Hz
sd,full,481,2.033834,0.0023626,0.0,0.1407059062693008,-2.012186e+12;-1.719394e+12,no imaginary mode
sd,round,338,2.033834,0.0023626,0.0,,-2.012186e+12;-1.719394e+12,no imaginary mode
sd,six,338,2.033835,0.0023626,2.0597828798875996e-07,,-2.012186e+12;-1.719394e+12,no imaginary mode
sd,freeze,82,1.679825,0.0099694,0.3439301548646094,,no imaginary mode,no imaginary mode
sd,dropmask,338,0.570366,0.52504,0.06290062996500298,,-1.408717e+12,no imaginary mode
lbfgs,full,91,2.033657,0.0045373,0.0,0.14071937747703683,-2.010363e+12;-1.719607e+12,no imaginary mode
lbfgs,round,59,2.033648,0.0042564,0.0008169448215099377,,-2.012004e+12;-1.719607e+12,no imaginary mode
lbfgs,six,59,2.033649,0.0059849,0.0008188916265442222,,-2.012247e+12;-1.720033e+12,no imaginary mode
lbfgs,freeze,16,1.607404,0.0085555,0.34497022921906384,,no imaginary mode,no imaginary mode
lbfgs,dropmask,65,1.64593,2.0892,0.42722862363504904,,-1.361602e+12;-7.031861e+11,no imaginary mode
```
Machine summary `paper/cpc/data/failure/e4_summary.json`:
```
{
  "eon": "/tmp/eon-build/client/eonclient",
  "potential": "morse_pt",
  "images": 7,
  "fmax_eV_A": 0.01,
  "sd": {
    "iterations": 481,
    "final_force": 0.0023626,
    "barrier_eV": 2.033834,
    "geometry": {
      "saddle_index": 3,
      "s": 0.19754764314323858,
      "d": 0.1407059062693008,
      "off_line_A": 0.1407059062693008,
      "n_images": 9
    },
    "returncode": 0,
    "prefactor": {
      "imaginary_frequency_Hz": "-2.012186e+12;-1.719394e+12",
      "prefactor_Hz": "no imaginary mode",
      "returncode": 0
    },
    "round": {
      "iterations": 338,
      "barrier_eV": 2.033834,
      "final_force": 0.0023626,
      "saddle_mic_rmsd_A": 0.0,
      "imaginary_frequency_Hz": "-2.012186e+12;-1.719394e+12",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "six": {
      "iterations": 338,
      "barrier_eV": 2.033835,
      "final_force": 0.0023626,
      "saddle_mic_rmsd_A": 2.0597828798875996e-07,
      "imaginary_frequency_Hz": "-2.012186e+12;-1.719394e+12",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "freeze": {
      "iterations": 82,
      "barrier_eV": 1.679825,
      "final_force": 0.0099694,
      "saddle_mic_rmsd_A": 0.3439301548646094,
      "imaginary_frequency_Hz": "no imaginary mode",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "dropmask": {
      "iterations": 338,
      "barrier_eV": 0.570366,
      "final_force": 0.52504,
      "saddle_mic_rmsd_A": 0.06290062996500298,
      "imaginary_frequency_Hz": "-1.408717e+12",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "interrupt_k": 144,
    "remaining": 338,
    "full_saddle_mic_rmsd_A": 0.0
  },
  "lbfgs": {
    "iterations": 91,
    "final_force": 0.0045373,
    "barrier_eV": 2.033657,
    "geometry": {
      "saddle_index": 3,
      "s": 0.19734555358192546,
      "d": 0.14071937747703683,
      "off_line_A": 0.14071937747703683,
      "n_images": 9
    },
    "returncode": 0,
    "prefactor": {
      "imaginary_frequency_Hz": "-2.010363e+12;-1.719607e+12",
      "prefactor_Hz": "no imaginary mode",
      "returncode": 0
    },
    "round": {
      "iterations": 59,
      "barrier_eV": 2.033648,
      "final_force": 0.0042564,
      "saddle_mic_rmsd_A": 0.0008169448215099377,
      "imaginary_frequency_Hz": "-2.012004e+12;-1.719607e+12",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "six": {
      "iterations": 59,
      "barrier_eV": 2.033649,
      "final_force": 0.0059849,
      "saddle_mic_rmsd_A": 0.0008188916265442222,
      "imaginary_frequency_Hz": "-2.012247e+12;-1.720033e+12",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "freeze": {
      "iterations": 16,
      "barrier_eV": 1.607404,
      "final_force": 0.0085555,
      "saddle_mic_rmsd_A": 0.34497022921906384,
      "imaginary_frequency_Hz": "no imaginary mode",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "dropmask": {
      "iterations": 65,
      "barrier_eV": 1.64593,
      "final_force": 2.0892,
      "saddle_mic_rmsd_A": 0.42722862363504904,
      "imaginary_frequency_Hz": "-1.361602e+12;-7.031861e+11",
      "prefactor_Hz": "no imaginary mode",
      "has_neb": true,
      "stderr_tail": ""
    },
    "interrupt_k": 27,
    "remaining": 65,
    "full_saddle_mic_rmsd_A": 0.0
  }
}
```
Steepest-descent band table `paper/cpc/evidence/work/e4/full/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000017
  1     1.328167     1.423924    -0.758395
  2     2.679850     0.904679    -0.040396
  3     4.061500     2.033834     0.000248
  4     5.627260     0.652754    -0.345168
  5     7.121850     2.012854     0.523010
  6     8.542622     1.039594    -0.572044
  7     9.893706     1.480917     1.104882
  8    11.185720    -0.133609     0.000005
```
Steepest-descent `results.dat` files for the five resume variants, then the L-BFGS copies:
`paper/cpc/evidence/work/e4/full/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
3369 total_force_calls
-2.167223371833e+02 potential_energy
3.367000000000e+03 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.423924 image1_energy
0.758421 image1_force
0.024336 image1_projected_force
0.904679 image2_energy
0.042003 image2_force
0.032100 image2_projected_force
2.033834 image3_energy
0.002363 image3_force
0.002363 image3_projected_force
0.652754 image4_energy
0.346015 image4_force
0.075169 image4_projected_force
2.012854 image5_energy
0.527211 image5_force
0.099303 image5_projected_force
1.039594 image6_energy
0.574070 image6_force
0.084728 image6_projected_force
1.480917 image7_energy
1.105093 image7_force
0.062884 image7_projected_force
-0.133609 image8_energy
0.000098 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.162991 extremum0_position
-215.219458 extremum0_energy
1.989734 extremum1_position
-215.817938 extremum1_energy
2.999949 extremum2_position
-214.688503 extremum2_energy
3.945448 extremum3_position
-216.084056 extremum3_energy
4.917890 extremum4_position
-214.678218 extremum4_energy
5.882057 extremum5_position
-215.729018 extremum5_energy
6.744631 extremum6_position
-215.064157 extremum6_energy
5.399154230000e-01 time_seconds
5.451230000000e-01 user_time
1.194790000000e-01 system_time
sd optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/round/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
2368 total_force_calls
-2.167223371833e+02 potential_energy
2.366000000000e+03 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.423924 image1_energy
0.758421 image1_force
0.024336 image1_projected_force
0.904679 image2_energy
0.042003 image2_force
0.032100 image2_projected_force
2.033834 image3_energy
0.002363 image3_force
0.002363 image3_projected_force
0.652754 image4_energy
0.346015 image4_force
0.075169 image4_projected_force
2.012854 image5_energy
0.527211 image5_force
0.099303 image5_projected_force
1.039594 image6_energy
0.574070 image6_force
0.084728 image6_projected_force
1.480917 image7_energy
1.105093 image7_force
0.062884 image7_projected_force
-0.133609 image8_energy
0.000098 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.162991 extremum0_position
-215.219458 extremum0_energy
1.989734 extremum1_position
-215.817938 extremum1_energy
2.999949 extremum2_position
-214.688503 extremum2_energy
3.945448 extremum3_position
-216.084056 extremum3_energy
4.917890 extremum4_position
-214.678218 extremum4_energy
5.882057 extremum5_position
-215.729018 extremum5_energy
6.744631 extremum6_position
-215.064157 extremum6_energy
3.758527350000e-01 time_seconds
3.923610000000e-01 user_time
7.042300000000e-02 system_time
sd optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/six/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
2368 total_force_calls
-2.167223392096e+02 potential_energy
2.366000000000e+03 force_calls_neb
-2.167223392096e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.423925 image1_energy
0.758420 image1_force
0.024336 image1_projected_force
0.904679 image2_energy
0.042003 image2_force
0.032100 image2_projected_force
2.033835 image3_energy
0.002363 image3_force
0.002363 image3_projected_force
0.652754 image4_energy
0.346014 image4_force
0.075170 image4_projected_force
2.012853 image5_energy
0.527211 image5_force
0.099303 image5_projected_force
1.039594 image6_energy
0.574072 image6_force
0.084728 image6_projected_force
1.480918 image7_energy
1.105093 image7_force
0.062884 image7_projected_force
-0.133609 image8_energy
0.000101 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.162990 extremum0_position
-215.219459 extremum0_energy
1.989734 extremum1_position
-215.817940 extremum1_energy
2.999949 extremum2_position
-214.688504 extremum2_energy
3.945448 extremum3_position
-216.084059 extremum3_energy
4.917890 extremum4_position
-214.678221 extremum4_energy
5.882057 extremum5_position
-215.729020 extremum5_energy
6.744630 extremum6_position
-215.064159 extremum6_energy
3.792695660000e-01 time_seconds
3.689040000000e-01 user_time
9.577300000000e-02 system_time
sd optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/freeze/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
576 total_force_calls
-2.167223371833e+02 potential_energy
5.740000000000e+02 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000063 image0_force
0.000000 image0_projected_force
0.556196 image1_energy
0.064543 image1_force
0.005199 image1_projected_force
1.528252 image2_energy
0.113013 image2_force
0.003595 image2_projected_force
1.337557 image3_energy
0.257786 image3_force
0.015809 image3_projected_force
0.633120 image4_energy
0.000869 image4_force
0.000920 image4_projected_force
1.280854 image5_energy
0.226974 image5_force
0.019703 image5_projected_force
1.679825 image6_energy
0.010029 image6_force
0.009969 image6_projected_force
0.460928 image7_energy
0.067733 image7_force
0.003954 image7_projected_force
-0.133609 image8_energy
0.000096 image8_force
0.000000 image8_projected_force
7 number_of_extrema
2.025277 extremum0_position
-215.193626 extremum0_energy
2.934445 extremum1_position
-215.387957 extremum1_energy
3.034289 extremum2_position
-215.382042 extremum2_energy
3.999997 extremum3_position
-216.089217 extremum3_energy
4.968684 extremum4_position
-215.439402 extremum4_energy
5.999675 extremum5_position
-215.042512 extremum5_energy
5.032274 extremum6_position
-215.442850 extremum6_energy
1.002274060000e-01 time_seconds
1.070530000000e-01 user_time
1.585900000000e-02 system_time
sd optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/dropmask/results.dat`:
```
1 termination_reason
FAIL_MAX_ITERATIONS termination_reason_text
neb job_type
MORSE_PT potential_type
2368 total_force_calls
-2.167223371833e+02 potential_energy
2.366000000000e+03 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
4.538105 image0_force
0.000000 image0_projected_force
-0.122335 image1_energy
1.306391 image1_force
0.525042 image1_projected_force
-0.299238 image2_energy
0.275497 image2_force
0.241937 image2_projected_force
0.570366 image3_energy
0.013292 image3_force
0.013223 image3_projected_force
-0.192143 image4_energy
0.210405 image4_force
0.036301 image4_projected_force
0.518019 image5_energy
0.436265 image5_force
0.074422 image5_projected_force
-0.293219 image6_energy
0.324995 image6_force
0.250788 image6_projected_force
-0.199058 image7_energy
1.239067 image7_force
0.478684 image7_projected_force
-0.133609 image8_energy
4.291557 image8_force
0.000000 image8_projected_force
0 number_of_extrema
4.049202730000e-01 time_seconds
4.356900000000e-01 user_time
7.511900000000e-02 system_time
sd optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/full/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
639 total_force_calls
-2.167223371833e+02 potential_energy
6.370000000000e+02 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.440716 image1_energy
0.687701 image1_force
0.013365 image1_projected_force
0.907047 image2_energy
0.124326 image2_force
0.037430 image2_projected_force
2.033657 image3_energy
0.004537 image3_force
0.004537 image3_projected_force
0.634095 image4_energy
0.127497 image4_force
0.016759 image4_projected_force
2.030444 image5_energy
0.402733 image5_force
0.028358 image5_projected_force
0.975291 image6_energy
0.169936 image6_force
0.015515 image6_projected_force
1.576538 image7_energy
0.781265 image7_force
0.015243 image7_projected_force
-0.133609 image8_energy
0.000098 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.147737 extremum0_position
-215.216608 extremum0_energy
1.970965 extremum1_position
-215.817586 extremum1_energy
2.999963 extremum2_position
-214.688681 extremum2_energy
4.022744 extremum3_position
-216.090245 extremum3_energy
5.074463 extremum4_position
-214.671421 extremum4_energy
6.850492 extremum5_position
-215.068153 extremum5_energy
6.036686 extremum6_position
-215.751337 extremum6_energy
1.089062200000e-01 time_seconds
1.064680000000e-01 user_time
2.981100000000e-02 system_time
lbfgs optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/round/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
415 total_force_calls
-2.167223371833e+02 potential_energy
4.130000000000e+02 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.442424 image1_energy
0.679857 image1_force
0.009042 image1_projected_force
0.907848 image2_energy
0.133492 image2_force
0.010264 image2_projected_force
2.033648 image3_energy
0.004256 image3_force
0.004256 image3_projected_force
0.633344 image4_energy
0.107802 image4_force
0.013087 image4_projected_force
2.031665 image5_energy
0.390749 image5_force
0.019241 image5_projected_force
0.976459 image6_energy
0.189168 image6_force
0.014677 image6_projected_force
1.581160 image7_energy
0.761524 image7_force
0.020338 image7_projected_force
-0.133609 image8_energy
0.000098 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.145828 extremum0_position
-215.216424 extremum0_energy
1.967597 extremum1_position
-215.817366 extremum1_energy
2.999592 extremum2_position
-214.688688 extremum2_energy
4.019382 extremum3_position
-216.090442 extremum3_energy
5.072927 extremum4_position
-214.671304 extremum4_energy
6.854206 extremum5_position
-215.067448 extremum5_energy
6.040589 extremum6_position
-215.751153 extremum6_energy
7.528797500000e-02 time_seconds
7.960300000000e-02 user_time
1.405400000000e-02 system_time
lbfgs optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/six/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
415 total_force_calls
-2.167223392096e+02 potential_energy
4.130000000000e+02 force_calls_neb
-2.167223392096e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000066 image0_force
0.000000 image0_projected_force
1.442557 image1_energy
0.679210 image1_force
0.009750 image1_projected_force
0.907902 image2_energy
0.134710 image2_force
0.010903 image2_projected_force
2.033649 image3_energy
0.005985 image3_force
0.005985 image3_projected_force
0.633288 image4_energy
0.106212 image4_force
0.013580 image4_projected_force
2.032428 image5_energy
0.385089 image5_force
0.026740 image5_projected_force
0.975924 image6_energy
0.185571 image6_force
0.027450 image6_projected_force
1.581390 image7_energy
0.760620 image7_force
0.024555 image7_projected_force
-0.133609 image8_energy
0.000101 image8_force
0.000000 image8_projected_force
7 number_of_extrema
1.145666 extremum0_position
-215.216425 extremum0_energy
1.967328 extremum1_position
-215.817364 extremum1_energy
2.999554 extremum2_position
-214.688689 extremum2_energy
4.019054 extremum3_position
-216.090454 extremum3_energy
5.071846 extremum4_position
-214.671118 extremum4_energy
6.854192 extremum5_position
-215.067354 extremum5_energy
6.039591 extremum6_position
-215.751420 extremum6_energy
7.549860100000e-02 time_seconds
7.739000000000e-02 user_time
1.934700000000e-02 system_time
lbfgs optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/freeze/results.dat`:
```
0 termination_reason
GOOD termination_reason_text
neb job_type
MORSE_PT potential_type
114 total_force_calls
-2.167223371833e+02 potential_energy
1.120000000000e+02 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
0.000063 image0_force
0.000000 image0_projected_force
0.428710 image1_energy
0.070096 image1_force
0.002885 image1_projected_force
1.578279 image2_energy
0.109671 image2_force
0.006477 image2_projected_force
1.549660 image3_energy
0.196950 image3_force
0.005147 image3_projected_force
0.643157 image4_energy
0.000900 image4_force
0.000488 image4_projected_force
1.377121 image5_energy
0.156454 image5_force
0.005573 image5_projected_force
1.607404 image6_energy
0.008558 image6_force
0.008555 image6_projected_force
0.266080 image7_energy
0.071953 image7_force
0.003330 image7_projected_force
-0.133609 image8_energy
0.000096 image8_force
0.000000 image8_projected_force
7 number_of_extrema
2.087521 extremum0_position
-215.142587 extremum0_energy
2.850395 extremum1_position
-215.177192 extremum1_energy
3.017459 extremum2_position
-215.171808 extremum2_energy
4.984115 extremum3_position
-215.344636 extremum3_energy
4.000038 extremum4_position
-216.079180 extremum4_energy
5.032792 extremum5_position
-215.346031 extremum5_energy
6.000012 extremum6_position
-215.114933 extremum6_energy
2.264443600000e-02 time_seconds
2.238100000000e-02 user_time
8.952000000000e-03 system_time
lbfgs optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/dropmask/results.dat`:
```
1 termination_reason
FAIL_MAX_ITERATIONS termination_reason_text
neb job_type
MORSE_PT potential_type
457 total_force_calls
-2.167223371833e+02 potential_energy
4.550000000000e+02 force_calls_neb
-2.167223371833e+02 energy_reference
7.000000000000e+00 number_of_images
0.000000 image0_energy
4.538105 image0_force
0.000000 image0_projected_force
0.473271 image1_energy
2.048821 image1_force
0.998333 image1_projected_force
1.645930 image2_energy
2.100368 image2_force
2.089163 image2_projected_force
0.149820 image3_energy
1.880415 image3_force
1.582319 image3_projected_force
-0.153414 image4_energy
0.650246 image4_force
0.739438 image4_projected_force
0.342486 image5_energy
0.866266 image5_force
0.377345 image5_projected_force
-0.248300 image6_energy
0.343587 image6_force
0.215400 image6_projected_force
-0.297092 image7_energy
0.999618 image7_force
0.358711 image7_projected_force
-0.133609 image8_energy
4.291557 image8_force
0.000000 image8_projected_force
0 number_of_extrema
8.677975600000e-02 time_seconds
8.281900000000e-02 user_time
2.615600000000e-02 system_time
lbfgs optimizer_backend
eon.optimizer.v1 optimizer_provenance_schema
eon.compatibility.v1 compatibility_schema
3 compatibility_readcon_spec_version
0.14.9 compatibility_readcon_min_version
0.2.3 compatibility_eon_schema_min_version
1.10.4 compatibility_rgpycrumbs_min_version
1.9.17 compatibility_chemparseplot_min_version
eon engine_id
3.6.0 engine_version
2d2adad engine_build_identity
morse_pt rgpot_name
eon.rgpot.v1 rgpot_schema
3.2.0 rgpot_version
```
`paper/cpc/evidence/work/e4/lbfgs/full/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000017
  1     1.351786     1.440716    -0.687579
  2     2.700192     0.907047    -0.118612
  3     4.045014     2.033657     0.000175
  4     5.449575     0.634095     0.126404
  5     6.852337     2.030444    -0.401733
  6     8.254634     0.975291     0.169227
  7     9.656895     1.576538     0.781140
  8    11.053065    -0.133609     0.000004
```
`paper/cpc/evidence/work/e4/round/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000017
  1     1.328167     1.423924    -0.758395
  2     2.679850     0.904679    -0.040396
  3     4.061500     2.033834     0.000248
  4     5.627260     0.652754    -0.345168
  5     7.121850     2.012854     0.523010
  6     8.542622     1.039594    -0.572044
  7     9.893706     1.480917     1.104882
  8    11.185720    -0.133609     0.000005
```
`paper/cpc/evidence/work/e4/six/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000020
  1     1.328167     1.423925    -0.758394
  2     2.679850     0.904679    -0.040397
  3     4.061500     2.033835     0.000248
  4     5.627260     0.652754    -0.345167
  5     7.121850     2.012853     0.523010
  6     8.542622     1.039594    -0.572045
  7     9.893706     1.480918     1.104883
  8    11.185720    -0.133609     0.000003
```
`paper/cpc/evidence/work/e4/freeze/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000004
  1     0.680109     0.556196    -0.012945
  2     1.650546     1.528252    -0.025309
  3     3.098511     1.337557    -0.068468
  4     5.457951     0.633120    -0.000006
  5     7.814383     1.280854     0.057003
  6     9.316020     1.679825     0.000555
  7    10.273585     0.460928     0.014184
  8    10.936300    -0.133609     0.000002
```
`paper/cpc/evidence/work/e4/dropmask/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000     1.563609
  1     1.723520    -0.122335    -1.218000
  2     3.692604    -0.299238     0.245795
  3     5.444929     0.570366     0.005068
  4     7.000428    -0.192143    -0.203691
  5     8.572282     0.518019     0.430915
  6    10.203111    -0.293219    -0.284475
  7    12.041573    -0.199058     1.160792
  8    13.656968    -0.133609    -1.437455
```
`paper/cpc/evidence/work/e4/lbfgs/round/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000017
  1     1.354242     1.442424    -0.679821
  2     2.702816     0.907848    -0.133350
  3     4.043184     2.033648     0.001949
  4     5.452546     0.633344     0.107479
  5     6.851818     2.031665    -0.390319
  6     8.245209     0.976459     0.188697
  7     9.644705     1.581160     0.761257
  8    11.046809    -0.133609     0.000005
```
`paper/cpc/evidence/work/e4/lbfgs/six/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000020
  1     1.354443     1.442557    -0.679166
  2     2.702967     0.907902    -0.134537
  3     4.042986     2.033649     0.002132
  4     5.452888     0.633288     0.105726
  5     6.853766     2.032428    -0.384225
  6     8.247519     0.975924     0.183595
  7     9.646152     1.581390     0.760233
  8    11.048587    -0.133609     0.000002
```
`paper/cpc/evidence/work/e4/lbfgs/freeze/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000    -0.000004
  1     0.589090     0.428710    -0.014683
  2     1.498719     1.578279    -0.025754
  3     2.850241     1.549660    -0.047236
  4     4.971472     0.643157     0.000082
  5     7.085536     1.377121     0.034749
  6     8.531354     1.607404    -0.000108
  7     9.389301     0.266080     0.015172
  8     9.924482    -0.133609     0.000003
```
`paper/cpc/evidence/work/e4/lbfgs/dropmask/neb.dat`:
```
img    rxn_coord       energy       f_para
  0     0.000000     0.000000     1.349392
  1     2.014233     0.473271    -1.919879
  2     4.731328     1.645930    -0.724816
  3     8.473408     0.149820     1.312888
  4    11.376654    -0.153414     0.537954
  5    13.624268     0.342486     0.849810
  6    15.503748    -0.248300    -0.267814
  7    17.357737    -0.297092     0.937065
  8    19.100788    -0.133609    -1.203716
```
`paper/cpc/evidence/work/e4/sd/prefactor_full/freqs.dat`:
```
[Prefactor] Frequencies at minimum 1

 -0.003557 
  0.012832 
  0.015146 
  0.021007 
  0.033892 

  0.042153 
  0.042947 
  0.044000 
  0.046106 
  0.047123 

  0.048076 
  0.048445 
  0.050724 
  0.055325 
  0.056194 

  0.069929 
  0.075667 
  0.081897 
  0.087163 
  0.092330 

  0.106389 
  0.112515 
  0.118694 
  0.119981 
  0.125868 

  0.141840 
  0.168454 
[Prefactor] Frequencies at saddle

 -0.016565 
 -0.012095 
  0.013523 
  0.018760 
  0.024983 

  0.033087 
  0.035691 
  0.039897 
  0.043097 
  0.043825 

  0.044325 
  0.051363 
  0.055059 
  0.056282 
  0.064057 

  0.070273 
  0.078667 
  0.083941 
  0.091374 
  0.106866 

  0.114157 
  0.116972 
  0.127974 
  0.139787 
  0.150278 

  0.180230 
  0.226784 
[Prefactor] Frequencies at minimum 2

 -0.001392 
  0.016217 
  0.017487 
  0.022638 
  0.035219 

  0.041119 
  0.044717 
  0.045875 
  0.046988 
  0.048213 

  0.049206 
  0.050353 
  0.055232 
  0.055766 
  0.059373 

  0.062968 
  0.067553 
  0.077343 
  0.080407 
  0.086057 

  0.090256 
  0.112625 
  0.114850 
  0.119217 
  0.122742 

  0.135785 
  0.158990 
```
## Spec 03: readcon-db ingest and per-stage timings
Does not repeat the paired peer timings. Fresh database per repeat (`readcon_db.ConCorpus`). Ingest time is `append_trajectory` only. Unique and duplicate counts walk `frame_hash` after the timed call.
The 10k-frame file is `resources/test/cuh2.con` (218 atoms) repeated 10000 times by the same text-repeat construction as `paper/cpc/bench/run_bench.py`, written to `/tmp/cloud-bench/frames-10000.con` (not committed). Every scan row records frames = 10000 and bytes = 167710000.
Five campaign bands, from the novel-measure set: uninterrupted `e1` neb/full, round trip, six decimals, height held, adatom frozen. Each band has 7 frames. The five together have 35 frames.
Stage definitions follow `paper/cpc/evidence/e2_layered.py`. `file_to_string` and `boundary_scan` come from `e2-bench` scan (file read, then frame-start offsets). `rust_parse` is `e2-bench` parse at 1, 2, 4, and 8 threads. `python_read_con` is `read_con` at 1 thread. `python_object_construction` is that Python time minus the same-repeat 1-thread Rust parse.
15 repeats. BCa median via `paper/cpc/bench/analyze_bench.py`: N_BOOT = 9999, seed = 20261011, alpha = 0.05. One warmup scan, parse, and Python read before the timed repeats. `e2-bench` release build: 7.23 s, one `non_camel_case_types` warning in readcon-core.
BCa medians, seconds [low, high]:
- file_to_string, 1 thread: 0.091680385 [0.090229286, 0.094404175]
- boundary_scan, 1 thread: 0.034323919 [0.034114358, 0.035251760]
- rust_parse, 1 thread: 0.466395400 [0.458254968, 0.476859739]
- rust_parse, 2 threads: 0.296515450 [0.292882869, 0.300948331]
- rust_parse, 4 threads: 0.190559481 [0.185210080, 0.193619768]
- rust_parse, 8 threads: 0.133593308 [0.131240362, 0.135338844]
- python_read_con, 1 thread: 0.955813806 [0.945106072, 0.959644711]
- python_object_construction, 1 thread: 0.484828095 [0.470553808, 0.495941456]
Ingest BCa, frames/s [low, high], then frames, unique hashes, duplicate frames:
- uninterrupted: 15561.849455 [11704.941824, 15977.868376], 7, 7, 0
- round_trip: 15061.472313 [11750.348733, 16421.825074], 7, 7, 0
- six_decimals: 13922.950394 [8110.450433, 14800.562419], 7, 7, 0
- height_held: 13310.540618 [10016.756607, 14347.114084], 7, 7, 0
- adatom_frozen: 13737.180270 [7841.125358, 14751.686965], 7, 7, 0
- five_bands: 14511.110328 [12327.555116, 15229.442430], 35, 35, 0
- frames-10000: 16319.316781 [16225.547520, 16473.420322], 10000, 1, 9999
The 10k file is one CuH2 frame repeated, so one unique hash and 9999 duplicates is the dedup result.
Repeat 0, seconds: file_to_string 0.092067088, boundary_scan 0.034269860, rust_parse 1 thread 0.476859739, rust_parse 2 threads 0.368002552. The remaining repeats are the CSV below.
`paper/cpc/bench/results/stages.csv` (same bytes as `paper/cpc/data/cloud-runs/spec03/stages.csv`):
```
stage,threads,repeat,seconds,frames,bytes,median_s,bca_low_s,bca_high_s
file_to_string,1,0,0.092067088,10000,167710000,,,
boundary_scan,1,0,0.034269860,10000,167710000,,,
rust_parse,1,0,0.476859739,10000,167710000,,,
rust_parse,2,0,0.368002552,10000,167710000,,,
rust_parse,4,0,0.184405388,10000,167710000,,,
rust_parse,8,0,0.129457987,10000,167710000,,,
python_read_con,1,0,0.947413547,10000,167710000,,,
python_object_construction,1,0,0.470553808,10000,167710000,,,
file_to_string,1,1,0.090229286,10000,167710000,,,
boundary_scan,1,1,0.034114358,10000,167710000,,,
rust_parse,1,1,0.543010983,10000,167710000,,,
rust_parse,2,1,0.296515450,10000,167710000,,,
rust_parse,4,1,0.188741120,10000,167710000,,,
rust_parse,8,1,0.134980319,10000,167710000,,,
python_read_con,1,1,0.958536263,10000,167710000,,,
python_object_construction,1,1,0.415525280,10000,167710000,,,
file_to_string,1,2,0.099452750,10000,167710000,,,
boundary_scan,1,2,0.036581184,10000,167710000,,,
rust_parse,1,2,0.611097328,10000,167710000,,,
rust_parse,2,2,0.333663443,10000,167710000,,,
rust_parse,4,2,0.195578535,10000,167710000,,,
rust_parse,8,2,0.155028722,10000,167710000,,,
python_read_con,1,2,0.984003963,10000,167710000,,,
python_object_construction,1,2,0.372906635,10000,167710000,,,
file_to_string,1,3,0.096657685,10000,167710000,,,
boundary_scan,1,3,0.035852545,10000,167710000,,,
rust_parse,1,3,0.470679830,10000,167710000,,,
rust_parse,2,3,0.306142687,10000,167710000,,,
rust_parse,4,3,0.192085403,10000,167710000,,,
rust_parse,8,3,0.135642502,10000,167710000,,,
python_read_con,1,3,0.982248423,10000,167710000,,,
python_object_construction,1,3,0.511568593,10000,167710000,,,
file_to_string,1,4,0.094404175,10000,167710000,,,
boundary_scan,1,4,0.035251760,10000,167710000,,,
rust_parse,1,4,0.466395400,10000,167710000,,,
rust_parse,2,4,0.292882869,10000,167710000,,,
rust_parse,4,4,0.197501361,10000,167710000,,,
rust_parse,8,4,0.131678582,10000,167710000,,,
python_read_con,1,4,0.945106072,10000,167710000,,,
python_object_construction,1,4,0.478710672,10000,167710000,,,
file_to_string,1,5,0.089439752,10000,167710000,,,
boundary_scan,1,5,0.034323919,10000,167710000,,,
rust_parse,1,5,0.462623125,10000,167710000,,,
rust_parse,2,5,0.292380076,10000,167710000,,,
rust_parse,4,5,0.186463307,10000,167710000,,,
rust_parse,8,5,0.130405286,10000,167710000,,,
python_read_con,1,5,0.943897943,10000,167710000,,,
python_object_construction,1,5,0.481274818,10000,167710000,,,
file_to_string,1,6,0.086769811,10000,167710000,,,
boundary_scan,1,6,0.033712855,10000,167710000,,,
rust_parse,1,6,0.452389349,10000,167710000,,,
rust_parse,2,6,0.296279425,10000,167710000,,,
rust_parse,4,6,0.183932488,10000,167710000,,,
rust_parse,8,6,0.133593308,10000,167710000,,,
python_read_con,1,6,1.020778520,10000,167710000,,,
python_object_construction,1,6,0.568389171,10000,167710000,,,
file_to_string,1,7,0.091259213,10000,167710000,,,
boundary_scan,1,7,0.034185580,10000,167710000,,,
rust_parse,1,7,0.459420960,10000,167710000,,,
rust_parse,2,7,0.290655408,10000,167710000,,,
rust_parse,4,7,0.184775678,10000,167710000,,,
rust_parse,8,7,0.144053718,10000,167710000,,,
python_read_con,1,7,0.945557065,10000,167710000,,,
python_object_construction,1,7,0.486136105,10000,167710000,,,
file_to_string,1,8,0.089299976,10000,167710000,,,
boundary_scan,1,8,0.033328368,10000,167710000,,,
rust_parse,1,8,0.445311240,10000,167710000,,,
rust_parse,2,8,0.297817374,10000,167710000,,,
rust_parse,4,8,0.194103507,10000,167710000,,,
rust_parse,8,8,0.132996890,10000,167710000,,,
python_read_con,1,8,0.929209747,10000,167710000,,,
python_object_construction,1,8,0.483898507,10000,167710000,,,
file_to_string,1,9,0.090911556,10000,167710000,,,
boundary_scan,1,9,0.034368863,10000,167710000,,,
rust_parse,1,9,0.458254968,10000,167710000,,,
rust_parse,2,9,0.297243000,10000,167710000,,,
rust_parse,4,9,0.189019438,10000,167710000,,,
rust_parse,8,9,0.129573242,10000,167710000,,,
python_read_con,1,9,0.954196424,10000,167710000,,,
python_object_construction,1,9,0.495941456,10000,167710000,,,
file_to_string,1,10,0.097263787,10000,167710000,,,
boundary_scan,1,10,0.035472925,10000,167710000,,,
rust_parse,1,10,0.452767765,10000,167710000,,,
rust_parse,2,10,0.291053933,10000,167710000,,,
rust_parse,4,10,0.185210080,10000,167710000,,,
rust_parse,8,10,0.135338844,10000,167710000,,,
python_read_con,1,10,0.959644711,10000,167710000,,,
python_object_construction,1,10,0.506876946,10000,167710000,,,
file_to_string,1,11,0.095156630,10000,167710000,,,
boundary_scan,1,11,0.035992805,10000,167710000,,,
rust_parse,1,11,0.479335140,10000,167710000,,,
rust_parse,2,11,0.300948331,10000,167710000,,,
rust_parse,4,11,0.190559481,10000,167710000,,,
rust_parse,8,11,0.131240362,10000,167710000,,,
python_read_con,1,11,0.925695580,10000,167710000,,,
python_object_construction,1,11,0.446360440,10000,167710000,,,
file_to_string,1,12,0.091680385,10000,167710000,,,
boundary_scan,1,12,0.034311993,10000,167710000,,,
rust_parse,1,12,0.484008343,10000,167710000,,,
rust_parse,2,12,0.326091459,10000,167710000,,,
rust_parse,4,12,0.191515739,10000,167710000,,,
rust_parse,8,12,0.136762486,10000,167710000,,,
python_read_con,1,12,0.982699825,10000,167710000,,,
python_object_construction,1,12,0.498691482,10000,167710000,,,
file_to_string,1,13,0.093019770,10000,167710000,,,
boundary_scan,1,13,0.035104734,10000,167710000,,,
rust_parse,1,13,0.463827333,10000,167710000,,,
rust_parse,2,13,0.293004182,10000,167710000,,,
rust_parse,4,13,0.193619768,10000,167710000,,,
rust_parse,8,13,0.133270295,10000,167710000,,,
python_read_con,1,13,0.959576670,10000,167710000,,,
python_object_construction,1,13,0.495749337,10000,167710000,,,
file_to_string,1,14,0.090525571,10000,167710000,,,
boundary_scan,1,14,0.034105199,10000,167710000,,,
rust_parse,1,14,0.470985711,10000,167710000,,,
rust_parse,2,14,0.296099651,10000,167710000,,,
rust_parse,4,14,0.195959528,10000,167710000,,,
rust_parse,8,14,0.134022973,10000,167710000,,,
python_read_con,1,14,0.955813806,10000,167710000,,,
python_object_construction,1,14,0.484828095,10000,167710000,,,
file_to_string,1,bca,0.091680385,,,0.091680385,0.090229286,0.094404175
boundary_scan,1,bca,0.034323919,,,0.034323919,0.034114358,0.035251760
rust_parse,1,bca,0.466395400,,,0.466395400,0.458254968,0.476859739
rust_parse,2,bca,0.296515450,,,0.296515450,0.292882869,0.300948331
rust_parse,4,bca,0.190559481,,,0.190559481,0.185210080,0.193619768
rust_parse,8,bca,0.133593308,,,0.133593308,0.131240362,0.135338844
python_read_con,1,bca,0.955813806,,,0.955813806,0.945106072,0.959644711
python_object_construction,1,bca,0.484828095,,,0.484828095,0.470553808,0.495941456
```
`paper/cpc/bench/results/db_ingest.csv` (same bytes as `paper/cpc/data/cloud-runs/spec03/db_ingest.csv`):
```
corpus,repeat,frames,unique_hashes,duplicate_frames,seconds,frames_per_s,median_frames_per_s,bca_low_frames_per_s,bca_high_frames_per_s
uninterrupted,0,7,7,0,0.002190417,3195.738529,,,
uninterrupted,1,7,7,0,0.000450260,15546.573092,,,
uninterrupted,2,7,7,0,0.000482362,14511.922589,,,
uninterrupted,3,7,7,0,0.000398862,17549.929565,,,
uninterrupted,4,7,7,0,0.000475747,14713.702868,,,
uninterrupted,5,7,7,0,0.000407846,17163.341078,,,
uninterrupted,6,7,7,0,0.000449818,15561.849455,,,
uninterrupted,7,7,7,0,0.000406920,17202.398509,,,
uninterrupted,8,7,7,0,0.000720517,9715.246130,,,
uninterrupted,9,7,7,0,0.000598038,11704.941824,,,
uninterrupted,10,7,7,0,0.000438106,15977.868376,,,
uninterrupted,11,7,7,0,0.000441471,15856.081141,,,
uninterrupted,12,7,7,0,0.000446920,15662.758425,,,
uninterrupted,13,7,7,0,0.000413624,16923.582772,,,
uninterrupted,14,7,7,0,0.000773306,9052.044079,,,
round_trip,0,7,7,0,0.000595727,11750.348733,,,
round_trip,1,7,7,0,0.000639424,10947.352619,,,
round_trip,2,7,7,0,0.000600993,11647.390240,,,
round_trip,3,7,7,0,0.000484666,14442.935962,,,
round_trip,4,7,7,0,0.000718991,9735.865960,,,
round_trip,5,7,7,0,0.000439483,15927.806072,,,
round_trip,6,7,7,0,0.000410924,17034.780159,,,
round_trip,7,7,7,0,0.000458480,15267.841551,,,
round_trip,8,7,7,0,0.000406353,17226.401675,,,
round_trip,9,7,7,0,0.000464762,15061.472313,,,
round_trip,10,7,7,0,0.000418623,16721.489269,,,
round_trip,11,7,7,0,0.000485333,14423.086825,,,
round_trip,12,7,7,0,0.000426262,16421.825074,,,
round_trip,13,7,7,0,0.000466740,14997.643232,,,
round_trip,14,7,7,0,0.000402144,17406.700089,,,
six_decimals,0,7,7,0,0.001531350,4571.130048,,,
six_decimals,1,7,7,0,0.000460418,15203.575885,,,
six_decimals,2,7,7,0,0.001810277,3866.811543,,,
six_decimals,3,7,7,0,0.000529173,13228.188137,,,
six_decimals,4,7,7,0,0.000533452,13122.080345,,,
six_decimals,5,7,7,0,0.001480851,4727.011698,,,
six_decimals,6,7,7,0,0.000528951,13233.739988,,,
six_decimals,7,7,7,0,0.000426911,16396.860236,,,
six_decimals,8,7,7,0,0.000863084,8110.450433,,,
six_decimals,9,7,7,0,0.000471852,14835.160166,,,
six_decimals,10,7,7,0,0.000502767,13922.950394,,,
six_decimals,11,7,7,0,0.000490475,14271.879304,,,
six_decimals,12,7,7,0,0.000472955,14800.562419,,,
six_decimals,13,7,7,0,0.000428992,16317.320610,,,
six_decimals,14,7,7,0,0.000492684,14207.889839,,,
height_held,0,7,7,0,0.000475392,14724.690354,,,
height_held,1,7,7,0,0.000556750,12572.968114,,,
height_held,2,7,7,0,0.000698829,10016.756607,,,
height_held,3,7,7,0,0.001850452,3782.859539,,,
height_held,4,7,7,0,0.000545071,12842.363655,,,
height_held,5,7,7,0,0.000959443,7295.899810,,,
height_held,6,7,7,0,0.000525899,13310.540618,,,
height_held,7,7,7,0,0.000487903,14347.114084,,,
height_held,8,7,7,0,0.000458810,15256.860136,,,
height_held,9,7,7,0,0.000500882,13975.347491,,,
height_held,10,7,7,0,0.000468066,14955.155899,,,
height_held,11,7,7,0,0.000675399,10364.243956,,,
height_held,12,7,7,0,0.000444913,15733.413044,,,
height_held,13,7,7,0,0.000501551,13956.706308,,,
height_held,14,7,7,0,0.001393991,5021.553224,,,
adatom_frozen,0,7,7,0,0.000779327,8982.108921,,,
adatom_frozen,1,7,7,0,0.000457967,15284.944116,,,
adatom_frozen,2,7,7,0,0.000892729,7841.125358,,,
adatom_frozen,3,7,7,0,0.001009648,6933.109364,,,
adatom_frozen,4,7,7,0,0.000962028,7276.295494,,,
adatom_frozen,5,7,7,0,0.000474522,14751.686965,,,
adatom_frozen,6,7,7,0,0.000509566,13737.180270,,,
adatom_frozen,7,7,7,0,0.000448021,15624.267612,,,
adatom_frozen,8,7,7,0,0.000499266,14020.582211,,,
adatom_frozen,9,7,7,0,0.000466054,15019.718735,,,
adatom_frozen,10,7,7,0,0.001373358,5096.995831,,,
adatom_frozen,11,7,7,0,0.000559251,12516.741138,,,
adatom_frozen,12,7,7,0,0.000806817,8676.069047,,,
adatom_frozen,13,7,7,0,0.000442847,15806.813634,,,
adatom_frozen,14,7,7,0,0.000493704,14178.536132,,,
five_bands,0,35,35,0,0.002904229,12051.391263,,,
five_bands,1,35,35,0,0.002902689,12057.785039,,,
five_bands,2,35,35,0,0.002371346,14759.550061,,,
five_bands,3,35,35,0,0.002839168,12327.555116,,,
five_bands,4,35,35,0,0.002248898,15563.178055,,,
five_bands,5,35,35,0,0.002411945,14511.110328,,,
five_bands,6,35,35,0,0.002437079,14361.454839,,,
five_bands,7,35,35,0,0.003754281,9322.690550,,,
five_bands,8,35,35,0,0.002298180,15229.442430,,,
five_bands,9,35,35,0,0.002376563,14727.150088,,,
five_bands,10,35,35,0,0.002270723,15413.592939,,,
five_bands,11,35,35,0,0.002208149,15850.379661,,,
five_bands,12,35,35,0,0.002269162,15424.196247,,,
five_bands,13,35,35,0,0.002632900,13293.326749,,,
five_bands,14,35,35,0,0.002725149,12843.334438,,,
frames-10000,0,10000,1,9999,0.653148865,15310.445345,,,
frames-10000,1,10000,1,9999,0.652215581,15332.353736,,,
frames-10000,2,10000,1,9999,0.602014958,16610.882948,,,
frames-10000,3,10000,1,9999,0.600867981,16642.590912,,,
frames-10000,4,10000,1,9999,0.615773237,16239.744437,,,
frames-10000,5,10000,1,9999,0.607038478,16473.420322,,,
frames-10000,6,10000,1,9999,0.605233167,16522.557826,,,
frames-10000,7,10000,1,9999,0.616312022,16225.547520,,,
frames-10000,8,10000,1,9999,0.610779150,16372.530071,,,
frames-10000,9,10000,1,9999,0.611877915,16343.129495,,,
frames-10000,10,10000,1,9999,0.613461441,16300.943029,,,
frames-10000,11,10000,1,9999,0.615114307,16257.140967,,,
frames-10000,12,10000,1,9999,0.627968854,15924.356656,,,
frames-10000,13,10000,1,9999,0.612770751,16319.316781,,,
frames-10000,14,10000,1,9999,0.595528266,16791.814211,,,
uninterrupted,bca,7,7,0,,15561.849455,15561.849455,11704.941824,15977.868376
round_trip,bca,7,7,0,,15061.472313,15061.472313,11750.348733,16421.825074
six_decimals,bca,7,7,0,,13922.950394,13922.950394,8110.450433,14800.562419
height_held,bca,7,7,0,,13310.540618,13310.540618,10016.756607,14347.114084
adatom_frozen,bca,7,7,0,,13737.180270,13737.180270,7841.125358,14751.686965
five_bands,bca,35,35,0,,14511.110328,14511.110328,12327.555116,15229.442430
frames-10000,bca,10000,1,9999,,16319.316781,16319.316781,16225.547520,16473.420322
```
## Where the files are
- Spec 01 raw: `paper/cpc/data/cloud-runs/spec01/` (variants, reproducer, Julia and Fortran CSV transcripts, test transcripts).
- Spec 01 table: `paper/cpc/data/failure/drift_bindings.csv`.
- Spec 02 raw campaign: `paper/cpc/evidence/work/e4/` (`full`, `round`, `six`, `freeze`, `dropmask` each have `neb.dat`, `neb.con`, `results.dat`; SD and L-BFGS trees, prefactor `freqs.dat`).
- Spec 02 table: `paper/cpc/data/failure/e4_restart.csv` and `e4_summary.json`. Figure under `paper/cpc/data/cloud-runs/spec02/`.
- Spec 03 tables: `paper/cpc/bench/results/stages.csv` and `db_ingest.csv`, copied under `paper/cpc/data/cloud-runs/spec03/`.
