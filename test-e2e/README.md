# Nexent formal D1–D5 tests

This directory is the Git-owned source of truth for requirement-driven tests. The existing `test/backend`, `test/sdk`, and `test/ext_components` suites remain separate Legacy UT.

For setup, failure diagnosis, Case/script changes and local verification, see the [developer guide (中文)](DEVELOPER_GUIDE.zh-CN.md).

## Layout

```text
test-e2e/
  features/<Feature-ID>/feature.yaml     product behavior and business rules
  features/<Feature-ID>/cases.md         generated navigation, no symlink requirement
  cases/<Case-ID>/case.yaml              acceptance contract
  cases/<Case-ID>/execution.yaml         local execution binding
  cases/<Case-ID>/test.*                 case-owned primary implementation
  changes/<type>/<Change-ID>.yaml       requirement/bug/refactor/test-fix trace
  infra/automation/                    shared helpers and framework configs
  infra/mock-services/                 reusable mock deployment mechanism
  infra/tools/                         validators and targeted runner
  infra/generated/                     derived registry and Excel view
  infra/migration/                     source audit and migration receipts
```

There is no manually maintained central manifest. `execution.yaml` is the binding for one Case. `registry.json`, Feature navigation pages, and the Excel view are generated. The registry and Excel view are local-only, ignored by Git, and optional in a fresh checkout. Do not edit them directly or treat Excel as the authoritative source.

The migrated formal directories under `test/` have been removed from the checkout after a hash-verified recoverable archive. Legacy UT and its existing helpers remain under `test/`. Historical receipts and converters under `infra/migration` describe the old layout; do not run them as current authoring commands. `audit_layout_copy.py --source-root <archive-root>` can check an archive containing the old `test/` tree. Direct external-suite comparison uses `infra/tools/audit_external_suite.py`; it does not depend on the removed tree and does not certify live execution parity.

## Validate

From the repository root, using the configured backend Python environment:

```bash
python test-e2e/infra/tools/validate_test_assets.py --phase design --generate
python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate
python test-e2e/infra/tools/validate_test_assets.py --phase implementation
```

The last command is read-only and fails on stale generated views if they exist; a fresh checkout without local registry or Excel files is valid. Use `--generate` when you need the local views. Design mode permits a newly designed automated Case without `execution.yaml`; implementation mode does not.

## Run a developer-selected Case

Each developer provides an absolute, machine-local test home outside this Git checkout. For this Windows workstation use `D:\work\public\nexent-test-suite`; the existing Ubuntu Daily host continues to use `/home/jason/nexent-test-suite`. These are separate machine-local directories, not a shared path or a migration of the Ubuntu controller. The home contains `config/daily.env`, `config/secrets.env`, `config/environment.yaml`, and the assets referenced by a Case. Do not commit local credentials, assets, run IDs, results, or screenshots.

The repository entrypoint can preview missing local configuration without writing anything, then create only missing templates when explicitly requested:

```powershell
python test-e2e/infra/scripts/run-suite.py onboard --test-home D:\work\public\nexent-test-suite
python test-e2e/infra/scripts/run-suite.py onboard --test-home D:\work\public\nexent-test-suite --execute
python test-e2e/infra/scripts/run-suite.py onboard --interactive --execute
python test-e2e/infra/scripts/run-suite.py doctor --test-home D:\work\public\nexent-test-suite --case UT-SDK-001
```

In interactive mode, omitting `--test-home` prompts each developer for an absolute path (default: a `nexent-test-suite` sibling of that checkout), followed by service addresses and container hosts. Providing `--test-home` skips only the path prompt. Existing config is never overwritten. Fill any newly created placeholders and credentials locally. `doctor --live` also probes the configured HTTP services; plain `doctor` remains read-only and offline. Plan, doctor, run, resume and daily use only `<test-home>/runtime/test-venv`; bootstrap creates this same environment when needed. See [environment preparation](infra/environment/README.md).

```bash
python test-e2e/infra/tools/run_cases.py --list
python test-e2e/infra/tools/run_cases.py AGT-001 --test-home /absolute/path/to/my-test-home
```

On Windows, the Python used to launch the command may be the installed Python launcher; the direct runner switches to `<test-home>/runtime/test-venv` before loading test dependencies. Use a Windows absolute path for `--test-home`. The runner creates results under `<test-home>/runs/repository-local/`. It does not install dependencies, deploy the product, or contact GitHub. D4 failure screenshots and traces are retained by the fixed Playwright journey; successful journeys do not retain them. D1 frontend cases require dependencies installed for `infra/automation/d1/frontend`; D4 requires Playwright under its package or the product frontend package.

## D1 code coverage and Legacy UT comparison

Python D1 measures the same `backend/` and `sdk/` source scope as Legacy UT,
including branches. Frontend components use Vitest V8 with a separate frontend
denominator. Install the frontend package with `npm ci` before collecting its
coverage. The pinned coverage provider must match the Vitest version.

```bash
# One or more D1 cases; ordinary execution stays unchanged without --coverage.
python test-e2e/infra/tools/run_cases.py UT-SDK-001 --test-home /absolute/path/to/my-test-home --coverage
# All active D1 cases, using the dedicated test-home Python automatically.
python test-e2e/infra/tools/run_d1_coverage.py --test-home /absolute/path/to/my-test-home
# Run both independent suites concurrently at the current worktree version.
python test-e2e/infra/tools/run_d1_coverage.py --test-home /absolute/path/to/my-test-home --compare-legacy --workers 4 --timeout 300
# Recheck only frontend components or regenerate reports from retained raw data.
python test-e2e/infra/tools/run_d1_coverage.py --test-home /absolute/path/to/my-test-home --framework vitest
python test-e2e/infra/tools/run_d1_coverage.py --test-home /absolute/path/to/my-test-home --report-batch /absolute/path/to/my-test-home/runs/d1-coverage/<batch>
```

Comparison batches stay under `<test-home>/runs/d1-coverage/`. Each suite owns
its raw data, logs and JUnit; Python reports include XML, JSON and HTML. Frontend
reports include HTML, JSON, LCOV and Cobertura and are never merged with Python.
The custom Node D1 case is executed but does not contribute to those percentages.
No deployment or result upload is performed. Existing PR CI is not switched.

Python comparison normalizes both reports to the union of their observed
in-scope source files: example/benchmark modules imported only by one suite
remain uncovered in the other, rather than disappearing from its denominator.
Source-inspection-only tests with no executed product code are retained as
test results and recorded as empty coverage data, not mixed into branch data.
The comparison launcher defaults its Windows child interpreters to UTF-8 text
mode, matching Linux CI when legacy tests omit an explicit file encoding.

The comparison records HEAD and actual source hashes, missing/exclusive lines
and branches, and legacy test contexts and assertions associated with exclusive
coverage. These are review leads; executing a line does not prove a requirement
was asserted. Failures, collection errors, skips and timeouts mean partial
evidence, not successful replacement of Legacy UT. A complete behavioral review
and stable passing execution are required before retiring old tests.

## Candidate batch entrypoint and Ubuntu Daily transition

The candidate repository batch entrypoint is now available:

```bash
python test-e2e/infra/scripts/run-suite.py bootstrap --test-home /absolute/path/to/test-home
python test-e2e/infra/scripts/run-suite.py doctor --test-home /absolute/path/to/test-home
python test-e2e/infra/scripts/run-suite.py plan --test-home /absolute/path/to/test-home --stage D4
python test-e2e/infra/scripts/run-suite.py run --test-home /absolute/path/to/test-home --case UT-SDK-001 --execute
python test-e2e/infra/scripts/run-suite.py resume --test-home /absolute/path/to/test-home --batch-dir /absolute/path/to/interrupted-batch
# Add --execute only after reviewing the resume preview and local environment.
```

`bootstrap`, `run`, `daily` and `resume` require `--execute` for side effects. Use `--feature` or `--change` for development selections. Local `resume` accepts only a cleanly finalized, interrupted `run` batch with matching product/test/config bytes and ready static assets; it creates a child batch and retains the source evidence. An interrupted in-flight Case or uncertain cleanup requires manual recovery, not automatic reuse. Daily resume is not enabled. The older `infra/tools/run_cases.py` remains a direct targeted runner and does not share this dry-run default. Batch prerequisites belong to each Case's `execution.yaml`; missing online preparation declarations block execution, but script-hash approval is not required. See [environment preparation](infra/environment/README.md) and the [remaining migration gates](infra/migration/runtime-migration-status.md) before attempting Daily cutover. No live cutover is implied by these commands.

The existing Ubuntu Daily deployment, scheduling, report, and notification controller is external to this repository. Keep it on the existing validated test suite until it has been adapted to read these Case-local contracts and scripts and a same-commit, same-assets parity run passes. The repo's targeted runner is not a replacement for Daily deployment or D0–D6 orchestration. Daily may consume repository assets but must not rewrite them; fixes return through the product branch.
