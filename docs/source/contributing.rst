=========================================
Developer workflow and release guidelines
=========================================



Development setup
-----------------

Prerequisites
~~~~~~~~~~~~~

- Rust >= 1.88 (edition 2024)

- `pixi <https://pixi.sh>`_ for environment management

- `cocogitto <https://github.com/cocogitto/cocogitto>`_ (``cog``) for conventional commits and the git changelog

- `cogapp <https://cog.readthedocs.io/en/latest/>`_ (``python -m cogapp``) to stamp generated copies of the package version

- `towncrier <https://towncrier.readthedocs.io/en/stable/>`_ for news fragments under ``changelog.d/``

- Pins for those two tools: ``requirements-version.txt``

- `prek <https://prek.j178.dev>`_ for git hooks (``prek.toml``)

- `lychee <https://github.com/lycheeverse/lychee>`_ for docs link checks (via ``pixi r -e docs linkcheck``)

Getting started
~~~~~~~~~~~~~~~

.. code:: shell

    git clone https://github.com/lode-org/readcon-core.git
    cd readcon-core
    pixi install

    # Run tests
    pixi r test

    # Run with all features (needs capnproto)
    pixi r test-all

    # Hooks (prek) and docs
    pixi r prek
    pixi r -e docs docbld
    pixi r -e docs linkcheck

    # Build release
    pixi r build

Environment-specific workflows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: shell

    # Python bindings
    pixi r -e python python-build
    pixi r -e python python-test

    # Julia bindings
    pixi r -e julia julia-test

    # Documentation
    pixi r -e docs docbld
    # Docs output in docs/build/

Commit conventions
------------------

The project uses `conventional commits <https://www.conventionalcommits.org/>`_ enforced by cocogitto.
The CI lint check rejects non-conforming commit messages on the PR range.
Some historical commits use ``docs+bench:`` or untyped merges; ``cog check --from-latest-tag`` is the local equivalent of the PR gate.
``scripts/release-prep.sh`` calls ``scripts/bump-version.sh``, so towncrier writes the ``## vX.Y.Z`` heading from the fragments in ``changelog.d/``.

Recognized commit types (from ``cog.toml``):

.. table::
    :name: commit-types

    +-------+-------------------+----------------------------------------+
    | Type  | Changelog section | Use for                                |
    +=======+===================+========================================+
    | feat  | Features          | New user-facing functionality          |
    +-------+-------------------+----------------------------------------+
    | enh   | Enhancements      | Improvements to existing features      |
    +-------+-------------------+----------------------------------------+
    | fix   | Bugfixes          | Bug corrections                        |
    +-------+-------------------+----------------------------------------+
    | bug   | Bugfixes          | Alias for fix                          |
    +-------+-------------------+----------------------------------------+
    | doc   | Documentation     | Documentation-only changes             |
    +-------+-------------------+----------------------------------------+
    | tst   | Tests             | Test additions or modifications        |
    +-------+-------------------+----------------------------------------+
    | bld   | Buildsystem       | Build system, CI, dependency changes   |
    +-------+-------------------+----------------------------------------+
    | maint | Maintenance       | Refactoring, cleanup, internal changes |
    +-------+-------------------+----------------------------------------+
    | bench | Benchmarks        | Benchmark additions or modifications   |
    +-------+-------------------+----------------------------------------+
    | gen   | Generated         | Auto-generated file updates            |
    +-------+-------------------+----------------------------------------+
    | dat   | Data              | Test data or resource changes          |
    +-------+-------------------+----------------------------------------+

Examples:

.. code:: text

    feat: add convel format support with optional velocity fields
    enh: integrate fast-float2 for f64 parsing hot path
    fix: handle empty velocity section in multi-frame files
    doc: update tutorials with Julia convel example
    bld: add CMakeLists.txt for cmake subproject use
    tst: add roundtrip test for convel writer

Branching and workflow
----------------------

- ``main`` is the release branch.
  All PRs target ``main``.

- Feature branches: ``feat/<description>``

- Bugfix branches: ``fix/<description>``

- Keep commits logical and atomic.
  Soft-reset and rebase as needed (never on ``main``).

- The CI runs on every PR: Rust tests, lint, coverage, Fortran fpm tests, Python (``ci_python.yml``: ``maturin develop`` + ``pytest tests/python/`` for lean and chemfiles features), and benchmark regression (one-runner ASV via Snakemake, memray peaks, asv-perch).

Testing
-------

.. code:: shell

    # Core Rust tests
    cargo test

    # All features (parallel, rpc, python)
    cargo test --all-features

    # Meson build with valgrind leak checking
    meson setup bbdir -Dwith_tests=True -Dwith_examples=True
    meson test -C bbdir

    # Benchmarks
    cargo bench
    # or: pixi r bench

Test data lives in ``resources/test/``.
Use the ``test_case!`` macro in integration tests to locate test files.

Fuzzing
~~~~~~~

The ``fuzz/`` crate defines `cargo-fuzz <https://github.com/rust-fuzz/cargo-fuzz>`_ targets for the line parsers, the frame readers, the frame index, the unit parser, the surface grammar and the bond metadata.
Each target keeps its seed inputs in ``fuzz/corpus/<target>/``.
The targets need a nightly toolchain and ``cargo install cargo-fuzz``.
Most targets only check that the code returns without a panic.
``frame-parser`` also checks that the frame iterator ends, and ``frame-parallel`` that two threads return the frames that one thread returns.

libFuzzer adds every input that finds new coverage to the corpus directory it runs on.
So the loop below runs each target on a scratch copy of its corpus, which keeps ``fuzz/corpus/`` as committed.
It gives each target an equal share of 600 seconds, the default fuzzing time of a `ClusterFuzzLite <https://google.github.io/clusterfuzzlite/running-clusterfuzzlite/github-actions/>`_ pull request job.

..
   #skip_lint_start

.. code:: shell

    seed=$(cat fuzz/seed.txt)
    targets=$(cargo +nightly fuzz list)
    secs=$((600 / $(printf '%s\n' "$targets" | wc -l)))
    for target in $targets; do
      corpus=$(mktemp -d)
      cp -a "fuzz/corpus/$target/." "$corpus/"
      cargo +nightly fuzz run "$target" "$corpus" -- -seed="$seed" -max_total_time="$secs"
      rm -rf "$corpus"
    done

..
   #skip_lint_end

A crash leaves its input in ``fuzz/artifacts/<target>/``, and ``cargo +nightly fuzz run <target> <input>`` runs that input again.
``fuzz/seed.txt`` fixes the random choices of libFuzzer, but two runs on it can still try different inputs.
The clock, address randomization, hash keys and threads all change which code a run reaches.
So keep the input of a crash, since the seed alone may not find it again.

Profile-guided optimisation (PGO)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``release`` and ``dist`` profiles in ``Cargo.toml`` already enable ``lto = "thin"`` / ``lto = "fat"`` and ``codegen-units = 1``.
PGO can give another 5--15% on parser hot paths by feeding the optimiser a real profile from the Criterion benchmarks.
It is opt-in because the build takes 2--3x longer.

Three-step workflow (Linux, ``rustc`` 1.88+):

.. code:: shell

    # 1. Build instrumented binary; pass --features for everything you
    #    want profile data on.
    mkdir -p /tmp/readcon-pgo
    RUSTFLAGS="-Cprofile-generate=/tmp/readcon-pgo" \
      cargo bench --features parallel,zstd,rpc --no-run

    # 2. Run the benches to collect .profraw files.
    RUSTFLAGS="-Cprofile-generate=/tmp/readcon-pgo" \
      cargo bench --features parallel,zstd,rpc

    # 3. Merge profraws then build with --use to consume the merged profile.
    $(rustc --print sysroot)/lib/rustlib/x86_64-unknown-linux-gnu/bin/llvm-profdata \
      merge -o /tmp/readcon-pgo/merged.profdata /tmp/readcon-pgo
    RUSTFLAGS="-Cprofile-use=/tmp/readcon-pgo/merged.profdata" \
      cargo build --release --features parallel,zstd,rpc

The same flow works for ``cargo cinstall`` when you want PGO-optimised ``libreadcon_core.so`` for distribution; substitute ``cargo cinstall`` for ``cargo build --release`` in step 3.

Continuous integration
----------------------

Workflows
~~~~~~~~~

.. table::
    :name: ci-workflows

    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Workflow                  | File                       | Trigger                                    | Purpose                                                    |
    +===========================+============================+============================================+============================================================+
    | Prek                      | ``ci_prek.yml``            | push, PR                                   | ``prek run -a`` (whitespace, ruff, taplo, codespell)       |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Documentation             | ``ci_docs.yml``            | push, PR                                   | ``pixi r -e docs docbld`` then lychee on HTML              |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | C/C++ dist                | ``ci_cxx.yml``             | push, PR                                   | CMake/Meson/pkg-config without cbindgen                    |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Python wheels             | ``python_wheels.yml``      | ``v*`` tag, PR                             | Build wheels for 5 platforms, publish to PyPI              |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Benchmark PR              | ``ci_benchmark.yml``       | PR to main                                 | ASV base vs head on one runner (Snakemake)                 |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Comment benchmark results | ``ci_bench_commenter.yml`` | benchmark complete                         | Post ASV table as PR comment                               |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Coverage                  | ``coverage.yml``           | push, PR                                   | Code coverage via tarpaulin                                |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Lint                      | ``lint.yml``               | PR                                         | Conventional commit check + large file audit               |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | Release                   | ``release.yml``            | PR plan, ``v*`` tag                        | cargo-dist plan on PRs; GitHub Release on tag              |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | crates.io                 | ``crates_publish.yml``     | ``v*`` tag                                 | ``cargo publish --locked``                                 |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | cxx tarball               | ``cxx_tarball.yml``        | GitHub Release                             | Attach slim + vendor C/C++ source tarballs                 |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+
    | clib tarball              | ``c_lib_tarball.yml``      | GitHub Release + ``workflow_dispatch`` tag | Attach prebuilt C ABI (``readcon-core-clib-$VER-$target``) |
    +---------------------------+----------------------------+--------------------------------------------+------------------------------------------------------------+

Benchmark regression detection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two-workflow pattern for safe PR comments:

1. ``ci_benchmark.yml`` is one job.
   It runs ``snakemake -s benchmarks/workflow/Snakefile``.
   asv builds and installs both commits.
   Main-vs-main repetitions on that runner set a per-benchmark noise band.
   For timing, one bound is the wider of the linear 99th percentile and median + 3*median absolute deviation (MAD) of the odd-round versus even-round ratios.
   A second bound is a Student t prediction limit for a ratio of two side medians from those repetitions.
   The timing upper bound is the wider of the two.
   The timing lower bound uses the reciprocal when it is smaller.
   The false-slowdown budget is 0.01, split across the timing rows in this comparison.
   Memory keeps the within-run bound, widened by one allocator granule over the median base peak.
   Base vs head wall time is ``asv continuous --interleave-rounds`` (no ``--quick``).
   Memory peaks are ``ray_*`` benchmarks (``asv_bench_memray``).
   Tool versions are pinned in ``benchmarks/workflow/requirements.txt`` and ``asv.conf.json``.
   ``ci_benchmark.yml`` also pins rustc 1.88.0, Actions commits, uv 0.13.6, Python 3.12.16, and exact cmake/gcc/g++ packages.
   The job writes ``results/comparison.txt`` and ``results/row-bounds.txt`` (benchmark, within upper, between upper, upper).

2. ``ci_bench_commenter.yml`` triggers on ``workflow_run`` completion when the Benchmark PR conclusion is ``success`` or ``failure``, downloads ``benchmark-results``, and posts the table with `asv-perch <https://github.com/HaoZeke/asv-perch>`_.
   A failed check does not meet the success condition.
   The comment table shows each row's own upper bound, the sample count per side, the base median, the head median, and the interquartile ranges.
   A row is a slowdown when its ratio is above that bound.
   The comment step passes a threshold of 1.
   Every row upper is at least 1, so a slowed row still drafts.
   A blank mark in the table is not significant.
   The job refuses identical base and head commits and exits non-zero when a row is a significant slowdown or is missing samples.

The ``workflow_run`` split is required for fork PRs to have write access for posting comments (GitHub security model).
Suite and local reproduce: `benchmarks.org <benchmarks.rst>`_ (``benchmarks/``, ``asv.conf.json``, ``benchmarks/workflow/Snakefile``).

Executable chemfiles pages
~~~~~~~~~~~~~~~~~~~~~~~~~~

:doc:`The chemfiles notebook <chemfiles-notebook>` is the executable Org Babel source of the chemfiles tutorial, for Python only.
Continuous integration (CI) runs ``scripts/run-chemfiles-notebook.sh`` from ``ci_python.yml``.
The script tangles the notebook into ``docs/notebooks/chemfiles_ingress.py``, fails if the committed file differs from the new tangle, and runs it with ``python3``.
The Rust blocks and the blocks in other languages on :doc:`the chemfiles tutorial page <chemfiles-tutorial>` are prose only, and CI does not run them.
Do not edit the tangled ``.py`` file by hand.
Change the notebook Org source instead, and tangle it again with ``READCON_TANGLE_UPDATE=1 scripts/run-chemfiles-notebook.sh``.

Release process
---------------

This section is the only guide a new contributor needs to **cut a release** without reading CI YAML.
Three layers work together; use all of them and do **not** short-circuit with a local-only ``cargo publish`` unless CI secrets are broken (fallback is documented below).

Mental model (new contributor)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    scripts/release-prep.sh X.Y.Z
          │  prek, pixi docbld + lychee, version bump, towncrier CHANGELOG,
          │  cxx-dist gate; cbindgen optional
          ▼
    commit: maint: bump to vX.Y.Z   ──►  open Pull Request to main
          │                                    │
          │                         cargo-dist workflow "Release"
          │                         runs `dist plan` on the PR (validate)
          ▼                                    ▼
    merge PR to main  ──►  git tag -s vX.Y.Z && git push origin vX.Y.Z
          │
          ├─► workflow "Release" (cargo-dist): CLI archives + GitHub Release
          ├─► workflow "Publish to crates.io": cargo publish --locked
          │         needs repo secret CARGO_REGISTRY_TOKEN
          ├─► workflow "Python wheels": maturin matrix → PyPI (OIDC env `pypi`)
          ├─► workflow "cxx source tarball": after the GitHub Release exists
          └─► workflow "C ABI library tarball": prebuilt clib (or dispatch tag later)

.. table::
    :name: release-layers

    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Layer       | What                                   | Workflow / tool                                                                                     |
    +=============+========================================+=====================================================================================================+
    | Prep        | Hooks + docs + versions + changelog    | ``prek``, ``pixi r -e docs docbld``, ``lychee``, ``scripts/release-prep.sh``, ``towncrier build``   |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Release PR  | Validate dist plan before a tag exists | ``.github/workflows/release.yml`` (cargo-dist; ``pr-run-mode = "plan"`` in ``dist-workspace.toml``) |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | crates.io                              | ``.github/workflows/crates_publish.yml``                                                            |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | PyPI wheels                            | ``.github/workflows/python_wheels.yml``                                                             |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | GitHub Release + CLI tarballs          | same cargo-dist ``Release`` workflow on the tag                                                     |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | C/C++ source tarballs                  | ``.github/workflows/cxx_tarball.yml`` (after the Release exists)                                    |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | Prebuilt C ABI tarballs                | ``.github/workflows/c_lib_tarball.yml`` (``release`` or ``workflow_dispatch`` ``tag``)              |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+

Attach prebuilt C ABI to an existing tag
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``.github/workflows/c_lib_tarball.yml`` matches ``cxx_tarball.yml``: ``release`` published, or ``workflow_dispatch`` with required ``inputs.tag``.
Use this to put ``readcon-core-clib-$VER-$target.tar.gz`` on a tag that predates the workflow (for example ``v0.14.7``).

1. Open Actions → **C ABI library tarball**.

2. Run the workflow from a branch that **has** ``scripts/package-clib.sh`` (usually ``main`` after this lands).

3. Set ``tag`` to the existing Git tag (``v0.14.7``).

The packager comes from the selected workflow ref.
Sources and the GitHub Release come from ``inputs.tag``.
Windows + chemfiles is an **explicit skip** (Python wheel path only).

cargo-dist release-PR path
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Do **not** push a version tag from a laptop until the version-bump commit is on ``main`` (via PR).
   That PR is the **release PR**: it should contain only the ``maint: bump to vX.Y.Z`` (and any intentional release-note / header sync) produced by ``scripts/release-prep.sh`` or the manual checklist below.

2. On every PR, GitHub Actions runs the workflow named **Release** (file ``release.yml``).
   With ``pr-run-mode = "plan"`` it runs ``dist plan`` only: it checks that cargo-dist can announce this version and list artifacts.
   It does **not** publish crates or create a GitHub Release on the PR.

3. If the plan job is red, fix ``dist-workspace.toml`` / version alignment and push; do not tag yet.

4. After the PR is merged, on a clean ``main``:

   .. code:: shell

       git checkout main && git pull origin main
       git tag -s vX.Y.Z -m "vX.Y.Z"
       git push origin vX.Y.Z

5. On the tag push, the **same** ``Release`` workflow switches to publishing mode: builds platform archives for the ``readcon-core`` CLI binary and creates (or updates) the GitHub Release with those artifacts and notes derived from the changelog.

Regenerate the workflow after editing ``dist-workspace.toml`` (never hand-edit ``release.yml`` long-term):

.. code:: shell

    # cargo-dist 0.28 from the sha256-pinned archive (scripts/install-cargo-dist-ci.sh)
    bash scripts/install-cargo-dist-ci.sh
    dist generate --mode=ci
    # Re-apply action SHA pins and the checksummed install steps. dist generate
    # rewrites release.yml to mutable tags and curl|sh.
    git add .github/workflows/release.yml dist-workspace.toml scripts/install-cargo-dist-ci.sh

crates.io publish workflow and ``CARGO_REGISTRY_TOKEN``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Workflow file: ``.github/workflows/crates_publish.yml`` (name: **Publish to crates.io**).

- **Trigger**: push of tags matching ``v*``, or ``workflow_dispatch`` on a branch (uses ``Cargo.toml`` package version; on a ``v*`` tag the tag must match that version or the job fails fast).

- **Action**: ``cargo publish --locked`` for the ``readcon-core`` crate.

- **Idempotent skip**: if ``https://crates.io/api/v1/crates/readcon-core/<version>`` already returns 200, the job logs “already published” and does **not** call ``cargo publish`` (avoids “crate already exists” on re-runs).

- **Secret**: repository secret **exactly named** ``CARGO_REGISTRY_TOKEN``.
  Value is a crates.io API token for an account allowed to publish ``readcon-core`` (create at `https://crates.io/settings/tokens <https://crates.io/settings/tokens>`_ ).
  Without it, the publish step fails with “please provide a non-empty token” / our explicit empty-secret guard.

Set or rotate the secret (example using ``pass`` and ``gh``; run as a repo admin):

.. code:: shell

    # Store offline (example path used by maintainers)
    pass insert -m crates-io/readcon-core   # paste the crates.io token

    # Push into GitHub Actions secrets for lode-org/readcon-core
    printf '%s' "$(pass show crates-io/readcon-core)" \
      | gh secret set CARGO_REGISTRY_TOKEN --repo lode-org/readcon-core

    # Confirm the secret exists (value is never shown)
    gh secret list --repo lode-org/readcon-core

Local fallback only if CI is red and you must unblock users:

.. code:: shell

    CARGO_REGISTRY_TOKEN="$(pass show crates-io/readcon-core)" cargo publish --locked

Prefer fixing the secret and re-running the workflow over making local publish the default path.

PyPI (wheels) on the same tag
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``python_wheels.yml`` builds sdist + manylinux/macOS/Windows wheels with maturin (``--features python``, **not** ``chemfiles`` by default) and publishes with ``pypa/gh-action-pypi-publish`` using OIDC trusted publishing (environment ``pypi``).
No password secret is required once the trusted publisher is configured (see **Initial PyPI setup** below).
Transient crates.io network errors are mitigated with ``CARGO_HTTP_MULTIPLEXING=false`` and a one-shot maturin retry; tag runs are not cancelled mid-flight by concurrency.

Version files
~~~~~~~~~~~~~

The package version is the single line in ``VERSION`` at the repository root.
That is the only hand-written copy.

Bump with ``scripts/bump-version.sh X.Y.Z`` (or ``cog bump``).
``scripts/stamp-version.sh`` only restamps cogapp copies.
It does not write the towncrier heading or refresh the exported pins.

.. code:: shell

    scripts/bump-version.sh X.Y.Z
    # scripts/stamp-version.sh
    # restamp only, after VERSION and the heading exist

``scripts/bump-version.sh X.Y.Z`` (also ``scripts/set-version.sh``) writes ``VERSION``, runs ``python -m towncrier build --yes --version X.Y.Z``, then ``scripts/stamp-version.sh``.
Towncrier is the only writer of ``## vX.Y.Z`` headings.
``cog.toml`` sets ``disable_changelog = true`` and its ``pre_bump_hooks`` call ``bump-version.sh``, so a ``cog bump`` commit already contains the heading and the compare links.
CMake reads ``VERSION`` and sets ``CMAKE_CONFIGURE_DEPENDS``.
Meson passes ``files('VERSION')`` to ``project()`` (`https://mesonbuild.com/Reference-manual_functions.html#project <https://mesonbuild.com/Reference-manual_functions.html#project>`_).
Sphinx (``docs/source/conf.py``) reads ``VERSION`` at configure time.
The C and Fortran strings, the Python and Julia and Fortran package files, citation metadata, and the changelog compare links are cogapp output.
The Fortran parameter does not repeat ``public``, because the module already lists ``readcon_version``.
Python ``__version__`` follows the Cargo package version, which cogapp stamps from ``VERSION``.
A Windows checkout may store a carriage return before the newline in ``VERSION``.
``build.rs`` strips that carriage return.
Python reads ``VERSION`` in text mode, which already drops it.
Tool versions are pinned in ``requirements-version.txt``.

Published pages stay on the org-to-rst export (``emacs --batch -l docs/export.el`` or ``pixi r -e docs orgbld``).
Org sources mark each install pin with an at-sign placeholder named READCON\_VERSION.
The exporter reads ``VERSION`` and does not take a version argument.
Do not type the version into ``docs/source/*.rst``.

News for a release is a fragment under ``changelog.d/``, collected by `towncrier <https://towncrier.readthedocs.io/en/stable/>`_.
The towncrier config imports ``readcon_meta.__version__``, which reads ``VERSION``.
Do not hand-edit the generated release section of ``CHANGELOG.md``.
Cocogitto still checks commit subjects and can render the git changelog; it is a separate program from cogapp, so version stamps call ``python -m cogapp``.

``scripts/check_version_sot.sh`` greps every copy of the version string and compares it to ``VERSION``.
CI runs ``python -m cogapp --check`` on the stamp file list and that script.
The ``cog`` executable is cocogitto, so the drift job does not call it.
``scripts/release-prep.sh X.Y.Z`` is the release path: it calls ``scripts/bump-version.sh`` and then the org export.
``scripts/set-version.sh`` is only an alias for ``bump-version.sh``.

Complete release checklist
~~~~~~~~~~~~~~~~~~~~~~~~~~

Fast path (preferred):

.. code:: shell

    prek run -a
    pixi r -e docs docbld
    pixi r -e docs linkcheck
    scripts/release-prep.sh X.Y.Z
    # review staged files, then:
    git commit -m "maint: bump to vX.Y.Z"
    # push a branch, open PR → cargo-dist Release workflow runs dist plan
    # merge PR to main, then:
    git checkout main && git pull
    git tag -s vX.Y.Z -m "vX.Y.Z"
    git push origin vX.Y.Z
    # wait for Release + Publish to crates.io + Python wheels + cxx tarball

Manual equivalent of the script:

1. Ensure all tests pass and the branch is clean:

   .. code:: shell

       cargo test --locked
       cargo test --locked --features chemfiles   # optional; needs libchemfiles/cmake policy
       pixi r -e python python-test
       prek run -a
       pixi r -e docs docbld
       pixi r -e docs linkcheck

2. Run ``scripts/bump-version.sh X.Y.Z``.
   That writes ``VERSION``, lets towncrier write the release heading, then runs cogapp.
   Re-export the docs with the org-to-rst pipeline so the published pages match.

3. Check the lock with ``cargo test --locked``.
   ``scripts/bump-version.sh`` already rewrites the ``readcon-core`` entry in ``Cargo.lock`` and ``fuzz/Cargo.lock``.

4. Regenerate the README from ``readme_src.org`` when the user-facing docs changed (optional for patch releases that only touch the crate version).
   Use the project script so ``docs/orgmode/*.org`` links stay ``.org`` (plain ``ox-md`` rewrites them to missing ``.md`` paths):

   .. code:: shell

       ./scripts/export-readme.sh

5. The release heading comes from towncrier, which ``bump-version.sh`` already ran.
   Do not rebuild ``CHANGELOG.md`` with ``cog changelog``; that drops the towncrier marker.
   Add a fragment under ``changelog.d/`` before the bump.
   Do not hand-edit the generated release section.

6. If the FFI surface changed, run ``scripts/regen-capi-headers.sh`` and commit ``include/readcon-core.h`` (CI ``build_test.yml`` runs ``--check``).

7. Commit the release preparation (``maint: bump to vX.Y.Z``) and open the **release PR** (cargo-dist plans on PRs).
   After merge:

   .. code:: shell

       git tag -s vX.Y.Z -m "vX.Y.Z"
       git push origin vX.Y.Z

8. Do **not** rely on a local ``cargo publish`` unless CI is red; prefer ``crates_publish.yml`` with ``CARGO_REGISTRY_TOKEN`` set.
   Local fallback:

   .. code:: shell

       CARGO_REGISTRY_TOKEN="$(pass show crates-io/readcon-core)" cargo publish --locked

9. Tag CI also runs ``python_wheels.yml`` (PyPI) and cargo-dist ``Release`` (CLI tarballs + GitHub Release body from the changelog).

10. Verify all distribution channels:

    - `crates.io <https://crates.io/crates/readcon-core>`_ shows the new version

    - `PyPI <https://pypi.org/project/readcon/>`_ shows the new version (wait for CI)

    - `GitHub Releases <https://github.com/lode-org/readcon-core/releases>`_ has cargo-dist archives (and any prior C ABI tarballs if still attached)

Optional local C ABI tarball for consumers that do not use cargo-dist CLI archives (headers + ``libreadcon_core.{a,so}`` via ``cargo build --release`` or ``cargo cinstall``) can still be attached with ``gh release upload`` if needed.

Initial PyPI setup (first release only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the very first release, PyPI trusted publisher is not yet configured.
Publish manually:

.. code:: shell

    # Build wheels
    maturin build --release --features python

    # Upload (first time, creates the project on PyPI)
    uvx twine upload target/wheels/*


Python ships **two** distributions from ``python_wheels.yml``:

.. table::
    :name: pypi-distributions

    +-----------------------+--------------------------------------------+-------------------------------------------------------+
    | PyPI name             | Features                                   | Import                                                |
    +=======================+============================================+=======================================================+
    | ``readcon``           | ``python`` only (stubs for chemfiles APIs) | ``import readcon``                                    |
    +-----------------------+--------------------------------------------+-------------------------------------------------------+
    | ``readcon-chemfiles`` | ``python,chemfiles`` (libchemfiles linked) | ``import readcon`` (``has_chemfiles_support()`` True) |
    +-----------------------+--------------------------------------------+-------------------------------------------------------+

Configure a trusted publisher on **each** PyPI project (same workflow ``python_wheels.yml``, environment ``pypi``).
Do not install both wheels in one venv (both export the ``readcon`` module).
Prefer ``pip install readcon-chemfiles`` when selection/import are required; lean ``readcon`` for CON I/O only.
``pip install 'readcon[chemfiles]'`` depends on ``readcon-chemfiles==X.Y.Z`` (pin updated by ``scripts/release-prep.sh``).

Then configure trusted publisher on PyPI:

1. Go to `https://pypi.org/manage/project/readcon/settings/publishing/ <https://pypi.org/manage/project/readcon/settings/publishing/>`_

2. Add a new pending publisher:

   - Owner: ``lode-org``

   - Repository: ``readcon-core``

   - Workflow: ``python_wheels.yml``

   - Environment: ``pypi``

After this, all subsequent tagged releases auto-publish via OIDC.

Adding new features
-------------------

Feature gates
~~~~~~~~~~~~~

Optional functionality is gated behind Cargo features:

.. table::
    :name: cargo-features

    +----------+-------------------------------+----------------------------+
    | Feature  | Dependencies                  | Purpose                    |
    +==========+===============================+============================+
    | parallel | rayon                         | Multi-frame parallel parse |
    +----------+-------------------------------+----------------------------+
    | rpc      | capnp, capnp-rpc, tokio, etc. | Cap'n Proto RPC serving    |
    +----------+-------------------------------+----------------------------+
    | python   | pyo3                          | Python bindings            |
    +----------+-------------------------------+----------------------------+

Add new optional features in ``Cargo.toml`` under ``[features]``.

Adding a new binding
~~~~~~~~~~~~~~~~~~~~

1. Add the binding source under ``src/`` (e.g., ``src/python.rs``) or as a separate package (e.g., ``julia/ReadCon/``).

2. Gate behind a feature flag if it adds dependencies.

3. Add tests under ``tests/`` or the binding's own test directory.

4. Document in ``docs/orgmode/bindings.org`` and ``docs/orgmode/howto.org``.

5. Add a pixi environment and tasks if applicable.

Updating the C header
~~~~~~~~~~~~~~~~~~~~~

The C header ``include/readcon-core.h`` is the shipped ABI, the same model as metatensor/metatomic.
CMake, Meson, cargo-c, CI, and the cxx tarball **never** run cbindgen.
Edit the header (or optionally draft with ``scripts/regen-capi-headers.sh``) and commit it with the FFI change.
CI compiles C/C++ against that file and checks symbols in the built library.

``ci_cxx.yml`` installs no cbindgen and must stay green.

The C++ header ``include/readcon-core.hpp`` is hand-maintained and must be updated manually to match any changes to ``CAtom``, ``CFrame``, or the FFI function signatures.
