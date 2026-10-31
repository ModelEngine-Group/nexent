# Direct external-suite comparison, 2026-09-29

The source is the canonical external suite (`nexent-test`), not the removed repository `test/` directories. This is a static migration audit, not a full test execution certificate. The external suite and Ubuntu are unchanged.

## Contracts

The source workbook SHA-256 is `aa4b32414d30f12b3b64e14236268145e556bd7cfc5d3eb8df80731608ebc022`. All 659 nonempty Case IDs from its three case sheets exist in `test-e2e/cases`. Title, priority, stage, preconditions, action steps, expected results and asset declaration match after the existing documented normalization of the historical product commit pin. No Case was omitted. All 186 named source Feature definitions match.

The repository has 667 Cases: the 659 V5 Cases plus eight CMSR Cases. The 360 Feature records include provisional V5 owners for rows without an original stable Feature ID and the repository-owned feature; they do not imply 360 original workbook features.

| Stage | Source V5 Cases | Bound in new layout | Blocked | Policy skipped | Retired |
| --- | ---: | ---: | ---: | ---: | ---: |
| D1 | 185 | 185 | 0 | 0 | 0 |
| D2 | 158 | 149 | 9 | 0 | 0 |
| D3 | 182 | 173 | 8 | 0 | 1 |
| D4 | 53 | 45 | 5 | 2 | 1 |
| D5 | 81 | 81 | 0 | 0 | 0 |
| Total | 659 | 633 | 22 | 2 | 2 |

The D4 count of 52 means 53 workbook records minus the retired `PW-HITL-01`, not 52 implemented Playwright journeys. Five blocked journeys and two excluded OAuth/CAS journeys remain documented.

The external catalog is stale for `API-105`, `PW-PROMPT-01`, `PW-PROMPT-02`, `PW-RESOURCE-04`, and `SEC-01`, despite storing the current workbook checksum. The repository follows workbook wording, not that stale catalog.

## Scripts and execution bindings

The external manifest lists 650 Cases. Seventeen of those are A2A policy-skip placeholders, not working implementations: D2 `API-092`, `API-093`, `CTR-034`, `CTR-035`, `CTR-039` through `CTR-043`; D3 `API-094`, `API-095`, `CTR-031` through `CTR-033`, `CTR-036` through `CTR-038`. The source code explicitly skips these IDs. The new layout retains their contracts as blocked and does not count the placeholders as implemented.

For the 633 V5 Cases with new bindings:

- 183 primary scripts are unchanged apart from line endings/outer whitespace.
- 168 Python Cases preserve the mechanically split module AST.
- 44 Vitest Cases preserve the documented split from their original TypeScript modules.
- 45 Playwright Cases preserve journey content with only the declared import/helper path transformations.
- 183 Cases retain the original scenario-helper AST after removing the multi-case parameter decorator and renaming its entrypoint. Their wrappers still require runtime verification.
- Ten bindings (`SEC-01` through `SEC-10`) share a security helper that differs. The substantive extension is the previously added `SEC-01` external Memory Provider cross-tenant API matrix, including provider state checks after unauthorized operations. Do not claim byte or whole-module behavior equivalence for these ten bindings. No security assertions were changed during this cleanup.

All source implementation files recorded by the earlier migration snapshot still match their source checksums. No newer source implementation was silently missed by relying on that snapshot.

## Supporting code and local assets

A scan of 312 source code/config files under the automation stage/frontend/shared directories found 234 files referenced by the source bindings, 68 unchanged support files, eight modified support files, and two without same-path counterparts. Backups, Syncthing conflict copies, node_modules and runtime output are excluded from that count.

The eight modified support files are `shared/cases.py`, `shared/config.py`, the frontend Vitest configuration and result converter, and D4 `playwright.config.ts`, `runner/assets.ts`, `runner/journey.ts`, `helpers/seed_citation_source.py`. These adapt formal Case loading, local configuration and repository paths. The root pytest plugin also uses the unique name `nexent_formal_pytest` to avoid colliding with pytest's built-in fixtures plugin.

The two no-same-path files are old D4 `asset-dependencies.json` and `validate_suite.py`. Case-local execution declarations and the new validator/registry replace these old derived structures. Historical tooling remains under `infra/migration/legacy-tools`, not as an execution entrypoint.

Machine-local config, credentials, assets, Daily orchestration, reports and notifications remain external. The prior 23-asset inventory is not a claim that those assets were committed or provisioned. Ubuntu Daily cutover and same-commit/same-assets full execution comparison remain outstanding.

## Old directory cleanup and verification

Eleven migrated directories were removed from the old repository `test/` tree using a recoverable archive: `automation`, `cases`, `features`, `changes`, `manifests`, `schemas`, `tools`, `generated`, `migration`, `mock-services`, and `compose`. All 1,429 archived files were hash-verified. Legacy UT and unrelated test helpers remain unchanged.

After removal, the new implementation validator passes. The three case-layout unit tests pass. Archive-to-new-layout validation still passes for 360 Features, 667 Cases, four Changes and 638 primary scripts. No dependency installation, Git commit, push, remote deployment or full product test run was performed.
