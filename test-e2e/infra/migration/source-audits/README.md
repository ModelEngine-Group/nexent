# Historical V5 baseline migration receipt

This document records the earlier `test/` migration snapshot. Its old paths and commands are historical, not current entrypoints. The formal source is now `test-e2e/features/<ID>/feature.yaml` and `test-e2e/cases/<ID>/case.yaml`, with case-local `execution.yaml`. The old formal directories have been archived outside the checkout. See `test-e2e/README.md` for maintained commands.

The existing V5 workbook in the external source suite is the frozen input
for this migration. All D1-D5 rows are read directly from its three case
worksheets; the old JSON catalog and manifest are cross-checks and script
locators, not authorities for case wording or total counts. The repository-owned source of truth is now
`test/features/v5-baseline.yaml` plus `test/cases/d1..d5/v5-baseline.yaml`;
`test/generated/Nexent_测试基线.xlsx` is only a deterministic view. The source
suite is not modified or deleted.

## Current state

- 659 raw V5 Case IDs are represented. 633 active automated cases have formal
  manifest bindings; 22 are blocked, 2 are skipped by policy, and 2 are
  retired by the current product contract. The stage reconciliation is:

  | Stage | V5 rows | Current scope | Script bindings | Blocked | Policy skip | Retired |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: |
  | D1 | 185 | 185 | 185 | 0 | 0 | 0 |
  | D2 | 158 | 158 | 149 | 9 | 0 | 0 |
  | D3 | 182 | 181 | 173 | 8 | 0 | 1 |
  | D4 | 53 | 52 | 45 | 5 | 2 | 1 |
  | D5 | 81 | 81 | 81 | 0 | 0 | 0 |

  `test/migration/v5-full-coverage.json` records the per-stage non-executable
  IDs. `script bindings` means a unique executable entrypoint exists; it does
  not mean the V5 behavior has passed a live run.
- Five old catalog records had stale wording despite recording the correct
  workbook SHA: `API-105`, `PW-PROMPT-01`, `PW-PROMPT-02`,
  `PW-RESOURCE-04`, and `SEC-01`. The formal YAML now uses the workbook
  wording. The four D3/D4 scripts already include the changed steps; SEC-01
  gained the missing external-memory provider cross-tenant API matrix. No
  semantic or live execution parity is claimed for the full 659-row baseline.
- Each implemented Case ID has its own executable file. D3/D5 parameterized
  cases invoke non-collected scenario helpers. The manifest hashes both the
  per-case entrypoint and its scenario helper, so shared logic changes are not
  invisible to the asset validator.
- Old copied multi-case source files were removed only after source hashes
  were checked. Other unbound tests that did not match source files were
  preserved. The old `case_data/*.json` copies were also removed; D3/D5
  parameter loading reads the formal YAML directly.
- The D4 workbook sheet has 53 rows, of which `PW-HITL-01` is explicitly
  retired. The other 52 comprise 45 fixed Playwright cases, 5 blocked cases
  without scripts, and 2 OAuth/CAS cases skipped by policy. D4 Playwright
  registration lists exactly 45 cases after the split. The repository's
  formal manifest enforces one Case ID per primary test file.
- `test/migration/v5-asset-inventory.yaml` inventories the source suite's
  23 declared static assets, machine-local configuration, runtime IDs and
  policy-skipped external identity dependencies. It is an inventory, not a
  claim that these files are safe to commit or already provisioned.

## Verification on this checkout

From the repository root, with the backend virtual environment available:

```text
backend/.venv/Scripts/python.exe test/tools/validate_test_assets.py --phase implementation --generate-excel
backend/.venv/Scripts/python.exe test/tools/verify_v5_case_isolation.py
backend/.venv/Scripts/python.exe -m pytest -q test/tools/tests/test_formal_test_assets.py
```

On Linux, replace the Python executable with the environment's Python 3
interpreter. For full pytest collection, supply the product and automation
directories on `PYTHONPATH`, `NEXENT_REPO`, and an isolated `NEXENT_TEST_HOME`.
The latter continues to hold machine-local credentials and provisioned test
assets; secrets are not Git assets.

## Not yet certified for Daily cutover

Do not point the existing Ubuntu Daily workflow at this checkout yet. These
checks certify structure, hashes, syntax, and selected collection, not live
D1-D5 execution parity. Remaining gates are:

1. Classify and move non-sensitive static fixtures from the source suite;
   leave credentials, runtime IDs, and run output local.
2. Supply/install the frontend test-only dependencies and rerun the split
   Vitest cases in one consistent React dependency tree. A product
   `frontend/node_modules` alone lacks the required Vitest plugins on this
   Windows checkout. Reusing the old suite's modules allowed a diagnostic run
   (240 passed, 80 failed, 12 post-test errors), but mixed two React trees and
   is not an execution-parity certificate. The 40 split core files yielded
   38 passes, one test failure, and one import-time suite failure; the original
   unsplit file also fails to import the same removed product module.
3. Run a disposable product stack and complete D2-D5 execution, including
   D4 screenshots/traces on failures and report parity.
   In particular, `SEC-01` now probes the memory-provider endpoints and may
   expose a product authorization defect: the checked-in backend's single-ID
   provider routes do not visibly scope by tenant. Its V5-required direct DB,
   service-log and run-evidence checks remain to be verified in that run.
4. Move or adapt the old Daily orchestrator and report generation only after
   the above gates pass. The old `/home/jason/nexent-test-suite` remains the
   operational Daily suite until that cutover.

Source tests already fail independently of this migration on this checkout:
`UT-BE-015` (database connectivity) and `UT-SDK-016` (reasoning model
initialization). Full pytest collection also exposes a missing `reportlab`
dependency and a removed SDK `telemetry` import in existing generated tests.
These are not treated as migration successes or silently skipped.
