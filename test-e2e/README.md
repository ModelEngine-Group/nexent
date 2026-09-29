# Nexent formal D1–D5 tests

This directory is the Git-owned source of truth for requirement-driven tests. The existing `test/backend`, `test/sdk`, and `test/ext_components` suites remain separate Legacy UT.

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

There is no manually maintained central manifest. `execution.yaml` is the binding for one Case. `registry.json`, Feature navigation pages, and the Excel view are generated. Do not edit them directly or treat Excel as the authoritative source.

The migrated formal directories under `test/` have been removed from the checkout after a hash-verified recoverable archive. Legacy UT and its existing helpers remain under `test/`. Historical receipts and converters under `infra/migration` describe the old layout; do not run them as current authoring commands. `audit_layout_copy.py --source-root <archive-root>` can check an archive containing the old `test/` tree. Direct external-suite comparison uses `infra/tools/audit_external_suite.py`; it does not depend on the removed tree and does not certify live execution parity.

## Validate

From the repository root, using the configured backend Python environment:

```bash
python test-e2e/infra/tools/validate_test_assets.py --phase design --generate
python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate
python test-e2e/infra/tools/validate_test_assets.py --phase implementation
```

The last command is read-only and fails on stale generated views. Design mode permits a newly designed automated Case without `execution.yaml`; implementation mode does not.

## Run a developer-selected Case

Each developer provides an absolute, machine-local test home outside this Git checkout. It contains `config/daily.env`, `config/secrets.env`, `config/environment.yaml`, and the assets referenced by that Case. Do not commit local credentials, assets, run IDs, results, or screenshots.

```bash
python test-e2e/infra/tools/run_cases.py --list
python test-e2e/infra/tools/run_cases.py AGT-001 --test-home /absolute/path/to/my-test-home
```

On Windows, use the installed Python launcher or the backend virtual environment's `python.exe`, and a Windows absolute path for `--test-home`. The runner creates results under `<test-home>/runs/repository-local/`. It does not install dependencies, deploy the product, or contact GitHub. D4 failure screenshots and traces are retained by the fixed Playwright journey; successful journeys do not retain them. D1 frontend cases require dependencies installed for `infra/automation/d1/frontend`; D4 requires Playwright under its package or the product frontend package.

## Ubuntu Daily transition

The existing Ubuntu Daily deployment, scheduling, report, and notification controller is external to this repository. Keep it on the existing validated test suite until it has been adapted to read these Case-local contracts and scripts and a same-commit, same-assets parity run passes. The repo's targeted runner is not a replacement for Daily deployment or D0–D6 orchestration. Daily may consume repository assets but must not rewrite them; fixes return through the product branch.
