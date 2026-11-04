"""Rules for the numbers printed in the prose of ``rg_supp.tex``."""

from __future__ import annotations

from numbers_lib import Rule, grep, h5md_version, jget, text

DOC = "rg_supp.tex"
SURVEY_PY = "scripts/failure_matrix.py"
DRIFT_PY = "scripts/drift.py"
RESTART = "data/failure/restart_formats.json"
RESTART_PY = "scripts/restart_formats.py"
ENVIRONMENT = "environment/conda-linux-64.txt"
PROVENANCE = "bench/results/r0174/provenance.json"
SPEC_PY = "scripts/gen_spec_supp.py"


def survey_ids() -> list[int]:
    return [int(x) for x in grep(SURVEY_PY, r"ids = np\.array\(\[([\d, ]+)\]").split(",")]


VACUUM = float(grep(RESTART_PY, r"^VACUUM = ([\d.]+)$"))
HEIGHT = float(grep(RESTART_PY, r"^HEIGHT = ([\d.]+)$"))
if (VACUUM, HEIGHT) != (jget(RESTART, "parameters.vacuum_A"), jget(RESTART, "parameters.held_height_A")):
    raise SystemExit(f"{RESTART}: vacuum or held height disagrees with {RESTART_PY}")
if "6.0" not in text(DRIFT_PY):
    raise SystemExit(f"{DRIFT_PY}: the z value 6.0 is gone from BASE_ROWS")
for package, recorded, source in (("python", jget(PROVENANCE, "tools.python"), PROVENANCE),
                                  ("rust", jget(PROVENANCE, "build.rustc").split()[0], PROVENANCE),
                                  ("pandoc", grep(SPEC_PY, r'if first != "pandoc ([\d.]+)":'), SPEC_PY)):
    if grep(ENVIRONMENT, rf"/{package}-([\d.]+)-") != recorded:
        raise SystemExit(f"{ENVIRONMENT}: {package} is not the {recorded} of {source}")

RULES: list[Rule] = [
    Rule("1.8", float(grep(SURVEY_PY, r'add_adsorbate\(s, "Pt", ([\d.]+), "hollow"\)')), SURVEY_PY,
         "adatom height in fixture()", (DOC,)),
    Rule("10^{-3}", float(grep(SURVEY_PY, r"rng\.uniform\(-1, 1, .*\) \* ([\d.e-]+)$")), SURVEY_PY,
         "half-width of the uniform coordinate offset in fixture()", (DOC,)),
    *[Rule(str(i), i, SURVEY_PY, "ids array in fixture()", (f"{DOC}~The identifiers are",))
      for i in survey_ids() if i > 9],
    Rule("4\\times10^{-3}", float(grep(SURVEY_PY, r"rng\.normal\(scale=([\d.e-]+),")), SURVEY_PY,
         "velocity standard deviation in fixture()", (DOC,)),
    Rule("10^{-6}", float(grep(SURVEY_PY, r'np\.allclose\([^\n]*, fx\["vel"\], rtol=([\d.e-]+),')), SURVEY_PY,
         "rtol of the declared-velocity comparison", (DOC,)),
    Rule("1.1", h5md_version(SURVEY_PY), SURVEY_PY, "h5md version attribute written by the survey", (DOC,)),
    Rule("6.0", float(grep(DRIFT_PY, r'r\.replace\("([\d.]+)", "[\d.]+d0"\)')), DRIFT_PY,
         "z value replaced in the fortran_exponent case", (f"{DOC}~value 6\\.0 as",)),
    Rule("6.0", jget(RESTART, "parameters.vacuum_A"), RESTART, "parameters.vacuum_A",
         (f"{DOC}~restart study", "figures/generated/restart_main.tex", "rg_main.tex~vacuum on each side")),
    Rule("1.75", jget(RESTART, "parameters.held_height_A"), RESTART, "parameters.held_height_A",
         (f"{DOC}~restart study", "figures/generated/restart_main.tex", "rg_main.tex~adatom height above")),
    Rule("3.13", float(grep(ENVIRONMENT, r"/pandoc-([\d.]+)-")), ENVIRONMENT, "pandoc package of the environment",
         (f"{DOC}~pandoc~3\\.13",)),
]
