=========================================
Developer workflow and release guidelines
=========================================



Development setup
-----------------

Prerequisites
~~~~~~~~~~~~~

- Rust >= 1.88 (edition 2024)

- `pixi <https://pixi.sh>`_ for environment management

- `cocogitto <https://github.com/cocogitto/cocogitto>`_ (``cog``) for conventional commits and changelog

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
The CI lint check rejects non-conforming commit messages.

Recognized commit types (from ``cog.toml``):

.. table::

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

- ``main`` is the release branch. All PRs target ``main``.

- Feature branches: ``feat/<description>``

- Bugfix branches: ``fix/<description>``

- Keep commits logical and atomic. Soft-reset and rebase as needed
  (never on ``main``).

- The CI runs on every PR: Rust tests, lint, coverage, Fortran fpm tests,
  Python (``ci_python.yml``: ``maturin develop`` + ``pytest tests/python/`` for lean
  and chemfiles features), and benchmark regression (Python ASV +
  ``asv-spyglass`` + asv-perch; optional Criterion baselines).

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

Test data lives in ``resources/test/``. Use the ``test_case!`` macro in
integration tests to locate test files.

Profile-guided optimisation (PGO)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``release`` and ``dist`` profiles in ``Cargo.toml`` already enable
``lto = "thin"`` / ``lto = "fat"`` and ``codegen-units = 1``. PGO can give
another 5--15% on parser hot paths by feeding the optimiser a real
profile from the Criterion benchmarks. It is opt-in because the build
takes 2--3x longer.

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

The same flow works for ``cargo cinstall`` when you want PGO-optimised
``libreadcon_core.so`` for distribution; substitute ``cargo cinstall``
for ``cargo build --release`` in step 3.

Continuous integration
----------------------

Workflows
~~~~~~~~~

.. table::

    +---------------------------+----------------------------+--------------------+-----------------------------------------------+
    | Workflow                  | File                       | Trigger            | Purpose                                       |
    +===========================+============================+====================+===============================================+
    | Python wheels             | ``python_wheels.yml``      | ``v*`` tag, PR     | Build wheels for 5 platforms, publish to PyPI |
    +---------------------------+----------------------------+--------------------+-----------------------------------------------+
    | Benchmark PR              | ``ci_benchmark.yml``       | PR to main         | ASV on base+PR (Python); optional Criterion   |
    +---------------------------+----------------------------+--------------------+-----------------------------------------------+
    | Comment benchmark results | ``ci_bench_commenter.yml`` | benchmark complete | Post ASV/spyglass table as PR comment         |
    +---------------------------+----------------------------+--------------------+-----------------------------------------------+
    | Coverage                  | ``coverage.yml``           | push, PR           | Code coverage via tarpaulin                   |
    +---------------------------+----------------------------+--------------------+-----------------------------------------------+
    | Lint                      | ``lint.yml``               | push, PR           | Conventional commit check + large file audit  |
    +---------------------------+----------------------------+--------------------+-----------------------------------------------+

Benchmark regression detection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two-workflow pattern for safe PR comments (eOn-style Python ASV):

1. ``ci_benchmark.yml`` matrix builds **base** and **PR** with
   ``maturin develop --features python,chemfiles --release``, then
   ``asv run -E existing:… --set-commit-hash $sha --quick``. Results upload as
   artifacts. A Criterion job still records ``iterator_bench`` baselines for
   local ``critcmp`` with ``continue-on-error: true`` so a Rust microbench miss
   cannot block the ASV/spyglass comment path.

2. The ``asv-combine`` job runs
   `asv-spyglass <https://github.com/airspeed-velocity/asv_spyglass>`_ ``compare`` on the two result JSONs →
   ``results/comparison.txt``.

3. ``ci_bench_commenter.yml`` triggers on ``workflow_run`` completion, downloads
   ``benchmark-results``, and posts the table with `asv-perch <https://github.com/HaoZeke/asv-perch>`_.

The ``workflow_run`` split is required for fork PRs to have write access for
posting comments (GitHub security model).

Regressions above the asv-perch threshold can auto-draft the PR. Suite and
local reproduce: `benchmarks.org <benchmarks.rst>`_ (``benchmarks/``, ``asv.conf.json``).

Release process
---------------

This section is the only guide a new contributor needs to **cut a release**
without reading CI YAML. Three layers work together; use all of them and do
**not** short-circuit with a local-only ``cargo publish`` unless CI secrets are
broken (fallback is documented below).

Mental model (new contributor)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    scripts/release-prep.sh X.Y.Z
          │  bumps 6 version files, cog CHANGELOG, cbindgen if needed
          ▼
    commit: maint: bump to vX.Y.Z   ──►  open Pull Request to main
          │                                    │
          │                         cargo-dist workflow "Release"
          │                         runs `dist plan` on the PR (validate)
          ▼                                    ▼
    merge PR to main  ──►  git tag -s vX.Y.Z && git push --tags
          │
          ├─► workflow "Release" (cargo-dist): CLI archives + GitHub Release
          ├─► workflow "Publish to crates.io": cargo publish --locked
          │         needs repo secret CARGO_REGISTRY_TOKEN
          └─► workflow "Python wheels": maturin matrix → PyPI (OIDC env `pypi`)

.. table::

    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Layer       | What                                   | Workflow / tool                                                                                     |
    +=============+========================================+=====================================================================================================+
    | Prep        | Versions + changelog                   | ``scripts/release-prep.sh``, ``cog``                                                                |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Release PR  | Validate dist plan before a tag exists | ``.github/workflows/release.yml`` (cargo-dist; ``pr-run-mode = "plan"`` in ``dist-workspace.toml``) |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | crates.io                              | ``.github/workflows/crates_publish.yml``                                                            |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | PyPI wheels                            | ``.github/workflows/python_wheels.yml``                                                             |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+
    | Tag publish | GitHub Release + CLI tarballs          | same cargo-dist ``Release`` workflow on the tag                                                     |
    +-------------+----------------------------------------+-----------------------------------------------------------------------------------------------------+

cargo-dist release-PR path
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Do **not** push a version tag from a laptop until the version-bump commit is
   on ``main`` (via PR). That PR is the **release PR**: it should contain only the
   ``maint: bump to vX.Y.Z`` (and any intentional release-note / header sync)
   produced by ``scripts/release-prep.sh`` or the manual checklist below.

2. On every PR, GitHub Actions runs the workflow named **Release** (file
   ``release.yml``). With ``pr-run-mode = "plan"`` it runs ``dist plan`` only: it
   checks that cargo-dist can announce this version and list artifacts. It
   does **not** publish crates or create a GitHub Release on the PR.

3. If the plan job is red, fix ``dist-workspace.toml`` / version alignment and
   push; do not tag yet.

4. After the PR is merged, on a clean ``main``:

   .. code:: shell

       git checkout main && git pull origin main
       git tag -s vX.Y.Z -m "vX.Y.Z"
       git push origin main --tags

5. On the tag push, the **same** ``Release`` workflow switches to publishing mode:
   builds platform archives for the ``readcon-core`` CLI binary and creates (or
   updates) the GitHub Release with those artifacts and notes derived from
   the changelog.

Regenerate the workflow after editing ``dist-workspace.toml`` (never hand-edit
``release.yml`` long-term):

.. code:: shell

    # cargo-dist 0.28+ installs the `dist` binary (also linked as cargo-dist)
    curl --proto '=https' --tlsv1.2 -LsSf \
      https://github.com/axodotdev/cargo-dist/releases/download/v0.28.0/cargo-dist-installer.sh | sh
    dist generate --mode=ci
    git add .github/workflows/release.yml dist-workspace.toml

crates.io publish workflow and ``CARGO_REGISTRY_TOKEN``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Workflow file: ``.github/workflows/crates_publish.yml`` (name: **Publish to crates.io**).

- **Trigger**: push of tags matching ``v*``, or ``workflow_dispatch`` on a branch
  (uses ``Cargo.toml`` package version; on a ``v*`` tag the tag must match that
  version or the job fails fast).

- **Action**: ``cargo publish --locked`` for the ``readcon-core`` crate.

- **Idempotent skip**: if ``https://crates.io/api/v1/crates/readcon-core/<version>``
  already returns 200, the job logs “already published” and does **not** call
  ``cargo publish`` (avoids “crate already exists” on re-runs).

- **Secret**: repository secret **exactly named** ``CARGO_REGISTRY_TOKEN``. Value is
  a crates.io API token for an account allowed to publish ``readcon-core``
  (create at `https://crates.io/settings/tokens <https://crates.io/settings/tokens>`_ ). Without it, the publish
  step fails with “please provide a non-empty token” / our explicit empty-secret
  guard.

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

Prefer fixing the secret and re-running the workflow over making local publish
the default path.

PyPI (wheels) on the same tag
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``python_wheels.yml`` builds sdist + manylinux/macOS/Windows wheels with maturin
(``--features python``, **not** ``chemfiles`` by default) and publishes with
``pypa/gh-action-pypi-publish`` using OIDC trusted publishing (environment
``pypi``). No password secret is required once the trusted publisher is
configured (see **Initial PyPI setup** below). Transient crates.io network
errors are mitigated with ``CARGO_HTTP_MULTIPLEXING=false`` and a one-shot
maturin retry; tag runs are not cancelled mid-flight by concurrency.

Version files
~~~~~~~~~~~~~

Versions are tracked in six source files that must stay synchronized:

1. ``Cargo.toml`` (``version = "X.Y.Z"``)

2. ``meson.build`` (``version: 'X.Y.Z'``)

3. ``pyproject.toml`` (``version = "X.Y.Z"``)

4. ``pixi.toml`` (``version = "X.Y.Z"``)

5. ``docs/source/conf.py`` (``release = "X.Y.Z"``)

6. ``src/lib.rs`` (``assert_eq!(VERSION, "X.Y.Z")`` in the version test)

Complete release checklist
~~~~~~~~~~~~~~~~~~~~~~~~~~

Fast path (preferred):

.. code:: shell

    scripts/release-prep.sh X.Y.Z
    # review staged files, then:
    git commit -m "maint: bump to vX.Y.Z"
    # push a branch, open PR → cargo-dist Release workflow runs dist plan
    # merge PR to main, then:
    git checkout main && git pull
    git tag -s vX.Y.Z -m "vX.Y.Z"
    git push origin main --tags
    # wait for Release + Publish to crates.io + Python wheels

Manual equivalent of the script:

1. Ensure all tests pass and the branch is clean:

   .. code:: shell

       cargo test --locked
       cargo test --locked --features chemfiles   # optional; needs libchemfiles/cmake policy
       pixi r -e python python-test

2. Bump the version in all six files listed above.

3. Regenerate ``Cargo.lock`` after the version bump (``cargo test --locked``).

4. Regenerate the README from ``readme_src.org`` when the user-facing docs changed
   (optional for patch releases that only touch the crate version). Use the
   project script so ``docs/orgmode/*.org`` links stay ``.org`` (plain ``ox-md``
   rewrites them to missing ``.md`` paths):

   .. code:: shell

       ./scripts/export-readme.sh

5. Regenerate ``CHANGELOG.md`` with ``cog``.
   Do not hand-edit the generated release section (extend ``cog.toml``
   ``[commit_types]`` if a historical type blocks ``cog changelog``).

   .. code:: shell

       {
         sed -n '1,3p' CHANGELOG.md
         cog changelog
       } > /tmp/CHANGELOG.md
       mv /tmp/CHANGELOG.md CHANGELOG.md

6. If the FFI surface changed, run ``scripts/regen-capi-headers.sh`` and commit
   ``include/readcon-core.h`` (CI ``build_test.yml`` runs ``--check``).

7. Commit the release preparation (``maint: bump to vX.Y.Z``) and open the
   **release PR** (cargo-dist plans on PRs). After merge:

   .. code:: shell

       git tag -s vX.Y.Z -m "vX.Y.Z"
       git push origin main --tags

8. Do **not** rely on a local ``cargo publish`` unless CI is red; prefer
   ``crates_publish.yml`` with ``CARGO_REGISTRY_TOKEN`` set. Local fallback:

   .. code:: shell

       CARGO_REGISTRY_TOKEN="$(pass show crates-io/readcon-core)" cargo publish --locked

9. Tag CI also runs ``python_wheels.yml`` (PyPI) and cargo-dist ``Release``
   (CLI tarballs + GitHub Release body from the changelog).

10. Verify all distribution channels:

    - `crates.io <https://crates.io/crates/readcon-core>`_ shows the new version

    - `PyPI <https://pypi.org/project/readcon/>`_ shows the new version (wait for CI)

    - `GitHub Releases <https://github.com/lode-org/readcon-core/releases>`_ has cargo-dist archives
      (and any prior C ABI tarballs if still attached)

Optional local C ABI tarball for consumers that do not use cargo-dist CLI
archives (headers + ``libreadcon_core.{a,so}`` via ``cargo build --release`` or
``cargo cinstall``) can still be attached with ``gh release upload`` if needed.

Initial PyPI setup (first release only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the very first release, PyPI trusted publisher is not yet
configured. Publish manually:

.. code:: shell

    # Build wheels
    maturin build --release --features python

    # Upload (first time, creates the project on PyPI)
    uvx twine upload target/wheels/*


Python ships **two** distributions from ``python_wheels.yml``:

.. table::

    +-----------------------+--------------------------------------------+-------------------------------------------------------+
    | PyPI name             | Features                                   | Import                                                |
    +=======================+============================================+=======================================================+
    | ``readcon``           | ``python`` only (stubs for chemfiles APIs) | ``import readcon``                                    |
    +-----------------------+--------------------------------------------+-------------------------------------------------------+
    | ``readcon-chemfiles`` | ``python,chemfiles`` (libchemfiles linked) | ``import readcon`` (``has_chemfiles_support()`` True) |
    +-----------------------+--------------------------------------------+-------------------------------------------------------+

Configure a trusted publisher on **each** PyPI project (same workflow
``python_wheels.yml``, environment ``pypi``). Do not install both wheels in one
venv (both export the ``readcon`` module). Prefer ``pip install readcon-chemfiles``
when selection/import are required; lean ``readcon`` for CON I/O only.
``pip install 'readcon[chemfiles]'`` depends on ``readcon-chemfiles==X.Y.Z`` (pin
updated by ``scripts/release-prep.sh``).

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

1. Add the binding source under ``src/`` (e.g., ``src/python.rs``) or as
   a separate package (e.g., ``julia/ReadCon/``).

2. Gate behind a feature flag if it adds dependencies.

3. Add tests under ``tests/`` or the binding's own test directory.

4. Document in ``docs/orgmode/bindings.org`` and ``docs/orgmode/howto.org``.

5. Add a pixi environment and tasks if applicable.

Updating the C header
~~~~~~~~~~~~~~~~~~~~~

The C header ``include/readcon-core.h`` is generated by cbindgen.
After modifying ``src/ffi.rs``:

.. code:: shell

    cbindgen --config cbindgen.toml --crate readcon --output include/readcon-core.h -- src/lib.rs

Or let the meson/cmake build regenerate it.

The C++ header ``include/readcon-core.hpp`` is hand-maintained and must
be updated manually to match any changes to ``CAtom``, ``CFrame``, or
the FFI function signatures.
